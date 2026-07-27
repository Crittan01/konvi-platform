"""La reversión del pago, que no es lo mismo que un reembolso.

LA DISTINCIÓN QUE FALTABA
El sistema solo sabía hacer una cosa cuando algo salía mal: devolver plata. Pero la ley
colombiana tiene DOS caminos, y el que faltaba es el que el consumidor puede ejercer sin
nuestro permiso:

  · REEMBOLSO comercial → lo devolvemos nosotros. Depende de nuestra voluntad y de que
    tengamos con qué.
  · REVERSIÓN del pago  → el consumidor le pide al EMISOR de su tarjeta que deshaga el
    cargo. Nosotros no la ejecutamos; en el trámite somos un tercero.

Confundirlas no es un matiz: en la reversión nuestra obligación no es pagar, es EMITIR UNA
CONSTANCIA. Y sin esa constancia el consumidor no puede ejercer su derecho, porque el
art. 2.2.2.51.7 num. 6 se la exige como contenido de la notificación a su banco.

FUENTES, verificadas el 2026-07-26 en texto oficial:
  · Ley 1480 de 2011 art. 51 (alcaldiabogota.gov.co/sisjur)
  · Decreto 1074 de 2015, cap. 2.2.2.51 — adicionado por el Decreto 587 de 2016
    (funcionpublica.gov.co/eva/gestornormativo)

Este módulo NO decide si una queja procede: eso lo declara el consumidor eligiendo su
causal, y la aplicabilidad la resuelve `reversion_procede` en SQL. Acá vive el vocabulario
legal y el cálculo de plazos, en un solo lugar, por la misma razón que `legal_texts`: los
plazos escritos a mano en diez sitios fue exactamente el bug de #192.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from lib.festivos_colombia import (
    a_hora_colombia,
    dias_habiles_entre,
    hoy_colombia,
    sumar_dias_habiles,
)

# ── Las cinco causales del art. 2.2.2.51.2 ──────────────────────────────────
#
# Lista CERRADA. La causal la elige el consumidor, no la infiere el bot: la norma pide
# "indicación de la causal que sustenta la petición", y poner un LLM a decidir en qué
# casilla legal cae una frase es justo lo que este proyecto no hace (ADR-0024).
#
# El texto de cada una está redactado para MOSTRARSE: es lo que el comprador escoge.

CAUSALES: dict[str, str] = {
    "fraude": "No reconozco esta compra (fraude)",
    "operacion_no_solicitada": "Yo no pedí esto",
    "producto_no_recibido": "No me llegó el producto",
    "producto_no_corresponde": "Me llegó algo distinto a lo que pedí",
    "producto_defectuoso": "Me llegó defectuoso",
}

#: Cómo se nombra cada causal DENTRO de la constancia, con el lenguaje de la norma.
#: Es un documento que va a leer un banco, no el comprador.
CAUSALES_FORMALES: dict[str, str] = {
    "fraude": "el consumidor fue objeto de fraude (num. 1)",
    "operacion_no_solicitada": "corresponde a una operación no solicitada (num. 2)",
    "producto_no_recibido": "el producto adquirido no fue recibido (num. 3)",
    "producto_no_corresponde": (
        "el producto entregado no corresponde a lo solicitado o no cumple con las "
        "características informadas (num. 4)"
    ),
    "producto_defectuoso": "el producto entregado se encuentra defectuoso (num. 5)",
}

#: Días HÁBILES que tiene el consumidor para presentar la queja, contados desde que tuvo
#: noticia del hecho (art. 2.2.2.51.4). Es un PISO de protección, no un techo nuestro: no
#: se puede acortar. Coincide en número con el retracto y es pura coincidencia — son
#: plazos distintos, de artículos distintos, y mezclarlos ya causó un bug.
QUEJA_DIAS_HABILES = 5

#: Días HÁBILES que tienen los participantes del proceso de pago para hacer efectiva la
#: reversión una vez notificados (art. 2.2.2.51.8). NO corre contra nosotros: sirve para
#: saber cuándo dejó de ser razonable esperar y hay que hacerle seguimiento al comprador.
TRAMITE_DIAS_HABILES = 15

#: Formas de pago que NO admiten reversión. Art. 2.2.2.51.1: "no procede cuando hayan sido
#: realizados por medio de canales presenciales". Contra entrega en efectivo es presencial.
#: Duplicado a propósito de la guarda en SQL (`reversion_procede`): la de SQL es la que
#: manda, esta permite responderle al comprador sin ir a la base.
FORMAS_SIN_REVERSION = frozenset({"cod", "cash", "efectivo"})


def admite_reversion(forma_pago: Optional[str]) -> tuple[bool, str]:
    """¿Este pedido admite reversión? Devuelve (sí/no, motivo).

    Decirle a alguien que pagó en efectivo que puede pedir una reversión sería prometerle
    un derecho que no tiene — el mismo error de #192, donde le declarábamos plazos ajenos.
    Su camino es el reembolso comercial, que sí existe y es nuestro.
    """
    fp = (forma_pago or "").strip().lower()
    if not fp:
        return False, "forma_de_pago_desconocida"
    if fp in FORMAS_SIN_REVERSION:
        return False, "pago_no_electronico"
    return True, ""


def vence_plazo_de_queja(desde: date | datetime) -> date:
    """Último día hábil para presentar la queja (art. 2.2.2.51.4).

    `desde` es la fecha en que el consumidor tuvo noticia del hecho: recibió el producto
    defectuoso, debió recibirlo y no llegó, o supo del cargo que no reconoce. No es la
    fecha de la compra, y confundirlas le recorta el plazo a quien más lo necesita.
    """
    return sumar_dias_habiles(_a_fecha(desde), QUEJA_DIAS_HABILES)


def dias_habiles_restantes(desde: date | datetime, hoy: Optional[date] = None) -> int:
    """Cuántos días hábiles le quedan al consumidor. Negativo si ya venció.

    Se devuelve el número y no una frase para que quien lo use decida qué decir: un 0 no
    es lo mismo que un -3, y un mensaje que diga "te queda 0 días" está mal escrito.
    """
    limite = vence_plazo_de_queja(desde)
    return dias_habiles_entre(hoy or hoy_colombia(), limite)


def vence_tramite(notificada: date | datetime) -> date:
    """Hasta cuándo tienen los participantes del proceso de pago para reversar
    (art. 2.2.2.51.8: 15 días hábiles). No es un plazo nuestro; es el que permite saber
    cuándo hay que preguntarle al comprador si el banco ya le devolvió."""
    return sumar_dias_habiles(_a_fecha(notificada), TRAMITE_DIAS_HABILES)


def _a_fecha(v: date | datetime) -> date:
    """Un datetime se lleva a hora COLOMBIA antes de quedarse con el día.

    El servidor corre en UTC: una queja presentada un viernes a las 8 de la noche caería
    en sábado y el conteo de días hábiles empezaría un día tarde, en contra del consumidor.
    """
    if isinstance(v, datetime):
        return a_hora_colombia(v).date()
    return v


def texto_constancia(constancia: dict) -> str:
    """La constancia, en palabras, para mandársela al comprador por WhatsApp.

    Contenido obligatorio del art. 2.2.2.51.4: FECHA y CAUSAL. Se agrega lo que el
    consumidor necesita para armar su notificación al emisor (art. 2.2.2.51.7): el valor,
    la identificación de la operación y la del instrumento.

    No se promete que la plata vuelva ni cuándo: eso no depende de nosotros, y el sistema
    ya tuvo un caso de declararle al comprador plazos que no eran los suyos. Se dice qué
    sigue y quién lo hace.
    """
    c = constancia or {}
    causal = CAUSALES_FORMALES.get(c.get("causal", ""), c.get("causal", "—"))
    valor = _pesos(c.get("valor"))
    vendedor = (c.get("vendedor") or {}).get("nombre") or "el vendedor"

    lineas = [
        f"*Constancia de queja {c.get('radicado', '')}*".strip(),
        "",
        f"Fecha de presentación: {c.get('presentada_co') or '—'}",
        f"Causal invocada: {causal}",
        f"Valor sobre el que se solicita la reversión: {valor}"
        + (" (reversión parcial)" if c.get("es_parcial") else ""),
    ]
    if c.get("instrumento"):
        lineas.append(f"Medio de pago: {c['instrumento']}")
    if c.get("bien_a_disposicion"):
        lineas.append(
            "El producto queda a disposición para ser recogido en las mismas condiciones "
            "y en el mismo lugar en que se recibió."
        )

    lineas += [
        "",
        "Con esta constancia puedes notificar a la entidad que emitió tu medio de pago "
        "para que tramite la reversión. La reversión la hacen ellos, no nosotros.",
        "",
        f"Emitida por {vendedor} conforme a la Ley 1480 de 2011 art. 51 y al "
        "Decreto 1074 de 2015 art. 2.2.2.51.4.",
    ]
    return "\n".join(lineas)


def _pesos(v) -> str:
    """Pesos colombianos, sin centavos: acá no circulan."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"${n:,.0f}".replace(",", ".")
