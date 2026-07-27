"""La única puerta por la que sale un mensaje proactivo al consumidor.

POR QUÉ UNA PUERTA ÚNICA
Los mensajes que el sistema envía por su cuenta —sin que el cliente escriba primero—
salían por caminos distintos, cada uno con sus propios controles, y esos controles habían
divergido. La revalidación legal del 2026-07-26 encontró que:

  • el recordatorio de pago (free-form) solo miraba `human_takeover`, así que un cliente
    que escribió STOP recibía "ya no recibirás mensajes nuestros" y **le seguía llegando**;
  • el HSM sí filtraba `consent_revoked_at`, o sea que dos caminos aplicaban reglas
    distintas a la misma persona;
  • el recordatorio de carrito abandonado —MARKETING, con descuento— se autorizaba con el
    consentimiento TRANSACCIONAL, que es justo lo que la Ley 2300 art. 5 par. 2 prohíbe;
  • el control de horario estaba apagado en `render.yaml` y, aun encendido, solo miraba la
    hora: un mensaje podía salir un domingo a las 20:00.

Cuando cada camino trae su propio criterio, el que se agregue mañana nace sin ninguno. Por
eso el gate es una función y no una convención: hay un test que falla si un camino de envío
proactivo no pasa por acá.

LAS DOS CATEGORÍAS, Y POR QUÉ IMPORTAN
  · TRANSACCIONAL — ejecuta el contrato que el cliente inició: confirmación de pedido,
    guía de envío, recordatorio de pago de SU pedido. No es publicidad.
  · COMERCIAL — busca vender algo más: carrito abandonado, promociones, novedades.

La ley las trata distinto. Meterlas en la misma bolsa fue la causa de fondo.

QUÉ BLOQUEA CADA UNA
  Ambas       → consentimiento de Habeas Data revocado (`consent_revoked_at`).
                Nuestro propio texto de baja dice "ya no recibirás mensajes nuestros": es
                una promesa absoluta y se cumple absoluta. Coincide además con la decisión
                del founder de 2026-05-28 de que el bot respete el opt-out en cualquier
                situación.
  Comercial   → además: consentimiento comercial explícito (Ley 2300 art. 5 par. 2) y la
                ventana horaria del art. 3 por remisión del art. 5 par. 3.

FAIL-CLOSED. Si no se puede verificar el estado del contacto, NO se envía. Un mensaje que
no sale se reintenta; uno que sale sin derecho no se puede recoger.
"""
from __future__ import annotations

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from lib.festivos_colombia import puede_contactar_comercialmente

logger = logging.getLogger(__name__)


class Categoria(str, Enum):
    """Qué clase de mensaje es. No es una etiqueta descriptiva: decide qué reglas aplican."""

    TRANSACCIONAL = "transaccional"
    COMERCIAL = "comercial"


class Decision:
    """Resultado del gate. Lleva el motivo porque un mensaje que no sale y no deja rastro
    del porqué es indistinguible de uno que se perdió."""

    __slots__ = ("permitido", "motivo", "detalle")

    def __init__(self, permitido: bool, motivo: str = "", detalle: str = ""):
        self.permitido = permitido
        self.motivo = motivo
        self.detalle = detalle

    def __bool__(self) -> bool:
        return self.permitido

    def __repr__(self) -> str:
        return f"Decision(permitido={self.permitido}, motivo={self.motivo!r})"


PERMITIDO = Decision(True)


