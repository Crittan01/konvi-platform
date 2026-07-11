"""
Webhook de Mercado Libre (IPN — Instant Payment Notifications).

Tópicos registrados: orders_v2, items, shipments.

Flujo:
  1. MeLi hace POST → respondemos 200 inmediatamente (MeLi penaliza latencia)
  2. BackgroundTask procesa la notificación de forma asíncrona:
     a. Busca el tenant por meli user_id en tenant_integrations.meta
     b. Obtiene el access_token del tenant (con auto-refresh si expiró)
     c. Consulta el recurso en la MeLi API
     d. Persiste en nuestra base de datos

Defensa de origen:
  MeLi NO firma webhooks. La doc oficial publica las IPs desde donde envía
  notificaciones: si la IP del request no está en esa lista, rechazamos
  con 403 antes de hacer cualquier trabajo. Esto cierra el vector DoS y
  el de costo (sin filtro, un atacante podría disparar GETs a la API MeLi).

Referencia oficial:
  https://developers.mercadolibre.com.co/es_ar/notificaciones
"""
import asyncio
import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from dependencies.auth import _get_service_client, get_service_client
from dependencies.security import webhook_rate_limit_check
from integrations import meli_client
from lib.phone import to_db_format as _phone_to_db_format  # rev. 104 F0-4 canon único

# Rev. 103 — Versión vigente del aviso de privacidad (sincronizar con
# apps/web/.../contacts/page.tsx CURRENT_PRIVACY_NOTICE_VERSION + docs/legal/privacy-policy.md).
CURRENT_PRIVACY_NOTICE_VERSION = "v2026-05-01"


def _hash_phone(phone: Optional[str]) -> Optional[str]:
    """Espejo de orchestrator._hash_phone — sha256 con strip de spaces/+/-."""
    if not phone:
        return None
    normalized = re.sub(r"[\s+\-]", "", str(phone))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_phone_e164(raw: Optional[str]) -> Optional[str]:
    """Rev. 104 (F0-4) — DEPRECATED. Mantenido por backwards-compat.

    Antes (rev. 103 D2): normalizaba a E.164 (`+digits`) — diferente del
    canon usado por orchestrator (`digits`), causando duplicación silenciosa
    de contacts (BUG-2).

    Ahora delega a `lib.phone.to_db_format` (canon = digits-only). El renombre
    se mantiene como `_normalize_phone_e164` solo para no tocar 20+ callsites
    en esta misma sesión; semánticamente ahora retorna canon, NO E.164.

    TODO Fase 1: renombrar a `_normalize_phone_canonical` y hacer callsites
    explícitos sobre el formato esperado.
    """
    return _phone_to_db_format(raw)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["MeLi Webhook"])

MELI_API_URL = "https://api.mercadolibre.com"

# IPs oficiales desde donde MeLi envía notificaciones.
# Fuente: https://developers.mercadolibre.com.co/es_ar/notificaciones
# Sección "Historial de notificaciones" (verificada 2026-04-28).
# Si MeLi cambia las IPs, override por env var MELI_WEBHOOK_ALLOWED_IPS (CSV).
_MELI_DEFAULT_NOTIFICATION_IPS: frozenset[str] = frozenset({
    "54.88.218.97",
    "18.215.140.160",
    "18.213.114.129",
    "18.206.34.84",
})


def _load_allowed_meli_ips() -> frozenset[str]:
    raw = os.getenv("MELI_WEBHOOK_ALLOWED_IPS", "").strip()
    if not raw:
        return _MELI_DEFAULT_NOTIFICATION_IPS
    ips = {ip.strip() for ip in raw.split(",") if ip.strip()}
    return frozenset(ips) if ips else _MELI_DEFAULT_NOTIFICATION_IPS


_ALLOWED_MELI_IPS: frozenset[str] = _load_allowed_meli_ips()

# Idempotencia in-memory para webhooks repetidos.
# MeLi reintenta hasta 8 veces durante 1 hora si no recibe 200; un atacante
# con IP legítima podría replay. Memoización TTL=300s evita reprocesar el
# mismo (application_id, resource, sent). Por instancia (no distribuido):
# acepta replay cross-instancia, pero el handler interno ya es idempotente.
_DEDUP_TTL_SECONDS = 300
_dedup_lock = threading.Lock()
_dedup_seen: dict[str, float] = {}


def _is_duplicate_event_local(application_id: str, resource: str, sent: str) -> bool:
    """Dedup in-memory (fallback si la RPC distribuida falla)."""
    if not (application_id and resource and sent):
        return False
    key = f"{application_id}|{resource}|{sent}"
    now = time.time()
    with _dedup_lock:
        cutoff = now - _DEDUP_TTL_SECONDS
        # Limpieza oportunista
        if len(_dedup_seen) > 1000:
            for k, ts in list(_dedup_seen.items()):
                if ts < cutoff:
                    _dedup_seen.pop(k, None)
        last_seen = _dedup_seen.get(key)
        if last_seen and last_seen >= cutoff:
            return True
        _dedup_seen[key] = now
        return False


