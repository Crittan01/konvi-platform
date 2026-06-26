"""
Cliente HTTP para la API de Wompi Colombia.

Referencia oficial: https://docs.wompi.co/en/docs/colombia/
Validado: 2026-04-24

Ambientes:
  Sandbox:    https://sandbox.wompi.co/v1
  Producción: https://production.wompi.co/v1

Algoritmo de firma webhook: SHA256 simple sobre string concatenado
(no HMAC) — ver verify_event_signature().

Credenciales: por-tenant en tenant_integrations (provider='wompi'),
almacenadas en Supabase Vault. No se usan env vars globales.

H.3.1 — Estado de exposición HTTP (cierre 2026-05-29):
    Las funciones get_transaction_sync(), get_transaction() async y
    get_transaction_with_resilience() son API INTERNA lista para callers
    Python (cron de reconciliation, scripts admin, background jobs).
    NO existe endpoint HTTP público GET /api/v1/wompi/transactions/{id} —
    decisión arquitectónica Sem 4 (2026-05-06) + cierre 2026-05-29 documentado
    en docs/reports/h31_wompi_get_transaction_closure.md. NO eliminar estas
    funciones: son contract estable para cuando se diseñe la UI
    "Reconciliar pago" o el cron de reconciliación background.
"""
import hashlib
import logging
from typing import Any, Optional, Tuple

import httpx

from lib.phone import is_valid_co as _phone_is_valid_co
from lib.phone import to_canonical as _phone_to_canonical  # rev. 104 F0-4

logger = logging.getLogger(__name__)

WOMPI_SANDBOX_URL = "https://sandbox.wompi.co/v1"
WOMPI_PROD_URL = "https://production.wompi.co/v1"

REQUEST_TIMEOUT_SECONDS = 15


def wompi_base_url(environment: str) -> str:
    return WOMPI_PROD_URL if environment == "production" else WOMPI_SANDBOX_URL


