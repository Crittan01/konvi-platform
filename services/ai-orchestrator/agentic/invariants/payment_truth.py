"""Invariant: verdad de estado de pago (B-0 F3, 2026-08-21).

Gap detectado en auditoría de dinero/verdad: el LLM podía escribir
"tu pago fue recibido / confirmado / aprobado" sin que NINGÚN invariant lo
validara contra DB. Una afirmación falsa de pago es el peor outbound
posible: el cliente cree que ya pagó (o que su plata llegó) cuando la
orden sigue `pending_payment` — reclamo garantizado y riesgo legal
(Ley 1480: información veraz al consumidor).

Diseño:
  1. Detector por ORACIÓN: una oración es "claim de pago" si afirma el
     pago completado ("pago recibido/confirmado/aprobado/exitoso",
     "recibimos tu pago") Y NO contiene negadores/condicionales
     ("aún no", "cuando recibamos", "una vez", instrucciones de pago).
     Textos como "aún no recibo tu pago" o "realiza el pago en el link"
     NO disparan (falsos positivos evitados por diseño).
  2. Si hay claim → buscar sustento REAL:
     a. Evidencia en el turno: tool `generate_payment_link` COD exitoso
        (orden confirmed creada en el turno) o `get_recent_orders` con
        orden paga en su resultado.
     b. Verdad DB: orden en estado pago (`confirmed` o posterior) reciente
        (30 días, misma ventana default de get_recent_orders) para ESTA
        conversación, filtrada por tenant_id.
  3. Sin sustento → REWRITE a texto neutro seguro (pago en verificación).
  4. FAIL-CLOSED: este invariant está en FAIL_CLOSED_INVARIANTS — si la
     consulta DB lanza, la excepción escapa a `base.apply_invariants`
     (BLOCK + mensaje neutro). Una afirmación de pago NO sale sin validar.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# Oraciones que AFIRMAN pago completado:
#   • "pago" + participio de cierre a <=40 chars en la misma oración
#     ("tu pago fue recibido", "pago aprobado", "el pago quedó confirmado").
#   • "recibimos/confirmamos/acreditamos (tu) pago".
_PAYMENT_CLAIM_PATTERN = re.compile(
    r"\bpago\b[^.!?\n]{0,40}?\b(?:recibid[oa]|confirmad[oa]|aprobad[oa]|exitos[oa])\b"
    r"|\b(?:recibimos|confirmamos|acreditamos)\s+(?:tu\s+)?pago\b",
    re.IGNORECASE,
)
# Negadores / condicionales / instrucciones que ANULAN el claim dentro de la
# oración: "aún no recibo tu pago", "cuando recibamos tu pago te avisamos",
# "una vez sea aprobado", "si el pago es aprobado", "puede tardar en ser
# aprobado", "realiza el pago", "paga aquí", "pago pendiente".
_PAYMENT_VOID_PATTERN = re.compile(
    r"\bno\b|aún|todavía|cuando|apenas|en\s+cuanto|una\s+vez"
    r"|\bsi\b[^.!?\n]{0,20}\bpago"
    r"|debes|deberás|realiza|instrucciones|link\s+de\s+pago"
    r"|paga\s+(?:aquí|ahora|en\s+línea|online)|pendiente|falta"
    r"|pued\w+\s+[^.!?\n]{0,25}?\bser\b"
    r"|será\s+(?:recibido|confirmado|aprobado)"
    r"|verificando|esperando",
    re.IGNORECASE,
)
# Estados de orden que evidencian pago recibido (mismo criterio que
# state_machine/resolver.py para POST_PAYMENT).
_PAID_ORDER_STATUSES = ("confirmed", "processing", "shipped", "delivered")
# Ventana de búsqueda de la orden que sustenta el claim — alineada con el
# default de la tool get_recent_orders.
_LOOKBACK_DAYS = 30

# Texto neutro seguro para el REWRITE: no afirma ni niega el pago; promete
# verificación real (el follow-up lo da el operador vía escalación).
_PAYMENT_VERIFYING_TEXT = (
    "Gracias por tu paciencia. Estoy verificando el estado de tu pago con "
    "el sistema — en cuanto quede confirmado te aviso de inmediato con los "
    "detalles de tu pedido."
)


def _claims_payment_received(text: str) -> bool:
    """True si alguna oración del outbound AFIRMA pago recibido/confirmado.

    La evaluación es por oración para que un negador en la misma frase
    ("aún no recibo tu pago") anule el claim sin necesidad de mirar
    contexto global — y para que un texto mixto ("aún no recibo el anterior,
    pero tu pago de hoy fue confirmado") sí dispare si alguna oración lo
    afirma limpio.
    """
    if not text:
        return False
    for sentence in re.split(r"[.!?\n]+", text):
        if _PAYMENT_CLAIM_PATTERN.search(sentence) and not (
            _PAYMENT_VOID_PATTERN.search(sentence)
        ):
            return True
    return False


def _turn_has_payment_evidence(tool_call_log: list[dict]) -> Optional[str]:
    """Evidencia de pago dentro del turno. Retorna la razón (str) o None.

    Cubre la "notificación de sistema de pago en el turno":
      • `generate_payment_link` exitoso con payment_method=cod — la orden
        COD queda `confirmed` al crearse (pago pactado contraentrega).
      • `get_recent_orders` exitoso cuya respuesta incluye una orden en
        estado pago — el LLM afirma sobre dato real recién leído.
    """
    for call in (tool_call_log or []):
        result = call.get("result") or {}
        if "error" in result:
            continue
        tool = call.get("tool")
        if tool == "generate_payment_link" and (
            (result.get("payment_method") or "").lower() == "cod"
        ):
            return "orden COD confirmada en el turno vía generate_payment_link"
        if tool == "get_recent_orders":
            for order in (result.get("orders") or []):
                if order.get("status") in _PAID_ORDER_STATUSES:
                    return (
                        "orden paga reportada por get_recent_orders "
                        "en el turno"
                    )
    return None


class PaymentTruthInvariant:
    """Si el outbound afirma pago recibido/confirmado, exigir sustento real."""

    name = "payment_truth"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
    ) -> InvariantResult:
        if not _claims_payment_received(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
            )

        # 1. Evidencia en el turno (tool de pago/órdenes exitosa).
        turn_evidence = _turn_has_payment_evidence(tool_call_log)
        if turn_evidence:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason=turn_evidence,
            )

        # 2. Verdad DB: orden en estado pago reciente para ESTA conversación.
        #    FAIL-CLOSED: si la consulta lanza, la excepción ESCAPA — el
        #    wrapper de base.py (este invariant está en FAIL_CLOSED_INVARIANTS)
        #    la convierte en BLOCK + mensaje neutro. Un claim de dinero NO
        #    sale sin validar.
        since = (
            datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)
        ).isoformat()
        res = (
            supabase.table("orders")
            .select("id, status")
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .in_("status", list(_PAID_ORDER_STATUSES))
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return InvariantResult(
                outcome=InvariantOutcome.OK,
                invariant_name=self.name,
                reason="orden paga reciente en DB sustenta el claim",
            )

        # 3. Claim sin sustento → REWRITE a texto neutro (pago pendiente de
        #    verificación). El cliente NO se queda creyendo que pagó.
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=_PAYMENT_VERIFYING_TEXT,
            reason=(
                "outbound afirma pago recibido/confirmado pero NO hay orden "
                f"en estado {_PAID_ORDER_STATUSES} en los últimos "
                f"{_LOOKBACK_DAYS} días para esta conversación"
            ),
        )