def _is_duplicate_event(application_id: str, resource: str, sent: str, supabase=None) -> bool:
    """Idempotencia distribuida via Supabase RPC `meli_webhook_seen` (rev. 69).

    Razón: en Render Starter+ con 2+ réplicas, el dedup in-memory no es
    coherente cross-réplica. La RPC en Supabase usa INSERT ON CONFLICT atómico
    para garantizar que un evento se procese exactamente una vez sin importar
    cuántas réplicas haya.

    Si la RPC falla (Supabase down, RPC no aplicada todavía, etc.) → fallback
    al dedup in-memory local. Mejor que nada cross-instancia.
    """
    if not (application_id and resource and sent):
        return False
    if supabase is None:
        return _is_duplicate_event_local(application_id, resource, sent)
    try:
        res = supabase.rpc(
            "meli_webhook_seen",
            {
                "p_application_id": application_id,
                "p_resource": resource,
                "p_sent": sent,
                "p_ttl_seconds": _DEDUP_TTL_SECONDS,
            },
        ).execute()
        # La RPC retorna boolean directo (no array). El cliente Supabase
        # devuelve `data` con el escalar.
        already = bool(res.data) if res.data is not None else False
        return already
    except Exception as exc:
        logger.warning("meli_webhook.dedup_rpc_failed err=%s — fallback local", exc)
        return _is_duplicate_event_local(application_id, resource, sent)


# ─── Alerta proactiva: rejected_origin threshold (B3 rev. 69) ────────────────

_alert_lock = threading.Lock()
_alert_counters: dict[str, list[float]] = {}


def _check_meli_origin_alert(ip: str) -> None:
    """Cuenta rechazos por IP en ventana deslizante. Si excede umbral, log warning.

    Razón B3: las 4 IPs MeLi están hardcoded como default. Si MeLi cambia las
    IPs, todos los webhooks fallan en silencio hasta que alguien revise logs.
    Aquí emitimos un log estructurado cuando excede umbral, para que el
    operador filtre por `meli_webhook.alert_threshold_exceeded` en Render
    Dashboard y revise la doc oficial MeLi.
    """
    if not ip:
        return
    threshold = int(os.getenv("MELI_WEBHOOK_ALERT_THRESHOLD", "5"))
    window = int(os.getenv("MELI_WEBHOOK_ALERT_WINDOW_SECONDS", "300"))
    now = time.time()
    with _alert_lock:
        timestamps = _alert_counters.get(ip, [])
        cutoff = now - window
        timestamps = [ts for ts in timestamps if ts >= cutoff]
        timestamps.append(now)
        _alert_counters[ip] = timestamps
        # Cleanup oportunista de IPs viejas que ya no acumulan rechazos.
        if len(_alert_counters) > 100:
            for k, tss in list(_alert_counters.items()):
                fresh = [ts for ts in tss if ts >= cutoff]
                if not fresh:
                    _alert_counters.pop(k, None)
                else:
                    _alert_counters[k] = fresh
        if len(timestamps) >= threshold:
            logger.warning(
                "meli_webhook.alert_threshold_exceeded ip=%s rejections=%d threshold=%d "
                "window=%ds — verificar IPs en https://developers.mercadolibre.com.co/es_ar/notificaciones",
                ip, len(timestamps), threshold, window,
            )