def get_tenant_wompi_creds(supabase, tenant_id: str) -> Tuple[Optional[str], Optional[str], str]:
    """
    Lee private_key, events_key y environment desde tenant_integrations (Vault).
    Retorna (private_key, events_key, environment).
    Retorna (None, None, "sandbox") si el tenant no tiene Wompi configurado.
    """
    try:
        from vault_helper import VaultHelper, resolve_secret
        res = (
            supabase.table("tenant_integrations")
            .select("credentials, meta, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "wompi")
            .eq("status", "connected")
            .maybe_single()
            .execute()
        )
        if not res.data:
            return None, None, "sandbox"

        creds = res.data.get("credentials", {})
        meta = res.data.get("meta", {})
        environment = meta.get("environment", "sandbox")

        vault = VaultHelper(supabase)
        private_key = resolve_secret(vault, creds, "private_key")
        events_key = resolve_secret(vault, creds, "events_key")

        return private_key, events_key, environment
    except Exception as e:
        logger.error("[WOMPI] error_leyendo_creds tenant=%s error=%s", tenant_id, e)
        return None, None, "sandbox"


def verify_event_signature(payload: dict, events_key: str) -> bool:
    """
    Valida la firma de un evento webhook de Wompi.

    Algoritmo oficial (SHA256 simple, no HMAC):
      1. Concatenar valores de signature.properties en orden
      2. Concatenar timestamp (entero Unix)
      3. Concatenar events_key
      4. SHA256 del string completo
      5. Comparar con signature.checksum

    Referencia: https://docs.wompi.co/en/docs/colombia/eventos/
    """
    if not events_key:
        logger.error("[WOMPI] events_key no configurada — rechazando evento")
        return False

    sig = payload.get("signature", {})
    properties = sig.get("properties", [])
    expected_checksum = sig.get("checksum", "")
    timestamp = payload.get("timestamp", 0)

    if not expected_checksum or not properties:
        logger.warning("[WOMPI] Payload sin signature.properties o checksum")
        return False

    # Wompi (CO docs sept-2024+) envía properties relativas a `data` —
    # ej. "transaction.id" se extrae de payload["data"]["transaction"]["id"],
    # NO de payload["transaction"]["id"]. Pero docs antiguos podían usar
    # paths absolutos. Intentamos ambos: primero data-relative, después
    # root. El que produzca valores no-vacíos es el correcto.
    def _traverse(root: object, dotted_path: str) -> str:
        cur: object = root
        for key in dotted_path.split("."):
            if isinstance(cur, dict):
                cur = cur.get(key, "")
            else:
                return ""
        if cur is None:
            return ""
        return str(cur)

    data_root = payload.get("data") if isinstance(payload, dict) else None

    parts: list[str] = []
    for prop in properties:
        v_data = _traverse(data_root, prop) if isinstance(data_root, dict) else ""
        v_root = _traverse(payload, prop)
        # Preferir el path data-relative si aporta valor; root como fallback
        # (compat con eventos legacy o non-data-wrapped en pruebas).
        chosen = v_data if v_data else v_root
        parts.append(chosen)

    concat = "".join(parts) + str(timestamp) + events_key
    computed = hashlib.sha256(concat.encode()).hexdigest().upper()
    valid = computed == expected_checksum.upper()

    if not valid:
        # Diagnóstico: log de las properties usadas (sin secrets) para
        # facilitar debugging si falla en producción.
        _props_preview = ", ".join(
            f"{p}={v[:24]}…" if len(v) > 24 else f"{p}={v}"
            for p, v in zip(properties, parts)
        )
        logger.warning(
            "[WOMPI] Firma inválida. computed=%s received=%s ts=%s props=[%s]",
            computed[:12] + "...",
            expected_checksum[:12] + "...",
            timestamp,
            _props_preview,
        )
    return valid


# Tipos de documento aceptados en customer_data Wompi (CO). La doc pública
# lista CC/CE/NIT explícitamente para PSE; PP/TI/OTHER son aceptados en
# práctica por el endpoint payment_links. Mantenemos el set completo del
# repo (rev. 68) porque está validado en producción contra Wompi sandbox+prod
# desde 2026-04. Si Wompi cambia la política y devuelve 422 para alguno,
# se ajusta acá puntualmente — no pre-mapeamos silenciosamente.
_WOMPI_LEGAL_ID_TYPES_ACCEPTED = {"CC", "CE", "NIT", "PP", "TI", "OTHER"}


def _build_customer_data(contact: Optional[dict]) -> Optional[dict]:
    """Construye el bloque customer_data Wompi a partir del contacto.

    ⚠️ NO USAR EN /v1/payment_links (Sem 7 F2 cierre, 2026-05-19).

    Reconfirmado en doc oficial Wompi
    (https://docs.wompi.co/en/docs/colombia/links-de-pago/): el campo
    ``customer_data`` del endpoint ``POST /v1/payment_links`` SOLO acepta
    ``customer_references`` (array máx 2 de ``{label, is_required}``)
    para campos custom adicionales. NO acepta email/full_name/phone_number/
    legal_id para pre-poblar el formulario del checkout hosted — Wompi
    ignora silenciosamente cualquier otra clave.

    Este builder queda preservado para FUTURA migración a:
      - Widget & Checkout Web (JS embebido en página propia, requiere
        storefront I.1 — diferido por decisión founder 2026-05-05).
      - POST /v1/transactions directo (Third-Party Payments API, requiere
        cerrar gap Habeas Data H.3.8 acceptance_token).

    Reglas (rev. 68, validadas contra schema teórico de Widget/Transactions):
      - Solo se incluyen claves con valor.
      - ``legal_id_type`` se envía tal cual dentro del set aceptado.
      - ``phone_number_prefix`` separado (ej. ``+57``).
    """
    if not contact:
        return None
    cd: dict = {}

    # Email (lowercase normalizado upstream)
    email = (contact.get("email") or "").strip()
    if email:
        cd["email"] = email

    full_name = (contact.get("name") or "").strip()
    if full_name:
        cd["full_name"] = full_name

    # Teléfono Wompi: requiere split prefix + number según schema oficial
    # (https://docs.wompi.co/docs/colombia/widget-checkout-web/).
    # Rev. 104 (F0-4): leemos canon (digits-only, alineado con DB) y
    # convertimos a la forma que Wompi espera. `to_canonical` tolera tanto
    # legacy '+57...' como nuevo '57...'.
    raw_phone = contact.get("phone") or ""
    canonical = _phone_to_canonical(raw_phone)
    if canonical:
        if _phone_is_valid_co(canonical):
            cd["phone_number_prefix"] = "+57"
            cd["phone_number"] = canonical[2:]  # quita '57'
        else:
            # No-CO: Wompi puede aceptarlo sin prefix o rechazar; entregamos
            # los dígitos tal cual y dejamos que Wompi valide.
            cd["phone_number"] = canonical

    # Documento: ambos juntos o ninguno (regla Wompi).
    doc_type_raw = (contact.get("document_type") or "").strip().upper()
    doc_num = (contact.get("document_number") or "").strip()
    if doc_type_raw and doc_num and doc_type_raw in _WOMPI_LEGAL_ID_TYPES_ACCEPTED:
        cd["legal_id"] = doc_num
        cd["legal_id_type"] = doc_type_raw

    return cd or None


def create_payment_link_sync(
    *,
    private_key: str,
    environment: str,
    order_id: str,
    name: str,
    description: str,
    amount_in_cents: int,
    expires_at: str,
    redirect_url: Optional[str] = None,
    contact: Optional[dict] = None,
) -> dict:
    """
    Versión síncrona de create_payment_link — para BackgroundTasks y webhooks síncronos.

    Param ``contact``: aceptado por compat con caller (rev. 68 lo pasaba para
    pre-poblar customer_data en checkout). Sem 7 F2 cierre 2026-05-19: doc
    oficial Wompi confirma que /v1/payment_links NO pre-popula comprador desde
    ``customer_data`` (ese campo solo acepta ``customer_references`` custom).
    El parámetro permanece en la firma por estabilidad de callers; el dato
    queda preservado para futura migración a Widget Web / /transactions.
    """
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")

    base_url = wompi_base_url(environment)
    payload = {
        "name": name[:100],
        "description": description[:255],
        "single_use": True,
        "collect_shipping": False,
        "amount_in_cents": amount_in_cents,
        "currency": "COP",
        "expires_at": expires_at,
        "sku": order_id,
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url
    # Sem 7 F2 cierre — NO enviar customer_data al endpoint /v1/payment_links.
    # Doc oficial Wompi confirma que ese campo solo acepta customer_references
    # (campos custom), NO pre-popula comprador. Cliente tipea email/nombre/
    # celular en el checkout hosted (~10s friction aceptable para WhatsApp
    # commerce). Builder _build_customer_data preservado para futura
    # migración a Widget Web / /transactions directo.
    # Ver docstring de _build_customer_data para detalles.

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(
            f"{base_url}/payment_links",
            headers={"Authorization": f"Bearer {private_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json().get("data", {})

    link_id = data.get("id", "")
    return {
        "link_id": link_id,
        "checkout_url": f"https://checkout.wompi.co/l/{link_id}",
        "active": data.get("active", False),
        "amount_in_cents": data.get("amount_in_cents"),
        "expires_at": data.get("expires_at"),
    }


async def create_payment_link(
    *,
    private_key: str,
    environment: str,
    order_id: str,
    name: str,
    description: str,
    amount_in_cents: int,
    expires_at: str,
    redirect_url: Optional[str] = None,
    contact: Optional[dict] = None,
) -> dict:
    """
    Crea un link de pago en Wompi.

    Campos requeridos por Wompi: name, description, single_use, collect_shipping.
    Correlación orden↔pago: order_id en campo `sku` (UUID v4 = 36 chars exactos).

    Param ``contact``: aceptado por compat con caller (rev. 68 lo pasaba para
    pre-poblar customer_data en checkout). Sem 7 F2 cierre 2026-05-19: doc
    oficial Wompi confirma que /v1/payment_links NO pre-popula comprador desde
    ``customer_data`` (ese campo solo acepta ``customer_references`` custom).
    El parámetro permanece en la firma por estabilidad de callers; el dato
    queda preservado para futura migración a Widget Web / /transactions.

    Returns dict con:
      - link_id: str (id del payment link)
      - checkout_url: str (https://checkout.wompi.co/l/{id})
      - active: bool
    Raises httpx.HTTPStatusError on HTTP errors.
    """
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")

    base_url = wompi_base_url(environment)
    payload = {
        "name": name[:100],
        "description": description[:255],
        "single_use": True,
        "collect_shipping": False,
        "amount_in_cents": amount_in_cents,
        "currency": "COP",
        "expires_at": expires_at,
        "sku": order_id,  # UUID v4 = 36 chars, cabe exacto en el campo
    }
    if redirect_url:
        payload["redirect_url"] = redirect_url
    # Sem 7 F2 cierre — NO enviar customer_data al endpoint /v1/payment_links.
    # (Ver docstring de _build_customer_data para justificación completa.)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{base_url}/payment_links",
            headers={"Authorization": f"Bearer {private_key}"},
            json=payload,
        )
        response.raise_for_status()
        data = response.json().get("data", {})

    link_id = data.get("id", "")
    return {
        "link_id": link_id,
        "checkout_url": f"https://checkout.wompi.co/l/{link_id}",
        "active": data.get("active", False),
        "amount_in_cents": data.get("amount_in_cents"),
        "expires_at": data.get("expires_at"),
    }


# ─── Rev. 105 Sem 4 H.3.1 — GET transaction (audit + reconciliation) ─────────
# Permite consultar directamente el estado de una transacción a Wompi sin
# depender del webhook. Cierra el riesgo P0 documentado en dossier Wompi
# 2026-05-05 sec. 6: Wompi reintenta webhooks 30min/3h/24h pero NO garantiza
# delivery. Si los retries fallan (red caída del lado nuestro), la orden
# queda en PENDING aunque el cliente sí pagó. Este endpoint permite
# reconciliar estado consultando Wompi directamente.
#
# Endpoint Wompi: GET /transactions/{id} — pública, requiere Bearer pub_key
# o prv_key. Documentación: https://docs.wompi.co/docs/colombia/transacciones/

def get_transaction_sync(
    *,
    private_key: str,
    environment: str,
    transaction_id: str,
) -> dict:
    """Consulta una transacción Wompi por ID. Síncrona — para scripts admin
    y reconciliation desde BackgroundTasks.

    Retorna el objeto transaction completo de Wompi:
        {
            "id": "01-1538687528-49201",
            "amount_in_cents": 4490000,
            "reference": "MZQ3X2",
            "customer_email": "...",
            "currency": "COP",
            "payment_method_type": "NEQUI",
            "redirect_url": "...",
            "status": "APPROVED" | "DECLINED" | "VOIDED" | "ERROR" | "PENDING",
            "status_message": "...",
            ...
        }

    Levanta httpx.HTTPStatusError si Wompi 4xx/5xx (caller decide manejo).
    Wompi 404 = transaction_id inválido o no existe en este merchant.
    """
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")
    if not transaction_id or not transaction_id.strip():
        raise ValueError("transaction_id no puede ser vacío")

    base_url = wompi_base_url(environment)
    url = f"{base_url}/transactions/{transaction_id.strip()}"

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.get(
            url,
            headers={"Authorization": f"Bearer {private_key}"},
        )
        if response.status_code >= 400:
            logger.error(
                "[WOMPI] GET /transactions/%s %d: %s",
                transaction_id, response.status_code, response.text[:300],
            )
        response.raise_for_status()
        data = response.json().get("data", {})
        if not isinstance(data, dict):
            logger.warning(
                "[WOMPI] GET transaction %s: data no es dict: %s",
                transaction_id, type(data).__name__,
            )
            return {}
        return data


async def get_transaction(
    *,
    private_key: str,
    environment: str,
    transaction_id: str,
) -> dict:
    """Async version para llamadas desde request handlers FastAPI."""
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")
    if not transaction_id or not transaction_id.strip():
        raise ValueError("transaction_id no puede ser vacío")

    base_url = wompi_base_url(environment)
    url = f"{base_url}/transactions/{transaction_id.strip()}"

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {private_key}"},
        )
        if response.status_code >= 400:
            logger.error(
                "[WOMPI] GET /transactions/%s %d: %s",
                transaction_id, response.status_code, response.text[:300],
            )
        response.raise_for_status()
        data = response.json().get("data", {})
        if not isinstance(data, dict):
            return {}
        return data


# ─── Rev. 109 — Wompi void (anulación pre-settlement) ───────────────────────
#
# POST /v1/transactions/{id}/void
# Documentación: docs/research/wompi-dossier-2026-05-05.md sec H.3.2.
#
# REALIDAD CRUDA:
#   • Wompi NO tiene API de refund pública. Solo `void`.
#   • Void aplica SOLO a tarjetas (CARD) ANTES de settlement (~24-48h).
#   • NEQUI, PSE, Bancolombia: NO se pueden voidear (fondos ya transferidos).
#   • Post-settlement: refund manual dashboard Wompi o soporte Bancolombia.
#
# Esta función intenta el void. Si no aplica (método ≠ CARD o ventana vencida),
# Wompi retorna 4xx — el caller debe marcar refund_pending_manual + notificar
# operador. NO se debe insistir.


def void_transaction_sync(
    *,
    private_key: str,
    environment: str,
    transaction_id: str,
) -> dict:
    """Intenta anular una transacción Wompi (pre-settlement, solo CARD).

    Args:
        private_key: clave prv_* del tenant.
        environment: 'sandbox' | 'production'.
        transaction_id: ID Wompi de la transacción a anular.

    Returns:
        dict con respuesta Wompi:
            {
                "id": "01-1538687528-49201",
                "status": "VOIDED",      # o el status actual si rechaza
                "amount_in_cents": ...,
                "voided_at": "...",
            }

    Raises:
        ValueError si args inválidos.
        httpx.HTTPStatusError si Wompi rechaza:
          • 422 Unprocessable Entity — método ≠ CARD o post-settlement.
          • 404 — transaction_id no existe.
          • 401 — private_key inválida.
        Caller debe interpretar el código:
          • 422 → fallback refund manual (operador dashboard).
          • 5xx → retry posible vía void_transaction_sync_with_resilience.
    """
    if not private_key:
        raise ValueError("private_key Wompi no configurada para este tenant")
    if not transaction_id or not transaction_id.strip():
        raise ValueError("transaction_id no puede ser vacío")

    base_url = wompi_base_url(environment)
    url = f"{base_url}/transactions/{transaction_id.strip()}/void"

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {private_key}",
                "Content-Type": "application/json",
            },
            json={},  # Wompi void no requiere payload, pero acepta body vacío.
        )
        if response.status_code >= 400:
            logger.error(
                "[WOMPI] POST /transactions/%s/void %d: %s",
                transaction_id, response.status_code, response.text[:300],
            )
        response.raise_for_status()
        data = response.json().get("data", {})
        if not isinstance(data, dict):
            logger.warning(
                "[WOMPI] void %s: data no es dict: %s",
                transaction_id, type(data).__name__,
            )
            return {}
        logger.info(
            "[WOMPI] void OK txn=%s new_status=%s",
            transaction_id, data.get("status", "?"),
        )
        return data


