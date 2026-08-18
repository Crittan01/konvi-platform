import logging
import os
import re
from typing import Any, Optional
import httpx
from supabase import Client

logger = logging.getLogger("orchestrator.whatsapp_sender")


def _mask_phone(p: str) -> str:
    """Enmascara el teléfono para logs (W1 Habeas Data): solo últimos 4 dígitos.
    NECESARIO en el call-site: los logs (stdout, retenidos por Render) son la
    fuente de verdad de errores — todo log que incluya el teléfono debe pasar
    por aquí."""
    if not p:
        return "?"
    return "***" + str(p)[-4:]

# Versión de Meta Graph API — ÚNICA definición del orquestador (G26).
# Env: META_GRAPH_API_VERSION (default "v22.0"). Existe para el bump
# calendarizado Q4-2026: Meta depreca versiones ~trimestralmente y subir de
# versión no debe exigir tocar N archivos — basta el env en Render.
# La consumen también services/meta_media.py y health_metrics.py.
GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v22.0")
META_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

REQUEST_TIMEOUT_SECONDS = 10

# Regex de placeholders Meta. POSITIONAL: {{1}}, {{2}}. NAMED: {{customer_name}}.
_POSITIONAL_PH_RE = re.compile(r"\{\{(\d+)\}\}")
_NAMED_PH_RE = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")


def _get_tenant_wa_credentials(tenant_id: str, supabase: Client) -> tuple[str, str]:
    """
    Returns (phone_number_id, access_token) only when the tenant has
    WhatsApp status=connected in tenant_integrations.
    """
    try:
        # BLOQUE J (review): maybe_single (no single) — un tenant SIN fila de
        # integración WhatsApp es estado benigno (onboarding / tenant no-WhatsApp).
        # .single() lanzaría PGRST116 con 0 filas → caería al except y loguearía un
        # falso "¿Vault/DB transitorio?". maybe_single devuelve data=None → el guard
        # `if not res.data` lo maneja limpio, y el except queda SOLO para fallos
        # genuinos (Vault/DB), cumpliendo el objetivo de distinguirlos.
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .maybe_single()
            .execute()
        )
        if not res or not res.data:
            return "", ""
        if res.data.get("status") != "connected":
            return "", ""
        creds = res.data.get("credentials", {})
        from vault_helper import VaultHelper, resolve_secret
        vault = VaultHelper(supabase)
        phone_id     = creds.get("phone_number_id", "")
        access_token = resolve_secret(vault, creds, "access_token") or ""
        return phone_id, access_token
    except Exception as exc:
        # BLOQUE J (robustez): loguear la excepción. Antes se tragaba en silencio,
        # con lo que un fallo TRANSITORIO de Vault/DB era indistinguible de "tenant
        # sin credenciales" — el caller logueaba "Faltan credenciales" y el mensaje
        # se perdía sin señal de que fue un outage recuperable. El retorno ("","")
        # se mantiene (el caller ya lo maneja), pero ahora queda traza para diagnóstico.
        logger.error(
            "[META API] _get_tenant_wa_credentials error (¿Vault/DB transitorio?) "
            "tenant=%s: %s",
            (tenant_id or "?")[:8], exc,
        )
        return "", ""


#: Código con el que Meta rechaza un mensaje libre fuera de la ventana de servicio de 24h
#: ("Re-engagement message"). Es el ÚNICO error que no tiene sentido reintentar: la ventana
#: no se reabre sola, y cada reintento es una llamada que ya sabemos que va a fallar.
META_ERROR_FUERA_DE_VENTANA = 131047

#: Último código de error por (tenant, teléfono). `send_whatsapp_message` devuelve None
#: para TODO —timeout, token malo, ventana cerrada— y el consumidor de la cola no podía
#: distinguirlos: reintentaba hasta agotar intentos y marcaba el mensaje con un motivo
#: genérico. Se guarda acá en vez de cambiar el tipo de retorno porque hay ~10 llamadores
#: que solo quieren el id; los que necesitan el detalle preguntan con `ultimo_error`.
_ULTIMO_ERROR: dict[str, Optional[int]] = {}


def _telefono_normalizado(p: str) -> str:
    """La misma forma que usa el envío. Si la clave del registro de errores se calculara
    distinto, `fuera_de_ventana` consultaría una entrada que nunca se escribió."""
    return (p or "").lstrip("+").replace(" ", "").replace("-", "")


