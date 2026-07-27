"""Lo que se le dice al consumidor sobre sus derechos, en un solo lugar.

POR QUÉ EXISTE ESTE MÓDULO
Los plazos y condiciones legales estaban escritos a mano en cuatro sitios distintos
—el correo del comprobante, dos ramas del dispatcher, la plantilla del agente— y habían
divergido. La revalidación legal del 2026-07-26 encontró que **le declarábamos al comprador
derechos que no son los suyos, en el 100% de los pedidos**:

  • "garantía de un año, salvo que se informe un plazo mayor" — el art. 8 dice que para
    PERECEDEROS el término es la fecha de vencimiento, que puede ser MENOR. Y cosmética es
    perecedera: la fórmula excluía justo el caso real.
  • "no aplica a productos de uso personal ni hechos a tu medida" — se emitía en TODOS los
    comprobantes sin mirar los ítems, declarando en abstracto la inaplicabilidad de un
    derecho. Y omitía perecederos, que es el numeral que sí aplica acá.
  • "reembolso en máximo 30 días calendario (Art. 49)" — el art. 49 es la DEFINICIÓN de
    comercio electrónico, no un plazo; y el plazo real en e-commerce es 15, no 30.

Bajo el **art. 29** las condiciones objetivas anunciadas OBLIGAN al anunciante en los
términos en que las anunció — incluido lo que anunció mal. Un texto legal equivocado no es
un detalle de redacción: es una obligación que el vendedor adquiere.

CÓMO SE USA
Todo texto legal que vea un consumidor sale de acá. Si hay que cambiar un plazo, se cambia
en un lugar y cambia en todos. Hay un test que falla si alguien vuelve a escribir un plazo
a mano en el bot o en el correo.

VERIFICACIÓN DE LAS FUENTES (2026-07-26, texto vigente en
alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=44306):

  Art. 47 (retracto, mod. art. 3 Ley 2439 de 2024)
    · plazo para retractarse: CINCO (5) DÍAS HÁBILES
    · devolución del dinero en comercio electrónico: QUINCE (15) DÍAS CALENDARIO
      — literal: "En los casos de comercio electrónico la devolución del dinero a favor
        del consumidor no podrá exceder de quince (15) días calendario". Bajó de 30.
    · siete excepciones (numerales 1-7), transcritas en EXCEPCIONES_RETRACTO.

  Art. 8 (término de la garantía legal)
    · orden de prelación: (i) el que disponga la ley o la autoridad competente,
      (ii) a falta de norma de obligatorio cumplimiento, el ANUNCIADO por productor o
      proveedor, (iii) si no se indica ninguno, UN AÑO para productos nuevos.
    · literal para perecederos: "Tratándose de productos perecederos, el término de la
      garantía legal será el de la fecha de vencimiento o expiración."

NOTA SOBRE EL MÍNIMO Y EL MÁXIMO
`retracto_window_business_days` es un PISO: la ley da 5 días hábiles y un comerciante puede
ofrecer más, nunca menos. `manual_refund_legal_days` es un TECHO: la ley da hasta 15 días
calendario y se puede prometer menos, nunca más. Se aplican en direcciones opuestas y
confundirlos fue exactamente el error del CHECK de la base (ver migración 20260726130000).
"""
from __future__ import annotations

from typing import Any, Optional

# ── Los números de la ley ────────────────────────────────────────────────────

#: Art. 47 — días HÁBILES para ejercer el retracto. Es un mínimo legal.
RETRACTO_DIAS_HABILES_MIN = 5

#: Art. 47 inc. final (mod. Ley 2439/2024) — días CALENDARIO máximos para devolver el
#: dinero en comercio electrónico. Es un máximo legal: prometer más es incumplir.
REEMBOLSO_DIAS_CALENDARIO_MAX = 15

#: Art. 8 — término supletorio de la garantía legal para productos nuevos, cuando no hay
#: norma especial ni plazo anunciado.
GARANTIA_SUPLETORIA_ANIOS = 1

