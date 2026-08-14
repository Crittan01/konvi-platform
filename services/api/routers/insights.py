"""
Router de Insights IA — espejo server-side de /api/insights (web).

G20 (drift D3): mueve la agregación Supabase + prompt a Gemini del route
handler Next.js al servicio `api` para retirar GEMINI_API_KEY del entorno web.
El handler del web queda como proxy (misma URL pública, el panel no se entera).

Endpoints:
  POST /api/v1/insights          — genera el análisis de un módulo
                                   (inventory/orders/contacts/metrics).
  GET  /api/v1/insights?module=… — último análisis persistido (decisión F4).

Paridad con el web (apps/web/app/api/insights/route.ts, rev. pre-G20):
  • Solo roles de escritura (owner/manager) — cada llamada es Gemini facturable.
  • Rate-limit 10/h por tenant+user+IP (bucket ai.insights) — mismo tope.
  • Ingreso canónico: recognized_revenue = PAID_ORDER_STATUSES (confirmed+),
    alineado con Finanzas; gross_sales es secundaria y NUNCA "ingreso".
  • Agregación exacta vía RPC metrics_orders_summary con feature-detect: si
    falla → cálculo acotado por ventana (cap PostgREST 1000) + flags
    revenue_is_exact / revenue_is_approximate.
  • Ventanas en hora Colombia (UTC-5 fijo, sin DST) — espejo de
    apps/web/lib/date-window.ts (bogotaWindowUTC).
  • Persistencia best-effort del último análisis en ai_insights (upsert por
    tenant+module) + evento audit_log insight.generated.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from supabase import Client, create_client

from dependencies.auth import (
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.security import RateLimitRule, build_rate_limit_dependency

logger = logging.getLogger(__name__)
router = APIRouter(tags=["insights"])

# Mismo tope que el insights web (10/h). include_user_id: un usuario no puede
# saturar el cupo del tenant desde IPs rotadas.
RL_AI_INSIGHTS = build_rate_limit_dependency(
    RateLimitRule(
        bucket="ai.insights",
        limit=int(os.getenv("API_RATE_LIMIT_AI_INSIGHTS_PER_HOUR", "10")),
        window_seconds=3600,
    ),
    include_user_id=True,
)

# Ingreso reconocido (canónico, = Finanzas PAID_ORDER_STATUSES): pago
# confirmado en adelante.
RECOGNIZED_STATUSES = frozenset({"confirmed", "processing", "shipped", "delivered"})

VALID_MODULES = ("inventory", "orders", "contacts", "metrics")

# PostgREST corta en max_rows (config.toml → 1000) SIN error.
MAX_ROWS = 1000

# Colombia = UTC-5 fijo (sin DST) — espejo de lib/date-window.ts.
_COLOMBIA_OFFSET = timedelta(hours=-5)


class InsightRequest(BaseModel):
    module: str = ""


# ── Ventanas temporales (hora Colombia) ──────────────────────────────────────


def _bogota_window_utc(days: int, now: Optional[datetime] = None) -> tuple[str, str]:
    """Ventana [from, to] ISO-UTC que cubre los últimos `days` días de CALENDARIO
    en Colombia (incluye hoy). Espejo exacto de bogotaWindowUTC() del web."""
    now = now or datetime.now(timezone.utc)
    bogota_now = now + _COLOMBIA_OFFSET  # "fake UTC": campos = wall-clock Bogotá
    start_bogota = datetime(
        bogota_now.year, bogota_now.month, bogota_now.day, tzinfo=timezone.utc
    ) - timedelta(days=days - 1)
    from_utc = start_bogota - _COLOMBIA_OFFSET  # Bogotá → UTC = +5h
    return from_utc.isoformat(), now.isoformat()


# ── RPC de agregación exacta (requiere JWT del USUARIO) ──────────────────────


def _bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    return auth.split(" ", 1)[1] if auth.startswith("Bearer ") else ""


def _orders_summary_rpc(
    user_token: str, p_from: Optional[str], p_to: Optional[str]
) -> Optional[dict]:
    """Agregación EXACTA de pedidos vía metrics_orders_summary (sin cap 1000).

    El RPC deriva el tenant de auth.jwt() → hay que invocarlo con el JWT del
    USUARIO (con la service key el claim app_metadata.tenant_id no existe y el
    RPC devuelve vacío). Se construye un cliente por-request con la service key
    como apikey y el Bearer del usuario como Authorization de PostgREST.

    Feature-detect (paridad con el web): cualquier error → None y el caller
    cae al cálculo client-side acotado por ventana.
    """
    if not user_token:
        return None
    try:
        sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        sb.postgrest.auth(user_token)
        res = sb.rpc(
            "metrics_orders_summary", {"p_from": p_from, "p_to": p_to}
        ).execute()
        rows = res.data or []
        if not rows:
            return None
        r = rows[0]
        return {
            "orders_total": int(r.get("orders_total") or 0),
            "orders_non_cancelled": int(r.get("orders_non_cancelled") or 0),
            "orders_cancelled": int(r.get("orders_cancelled") or 0),
            "gross_sales": float(r.get("gross_sales") or 0),
            "recognized_revenue": float(r.get("recognized_revenue") or 0),
            "delivered_revenue": float(r.get("delivered_revenue") or 0),
            "by_status": r.get("by_status") or {},
        }
    except Exception as exc:  # noqa: BLE001 — feature-detect, el caller cae al fallback
        logger.info("[INSIGHTS] metrics_orders_summary no disponible: %s", exc)
        return None


# ── Fetcher de datos por módulo ──────────────────────────────────────────────


def _sum_amount(rows: list, statuses: Optional[frozenset] = None) -> float:
    total = 0.0
    for o in rows:
        if statuses is not None and o.get("status") not in statuses:
            continue
        total += float(o.get("total_amount") or 0)
    return total


def _count_exact(supabase: Client, table: str, tenant_id: str, **filters) -> int:
    """SELECT id count=exact head=true con filtros eq/gte/lt opcionales."""
    q = (
        supabase.table(table)
        .select("id", count="exact", head=True)
        .eq("tenant_id", tenant_id)
    )
    for key, val in filters.items():
        if key.startswith("gte__"):
            q = q.gte(key[len("gte__"):], val)
        elif key.startswith("lt__"):
            q = q.lt(key[len("lt__"):], val)
        else:
            q = q.eq(key, val)
    res = q.execute()
    return res.count or 0


def _fetch_module_data(
    module: str, tenant_id: str, supabase: Client, user_token: str
) -> dict:
    cur_from, _ = _bogota_window_utc(30)
    prev_from, _ = _bogota_window_utc(60)  # [prev_from, cur_from) = 30d previos

    if module == "inventory":
        var_res = (
            supabase.table("product_variations")
            .select("id, product_id, attributes, stock_quantity, price")
            .eq("tenant_id", tenant_id)
            .order("stock_quantity")
            .limit(200)
            .execute()
        )
        mov_res = (
            supabase.table("stock_movements")
            .select("variation_id, delta, reason, created_at")
            .eq("tenant_id", tenant_id)
            .gte("created_at", cur_from)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        thresh_res = (
            supabase.table("tenants")
            .select("low_stock_threshold")
            .eq("id", tenant_id)
            .maybe_single()
            .execute()
        )
        variations = var_res.data or []
        threshold = (
            (thresh_res.data or {}).get("low_stock_threshold") or 5
            if thresh_res and thresh_res.data
            else 5
        )
        out_of_stock = sum(1 for v in variations if (v.get("stock_quantity") or 0) == 0)
        low_stock = sum(
            1 for v in variations if 0 < (v.get("stock_quantity") or 0) <= threshold
        )
        return {
            "variations": variations,
            "recent_movements": mov_res.data or [],
            "low_stock_threshold": threshold,
            "total_variants": len(variations),
            "out_of_stock": out_of_stock,
            "low_stock": low_stock,
        }

    if module == "orders":
        total_res = (
            supabase.table("orders")
            .select("id", count="exact", head=True)
            .eq("tenant_id", tenant_id)
            .gte("created_at", cur_from)
            .execute()
        )
        prev_total_res = (
            supabase.table("orders")
            .select("id", count="exact", head=True)
            .eq("tenant_id", tenant_id)
            .gte("created_at", prev_from)
            .lt("created_at", cur_from)
            .execute()
        )
        rows_res = (
            supabase.table("orders")
            .select("status, total_amount", count="exact")
            .eq("tenant_id", tenant_id)
            .gte("created_at", cur_from)
            .execute()
        )
        summary = _orders_summary_rpc(user_token, cur_from, None)

        rows = rows_res.data or []
        if summary and summary.get("by_status"):
            by_status = summary["by_status"]
        else:
            by_status = {}
            for o in rows:
                s = o.get("status")
                by_status[s] = by_status.get(s, 0) + 1
        # Canónico: ingreso reconocido = confirmed+; ventas brutas = no
        # canceladas (secundaria).
        gross_fallback = _sum_amount([o for o in rows if o.get("status") != "cancelled"])
        recognized_fallback = _sum_amount(rows, RECOGNIZED_STATUSES)
        rows_count = rows_res.count or 0
        return {
            "total_orders": (
                total_res.count if total_res.count is not None else len(rows)
            ),
            "total_orders_prev_30d": prev_total_res.count or 0,
            "by_status": by_status,
            # dinero comprometido (canónico)
            "recognized_revenue": (
                summary["recognized_revenue"] if summary else recognized_fallback
            ),
            # secundaria: NO es ingreso
            "gross_sales": summary["gross_sales"] if summary else gross_fallback,
            "revenue_is_exact": summary is not None,
            "revenue_is_approximate": (
                summary is None and rows_count > len(rows) and len(rows) >= MAX_ROWS
            ),
            "period_days": 30,
        }

    if module == "contacts":
        total = _count_exact(supabase, "contacts", tenant_id)
        with_consent = _count_exact(supabase, "contacts", tenant_id, consent_given=True)
        new_30d = _count_exact(supabase, "contacts", tenant_id, gte__created_at=cur_from)
        return {
            "total_contacts": total,
            "with_consent": with_consent,
            "without_consent": max(total - with_consent, 0),
            "new_last_30d": new_30d,
        }

    # metrics — conteos con count='exact',head (exactos a escala); revenue
    # sobre filas acotadas + flag de aproximación; período previo real para el LLM.
    msg_cur = _count_exact(supabase, "messages", tenant_id, gte__created_at=cur_from)
    msg_prev = _count_exact(
        supabase, "messages", tenant_id, gte__created_at=prev_from, lt__created_at=cur_from
    )
    msg_in = _count_exact(
        supabase, "messages", tenant_id, gte__created_at=cur_from, direction="inbound"
    )
    ord_cur = _count_exact(supabase, "orders", tenant_id, gte__created_at=cur_from)
    ord_prev = _count_exact(
        supabase, "orders", tenant_id, gte__created_at=prev_from, lt__created_at=cur_from
    )
    conv_total = _count_exact(supabase, "conversations", tenant_id, gte__created_at=cur_from)
    conv_bot = _count_exact(
        supabase, "conversations", tenant_id, gte__created_at=cur_from, status="bot_active"
    )
    conv_human = _count_exact(
        supabase, "conversations", tenant_id, gte__created_at=cur_from, status="human_takeover"
    )
    rev_rows_res = (
        supabase.table("orders")
        .select("status, total_amount", count="exact")
        .eq("tenant_id", tenant_id)
        .gte("created_at", cur_from)
        .execute()
    )
    summary_cur = _orders_summary_rpc(user_token, cur_from, None)
    summary_prev = _orders_summary_rpc(user_token, prev_from, cur_from)

    rev_rows = rev_rows_res.data or []
    gross_fallback = _sum_amount([o for o in rev_rows if o.get("status") != "cancelled"])
    recognized_fallback = _sum_amount(rev_rows, RECOGNIZED_STATUSES)
    rev_count = rev_rows_res.count or 0

    return {
        "period_days": 30,
        "messages_total": msg_cur,
        "messages_total_prev_30d": msg_prev,
        "messages_inbound": msg_in,
        "orders_total": ord_cur,
        "orders_total_prev_30d": ord_prev,
        # Canónico: 'ingreso' = recognized_revenue (confirmed+). gross_sales es
        # secundaria (no canceladas, incluye checkout sin pago) — nunca 'ingreso'.
        "recognized_revenue": (
            summary_cur["recognized_revenue"] if summary_cur else recognized_fallback
        ),
        "recognized_revenue_prev_30d": (
            summary_prev["recognized_revenue"] if summary_prev else None
        ),
        "gross_sales": summary_cur["gross_sales"] if summary_cur else gross_fallback,
        "revenue_is_exact": summary_cur is not None,
        "revenue_is_approximate": (
            summary_cur is None and rev_count > len(rev_rows) and len(rev_rows) >= MAX_ROWS
        ),
        "conversations_total": conv_total,
        "bot_active": conv_bot,
        "human_takeover": conv_human,
        # Math.round del web = floor(x + 0.5) para x ≥ 0 (Python round() usa
        # banker's rounding — no es equivalente en los .5).
        "conversion_rate": (
            int((ord_cur / conv_total) * 100 + 0.5) if conv_total > 0 else 0
        ),
    }


# ── Prompts por módulo (verbatim del web — son parte del comportamiento) ──────


def _json_spec() -> str:
    return """Responde ÚNICAMENTE con este JSON válido (sin texto adicional):
{
  "resumen": "Una oración directa con números concretos de los DATOS",
  "hallazgos": ["hallazgo 1 con cifras", "hallazgo 2 con cifras", "hallazgo 3 con cifras"],
  "acciones": [
    { "prioridad": "alta", "accion": "Acción concreta" },
    { "prioridad": "media", "accion": "Segunda acción" }
  ],
  "alerta": "Alerta crítica si existe, o null"
}"""


def _build_prompt(module: str, data: dict) -> str:
    base = (
        "Eres un analista experto en e-commerce latinoamericano con especialización en "
        "WhatsApp Commerce y Mercado Libre. Responde siempre en español, de forma directa "
        "y accionable. Usa ÚNICAMENTE los números presentes en los DATOS; no inventes "
        "tendencias, cifras ni comparaciones que no puedas derivar de ellos."
    )
    data_json = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    spec = _json_spec()

    if module == "inventory":
        return f"""{base}