def _clave_error(tenant_id: str, telefono: str) -> str:
    return f"{tenant_id}:{_telefono_normalizado(telefono)}"


def _codigo_de_error(response) -> Optional[int]:
    """El `error.code` que devuelve la Graph API, o None si no vino."""
    try:
        return int((response.json().get("error") or {}).get("code"))
    except (ValueError, TypeError, AttributeError):
        return None


def ultimo_error(tenant_id: str, telefono: str) -> Optional[int]:
    """Código del último rechazo de Meta para ese destinatario, o None."""
    return _ULTIMO_ERROR.get(_clave_error(tenant_id, telefono))


def fuera_de_ventana(tenant_id: str, telefono: str) -> bool:
    """¿El último intento falló porque la ventana de 24h está cerrada?

    Distinguirlo importa: un timeout se reintenta, una ventana cerrada NO — no se reabre
    sola. Reintentarla quema llamadas a la Graph API y termina marcando el mensaje con un
    motivo genérico que no le dice nada al operador.
    """
    return ultimo_error(tenant_id, telefono) == META_ERROR_FUERA_DE_VENTANA


async def send_whatsapp_message(
    tenant_id: str,
    supabase: Client,
    to_phone: str,
    text: Optional[str] = None,
    image_link: Optional[str] = None,
    image_caption: Optional[str] = None,
) -> Optional[str]:
    """Envía un mensaje WhatsApp al cliente.

    Modo TEXTO (default, backwards-compat): pasar `text`.
    Modo IMAGEN (F8.B): pasar `image_link` (URL HTTPS) y opcionalmente
    `image_caption`. Meta v22.0 exige HTTPS y MIME image/jpeg|png|webp.

    Si se pasan ambos, IMAGEN tiene prioridad — el caller debe enviar texto
    como mensaje separado si lo necesita.
    """
    phone_id, access_token = _get_tenant_wa_credentials(tenant_id, supabase)

    if not phone_id or not access_token:
        logger.error(
            "Faltan credenciales WhatsApp conectadas en tenant_integrations para tenant=%s",
            tenant_id,
        )
        return None

    clean_phone = to_phone.lstrip("+").replace(" ", "").replace("-", "")

    if image_link:
        # F8.B.1 — payload type=image. Meta exige link HTTPS público.
        if not image_link.startswith("https://"):
            logger.error(
                "[META API] image_link debe ser HTTPS (Meta v22.0 lo exige). Recibido=%s",
                image_link,
            )
            return None
        image_obj: dict = {"link": image_link}
        if image_caption:
            image_obj["caption"] = image_caption
        payload: dict = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "image",
            "image": image_obj,
        }
        msg_kind = "image"
    elif text is not None:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_phone,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        msg_kind = "text"
    else:
        logger.error(
            "[META API] send_whatsapp_message requiere `text` o `image_link` para tenant=%s",
            tenant_id,
        )
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"{META_BASE_URL}/{phone_id}/messages"

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            message_id = response.json().get("messages", [{}])[0].get("id", "unknown")
            logger.info(
                "[META API] Mensaje enviado | type=%s | to=%s | meta_message_id=%s",
                msg_kind, _mask_phone(clean_phone), message_id,
            )
            _ULTIMO_ERROR.pop(_clave_error(tenant_id, clean_phone), None)
            return message_id
        else:
            codigo = _codigo_de_error(response)
            logger.error(
                "[META API] Error type=%s | status=%s | code=%s | body=%s",
                msg_kind, response.status_code, codigo, response.text,
            )
            _ULTIMO_ERROR[_clave_error(tenant_id, clean_phone)] = codigo
            return None

    except httpx.TimeoutException:
        logger.error("[META API] Timeout al enviar a %s", _mask_phone(clean_phone))
        _ULTIMO_ERROR[_clave_error(tenant_id, clean_phone)] = None
        return None
    except Exception as e:
        logger.error("[META API] Error inesperado: %s", e, exc_info=True)
        _ULTIMO_ERROR[_clave_error(tenant_id, clean_phone)] = None
        return None