#: Art. 47 numerales 1-7, en las palabras del consumidor. Se citan solo las que apliquen
#: al pedido concreto: enunciarlas todas en abstracto es lo que se estaba haciendo mal.
EXCEPCIONES_RETRACTO = {
    1: "servicios que ya empezaron a prestarse con tu acuerdo",
    2: "productos cuyo precio depende de fluctuaciones del mercado que el vendedor no controla",
    3: "productos hechos a tu medida o personalizados",
    4: "productos que se deterioran rápido o que no pueden devolverse",
    5: "servicios de apuestas y loterías",
    6: "productos perecederos",
    7: "productos de uso personal",
}


def dias_retracto(politica: Optional[dict]) -> int:
    """Días hábiles para retractarse. La ley es un PISO: un comerciante puede ofrecer más
    días, nunca menos, ni por error de configuración ni a propósito."""
    p = politica or {}
    try:
        configurado = int(p.get("retracto_window_business_days") or RETRACTO_DIAS_HABILES_MIN)
    except (TypeError, ValueError):
        configurado = RETRACTO_DIAS_HABILES_MIN
    return max(RETRACTO_DIAS_HABILES_MIN, configurado)


def dias_reembolso(politica: Optional[dict]) -> int:
    """Días calendario para devolver el dinero. La ley es un TECHO: se puede prometer menos,
    nunca más. El sentido OPUESTO al del retracto — confundirlos fue el bug del CHECK."""
    p = politica or {}
    try:
        configurado = int(p.get("manual_refund_legal_days") or REEMBOLSO_DIAS_CALENDARIO_MAX)
    except (TypeError, ValueError):
        configurado = REEMBOLSO_DIAS_CALENDARIO_MAX
    return max(1, min(REEMBOLSO_DIAS_CALENDARIO_MAX, configurado))


def texto_retracto(politica: Optional[dict], items: Optional[list[dict]] = None) -> str:
    """El bloque de retracto del comprobante, dicho sobre ESTE pedido y no en abstracto.

    `items` son los del snapshot congelado. Cada uno puede traer `retracto_excluido` y
    `retracto_excluido_motivo`, evaluados al emitir — no en vivo: un comprobante no puede
    cambiar de contenido porque el catálogo cambió después.

    Tres casos, y la diferencia entre ellos es la que estaba mal:
      · ningún ítem excluido → se enuncia el derecho, limpio;
      · todos excluidos      → se dice que no aplica, Y POR QUÉ;
      · algunos              → se nombran los que quedan fuera. Decir "no aplica" a secas
        cuando la mitad del pedido sí admite retracto le quita al comprador un derecho real.
    """
    p = politica or {}
    if p.get("enable_retracto_flow", True) is False:
        return ""

    dias = dias_retracto(p)
    devol = dias_reembolso(p)
    quien_paga = (p.get("retracto_return_paid_by") or "customer")
    costo = (
        "El costo de la devolución corre por tu cuenta."
        if quien_paga == "customer"
        else "El costo de la devolución lo asume el vendedor."
    )

    lista = items or []
    excluidos = [i for i in lista if i.get("retracto_excluido")]

    if lista and len(excluidos) == len(lista):
        motivos = _motivos(excluidos)
        return (
            f"Retracto. Este pedido no admite retracto{motivos}. "
            f"Tus demás derechos como consumidor siguen vigentes."
        )

    base = (
        f"Retracto. Tienes {dias} días hábiles desde que recibes el producto para "
        f"retractarte de la compra. {costo} La devolución del dinero se hace dentro de "
        f"los {devol} días calendario siguientes."
    )
    if excluidos:
        nombres = ", ".join(
            str(i.get("titulo") or "un producto") for i in excluidos[:4]
        )
        base += f" No aplica a: {nombres}{_motivos(excluidos)}."
    return base