def _extract_request_ip(request: Request) -> str:
    """Extrae IP real del cliente. Prefiere x-forwarded-for[0] (LB Render)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        return request.client.host
    return ""


def _verify_meli_origin(request: Request, supabase=Depends(get_service_client)) -> None:
    """Dependency: valida origen IP + rate-limit. <1ms en happy path."""
    ip = _extract_request_ip(request)
    if ip not in _ALLOWED_MELI_IPS:
        ua = request.headers.get("user-agent", "")[:80]
        logger.warning("meli_webhook.rejected_origin ip=%s ua=%r", ip or "<empty>", ua)
        # Rev. 69 — alerta proactiva: log estructurado si excede umbral en ventana.
        _check_meli_origin_alert(ip)
        raise HTTPException(status_code=403, detail="Origen no autorizado")
    allowed, retry_after = webhook_rate_limit_check(
        supabase, ip=ip, bucket="webhook.meli", limit=200, window_seconds=60,
    )
    if not allowed:
        logger.warning("meli_webhook.rate_limited ip=%s retry_after=%s", ip, retry_after)
        raise HTTPException(
            status_code=429,
            detail="Rate limit excedido",
            headers={"Retry-After": str(retry_after)},
        )

# Mapeo de status MeLi (pedido) → status interno
MELI_ORDER_STATUS_MAP: dict[str, str] = {
    "confirmed":          "confirmed",
    "payment_required":   "pending",
    "payment_in_process": "pending",
    "partially_paid":     "pending",
    "paid":               "confirmed",
    "cancelled":          "cancelled",
}

# Rango monotónico de estados de orden (para no retroceder un pedido a un estado anterior).
# Compartido por _process_order y _process_shipment: MeLi mantiene order.status='paid' durante
# TODO el fulfillment, así que un orders_v2 tardío re-deriva 'confirmed' y NO debe pisar un
# estado más avanzado (shipped/delivered) que vino de _process_shipment. 'cancelled' es terminal.
_STATUS_RANK: dict[str, int] = {
    "pending": 0, "pending_payment": 0, "confirmed": 1,
    "processing": 2, "shipped": 3, "delivered": 4, "cancelled": 5,
}

# Mapeo de status MeLi (envío) → status de orden interno
# Solo se actualiza cuando el shipment avanza — no retrocede.
MELI_SHIPMENT_ORDER_STATUS_MAP: dict[str, str] = {
    "handling":      "processing",
    "ready_to_ship": "processing",
    "shipped":       "shipped",
    "delivered":     "delivered",
}


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _find_tenant_by_meli_user(meli_user_id: str, supabase) -> str | None:
    """Busca el tenant que tiene ese meli user_id en tenant_integrations.meta."""
    result = (
        supabase.table("tenant_integrations")  # tenant_filter:exempt:resolution_lookup_by_external_meli_user_id
        .select("tenant_id, meta")
        .eq("provider", "mercadolibre")
        .eq("status", "connected")
        .execute()
    )
    for row in (result.data or []):
        if str(row.get("meta", {}).get("user_id", "")) == str(meli_user_id):
            return row["tenant_id"]
    return None


# BLOQUE D item 3 (parte 2): el `resource` viene del cuerpo del webhook — que MeLi NO firma
# (ni HMAC ni JWT; la única defensa documentada es IP allowlist) — y se usa directo en
# `GET {MELI_API_URL}{resource}` con el access_token del seller. Sin validar, un webhook que
# pase el allowlist de IP podría apuntar ese GET autenticado a rutas arbitrarias de la API de
# MeLi (SSRF sobre la API del proveedor / creación de órdenes basura). Validar el `resource`
# contra un patrón estricto por tópico ANTES de cualquier fetch cierra ese vector — defensa en
# profundidad INDEPENDIENTE de la topología de proxies (el hardening del hop X-Forwarded-For
# queda pendiente de verificar el nº de proxies confiables de Render, ver ADR-0036).
# Prefijo estricto (el endpoint) + UN solo segmento sin `/`, `?` ni `#` para el id: bloquea el
# cambio de endpoint y el path-traversal (`/orders/../users/me`, `/users/me`) — que es el vector
# SSRF real — sin fail-closed frágil sobre el formato exacto del id (evita romper la ingesta si
# MeLi varía el id). Un id inválido simplemente 404 en MeLi; no puede redirigir a otro recurso.
_RESOURCE_PATTERNS: dict[str, "re.Pattern[str]"] = {
    "orders_v2": re.compile(r"^/orders/[^/?#]+$"),
    "items":     re.compile(r"^/items/[^/?#]+$"),
    "shipments": re.compile(r"^/shipments/[^/?#]+$"),
}


def _is_valid_resource(topic: str, resource: str) -> bool:
    """True si `resource` coincide con el patrón esperado para el tópico (que hace fetch)."""
    pat = _RESOURCE_PATTERNS.get(topic)
    return bool(pat and pat.match(resource or ""))


def _schedule_meli_sync(variation_id: str, new_stock: int, supabase) -> None:
    """Programa el push del nuevo stock a MeLi sin bloquear el decremento/reposición.

    Loop-aware (mismo patrón que orders._decrement_stock_on_confirm): usa el event loop
    activo (contexto async del webhook) o cae a un loop dedicado si no hay ninguno. Un
    fallo del sync a MeLi NO corrompe el stock local (ya persistido atómicamente por el RPC).
    """
    from routers.marketplace import sync_meli_stock
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(sync_meli_stock(variation_id, new_stock, supabase))
    except RuntimeError:
        try:
            asyncio.run(sync_meli_stock(variation_id, new_stock, supabase))
        except Exception as meli_err:
            logger.warning(
                "[MELI][STOCK] sync MeLi falló variation=%s (no bloquea): %s",
                variation_id, meli_err,
            )


async def _fetch_meli_resource(resource_path: str, access_token: str) -> dict | None:
    """GET al recurso indicado en la MeLi API."""
    url = f"{MELI_API_URL}{resource_path}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        if resp.status_code != 200:
            logger.warning("MeLi API %s → %d: %s", url, resp.status_code, resp.text[:200])
            return None
        return resp.json()


# ─── Identidad de canal (source + external_order_id) ─────────────────────────
# F3: los pedidos MeLi se correlacionan por (source='mercadolibre',
# external_order_id=<id MeLi>) — identidad estable inmune a que el operador
# edite las notas. Degradación segura: si la migración que añade esas columnas
# aún no está aplicada, caemos al match legacy por `notes` (prefijo).

_ORDERS_CHANNEL_COLS: dict[str, Optional[bool]] = {"available": None}


def _orders_channel_cols_available(supabase) -> bool:
    """Feature-detect de columnas orders.source / orders.external_order_id.

    Se prueba una sola vez por proceso y se cachea. Si las columnas no existen
    todavía (migración pendiente), el módulo sigue funcionando con el match por
    notes — sin romper la ingesta.
    """
    state = _ORDERS_CHANNEL_COLS
    if state["available"] is None:
        try:
            (
                supabase.table("orders")  # tenant_filter:exempt:schema_capability_probe
                .select("source, external_order_id")
                .limit(1)
                .execute()
            )
            state["available"] = True
        except Exception:
            state["available"] = False
    return bool(state["available"])


def _find_meli_order(supabase, tenant_id: str, meli_order_id: str):
    """Localiza la fila orders del pedido MeLi.

    Prefiere identidad estable (source + external_order_id). Cae al match por
    prefijo de notes para pedidos legacy o si la columna no existe todavía.
    Retorna dict {id, status} o None. Nunca lanza AttributeError sobre None
    (postgrest 2.28.3: maybe_single() → None en 0 filas).
    """
    if _orders_channel_cols_available(supabase):
        try:
            res = (
                supabase.table("orders")
                .select("id, status")
                .eq("tenant_id", tenant_id)
                .eq("source", "mercadolibre")
                .eq("external_order_id", str(meli_order_id))
                .maybe_single()
                .execute()
            )
            if res and res.data:
                return res.data
        except Exception as e:
            logger.warning("Lookup MeLi por external_order_id falló (%s) — fallback notes", e)
    # Fallback legacy por prefijo de notes.
    try:
        res = (
            supabase.table("orders")
            .select("id, status")
            .eq("tenant_id", tenant_id)
            .like("notes", f"MeLi order #{meli_order_id}%")
            .maybe_single()
            .execute()
        )
        return res.data if res else None
    except Exception as e:
        logger.warning("Lookup MeLi por notes falló para orden %s: %s", meli_order_id, e)
        return None


# ─── Procesamiento por tópico ────────────────────────────────────────────────

def _resolve_variation_ids(meli_item_ids: list[str], tenant_id: str, supabase) -> dict[str, str]:
    """
    Dado una lista de MeLi item IDs, retorna un mapa {meli_id: variation_id}
    buscando en marketplace_listings las variantes vinculadas del tenant.
    Items sin vínculo no aparecen en el resultado.
    """
    if not meli_item_ids:
        return {}
    try:
        result = (
            supabase.table("marketplace_listings")
            .select("external_id, variation_id")
            .eq("tenant_id", tenant_id)
            .eq("provider", "mercadolibre")
            .in_("external_id", meli_item_ids)
            .execute()
        )
        return {
            row["external_id"]: row["variation_id"]
            for row in (result.data or [])
            if row.get("variation_id")
        }
    except Exception as e:
        logger.warning("Error resolviendo variation_ids para items MeLi: %s", e)
        return {}


def _decrement_stock_for_meli_order(order_id: str, tenant_id: str, supabase) -> None:
    """Decrementa stock de un pedido MeLi (ATÓMICO e IDEMPOTENTE vía rpc_stock_decrement) +
    sincroniza con MeLi.

    BLOQUE D item 1 / item-4 continuación: reemplaza el read-modify-write en 3 llamadas
    separadas (SELECT→UPDATE→INSERT, race-prone) y la idempotencia coarse por-orden. Ahora la
    idempotencia es por (order_id, variation_id, 'sale') vía el índice único → un webhook MeLi
    duplicado / re-entrega no re-decrementa (cierra el oversell cross-canal). El clamp y el ledger
    consistente los garantiza el RPC (ADR-0035).
    """
    try:
        items_result = (
            supabase.table("order_items")
            .select("variation_id, quantity")
            .eq("order_id", order_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        # Agregar por variación (2 líneas de la misma variante colapsarían el idempotency key).
        agg: dict = {}
        for item in (items_result.data or []):
            vid = item.get("variation_id")
            qty = item.get("quantity", 0) or 0
            if vid and qty > 0:
                agg[vid] = agg.get(vid, 0) + int(qty)

        for variation_id, quantity in agg.items():
            try:
                _rpc = supabase.rpc("rpc_stock_decrement", {
                    "p_tenant_id": tenant_id,
                    "p_variation_id": variation_id,
                    "p_qty": int(quantity),
                    "p_order_id": order_id,
                    "p_reason": "sale",
                }).execute()
                new_stock = _rpc.data if isinstance(_rpc.data, int) else None
            except Exception as _dec_exc:
                logger.error(
                    "[MELI][STOCK] rpc_stock_decrement falló order=%s var=%s: %s",
                    order_id, variation_id, _dec_exc,
                )
                continue
            if new_stock is None:
                continue
            _schedule_meli_sync(variation_id, new_stock, supabase)
            logger.info("Stock variation %s → %d (orden MeLi %s)", variation_id, new_stock, order_id)

    except Exception as e:
        logger.error("Error decrementando stock para orden MeLi %s: %s", order_id, e)


def _restore_stock_for_meli_order(order_id: str, tenant_id: str, supabase) -> None:
    """Repone stock de un pedido MeLi CANCELADO (ATÓMICO e IDEMPOTENTE vía rpc_stock_restore) +
    sincroniza con MeLi.

    BLOQUE D item 4: antes una cancelación MeLi NUNCA reponía stock → inventario inflado
    permanente. Repone lo realmente decrementado (movimientos 'sale'/'reservation_consumed' de
    la orden); idempotente por (order_id, variation_id, 'cancellation_refund').
    """
    try:
        movements = (
            supabase.table("stock_movements")
            .select("variation_id, delta")
            .eq("tenant_id", tenant_id)
            .eq("order_id", order_id)
            .in_("reason", ["sale", "reservation_consumed"])
            .execute()
        ).data or []
        restore_by_var: dict = {}
        for mv in movements:
            vid = mv.get("variation_id")
            qty = abs(int(mv.get("delta") or 0))
            if vid and qty > 0:
                restore_by_var[vid] = restore_by_var.get(vid, 0) + qty

        for variation_id, qty in restore_by_var.items():
            try:
                _rpc = supabase.rpc("rpc_stock_restore", {
                    "p_tenant_id": tenant_id,
                    "p_variation_id": variation_id,
                    "p_qty": int(qty),
                    "p_order_id": order_id,
                    "p_reason": "cancellation_refund",
                }).execute()
                new_stock = _rpc.data if isinstance(_rpc.data, int) else None
            except Exception as _res_exc:
                logger.error(
                    "[MELI][STOCK] rpc_stock_restore falló order=%s var=%s: %s",
                    order_id, variation_id, _res_exc,
                )
                continue
            if new_stock is not None:
                _schedule_meli_sync(variation_id, new_stock, supabase)
                logger.info("Stock repuesto variation %s → %d (cancelación MeLi %s)", variation_id, new_stock, order_id)

    except Exception as e:
        logger.error("Error reponiendo stock para orden MeLi %s: %s", order_id, e)


def _upsert_meli_contact(
    buyer: dict,
    tenant_id: str,
    supabase,
    meli_order_id: Optional[str] = None,
) -> str | None:
    """
    Rev. 103 (SaaS B2B pivot) — crea o actualiza contact desde MeLi con
    consent_source='marketplace_meli' + audit log inmutable.

    Filosofía: el tenant operador es Responsable bajo DPA + Mercado Libre
    tiene su propia política de privacidad que cubre la captura del comprador.
    La plataforma marca el origen del dato (trazable ante SIC) y registra
    audit; no añade restricciones especiales sobre el flujo posterior.

    Retorna contact_id si hay teléfono disponible; None si no hay datos suficientes.
    MeLi expone phone en billing_info para vendedores verificados.
    """
    raw_phone = (
        (buyer.get("billing_info") or {}).get("phone")
        or buyer.get("phone")
        or None
    )
    # Rev. 104 (F0-4) — phone canon = digits-only (`to_db_format`). El
    # nombre del local var queda como `phone_canonical` para reflejar la
    # nueva semántica (antes `phone_e164` con `+` causaba BUG-2).
    phone_canonical = _normalize_phone_e164(raw_phone)
    if not phone_canonical:
        return None

    buyer_name = (
        f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
        or buyer.get("nickname")
        or None
    )
    now_iso = datetime.now(timezone.utc).isoformat()

    contact_payload = {
        "tenant_id": tenant_id,
        "phone": phone_canonical,
        "name": buyer_name,
        "consent_given": True,
        "consent_source": "marketplace_meli",
        "consent_date": now_iso,
        "consent_given_at": now_iso,   # F116: sync con la columna v2 que lee el export legal SAR/SIC
        "consent_channel": "marketplace_meli",
        "consent_notice_version": CURRENT_PRIVACY_NOTICE_VERSION,
        "consent_evidence": {
            "imported_from": "mercadolibre",
            "meli_order_id": meli_order_id,
            "captured_at": now_iso,
        },
        "consent_actor_email": "system:meli_webhook",
    }

    # Rev. 104 (F0-4) — Migración data legacy (rev. 103 D2 dejó filas con
    # `+57...` E.164). Si encontramos un contact con phone en formato legacy
    # (con '+'), lo migramos a canonical. La lógica anterior buscaba SIN '+'
    # asumiendo que el escrito era CON '+'; ahora se invierte.
    legacy_phone_with_plus = f"+{phone_canonical}"
    contact_id: Optional[str] = None
    try:
        legacy = (
            supabase.table("contacts")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("phone", legacy_phone_with_plus)
            .limit(1)
            .execute()
        )
        if legacy.data:
            contact_id = legacy.data[0]["id"]
            supabase.table("contacts").update(contact_payload).eq("id", contact_id).eq("tenant_id", tenant_id).execute()
        else:
            result = supabase.table("contacts").upsert(  # tenant_filter:exempt:upsert_on_conflict_tenant_id_phone
                contact_payload,
                on_conflict="tenant_id,phone",
            ).execute()
            contact_id = result.data[0]["id"] if result.data else None
    except Exception as e:
        logger.warning(
            "No se pudo crear/actualizar contacto MeLi (phone=%s): %s",
            phone_canonical, e,
        )
        return None

    # Audit log append-only — el tenant tiene trazabilidad del origen
    # MeLi y SIC puede consultar event='granted' con source='system'.
    # phone_hash invariante a presencia de `+` (la regex strip lo ignora).
    if contact_id:
        try:
            supabase.table("consent_audit_log").insert({
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "phone_hash": _hash_phone(phone_canonical),
                "event": "granted",
                "source": "system",
                "actor_email": "system:meli_webhook",
                "evidence": {
                    "imported_from": "mercadolibre",
                    "meli_order_id": meli_order_id,
                    "consent_source": "marketplace_meli",
                },
            }).execute()
        except Exception as e:
            logger.warning(
                "[MeLi] consent_audit_log insert falló contact=%s: %s",
                contact_id, e,
            )

    return contact_id


async def _process_order(resource: str, tenant_id: str, access_token: str, supabase):
    """
    Crea o actualiza un pedido MeLi en nuestra tabla orders.
    Al crear, vincula variation_id en order_items, crea contacto si hay teléfono
    y decrementa stock si el pedido llega confirmado/pagado desde MeLi.
    """
    order_data = await _fetch_meli_resource(resource, access_token)
    if not order_data:
        return

    meli_order_id   = str(order_data.get("id", ""))
    meli_status     = order_data.get("status", "")
    internal_status = MELI_ORDER_STATUS_MAP.get(meli_status, "pending")
    total_amount    = float(order_data.get("total_amount", 0))
    buyer           = order_data.get("buyer", {})
    buyer_name      = f"{buyer.get('first_name', '')} {buyer.get('last_name', '')}".strip()
    buyer_nickname  = buyer.get("nickname", "")
    notes           = f"MeLi order #{meli_order_id} · vendedor: {buyer_nickname or buyer_name}"

    existing = _find_meli_order(supabase, tenant_id, meli_order_id)

    if existing:
        old_status = existing["status"]
        # BLOQUE D (review B): avance de status MONOTÓNICO. Antes se pisaba el status con un
        # UPDATE incondicional → un orders_v2 tardío (order.status='paid' persiste durante todo
        # el fulfillment) REGRESABA shipped/delivered → confirmed, perdiendo el estado real de
        # envío que puso _process_shipment. Solo avanzar si el rank sube; 'cancelled' es terminal.
        advances = (
            internal_status == "cancelled"
            or _STATUS_RANK.get(internal_status, 0) > _STATUS_RANK.get(old_status, 0)
        )
        if advances and old_status != internal_status:
            supabase.table("orders").update({
                "status": internal_status,
            }).eq("id", existing["id"]).eq("tenant_id", tenant_id).execute()
            logger.info("Orden MeLi %s → status %s (tenant %s)", meli_order_id, internal_status, tenant_id)

        # BLOQUE D item 1 (review A): el decremento va DESACOPLADO del status write y NO se
        # llavea al old_status. MeLi no garantiza orden de webhooks: un shipments puede mover la
        # orden pending→processing (que NO decrementa) ANTES de llegar el 'paid', dejando
        # old_status='processing' cuando se sabe pagada → el guard viejo (old in pending/*) se
        # saltaba el decremento → oversell. Ahora decrementa la PRIMERA vez que se sabe pagada,
        # sea cual sea el estado previo; el RPC es idempotente por (order_id, variation_id,'sale')
        # → re-llamarlo sobre una orden ya decrementada es no-op (no doble-decremento).
        if internal_status == "confirmed" and old_status != "cancelled":
            _decrement_stock_for_meli_order(existing["id"], tenant_id, supabase)
        # BLOQUE D item 4 (+ review C): cancelación desde CUALQUIER estado ya decrementado
        # (incluye 'delivered') → reponer stock. El restore lee los movimientos 'sale' reales y
        # es idempotente → incluir 'delivered' es seguro (no-op si no hubo decremento previo).
        elif internal_status == "cancelled" and old_status in ("confirmed", "processing", "shipped", "delivered"):
            _restore_stock_for_meli_order(existing["id"], tenant_id, supabase)
    else:
        # Crear contacto si hay teléfono disponible
        contact_id = _upsert_meli_contact(buyer, tenant_id, supabase, meli_order_id=meli_order_id)

        # Resolver variation_id para cada item del pedido
        meli_order_items = order_data.get("order_items", [])
        meli_item_ids    = [item.get("item", {}).get("id", "") for item in meli_order_items if item.get("item", {}).get("id")]
        variation_map    = _resolve_variation_ids(meli_item_ids, tenant_id, supabase)

        order_payload = {
            "tenant_id":    tenant_id,
            "status":       internal_status,
            "total_amount": total_amount,
            "notes":        notes,
        }
        if contact_id:
            order_payload["contact_id"] = contact_id
        # F3: identidad estable del canal — solo si la migración ya añadió las
        # columnas (degradación segura hacia el match por notes).
        if _orders_channel_cols_available(supabase):
            order_payload["source"] = "mercadolibre"
            order_payload["external_order_id"] = meli_order_id

        order_result = supabase.table("orders").insert(order_payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id

        if order_result.data:
            new_order_id = order_result.data[0]["id"]

            items_to_insert = [
                {
                    "order_id":     new_order_id,
                    "tenant_id":    tenant_id,
                    "title":        item.get("item", {}).get("title", "Producto MeLi"),
                    "quantity":     item.get("quantity", 1),
                    "unit_price":   float(item.get("unit_price", 0)),
                    "variation_id": variation_map.get(item.get("item", {}).get("id", "")),
                }
                for item in meli_order_items
            ]
            if items_to_insert:
                supabase.table("order_items").insert(items_to_insert).execute()  # tenant_filter:exempt:payload_includes_tenant_id

            # Decrementar stock si el pedido llega ya confirmado/pagado
            if internal_status == "confirmed":
                _decrement_stock_for_meli_order(new_order_id, tenant_id, supabase)

            logger.info("Orden MeLi %s creada → id %s, status=%s, contact=%s (tenant %s)",
                        meli_order_id, new_order_id, internal_status, contact_id, tenant_id)


async def _process_shipment(resource: str, tenant_id: str, access_token: str, supabase):
    """
    Actualiza el estado de la orden asociada al envío y persiste el tracking.

    MeLi envía el shipment_id en el recurso. El shipment contiene order_id,
    que usamos para buscar la orden en Supabase por su campo notes.

    Solo avanza el estado — nunca retrocede (shipped no vuelve a processing).
    El tracking (tracking_number, carrier, estimated_delivery) se persiste en
    order_tracking independientemente del avance de estado de la orden.
    """
    shipment_data = await _fetch_meli_resource(resource, access_token)
    if not shipment_data:
        return

    shipment_id     = str(shipment_data.get("id", ""))
    shipment_status = shipment_data.get("status", "")
    meli_order_id   = str(shipment_data.get("order_id", ""))

    if not meli_order_id:
        logger.info("Shipment MeLi %s sin order_id — sin acción", shipment_id)
        return

    # Buscar la orden por identidad de canal (source+external_order_id) con
    # fallback a notes — helper único, sin AttributeError sobre None.
    existing = _find_meli_order(supabase, tenant_id, meli_order_id)
    order_id = existing["id"] if existing else None

    # Actualizar estado de la orden si el shipment implica un avance
    new_order_status = MELI_SHIPMENT_ORDER_STATUS_MAP.get(shipment_status)
    if order_id and new_order_status:
        current_status = existing["status"]
        if _STATUS_RANK.get(new_order_status, 0) > _STATUS_RANK.get(current_status, 0):
            supabase.table("orders").update({
                "status": new_order_status,
            }).eq("id", order_id).eq("tenant_id", tenant_id).execute()
            logger.info("Orden MeLi %s → status %s (vía shipment %s, tenant %s)",
                        meli_order_id, new_order_status, shipment_id, tenant_id)
        else:
            logger.info("Shipment MeLi %s: estado %s no avanza sobre %s — omitido",
                        shipment_id, new_order_status, current_status)
    elif not existing:
        logger.warning("Shipment MeLi %s: no se encontró orden para MeLi order #%s (tenant %s)",
                       shipment_id, meli_order_id, tenant_id)

    # Persistir tracking en order_tracking (aunque la orden no haya avanzado de estado)
    if order_id and shipment_id:
        tracking_number = shipment_data.get("tracking_number")
        carrier         = (shipment_data.get("shipping_option") or {}).get("name")
        tracking_url    = shipment_data.get("tracking_url")

        estimated_delivery = None
        est_final = shipment_data.get("estimated_delivery_final") or {}
        if est_final.get("date"):
            try:
                estimated_delivery = str(est_final["date"])[:10]   # YYYY-MM-DD
            except Exception:
                pass

        try:
            existing_tracking = (
                supabase.table("order_tracking")
                .select("id")
                .eq("tenant_id", tenant_id)
                .eq("provider", "mercadolibre")
                .eq("external_id", shipment_id)
                .maybe_single()
                .execute()
            )
            tracking_payload = {
                "tenant_id":          tenant_id,
                "order_id":           order_id,
                "provider":           "mercadolibre",
                "external_id":        shipment_id,
                "status":             shipment_status,
                "tracking_number":    tracking_number,
                "tracking_url":       tracking_url,
                "carrier":            carrier,
                "estimated_delivery": estimated_delivery,
                "raw":                shipment_data,
            }
            if existing_tracking and existing_tracking.data:  # F-doc: maybe_single() → None en 0 filas (postgrest 2.28.3)
                supabase.table("order_tracking").update(tracking_payload).eq(
                    "id", existing_tracking.data["id"]
                ).eq("tenant_id", tenant_id).execute()
            else:
                supabase.table("order_tracking").insert(tracking_payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
            logger.info("Tracking MeLi shipment %s → %s (orden %s)", shipment_id, shipment_status, order_id)
        except Exception as track_err:
            logger.warning("No se pudo persistir tracking MeLi shipment %s: %s", shipment_id, track_err)


async def _process_notification(topic: str, resource: str, meli_user_id: str):
    """Procesamiento asíncrono de la notificación MeLi."""
    supabase = _get_service_client()

    tenant_id = await _find_tenant_by_meli_user(meli_user_id, supabase)
    if not tenant_id:
        logger.info("Webhook MeLi ignorado: meli_user_id=%s sin tenant asociado", meli_user_id)
        return

    access_token = await meli_client.get_valid_token(supabase, tenant_id)
    if not access_token:
        logger.error("No hay token MeLi válido para tenant %s", tenant_id)
        return

    # BLOQUE D item 3: rechazar resources malformados de los tópicos que hacen fetch ANTES
    # del GET autenticado (evita apuntar el token del seller a rutas arbitrarias de la API).
    if topic in _RESOURCE_PATTERNS and not _is_valid_resource(topic, resource):
        logger.warning(
            "meli_webhook.resource_rejected topic=%s resource=%r — no coincide con el patrón esperado (posible spoof)",
            topic, resource,
        )
        return

    if topic == "orders_v2":
        await _process_order(resource, tenant_id, access_token, supabase)
    elif topic == "items":
        item_data = await _fetch_meli_resource(resource, access_token)
        if item_data:
            supabase.table("marketplace_listings").update({
                "status":          item_data.get("status", "active"),
                "external_price":  item_data.get("price"),
                "meli_title":      item_data.get("title"),
                "meli_thumbnail":  item_data.get("thumbnail"),
                "meli_condition":  item_data.get("condition"),
                "meli_category_id": item_data.get("category_id"),
                "meli_attributes": item_data.get("attributes"),
                "synced_at":       datetime.now(timezone.utc).isoformat(),
            }).eq("tenant_id", tenant_id).eq("external_id", item_data.get("id")).execute()
            logger.info("Listing MeLi %s → status %s (pull completo, tenant %s)",
                        item_data.get("id"), item_data.get("status"), tenant_id)
    elif topic == "shipments":
        await _process_shipment(resource, tenant_id, access_token, supabase)
    else:
        logger.info("Tópico MeLi no manejado: %s", topic)


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post("/webhook", dependencies=[Depends(_verify_meli_origin)])
async def meli_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    supabase=Depends(get_service_client),
):
    """
    Recibe notificaciones IPN de MeLi.
    Retorna 200 inmediatamente y procesa en background.
    MeLi reintenta hasta 8 veces si no recibe 200 en 500ms.

    Rev. 69 — idempotencia distribuida via Supabase RPC `meli_webhook_seen`,
    coherente cross-réplica.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": True})

    topic        = body.get("topic", "")
    resource     = body.get("resource", "")
    meli_user_id = str(body.get("user_id", ""))
    application_id = str(body.get("application_id", ""))
    sent         = str(body.get("sent", ""))

    logger.info("Webhook MeLi — topic=%s resource=%s user_id=%s", topic, resource, meli_user_id)

    if not (topic and resource and meli_user_id):
        return JSONResponse({"ok": True})

    if _is_duplicate_event(application_id, resource, sent, supabase):
        logger.info("meli_webhook.duplicate_skipped resource=%s sent=%s", resource, sent)
        return JSONResponse({"ok": True, "duplicate": True})

    background_tasks.add_task(_process_notification, topic, resource, meli_user_id)
    return JSONResponse({"ok": True})
