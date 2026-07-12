"""
Router de Reclamos / Claims — CRUD con aislamiento multi-tenant.

Rev. 72 — cierra el drift D1 (Claims escribía directo a DB desde RSC sin pasar por API).

Endpoints:
  GET    /api/v1/claims/                 — listar reclamos del tenant
  POST   /api/v1/claims/                 — crear reclamo                       [owner, manager, operator]
  GET    /api/v1/claims/{id}             — detalle
  PATCH  /api/v1/claims/{id}             — cambiar status / resolution_notes   [owner, manager]
  POST   /api/v1/claims/{id}/resolve     — atajo: status=resolved + notas      [owner, manager]

Estados válidos: open → in_progress → resolved | closed | cancelled

Coexistencia con orchestrator: el bot inserta claims via service_role direct
(`.table('claims').insert({'tenant_id': ..., ...})`), bypassa este router. Es
intencional: el bot tiene contexto de conversación que el frontend no tiene.
Ambos paths escriben a la misma tabla; RLS + tenant_id explícito mantiene
aislamiento. Patrón canónico `.table(X).eq('tenant_id', tid)` enforced por lint
AST scripts/audit_tenant_filter.py (ADR-0025 — helper scoped_table eliminado).
"""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import (
    get_current_tenant,
    get_service_client,
    require_write_role,
)
from dependencies.security import RL_WRITE_DEFAULT

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Claims"])

# A4 finiquito (audit §3 BUG#2 CRITICAL) — vocabulario canónico alineado con la UI
# (claims-manager.tsx STATUS_MAP + botones Investigando/Reembolsar/Rechazar). Antes
# el API tenía {in_progress, closed} que la UI NO usaba, y rechazaba 422 los
# {investigating, refunded, rejected} de los botones → 3 botones rotos. 0 claims en
# DB al alinear (sin migración de datos). Mismo set en el tool agentic
# (tools/claims.py) + CHECK constraint DB (migración 20260624010000).
VALID_STATUSES = {"open", "investigating", "resolved", "refunded", "rejected", "cancelled"}

# Estados terminales: el ticket ya está cerrado. Coincide con TERMINAL en la UI
# (claims-manager.tsx). Reabrir uno de estos es una transición especial (ver abajo).
TERMINAL_STATUSES = {"resolved", "refunded", "rejected", "cancelled"}

# Terminales que un OWNER puede reabrir (decisión F2 — Opción B).
#   - 'rejected' / 'cancelled': reversibles, sin impacto financiero → reabribles.
#   - 'refunded': revertir un reembolso ya movió dinero → NUNCA reabrir.
#   - 'resolved': cierre positivo → se maneja como reclamo nuevo, no se reabre.
# Reabrir = pasar de un estado terminal a uno no-terminal ('open' / 'investigating').
REOPENABLE_STATUSES = {"rejected", "cancelled"}

# Vocabulario canónico de 'reason' (decisión F2 — Opción A). El set de la UI
# (claims-manager.tsx REASON_MAP + dropdown de "Nuevo Reclamo") es la fuente de
# verdad; este API lo valida en create para mantener reporting consistente.
# El bot escribe reason en texto libre directo a DB (bypassa este router) y su
# mapeo a estas keys vive en el orchestrator (fuera de este router). La DB NO tiene
# CHECK sobre reason justamente para no romper esa escritura libre del bot.
VALID_REASONS = {"defective", "wrong_item", "missing_parts", "delayed", "other"}


# ─── Modelos ─────────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
    order_id: str = Field(..., description="UUID del pedido reclamado.")
    customer_id: Optional[str] = Field(default=None, description="UUID del contacto. Si no viene, el back lo deriva del order.")
    reason: str = Field(..., min_length=3, max_length=500)
    requested_amount: Optional[float] = Field(default=None, ge=0)
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)


class ClaimPatch(BaseModel):
    status: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=2000)
    # BLOQUE G-2 — monto REAL reembolsado (obligatorio al pasar a 'refunded'). Es lo
    # que el KPI net-revenue resta; NO uses requested_amount (intención del cliente).
    refunded_amount: Optional[float] = Field(default=None, ge=0)