Analiza el siguiente inventario y da recomendaciones específicas y accionables.

DATOS DE INVENTARIO:
{data_json}

Considera: stock agotado (ventas perdidas), stock bajo (riesgo de quiebre), oportunidades de recompra.

{spec}"""

    if module == "orders":
        return f"""{base}

Analiza los siguientes pedidos.

DATOS DE PEDIDOS:
{data_json}

Considera: pedidos pendientes de confirmar, tasa de conversión, patrones de cancelación. NOTA sobre dinero: 'recognized_revenue' es el INGRESO reconocido (pago confirmado en adelante) — úsalo como la cifra de ingreso; 'gross_sales' es ventas brutas (incluye pedidos sin pago) y es SECUNDARIA — nunca la llames ingreso.

{spec}"""

    if module == "contacts":
        return f"""{base}

Analiza los siguientes contactos/clientes.

DATOS DE CONTACTOS:
{data_json}

Considera: clientes sin Habeas Data (riesgo legal), reactivación, crecimiento de la base.

{spec}"""

    # metrics
    return f"""{base}

Analiza las siguientes métricas del negocio. El payload incluye el período actual (30 días) y el período previo (30 días anteriores) para que la comparación sea real; NO estimes tendencias fuera de estos datos.

DATOS DE MÉTRICAS:
{data_json}

