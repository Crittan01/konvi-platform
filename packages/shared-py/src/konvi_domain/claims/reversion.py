"""Reversión del pago — `claims.register_reversion` / `…_movement` (Track 5 M2.4).

Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51. Figura DISTINTA del reembolso:
acá el dinero no lo devolvemos nosotros — el consumidor le pide al EMISOR de su
medio de pago que deshaga el cargo. Nuestra única obligación —y es dura— es
emitir la constancia de la queja con fecha y causal (art. 2.2.2.51.4), porque el
art. 2.2.2.51.7 num. 6 se la exige al consumidor como contenido de la
notificación a su banco. Sin ella no puede ejercer el derecho.

R2 del contrato: la verdad transaccional ya vive en Postgres — estas operaciones
DELEGAN en las RPCs SECURITY DEFINER existentes (`rpc_registrar_reversion`,
`rpc_registrar_movimiento_reversion`), NO las reimplementan. Lo que migra al
servicio es la traducción: causal cerrada (422 con las cinco), motivo de la RPC
→ DomainError con `http_status` exacto (la tabla `_MOTIVO_HTTP` del router
histórico), y la lectura de la constancia.

La causal la DECLARA el consumidor y el operador la transcribe: la norma pide
"indicación de la causal que sustenta la petición", y clasificarla con un LLM
sería ponerlo a decidir verdad legal.
"""
from __future__ import annotations

import logging
from typing import Any

from konvi_domain.claims.models import (
    CAUSALES_REVERSION,
    VIAS_REVERSION,
    ReversionInput,
)
from konvi_domain.errors import DomainError, ErrorCode

logger = logging.getLogger(__name__)

#: Motivos por los que la radicación no procede, traducidos a (http_status,
#: mensaje). Un 404 para "el reclamo no existe" y un 409 para "existe pero esta
#: figura no aplica": son cosas distintas y el operador necesita distinguirlas.
_MOTIVO_HTTP = {
    "reclamo_inexistente": (404, "Reclamo no encontrado"),
    "reclamo_sin_pedido": (409, "El reclamo no está asociado a un pedido"),
    "pago_no_electronico": (
        409,
        "La reversión del pago no procede sobre pagos presenciales (contra entrega en "
        "efectivo): Decreto 1074 art. 2.2.2.51.1. El camino acá es el reembolso.",
    ),
    "forma_de_pago_desconocida": (
        409,
        "El pedido no tiene forma de pago registrada; no se puede afirmar que fue "
        "electrónico y la constancia afirma hechos.",
    ),
    "valor_excede_el_pedido": (
        422,
        "El valor solicitado excede el total del pedido. Al emisor le es oponible la "
        "inexistencia de la operación (art. 2.2.2.51.8).",
    ),
}

_HTTP_TO_ERRORCODE = {
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.VALIDATION,
}


def _motivo_error(motivo: str) -> DomainError:
    """Motivo de la RPC → DomainError con el http_status heredado exacto."""
    status, detalle = _MOTIVO_HTTP.get(motivo, (422, f"No se pudo radicar: {motivo}"))
    return DomainError(
        _HTTP_TO_ERRORCODE.get(status, ErrorCode.VALIDATION), detalle, http_status=status,
        detail={"motivo": motivo},
    )


def read_reversion(supabase: Any, *, tenant_id: str, claim_id: str) -> dict:
    """La constancia radicada de un reclamo, o NOT_FOUND si no hay ninguna."""
    res = (
        supabase.table("payment_reversal_requests")
        .select("*")
        .eq("claim_id", claim_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
    )
    filas = res.data or []
    if not filas:
        raise DomainError(
            ErrorCode.NOT_FOUND,
            "Este reclamo no tiene una solicitud de reversión radicada",
        )
    return filas[0]


def register_reversion(
    supabase: Any,
    *,
    tenant_id: str,
    claim_id: str,
    input: ReversionInput,
) -> dict:
    """Radica la queja de reversión y emite su constancia, en el mismo acto.

    No son dos pasos: el art. 2.2.2.51.4 no condiciona la constancia a nada, así
    que el estado "radicada sin constancia" sería justamente el incumplimiento.

    Idempotente por reclamo (UNIQUE(claim_id) en la RPC): un reintento devuelve
    la constancia que ya existe y NO emite una segunda con otra fecha — la fecha
    es lo que prueba que la queja llegó dentro de los cinco días hábiles.
    """
    if input.causal not in CAUSALES_REVERSION:
        raise DomainError(
            ErrorCode.VALIDATION,
            f"Causal inválida '{input.causal}'. La ley enumera cinco: "
            f"{sorted(CAUSALES_REVERSION)} (Decreto 1074 art. 2.2.2.51.2).",
        )

    # Params EXACTOS heredados del router (test_claim_reversion_api los aserta).
    res = supabase.rpc("rpc_registrar_reversion", {
        "p_claim_id": claim_id,
        "p_tenant_id": tenant_id,
        "p_causal": input.causal,
        "p_razones": input.razones.strip(),
        "p_valor": input.valor,
        "p_instrumento": input.instrumento,
        "p_es_parcial": input.es_parcial,
        "p_items": input.items,
        "p_bien_a_disposicion": input.bien_a_disposicion,
        "p_canal": input.canal,
        "p_conversation_id": input.conversation_id,
        "p_message_id": input.message_id,
        "p_meta_message_id": input.meta_message_id,
    }).execute()
    fila = (res.data or [{}])[0] if isinstance(res.data, list) else (res.data or {})

    motivo = fila.get("motivo")
    if motivo:
        raise _motivo_error(motivo)

    logger.info(
        "[REVERSION] radicada claim=%s causal=%s radicado=%s",
        claim_id, input.causal, fila.get("radicado"),
    )
    return read_reversion(supabase, tenant_id=tenant_id, claim_id=claim_id)


def register_reversion_movement(
    supabase: Any,
    *,
    tenant_id: str,
    claim_id: str,
    via: str,
    valor: float,
) -> dict:
    """Registra por cuál de los dos caminos volvió el dinero.

    Y si volvió por LOS DOS, lo marca. El art. 2.2.2.51.10 contempla expresamente
    ese escenario —el comerciante reembolsa mientras el emisor reversa en
    paralelo— y dice que el consumidor debe devolver esos recursos. Sin
    registrarlo sería invisible: no se puede reclamar lo que no se sabe que se pagó.
    """
    if via not in VIAS_REVERSION:
        raise DomainError(
            ErrorCode.VALIDATION,
            f"Vía inválida '{via}'. Válidas: {sorted(VIAS_REVERSION)}",
        )
    actual = read_reversion(supabase, tenant_id=tenant_id, claim_id=claim_id)

    res = supabase.rpc("rpc_registrar_movimiento_reversion", {
        "p_reversal_id": actual["id"],
        "p_tenant_id": tenant_id,
        "p_via": via,
        "p_valor": valor,
    }).execute()
    fila = (res.data or [{}])[0] if isinstance(res.data, list) else (res.data or {})
    if fila.get("motivo"):
        raise DomainError(
            ErrorCode.VALIDATION, fila["motivo"], http_status=422,
            detail={"motivo": fila["motivo"]},
        )

    if fila.get("doble_pago"):
        logger.warning(
            "[REVERSION] doble pago detectado (art. 2.2.2.51.10) claim=%s — "
            "el consumidor debe devolver uno de los dos recursos",
            claim_id,
        )
    return read_reversion(supabase, tenant_id=tenant_id, claim_id=claim_id)