def is_void_eligible(payment_method_type: str, paid_at_iso: str | None) -> bool:
    """Heurística pre-call: ¿este pago es elegible para void?

    Reglas (dossier Wompi sec H.3.2):
      • Método debe ser CARD (Visa/Mastercard/Amex).
      • Tiempo desde captura < 24h (settlement window típico Bancolombia).

    NO es garantía — Wompi puede rechazar igual si captura cerró antes.
    Sirve como GATE PRE-CALL para evitar 422 cuando ya sabemos que no aplica.

    Args:
        payment_method_type: 'CARD' | 'NEQUI' | 'PSE' | 'BANCOLOMBIA_TRANSFER'
        paid_at_iso: cuando se aprobó el pago (ISO 8601). None si desconocido.

    Returns:
        True si TODOS los gates pasan; False si claramente no aplica.
    """
    if (payment_method_type or "").upper() != "CARD":
        return False
    if not paid_at_iso:
        # Sin timestamp = optimista, intentamos.
        return True
    try:
        from datetime import datetime, timedelta, timezone
        paid_at = datetime.fromisoformat(paid_at_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        # Ventana conservadora 23h para no llegar al borde de settlement.
        return (now - paid_at) < timedelta(hours=23)
    except Exception:
        return True  # Defensive: intentar si no podemos parsear timestamp.


# ─── Rev. 105 Sem 4 H.3.2 — Retry + Circuit Breaker (resilience) ─────────────
# Wrappers opt-in sobre create_payment_link / get_transaction / etc. que
# agregan:
#   - Retry exponential backoff + jitter (3 intentos default) ante 5xx /
#     network / timeout
#   - Circuit breaker per-tenant (opcional, evita gastar tiempo si Wompi
#     está caído)
#
# NO modifica los wrappers originales — callers actuales siguen funcionando.
# Para activar resilience en una callsite, cambiar:
#   create_payment_link_sync(...)  →  create_payment_link_sync_with_resilience(...)
#
# Cierra riesgo P0 dossier Wompi 2026-05-05 sec. 6: outages temporales de
# Wompi causaban falla inmediata en primer intento; con retry el flow se
# recupera; con CB damos UX claro al cliente cuando Wompi está caído real.

from typing import TypeVar as _TypeVar

_T = _TypeVar("_T")


def _is_retriable_wompi(error: Exception) -> bool:
    """5xx + network + timeout → retry. 4xx (validación) → no retry."""
    # httpx.HTTPStatusError tiene .response.status_code
    if hasattr(error, "response"):
        try:
            status = error.response.status_code  # type: ignore
            if 500 <= status < 600:
                return True
            return False  # 4xx no retriable
        except AttributeError:
            pass
    # Otros errores (timeout, connection, etc.) → retry.
    return True


def create_payment_link_sync_with_resilience(
    *,
    private_key: str,
    environment: str,
    order_id: str,
    name: str,
    description: str,
    amount_in_cents: int,
    expires_at: str,
    redirect_url: Optional[str] = None,
    contact: Optional[dict] = None,
    max_attempts: int = 3,
    circuit_breaker: Optional[Any] = None,
) -> dict:
    """Versión resiliente de create_payment_link_sync con retry + opcional
    circuit breaker. Para callsites que toleran latencia adicional (BackgroundTasks).

    circuit_breaker: instancia opcional de
        services.api.lib.integration_client.CircuitBreaker. Si pasada, abre
        tras N fallos consecutivos y levanta CircuitOpenError; caller debe
        manejar (mostrar error UX-claro al cliente, encolar pgmq, etc.).
    """
    from lib.integration_client.retry import RetryPolicy, retry_sync  # noqa: PLC0415

    if circuit_breaker is not None:
        circuit_breaker.before_request("wompi")

    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay_seconds=1.0,
        max_delay_seconds=15.0,
        jitter_seconds=0.5,
    )

    def _do() -> dict:
        return create_payment_link_sync(
            private_key=private_key,
            environment=environment,
            order_id=order_id,
            name=name,
            description=description,
            amount_in_cents=amount_in_cents,
            expires_at=expires_at,
            redirect_url=redirect_url,
            contact=contact,
        )

    try:
        result = retry_sync(_do, policy=policy, is_retriable=_is_retriable_wompi)
        if circuit_breaker is not None:
            circuit_breaker.record_success("wompi")
        return result
    except Exception:
        if circuit_breaker is not None:
            circuit_breaker.record_failure("wompi")
        raise