class ClaimResolve(BaseModel):
    resolution_notes: str = Field(..., min_length=3, max_length=2000)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _validate_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Status inválido '{status}'. Válidos: {sorted(VALID_STATUSES)}",
        )


def _validate_reason(reason: str) -> None:
    if reason not in VALID_REASONS:
        raise HTTPException(
            status_code=422,
            detail=f"Motivo inválido '{reason}'. Válidos: {sorted(VALID_REASONS)}",
        )


def _fetch_claim(supabase: Client, tenant_id: str, claim_id: str) -> dict:
    """Lee un reclamo del tenant o lanza 404. Usado para validar transiciones."""
    res = (
        supabase.table("claims")
        .select("id, status, refunded_amount, refunded_at")
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    return res.data


def _refund_ledger_fields(
    patch: "ClaimPatch", *, cur_status: Optional[str], new_status: Optional[str], current: dict,
) -> dict:
    """BLOQUE G-2 — campos refunded_* a persistir en un patch de reclamo (o {}).

    El KPI net-revenue resta refunded_amount por refunded_at, no requested_amount
    (intención, nullable). Reglas (write-once):
      · transición a 'refunded': exige patch.refunded_amount → sella monto + fecha.
      · corrección (sin cambio de status) de un 'refunded' con monto NULL (backfill
        histórico sin monto): setea el monto (+ fecha si faltaba). No re-escribe.
    Raises 422/409 según corresponda.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    if new_status == "refunded" and cur_status != "refunded":
        if patch.refunded_amount is None:
            raise HTTPException(
                status_code=422,
                detail="Indica el monto reembolsado real para marcar el reclamo reembolsado.",
            )
        return {"refunded_amount": patch.refunded_amount, "refunded_at": now_iso}
    if new_status is None and patch.refunded_amount is not None:
        if cur_status != "refunded":
            raise HTTPException(
                status_code=422,
                detail="El monto reembolsado solo aplica a un reclamo ya reembolsado.",
            )
        if current.get("refunded_amount") is not None:
            raise HTTPException(
                status_code=409,
                detail="El monto reembolsado ya está registrado y no se puede cambiar.",
            )
        out: dict = {"refunded_amount": patch.refunded_amount}
        if not current.get("refunded_at"):
            out["refunded_at"] = now_iso
        return out
    return {}


def _ensure_order_belongs_to_tenant(supabase: Client, tenant_id: str, order_id: str) -> dict:
    res = (
        supabase.table("orders")
        .select("id, tenant_id, contact_id, status")
        .eq("id", order_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Pedido no encontrado para este tenant")
    return res.data


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_claims(
    status: Optional[str] = Query(default=None),
    customer_id: Optional[str] = Query(default=None),
    order_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista reclamos del tenant. Filtros opcionales por status / customer / order."""
    q = supabase.table("claims").select("*").eq("tenant_id", tenant_id)
    if status:
        _validate_status(status)
        q = q.eq("status", status)
    if customer_id:
        q = q.eq("customer_id", customer_id)
    if order_id:
        q = q.eq("order_id", order_id)
    q = q.order("created_at", desc=True).limit(limit)
    res = q.execute()
    return res.data or []


@router.post("/", response_model=dict, status_code=201, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="created")
async def create_claim(
    body: ClaimCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Crea un reclamo. Valida que el order pertenezca al tenant.
    Si customer_id no viene, se deriva del order.contact_id.

    BLOQUE G-4 (decisión founder): CREAR reclamos es owner/manager/operator — el
    operator es front-line de soporte y la UI ya expone «Nuevo Reclamo» (canWrite
    incluye operator). Se quitó require_write_role para alinear la API con la UI
    (antes el operator veía el botón y recibía 403). RESOLVER/reembolsar sigue
    restringido (patch_claim/resolve_claim mantienen require_write_role)."""
    order = _ensure_order_belongs_to_tenant(supabase, tenant_id, body.order_id)
    _validate_reason(body.reason.strip())

    customer_id = body.customer_id or order.get("contact_id")

    payload: dict = {
        "tenant_id": tenant_id,
        "order_id":  body.order_id,
        "customer_id": customer_id,
        "reason":    body.reason.strip(),
        "status":    "open",
    }
    if body.requested_amount is not None:
        payload["requested_amount"] = body.requested_amount
    if body.resolution_notes:
        payload["resolution_notes"] = body.resolution_notes.strip()

    res = supabase.table("claims").insert(payload).execute()  # tenant_filter:exempt:payload_includes_tenant_id
    if not res.data:
        raise HTTPException(status_code=500, detail="No fue posible crear el reclamo")
    return res.data[0]


@router.get("/{claim_id}", response_model=dict)
async def get_claim(
    claim_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    res = (
        supabase.table("claims")
        .select("*")
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
        .execute()
    )
    if not res or not res.data:  # F-doc: maybe_single() retorna None en 0 filas (postgrest 2.28.3)
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    return res.data


def _notify_client_claim_outcome(supabase, *, claim: dict, tenant_id: str, enabled: bool = True) -> None:
    """BLOQUE F-5: notifica al cliente por WhatsApp cuando su reclamo se RESUELVE o RECHAZA.

    Antes los paths de mutación (resolve/patch) solo escribían a DB → el cliente NUNCA se enteraba,
    aunque la UI se lo afirmaba al operador. Reusa el patrón best-effort de wompi_webhook
    (_enqueue_whatsapp_outbound): encola el mensaje y la ventana 24h de Meta la aplica el downstream
    (si el cliente escribió hace >24h la entrega falla igual que en las notifs de pago/envío). NUNCA
    rompe la mutación (best-effort). `claim` es la fila YA actualizada (incluye status/notes/order_id).
    `enabled` deja al caller (patch_claim) notificar solo en la TRANSICIÓN sin añadir una rama propia.
    """
    if not enabled:
        return
    try:
        status = (claim or {}).get("status")
        if status not in ("resolved", "rejected"):
            return
        order_id = claim.get("order_id")
        if not order_id:
            return
        order = (
            supabase.table("orders")
            .select("conversation_id")
            .eq("id", order_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        ).data
        conversation_id = (order or [{}])[0].get("conversation_id")
        if not conversation_id:
            return  # sin conversación WhatsApp (p.ej. pedido MeLi/consola) → no hay canal

        ticket = claim.get("ticket_number")
        notes = (claim.get("resolution_notes") or "").strip()
        ref = f"#{ticket}" if ticket else f"del pedido #{str(order_id)[:8].upper()}"
        if status == "resolved":
            text = (
                f"✅ *Reclamo resuelto*\n\nTu reclamo {ref} fue resuelto."
                + (f"\n\n{notes}" if notes else "")
                + "\n\nGracias por tu paciencia. Si necesitas algo más, escríbenos."
            )
        else:  # rejected
            text = (
                f"Hemos revisado tu reclamo {ref}."
                + (f"\n\n{notes}" if notes else "")
                + "\n\nSi tienes dudas o nueva información, escríbenos y lo revisamos."
            )

        from routers.wompi_webhook import _enqueue_whatsapp_outbound
        _enqueue_whatsapp_outbound(
            supabase, conversation_id=conversation_id, tenant_id=tenant_id,
            text=text, log_tag="CLAIM_WA_OUTCOME",
        )
    except Exception as exc:
        logger.warning("[CLAIMS] notif cliente falló claim=%s: %s", (claim or {}).get("id"), exc)


@router.patch("/{claim_id}", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="updated")
async def patch_claim(
    claim_id: str,
    patch: ClaimPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Actualiza status y/o resolution_notes. RBAC: owner+manager.

    Reapertura (terminal → no-terminal): restringida a OWNER y solo desde
    'rejected'/'cancelled'. 'refunded' nunca se reabre (el reembolso ya movió
    dinero); 'resolved' tampoco (cierre positivo). Decisión F2 — Opción B.
    """
    update: dict = {}
    if patch.status is not None:
        _validate_status(patch.status)
        update["status"] = patch.status
    if patch.resolution_notes is not None:
        update["resolution_notes"] = patch.resolution_notes.strip() or None

    # BLOQUE G-2: leemos el estado actual si cambia el status O si se corrige el monto
    # reembolsado (path de corrección de reembolsos históricos con monto NULL).
    need_current = ("status" in update) or (patch.refunded_amount is not None)
    current = _fetch_claim(supabase, tenant_id, claim_id) if need_current else None
    cur_status = current.get("status") if current else None

    # F-5: notificar al cliente SOLO en la transición a un outcome (resolved/rejected), no en cada patch.
    _notify_outcome = False
    if "status" in update:
        new_status = update["status"]
        _notify_outcome = new_status in ("resolved", "rejected") and cur_status != new_status

        # BLOQUE G-2: 'refunded' es FINAL — no se puede cambiar a NINGÚN otro estado.
        # Antes refunded→resolved pasaba (terminal→terminal, no lo atrapaba is_reopen)
        # y sacaba el reembolso del neteo del KPI (el RPC solo cuenta status='refunded').
        if cur_status == "refunded" and new_status != "refunded":
            raise HTTPException(
                status_code=409,
                detail="Un reclamo reembolsado es final; no se puede cambiar de estado.",
            )

        # BLOQUE G-2: captura del monto/fecha reales al marcar 'refunded' (write-once).
        update.update(_refund_ledger_fields(
            patch, cur_status=cur_status, new_status=new_status, current=current or {},
        ))

        # Guard de reapertura: terminal → no-terminal (solo owner, desde rejected/cancelled).
        # El caso 'refunded' ya lo cortó el guard de finalidad de arriba (rama eliminada).
        is_reopen = cur_status in TERMINAL_STATUSES and new_status not in TERMINAL_STATUSES
        if is_reopen:
            if _role != "owner":
                raise HTTPException(
                    status_code=403,
                    detail="Solo el owner puede reabrir un reclamo cerrado.",
                )
            if cur_status not in REOPENABLE_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"No se puede reabrir un reclamo en estado '{cur_status}'. "
                        "Solo 'rejected' o 'cancelled' se pueden reabrir."
                    ),
                )
    elif patch.refunded_amount is not None:
        # BLOQUE G-2: corrección de monto en un reclamo YA 'refunded' con monto NULL
        # (backfill histórico sin monto) — única vía sin cambiar el status.
        update.update(_refund_ledger_fields(
            patch, cur_status=cur_status, new_status=None, current=current or {},
        ))

    if not update:
        raise HTTPException(status_code=422, detail="Sin campos a actualizar")

    res = (
        supabase.table("claims")
        .update(update)
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    _notify_client_claim_outcome(supabase, claim=res.data[0], tenant_id=tenant_id, enabled=_notify_outcome)
    return res.data[0]


@router.post("/{claim_id}/resolve", response_model=dict, dependencies=[Depends(RL_WRITE_DEFAULT)])
@audit_log(entity_type="claim", action="status_changed")
async def resolve_claim(
    claim_id: str,
    body: ClaimResolve,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Atajo: marca status=resolved + persiste resolution_notes obligatoria."""
    prev = _fetch_claim(supabase, tenant_id, claim_id)  # status previo + 404 si no existe
    # BLOQUE G-2: 'refunded' es FINAL también por esta puerta. Sin este guard, /resolve
    # sacaba un reclamo reembolsado del neteo del KPI (el RPC solo cuenta 'refunded')
    # → revenue sobrestimado. Simétrico con patch_claim.
    if prev.get("status") == "refunded":
        raise HTTPException(
            status_code=409,
            detail="Un reclamo reembolsado es final; no se puede cambiar de estado.",
        )
    res = (
        supabase.table("claims")
        .update({
            "status": "resolved",
            "resolution_notes": body.resolution_notes.strip(),
        })
        .eq("id", claim_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Reclamo no encontrado")
    # F-5: notificar SOLO en la transición real a 'resolved' (idempotente: repetir /resolve —o
    # PATCH-resolve seguido de /resolve— NO re-notifica al cliente).
    _notify_client_claim_outcome(
        supabase, claim=res.data[0], tenant_id=tenant_id,
        enabled=(prev.get("status") != "resolved"),
    )
    return res.data[0]