# ─── HSM Templates (Sem 7 F2 / 2026-05-17) ───────────────────────────────────
#
# send_whatsapp_template envía mensajes type=template (HSM) fuera de la ventana
# CSW 24h Meta. Único modo válido para mensajes proactivos (recordatorios pago,
# abandoned cart, notificaciones de envío, etc.).
#
# Pre-requisito: el template debe estar APPROVED en la tabla whatsapp_templates
# (status sincronizado vía webhook message_template_status_update).
#
# Refs:
#   - services/api/lib/whatsapp_templates.py (helper canonical, mismo schema)
#   - docs/research/whatsapp-meta-dossier-2026-05-05.md sec. 4.5
#   - https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages/


# Códigos de error de retorno (string, no excepciones — fácil log + retry policy).
TEMPLATE_ERR_NO_CREDENTIALS = "NO_CREDENTIALS"
TEMPLATE_ERR_TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"
TEMPLATE_ERR_TEMPLATE_NOT_APPROVED = "TEMPLATE_NOT_APPROVED"
TEMPLATE_ERR_PARAM_COUNT_MISMATCH = "PARAM_COUNT_MISMATCH"
TEMPLATE_ERR_META_AUTH = "META_AUTH"
TEMPLATE_ERR_META_RATE_LIMIT = "META_RATE_LIMIT"
TEMPLATE_ERR_META_OTHER = "META_OTHER"
TEMPLATE_ERR_TIMEOUT = "TIMEOUT"
TEMPLATE_ERR_UNKNOWN = "UNKNOWN"