async def create_payment_link_with_resilience(
    *,
    private_key: str,
    environment: str,
    order_id: str,
    name: str,
    description: str,
    amount_in_cents: int,
    expires_at: str,
    redirect_url: Optional[str] = None,
    contact: Optional[dict] = None,
    max_attempts: int = 3,
    circuit_breaker: Optional[Any] = None,
) -> dict:
    """Versión async resiliente. Mismo contrato que create_payment_link
    con retry + opcional circuit breaker."""
    from lib.integration_client.retry import RetryPolicy, retry_async  # noqa: PLC0415

    if circuit_breaker is not None:
        circuit_breaker.before_request("wompi")

    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay_seconds=1.0,
        max_delay_seconds=15.0,
        jitter_seconds=0.5,
    )

    async def _do() -> dict:
        return await create_payment_link(
            private_key=private_key,
            environment=environment,
            order_id=order_id,
            name=name,
            description=description,
            amount_in_cents=amount_in_cents,
            expires_at=expires_at,
            redirect_url=redirect_url,
            contact=contact,
        )

    try:
        result = await retry_async(_do, policy=policy, is_retriable=_is_retriable_wompi)
        if circuit_breaker is not None:
            circuit_breaker.record_success("wompi")
        return result
    except Exception:
        if circuit_breaker is not None:
            circuit_breaker.record_failure("wompi")
        raise


async def get_transaction_with_resilience(
    *,
    private_key: str,
    environment: str,
    transaction_id: str,
    max_attempts: int = 3,
    circuit_breaker: Optional[Any] = None,
) -> dict:
    """Versión resiliente de get_transaction. Útil para reconciliation
    background jobs donde puede tolerarse algo más de latencia ante
    outages."""
    from lib.integration_client.retry import RetryPolicy, retry_async  # noqa: PLC0415

    if circuit_breaker is not None:
        circuit_breaker.before_request("wompi")

    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay_seconds=1.0,
        max_delay_seconds=10.0,
        jitter_seconds=0.5,
    )

    async def _do() -> dict:
        return await get_transaction(
            private_key=private_key,
            environment=environment,
            transaction_id=transaction_id,
        )

    try:
        result = await retry_async(_do, policy=policy, is_retriable=_is_retriable_wompi)
        if circuit_breaker is not None:
            circuit_breaker.record_success("wompi")
        return result
    except Exception:
        if circuit_breaker is not None:
            circuit_breaker.record_failure("wompi")
        raise