Considera: variación vs. período previo (usa los campos *_prev, incl. recognized_revenue_prev_30d si no es null), eficiencia del canal WhatsApp, tasa conversación → venta. NOTA sobre dinero: 'recognized_revenue' es el INGRESO reconocido canónico (pago confirmado en adelante); 'gross_sales' es ventas brutas (incluye pedidos sin pago) y es SECUNDARIA — nunca la llames ingreso.

{spec}"""


# ── Gemini (cascade canónico del api) ─────────────────────────────────────────


def _generate_insight(prompt: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """Invoca el cascade Gemini (mismos tiers que llm_suggest / ai_preview).
    Devuelve (texto, tokens_used, model_used); (None, None, None) si degradó —
    el caller traduce a 502. Temperatura 0.2 y max 1024 tokens = paridad web."""
    try:
        from google.genai import types as genai_types

        from lib.gemini_client import get_genai_client
        from lib.llm_cascade import cascade_invoke
        from lib.llm_suggest import _suggest_tiers

        client = get_genai_client()

        def _invoke(model_name: str):
            return client.models.generate_content(
                model=model_name,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config=genai_types.GenerateContentConfig(
                    max_output_tokens=1024,
                    temperature=0.2,
                ),
            )

        outcome = cascade_invoke(
            gemini_invoker=_invoke,
            tiers=_suggest_tiers(),
            attempts_per_tier=2,
        )
        if not outcome.degraded and outcome.response is not None:
            text = (getattr(outcome.response, "text", "") or "").strip()
            usage = getattr(outcome.response, "usage_metadata", None)
            tokens = getattr(usage, "total_token_count", None) if usage else None
            return text, tokens, outcome.model_used
    except Exception as exc:  # noqa: BLE001
        logger.warning("[INSIGHTS] cascade falló: %s", exc)
    return None, None, None


# ── Validación de shape de la respuesta de Gemini ─────────────────────────────
# El panel cliente hace insight.hallazgos.map y PRIORITY_STYLES[a.prioridad]:
# un JSON válido con estructura inesperada lo rompería. Se valida y sanea aquí.

_PRIORIDADES = frozenset({"alta", "media", "baja"})


def _validate_insight(x) -> Optional[dict]:
    if not isinstance(x, dict):
        return None
    resumen = x.get("resumen")
    if not isinstance(resumen, str) or not resumen.strip():
        return None
    hallazgos = x.get("hallazgos")
    if not isinstance(hallazgos, list) or not all(isinstance(h, str) for h in hallazgos):
        return None
    acciones_raw = x.get("acciones")
    if not isinstance(acciones_raw, list):
        return None
    acciones = [
        {"prioridad": a["prioridad"], "accion": a["accion"]}
        for a in acciones_raw
        if isinstance(a, dict)
        and isinstance(a.get("accion"), str)
        and a.get("prioridad") in _PRIORIDADES
    ]
    alerta = x.get("alerta")
    return {
        "resumen": resumen,
        "hallazgos": hallazgos[:10],
        "acciones": acciones[:6],
        "alerta": alerta if isinstance(alerta, str) and alerta.strip() else None,
    }


def _actor_from_jwt(request: Request) -> tuple[Optional[str], Optional[str]]:
    """user_id (sub) + email del JWT, best-effort (no levanta si faltan)."""
    try:
        from dependencies.auth import _extract_jwt_payload
        payload = _extract_jwt_payload(request)
        return payload.get("sub"), payload.get("email")
    except Exception:  # noqa: BLE001
        return None, None


# ── Handlers ──────────────────────────────────────────────────────────────────


@router.post("/insights", response_model=dict, dependencies=[Depends(RL_AI_INSIGHTS)])
def generate_insight(
    body: InsightRequest,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    module = (body.module or "").strip()
    if module not in VALID_MODULES:
        raise HTTPException(status_code=400, detail="Módulo no válido")

    user_token = _bearer_token(request)
    user_id, user_email = _actor_from_jwt(request)

    data = _fetch_module_data(module, tenant_id, supabase, user_token)
    prompt = _build_prompt(module, data)

    text, tokens_used, model_used = _generate_insight(prompt)
    if text is None:
        raise HTTPException(status_code=502, detail="Error al consultar Gemini")

    # El modelo a veces envuelve el JSON en fences ```json … ``` — se limpian.
    json_text = re.sub(r"```json\n?", "", text)
    json_text = re.sub(r"```\n?", "", json_text).strip()
    try:
        parsed = json.loads(json_text)
    except Exception:  # noqa: BLE001
        logger.warning(
            "[INSIGHTS] JSON.parse falló module=%s tenant=%s raw=%.500s",
            module, tenant_id[:8], text,
        )
        raise HTTPException(status_code=502, detail="Respuesta inválida de Gemini") from None

    validated = _validate_insight(parsed)
    if not validated or not validated["acciones"]:
        logger.warning(
            "[INSIGHTS] shape inesperado module=%s tenant=%s raw=%.500s",
            module, tenant_id[:8], text,
        )
        raise HTTPException(
            status_code=502, detail="Respuesta con formato inesperado de Gemini"
        )

    result = {
        **validated,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tokens_used": tokens_used,
    }

    # Audit trail (best-effort): uso de IA por tenant, para accounting/abuso.
    try:
        supabase.table("audit_log").insert({  # tenant_filter:exempt:payload_includes_tenant_id
            "tenant_id":   tenant_id,
            "user_id":     user_id,
            "user_email":  user_email,
            "action":      "insight.generated",
            "entity_type": "insight",
            "entity_id":   module,
            "payload":     {"model": model_used, "tokens_used": tokens_used},
        }).execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[INSIGHTS] audit_log insert falló tenant=%s: %s", tenant_id[:8], exc)

    # Persistencia del último análisis por tenant/módulo (decisión F4): evita
    # regenerar/gastar tokens al navegar. Best-effort + feature-detect: si la
    # tabla ai_insights no existe, se registra y se sigue (el panel cae a idle).
    try:
        supabase.table("ai_insights").upsert({
            "tenant_id":    tenant_id,
            "module":       module,
            "result":       result,
            "tokens_used":  tokens_used,
            "generated_by": user_id,
            "generated_at": result["generated_at"],
        }, on_conflict="tenant_id,module").execute()
    except Exception as exc:  # noqa: BLE001
        logger.info("[INSIGHTS] persistencia no disponible: %s", exc)

    return result


@router.get("/insights", response_model=dict)
def get_last_insight(
    module: str = "",
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Último análisis persistido por módulo (decisión F4). El panel lo consulta
    al montar para restaurar el último insight sin gastar tokens. Devuelve
    {insight: None} si no hay (o si la tabla no existe todavía)."""
    if module not in VALID_MODULES:
        raise HTTPException(status_code=400, detail="Módulo no válido")
    try:
        res = (
            supabase.table("ai_insights")
            .select("result")
            .eq("tenant_id", tenant_id)
            .eq("module", module)
            .maybe_single()
            .execute()
        )
        data = res.data if res else None
        if not data:
            return {"insight": None}
        return {"insight": data.get("result")}
    except Exception as exc:  # noqa: BLE001 — feature-detect: sin tabla → null
        logger.info("[INSIGHTS] GET persistencia no disponible: %s", exc)
        return {"insight": None}