def _motivos(excluidos: list[dict]) -> str:
    """Los motivos legales distintos, sin repetir. Un comprobante que dice 'no aplica' sin
    decir por qué obliga al comprador a creer en vez de verificar."""
    vistos: list[str] = []
    for i in excluidos:
        m = (i.get("retracto_excluido_motivo") or "").strip()
        if m and m not in vistos:
            vistos.append(m)
    return f" ({'; '.join(vistos)})" if vistos else ""


def texto_garantia(items: Optional[list[dict]] = None) -> str:
    """El bloque de garantía. Respeta el orden de prelación del art. 8 en vez de afirmar
    "un año" como si fuera la regla.

    Si algún ítem trae `vence_el` (perecedero), se dice la regla que de verdad aplica: el
    término es la fecha de vencimiento. Para cosmética ése es el caso normal, y la versión
    anterior —"un año, salvo plazo mayor"— lo excluía justo al revés.
    """
    perecederos = [i for i in (items or []) if i.get("vence_el")]
    if perecederos:
        return (
            "Garantía. En productos perecederos el término de la garantía legal es su "
            "fecha de vencimiento. En los demás productos nuevos es de un año desde la "
            "entrega, salvo que se haya informado otro plazo."
        )
    # "un año" y no "1 año": es un texto que lee una persona, no un log.
    return (
        "Garantía. Los productos nuevos tienen garantía legal de un año desde la entrega, "
        "salvo que la ley o el vendedor hayan informado otro plazo."
    )


def texto_reembolso_bot(politica: Optional[dict] = None) -> str:
    """La frase que el bot le dice a alguien que cancela. Reemplaza el
    "máximo 30 días calendario (Art. 49)" que estaba mal por partida doble: el plazo era el
    del comercio presencial y el artículo citado es la definición de comercio electrónico,
    no un plazo."""
    return (
        f"El reembolso se hace dentro de los {dias_reembolso(politica)} días calendario "
        f"siguientes (Ley 1480, art. 47)."
    )


def cita_articulo(clave: str) -> str:
    """La cita correcta, para que nadie tenga que recordarla. Existe porque el bot citaba
    'Art. 49' —la definición de comercio electrónico— como si fuera el plazo."""
    return {
        "retracto": "Ley 1480, art. 47 (mod. Ley 2439 de 2024)",
        "reembolso": "Ley 1480, art. 47 (mod. Ley 2439 de 2024)",
        "garantia": "Ley 1480, art. 8",
        "informacion": "Ley 1480, art. 23",
        "precio": "Ley 1480, art. 26",
        "identidad_vendedor": "Ley 1480, art. 50 lit. a)",
        "acuse_recibo": "Ley 1480, art. 50 lit. d)",
    }.get(clave, "Ley 1480 de 2011")


def es_plazo_legalmente_valido(dias_retracto_cfg: Any, dias_reembolso_cfg: Any) -> tuple[bool, str]:
    """¿Una configuración de tenant cumple la ley? Devuelve (ok, motivo).

    Se usa para validar antes de guardar, en vez de descubrirlo cuando ya se le prometió
    algo imposible a un comprador.
    """
    try:
        r = int(dias_retracto_cfg)
        d = int(dias_reembolso_cfg)
    except (TypeError, ValueError):
        return False, "los plazos deben ser números enteros de días"
    if r < RETRACTO_DIAS_HABILES_MIN:
        return False, (
            f"el retracto no puede ser menor a {RETRACTO_DIAS_HABILES_MIN} días hábiles "
            f"({cita_articulo('retracto')})"
        )
    if d > REEMBOLSO_DIAS_CALENDARIO_MAX:
        return False, (
            f"la devolución del dinero no puede exceder {REEMBOLSO_DIAS_CALENDARIO_MAX} "
            f"días calendario en comercio electrónico ({cita_articulo('reembolso')})"
        )
    if d < 1:
        return False, "la devolución del dinero debe tener al menos 1 día"
    return True, ""