def _get_approved_template(
    supabase: Client,
    tenant_id: str,
    name: str,
    language: str,
) -> Optional[dict[str, Any]]:
    """Lookup directo en whatsapp_templates para outbound HSM.

    Retorna row dict si encuentra un template APPROVED + matching name + language
    + tenant. None si no existe o no está APPROVED — caller decide flow.

    Inline (no import del helper services/api/lib/) porque orchestrator es
    deploy unit independiente (mismo pattern que HMAC verify).
    """
    if not (name and language and tenant_id):
        return None
    try:
        res = (
            supabase.table("whatsapp_templates")
            .select(
                "id, meta_template_id, name, language, category, components, "
                "parameter_format, status, quality_rating"
            )
            .eq("tenant_id", tenant_id)
            .eq("name", name.strip())
            .eq("language", language.strip())
            .eq("status", "APPROVED")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None
    except Exception as exc:
        logger.error(
            "[WA_TPL] error lookup approved template tenant=%s name=%s lang=%s: %s",
            tenant_id, name, language, exc,
        )
        return None


def _extract_placeholders(components_def: list[dict[str, Any]], parameter_format: str) -> dict[str, list]:
    """Extrae los placeholders esperados de los components del template.

    Retorna dict con keys 'header', 'body', 'buttons' — cada uno con lista
    de placeholders en el orden que aparecen (positional) o nombres (named).

    Útil para validar pre-envío que el caller pasó la cantidad correcta de
    runtime params antes de hacer POST a Meta (evitar error 132000).
    """
    pattern = _NAMED_PH_RE if parameter_format == "NAMED" else _POSITIONAL_PH_RE
    result: dict[str, list] = {"header": [], "body": [], "buttons": []}
    for comp in components_def:
        if not isinstance(comp, dict):
            continue
        ctype = (comp.get("type") or "").upper()
        text = comp.get("text") or ""
        matches = pattern.findall(text)
        if ctype == "HEADER":
            result["header"] = matches
        elif ctype == "BODY":
            result["body"] = matches
        elif ctype == "BUTTONS":
            # BUTTONS pueden tener placeholders en URL de tipo URL button
            btns_phs: list[str] = []
            for btn in comp.get("buttons") or []:
                btn_text = (btn.get("url") or "") + " " + (btn.get("text") or "")
                btns_phs.extend(pattern.findall(btn_text))
            result["buttons"] = btns_phs
    return result


def _build_template_components(
    components_def: list[dict[str, Any]],
    *,
    body_params: Optional[list[str]] = None,
    header_params: Optional[list[str]] = None,
    button_params: Optional[list[dict[str, Any]]] = None,
    named_params: Optional[dict[str, str]] = None,
    parameter_format: str = "POSITIONAL",
) -> list[dict[str, Any]]:
    """Construye el array `components` del payload Meta `type=template`.

    Args:
        components_def: la definición canonical del template (whatsapp_templates.components).
        body_params: lista de strings para placeholders BODY (positional).
        header_params: idem HEADER.
        button_params: lista de dicts con shape Meta para BUTTONS
                       (e.g., [{"type":"url","index":0,"parameters":[{"type":"text","text":"AB12"}]}]).
        named_params: dict {name: value} para parameter_format=NAMED.
        parameter_format: "POSITIONAL" (default) o "NAMED".

    Returns:
        Lista compatible con Meta v22 `template.components` payload.
    """
    components_out: list[dict[str, Any]] = []
    named_mode = parameter_format == "NAMED"

    def _build_text_param(value: str, name: Optional[str] = None) -> dict[str, Any]:
        param: dict[str, Any] = {"type": "text", "text": value}
        if named_mode and name:
            param["parameter_name"] = name
        return param

    for comp in components_def:
        if not isinstance(comp, dict):
            continue
        ctype = (comp.get("type") or "").upper()

        if ctype == "HEADER":
            # Solo HEADER text con placeholders requiere parameters runtime.
            text = comp.get("text") or ""
            if not text:
                continue
            phs = (_NAMED_PH_RE if named_mode else _POSITIONAL_PH_RE).findall(text)
            if not phs:
                continue
            params: list[dict[str, Any]] = []
            if named_mode and named_params:
                for ph_name in phs:
                    if ph_name in named_params:
                        params.append(_build_text_param(named_params[ph_name], ph_name))
            elif not named_mode and header_params:
                for value in header_params:
                    params.append(_build_text_param(str(value)))
            if params:
                components_out.append({
                    "type": "header",
                    "parameters": params,
                })

        elif ctype == "BODY":
            text = comp.get("text") or ""
            phs = (_NAMED_PH_RE if named_mode else _POSITIONAL_PH_RE).findall(text)
            if not phs:
                continue
            params = []
            if named_mode and named_params:
                for ph_name in phs:
                    if ph_name in named_params:
                        params.append(_build_text_param(named_params[ph_name], ph_name))
            elif not named_mode and body_params:
                for value in body_params:
                    params.append(_build_text_param(str(value)))
            if params:
                components_out.append({
                    "type": "body",
                    "parameters": params,
                })

        elif ctype == "BUTTONS" and button_params:
            # Caller pasa estructura completa Meta-ready (más flexible que parsear
            # botones URL/QUICK_REPLY/PHONE separadamente acá).
            components_out.extend(button_params)

    return components_out


async def send_whatsapp_template(
    tenant_id: str,
    supabase: Client,
    to_phone: str,
    *,
    template_name: str,
    language: str,
    body_params: Optional[list[str]] = None,
    header_params: Optional[list[str]] = None,
    button_params: Optional[list[dict[str, Any]]] = None,
    named_params: Optional[dict[str, str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Envía un mensaje WhatsApp tipo template HSM (proactivo, fuera CSW 24h).

    Lookup el template en whatsapp_templates con status=APPROVED.
    Hidrata los placeholders con runtime params.
    POST a `/{PHONE_NUMBER_ID}/messages` con type=template.

    Args:
        tenant_id: dueño del WABA (lookup credenciales).
        supabase: client supabase para queries DB.
        to_phone: número destinatario (E.164 o digits-only — se limpia).
        template_name: name canonical del template (e.g. "payment_reminder_v1").
        language: locale (e.g. "es_CO", "es", "en_US").
        body_params: lista strings para placeholders BODY POSITIONAL.
        header_params: lista strings para placeholders HEADER POSITIONAL.
        button_params: estructura Meta completa para BUTTONS (URL/etc dinámicos).
        named_params: dict {name: value} si template usa parameter_format=NAMED.

    Returns:
        Tuple (meta_message_id, error_code):
          - (msg_id, None) si OK
          - (None, TEMPLATE_ERR_*) si fallo. Error code es string canonical.
    """
    # 1. Credenciales tenant
    phone_id, access_token = _get_tenant_wa_credentials(tenant_id, supabase)
    if not phone_id or not access_token:
        logger.error(
            "[WA_TPL] credenciales WhatsApp faltantes tenant=%s",
            tenant_id,
        )
        return None, TEMPLATE_ERR_NO_CREDENTIALS

    # 2. Lookup template approved
    template = _get_approved_template(
        supabase, tenant_id, template_name, language,
    )
    if not template:
        # Distinguir not_found vs not_approved para mejor diagnóstico
        # (segundo query con sin filtro status)
        try:
            res = (
                supabase.table("whatsapp_templates")
                .select("status")
                .eq("tenant_id", tenant_id)
                .eq("name", template_name)
                .eq("language", language)
                .limit(1)
                .execute()
            )
            exists = bool(res.data or [])
            current_status = res.data[0].get("status") if exists else None
        except Exception:
            exists = False
            current_status = None
        if not exists:
            logger.warning(
                "[WA_TPL] template no existe tenant=%s name=%s lang=%s",
                tenant_id, template_name, language,
            )
            return None, TEMPLATE_ERR_TEMPLATE_NOT_FOUND
        logger.warning(
            "[WA_TPL] template existe pero status=%s (no APPROVED) tenant=%s name=%s",
            current_status, tenant_id, template_name,
        )
        return None, TEMPLATE_ERR_TEMPLATE_NOT_APPROVED

    parameter_format = template.get("parameter_format") or "POSITIONAL"
    components_def = template.get("components") or []

    # 3. Validar count placeholders pre-envío (evita error 132000 Meta)
    expected = _extract_placeholders(components_def, parameter_format)
    if parameter_format == "POSITIONAL":
        if expected["body"] and len(body_params or []) < len(expected["body"]):
            logger.error(
                "[WA_TPL] body params mismatch tenant=%s name=%s expected=%d got=%d",
                tenant_id, template_name,
                len(expected["body"]), len(body_params or []),
            )
            return None, TEMPLATE_ERR_PARAM_COUNT_MISMATCH
        if expected["header"] and len(header_params or []) < len(expected["header"]):
            logger.error(
                "[WA_TPL] header params mismatch tenant=%s name=%s",
                tenant_id, template_name,
            )
            return None, TEMPLATE_ERR_PARAM_COUNT_MISMATCH
    elif parameter_format == "NAMED":
        all_named = set(expected["body"]) | set(expected["header"]) | set(expected["buttons"])
        missing = all_named - set((named_params or {}).keys())
        if missing:
            logger.error(
                "[WA_TPL] named params missing tenant=%s name=%s missing=%s",
                tenant_id, template_name, sorted(missing),
            )
            return None, TEMPLATE_ERR_PARAM_COUNT_MISMATCH

    # 4. Build payload
    components_payload = _build_template_components(
        components_def,
        body_params=body_params,
        header_params=header_params,
        button_params=button_params,
        named_params=named_params,
        parameter_format=parameter_format,
    )

    clean_phone = to_phone.lstrip("+").replace(" ", "").replace("-", "")

    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},
        },
    }
    if components_payload:
        payload["template"]["components"] = components_payload

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"{META_BASE_URL}/{phone_id}/messages"

    # 5. POST a Meta
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload, headers=headers)
    except httpx.TimeoutException:
        logger.error("[WA_TPL] timeout to=%s template=%s", _mask_phone(clean_phone), template_name)
        return None, TEMPLATE_ERR_TIMEOUT
    except Exception as e:
        logger.error("[WA_TPL] error inesperado: %s", e, exc_info=True)
        return None, TEMPLATE_ERR_UNKNOWN

    if response.status_code == 200:
        meta_message_id = response.json().get("messages", [{}])[0].get("id")
        logger.info(
            "[WA_TPL] template enviado tenant=%s name=%s to=%s meta_msg_id=%s",
            tenant_id, template_name, _mask_phone(clean_phone), meta_message_id,
        )
        return meta_message_id, None

    # 6. Mapear errores Meta a códigos canónicos
    try:
        body = response.json()
        meta_error = (body or {}).get("error") or {}
        meta_code = meta_error.get("code")
        meta_msg = meta_error.get("message", "")
    except Exception:
        meta_code = None
        meta_msg = response.text[:200]

    if meta_code in (0, 190, 3, 200):
        err = TEMPLATE_ERR_META_AUTH
    elif meta_code in (4, 80, 130429, 131048, 131056):
        err = TEMPLATE_ERR_META_RATE_LIMIT
    elif meta_code in (132000, 132001):
        err = TEMPLATE_ERR_PARAM_COUNT_MISMATCH
    else:
        err = TEMPLATE_ERR_META_OTHER

    logger.error(
        "[WA_TPL] Meta error tenant=%s name=%s status=%s code=%s msg=%s",
        tenant_id, template_name, response.status_code, meta_code, meta_msg,
    )
    return None, err