def puede_enviar_proactivo(
    supabase: Any,
    *,
    tenant_id: str,
    categoria: Categoria,
    contact_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> Decision:
    """¿Se le puede mandar AHORA un mensaje que el cliente no pidió?

    `contact_id` o `conversation_id`: con el segundo se resuelve el primero. Si no llega
    ninguno no se puede verificar el consentimiento y se niega — fail-closed.
    """
    if not tenant_id:
        return Decision(False, "sin_tenant")

    if contact_id is None and conversation_id is None:
        return Decision(False, "sin_destinatario_identificable")

    contacto = _cargar_contacto(
        supabase, tenant_id=tenant_id,
        contact_id=contact_id, conversation_id=conversation_id,
    )
    if contacto is None:
        # No se pudo leer el estado: no sabemos si revocó. No se envía.
        return Decision(False, "no_pude_verificar_consentimiento")

    if contacto.get("consent_revoked_at"):
        return Decision(
            False, "consentimiento_revocado",
            "el titular pidió no recibir más mensajes (Ley 1581 art. 9)",
        )

    if categoria is Categoria.TRANSACCIONAL:
        # Ejecuta el contrato que el cliente inició: no es publicidad, no tiene horario.
        return PERMITIDO

    # ── De acá para abajo, solo lo COMERCIAL ────────────────────────────────
    # Quien NUNCA autorizó el tratamiento de sus datos no puede recibir publicidad, tenga
    # lo que tenga en la columna comercial. `consent_revoked_at` cubre a quien dijo que no
    # DESPUÉS; esto cubre a quien nunca dijo que sí — que no es lo mismo y hasta ahora
    # pasaba. Lo destapó un test cuyo nombre decía "sin consent" y que solo fallaba dentro
    # del horario de contacto de la Ley 2300, así que el reloj lo tapaba media jornada.
    #
    # `is False` y no un falsy: un contacto sin la columna cargada devuelve None, y tratar
    # "no lo sé" como "no autorizó" bloquearía envíos legítimos por un SELECT incompleto.
    if contacto.get("consent_given") is False:
        return Decision(
            False, "sin_consentimiento_de_datos",
            "el titular nunca autorizó el tratamiento de sus datos (Ley 1581)",
        )

    if not contacto.get("consent_comercial_at") or contacto.get("consent_comercial_revoked_at"):
        return Decision(
            False, "sin_consentimiento_comercial",
            "el consentimiento transaccional NO autoriza publicidad "
            "(Ley 2300 art. 5 par. 2)",
        )

    en_ventana, motivo_horario = puede_contactar_comercialmente(ahora)
    if not en_ventana:
        return Decision(
            False, f"horario_{motivo_horario}",
            "fuera de la ventana de contacto: L-V 7-19, sáb 8-15, nunca domingos ni "
            "festivos (Ley 2300 art. 5 par. 3 → art. 3)",
        )

    return PERMITIDO


def _cargar_contacto(
    supabase: Any, *, tenant_id: str,
    contact_id: Optional[str], conversation_id: Optional[str],
) -> Optional[dict]:
    """Estado de consentimiento del destinatario. `None` = no se pudo verificar, que el
    caller debe tratar como negativa y no como ausencia de restricciones."""
    campos = ("consent_given, consent_revoked_at, "
              "consent_comercial_at, consent_comercial_revoked_at")
    try:
        if contact_id:
            res = (
                supabase.table("contacts").select(campos)
                .eq("id", contact_id).eq("tenant_id", tenant_id)
                .limit(1).execute()
            )
            filas = res.data or []
            return filas[0] if filas else None

        conv = (
            supabase.table("conversations").select("contact_id")
            .eq("id", conversation_id).eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        cid = ((conv.data or [{}])[0] or {}).get("contact_id")
        if not cid:
            return None
        res = (
            supabase.table("contacts").select(campos)
            .eq("id", cid).eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        filas = res.data or []
        return filas[0] if filas else None
    except Exception as exc:
        logger.warning(
            "[GATE] no pude verificar el consentimiento tenant=%s: %s",
            str(tenant_id)[:8], exc,
        )
        return None


def registrar_bloqueo(decision: Decision, *, canal: str, referencia: str) -> None:
    """Deja el motivo en el log con un formato uniforme.

    Se separa del gate para que la decisión sea pura y testeable sin mirar logs, pero se
    ofrece acá para que todos los caminos registren igual: un bloqueo que cada camino
    loguea a su manera es un bloqueo que nadie puede contar.
    """
    logger.info(
        "[GATE] bloqueado canal=%s ref=%s motivo=%s%s",
        canal, referencia, decision.motivo,
        f" ({decision.detalle})" if decision.detalle else "",
    )
