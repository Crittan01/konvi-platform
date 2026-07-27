"""Festivos colombianos y días hábiles.

POR QUÉ HACÍA FALTA
Varias obligaciones se cuentan en días HÁBILES o excluyen días festivos, y no había forma
de calcularlos en todo el repo:

  • Ley 2300 art. 5 par. 3 → art. 3: las comunicaciones comerciales solo pueden salir de
    lunes a viernes 7:00-19:00 y sábados 8:00-15:00, **excluyendo domingos y festivos**.
    El control anterior solo miraba la hora: un mensaje podía salir un domingo a las 20:00.
  • Ley 1480 art. 47: la ventana de retracto son 5 días HÁBILES.
  • Decreto 1074 art. 2.2.2.51.8: la reversión del pago corre en días HÁBILES.

SE IMPLEMENTA LA REGLA, NO UNA LISTA
Una tabla de fechas precalculadas caduca en silencio: el 1 de enero siguiente el sistema
empieza a tratar festivos como hábiles y nadie se entera. Acá se computan desde la norma,
así que sirve para cualquier año.

FUENTE — Ley 51 de 1983 ("Ley Emiliani"), verificada el 2026-07-26:
  · festivos fijos (no se trasladan): 1-ene, 1-may, 20-jul, 7-ago, 8-dic, 25-dic
  · se TRASLADAN al lunes siguiente cuando no caen lunes: 6-ene, 19-mar, 29-jun, 15-ago,
    12-oct, 1-nov, 11-nov, y los móviles Ascensión, Corpus Christi y Sagrado Corazón
  · Jueves y Viernes Santo NO se trasladan
  · literal: "cuando no caigan en día lunes se trasladará el descanso remunerado al lunes
    siguiente. (...) Cuando las mencionadas festividades caigan en domingo, el descanso
    remunerado igualmente se trasladará al lunes."

Los móviles se derivan de la Pascua con el algoritmo gregoriano anónimo (Meeus/Jones/
Butcher), que es aritmético y no depende de tablas.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

#: Colombia no tiene horario de verano, pero fijar la zona explícitamente evita que el
#: servidor —que corre en UTC— cuente un domingo a las 20:00 como lunes.
TZ_COLOMBIA = ZoneInfo("America/Bogota")

#: Festivos que NO se trasladan (Ley 51/1983 art. 1).
_FIJOS = ((1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25))

#: Festivos que se trasladan al lunes siguiente si no caen lunes (art. 2).
_TRASLADABLES = ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))

#: Móviles derivados de la Pascua. (días desde el domingo de Pascua, ¿se traslada?)
#: Jueves y Viernes Santo NO se trasladan; los otros tres sí.
_MOVILES = (
    (-3, False),   # Jueves Santo
    (-2, False),   # Viernes Santo
    (39, True),    # Ascensión del Señor
    (60, True),    # Corpus Christi
    (68, True),    # Sagrado Corazón de Jesús
)



def ahora_colombia() -> datetime:
    """La hora actual en Colombia. LA ÚNICA forma correcta de preguntarla.

    Los servidores corren en UTC. Un `datetime.now()` sin zona, o un `now(utc)` usado para
    decidir "¿qué día es hoy?", da resultados equivocados cinco horas al día: un pedido de
    las 8 de la noche del sábado cae en domingo, y el domingo está prohibido para contacto
    comercial.

    Se retiró un `COLOMBIA_UTC_OFFSET_HOURS` hardcodeado que hacía esto a mano. Un offset
    no es una zona horaria: no sabe de reglas ni de cambios futuros.
    """
    return datetime.now(TZ_COLOMBIA)


def hoy_colombia() -> date:
    """El día de hoy EN COLOMBIA, que no siempre es el mismo que en UTC."""
    return ahora_colombia().date()


def a_hora_colombia(momento: datetime) -> datetime:
    """Convierte cualquier datetime con zona a hora colombiana. Un naive se asume ya en
    Colombia: adivinar que era UTC sería peor que ser explícito."""
    if momento.tzinfo is None:
        return momento.replace(tzinfo=TZ_COLOMBIA)
    return momento.astimezone(TZ_COLOMBIA)


def domingo_de_pascua(anio: int) -> date:
    """Algoritmo gregoriano anónimo (Meeus/Jones/Butcher). Aritmético: no usa tablas."""
    a = anio % 19
    b, c = divmod(anio, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    mes, dia = divmod(h + lam - 7 * m + 114, 31)
    return date(anio, mes, dia + 1)


def _al_lunes_siguiente(d: date) -> date:
    """La regla Emiliani: si no cae lunes, se corre al lunes siguiente. `weekday()` da 0
    para lunes, así que un 0 se queda quieto."""
    return d if d.weekday() == 0 else d + timedelta(days=7 - d.weekday())


@lru_cache(maxsize=32)
def festivos(anio: int) -> frozenset[date]:
    """Todos los festivos de un año. Cacheado: se calcula una vez por año consultado."""
    dias: set[date] = {date(anio, m, d) for m, d in _FIJOS}
    dias |= {_al_lunes_siguiente(date(anio, m, d)) for m, d in _TRASLADABLES}
    pascua = domingo_de_pascua(anio)
    for offset, traslada in _MOVILES:
        f = pascua + timedelta(days=offset)
        dias.add(_al_lunes_siguiente(f) if traslada else f)
    return frozenset(dias)


def es_festivo(d: date) -> bool:
    return d in festivos(d.year)


def es_habil(d: date) -> bool:
    """Hábil = ni sábado, ni domingo, ni festivo.

    Ojo: para la Ley 2300 el SÁBADO sí es día de contacto (con horario propio). "Hábil" acá
    es el concepto de los PLAZOS legales, que es distinto — por eso el gate de comunicaciones
    no usa esta función sino `puede_contactar_comercialmente`.
    """
    return d.weekday() < 5 and not es_festivo(d)


def sumar_dias_habiles(desde: date, dias: int) -> date:
    """Fecha resultante de sumar N días hábiles. El día de partida no cuenta.

    Se usa para las ventanas del art. 47 (retracto, 5 días hábiles) y del Decreto 1074
    art. 2.2.2.51.8 (reversión del pago), que hasta ahora eran incalculables.
    """
    if dias <= 0:
        return desde
    d = desde
    restantes = dias
    while restantes > 0:
        d += timedelta(days=1)
        if es_habil(d):
            restantes -= 1
    return d


def dias_habiles_entre(inicio: date, fin: date) -> int:
    """Días hábiles transcurridos, sin contar el de inicio. Negativo si `fin` es anterior."""
    if fin < inicio:
        return -dias_habiles_entre(fin, inicio)
    n, d = 0, inicio
    while d < fin:
        d += timedelta(days=1)
        if es_habil(d):
            n += 1
    return n


# ── Horario de contacto de la Ley 2300 ──────────────────────────────────────
#
# Art. 5 par. 3: las comunicaciones comerciales "solo podrán hacerlo por dentro de los
# horarios establecidos en el artículo 3". Art. 3: lunes a viernes de 7:00 a 19:00 y
# sábados de 8:00 a 15:00, "excluyendo cualquier tipo de contacto con el consumidor los
# domingos y días festivos".

VENTANAS_CONTACTO = {
    0: (7, 19),   # lunes
    1: (7, 19),
    2: (7, 19),
    3: (7, 19),
    4: (7, 19),   # viernes
    5: (8, 15),   # sábado
    # domingo (6) ausente a propósito: prohibido.
}


def puede_contactar_comercialmente(cuando: datetime | None = None) -> tuple[bool, str]:
    """¿Se puede mandar AHORA un mensaje comercial? Devuelve (sí/no, motivo).

    El motivo se devuelve para poder registrarlo: un mensaje que no sale y no deja rastro
    del porqué es indistinguible de uno que se perdió.

    Solo aplica a lo COMERCIAL. Un mensaje transaccional —confirmación de pedido, guía de
    envío— no es una comunicación comercial y no está sujeto a este horario.
    """
    ahora = (cuando or datetime.now(TZ_COLOMBIA)).astimezone(TZ_COLOMBIA)
    hoy = ahora.date()

    if es_festivo(hoy):
        return False, "dia_festivo"
    ventana = VENTANAS_CONTACTO.get(ahora.weekday())
    if ventana is None:
        return False, "domingo"
    desde, hasta = ventana
    if not (desde <= ahora.hour < hasta):
        return False, f"fuera_de_horario_{desde}_{hasta}"
    return True, ""


def proxima_ventana_de_contacto(desde: datetime | None = None) -> datetime:
    """Cuándo se abre la próxima ventana. Sirve para reprogramar en vez de descartar:
    un mensaje comercial que llega tarde sigue sirviendo; uno que se pierde, no."""
    ahora = (desde or datetime.now(TZ_COLOMBIA)).astimezone(TZ_COLOMBIA)
    for salto in range(0, 15):          # 15 días cubre cualquier puente colombiano
        candidato = ahora + timedelta(days=salto)
        d = candidato.date()
        ventana = VENTANAS_CONTACTO.get(candidato.weekday())
        if ventana is None or es_festivo(d):
            continue
        inicio, fin = ventana
        if salto == 0 and ahora.hour < fin:
            hora = max(ahora.hour, inicio)
            if hora < fin:
                return ahora.replace(
                    hour=hora, minute=ahora.minute if hora == ahora.hour else 0,
                    second=0, microsecond=0,
                )
        if salto > 0:
            return datetime.combine(d, datetime.min.time(), TZ_COLOMBIA).replace(hour=inicio)
    # Inalcanzable en la práctica: no existen 15 días seguidos sin ventana.
    return ahora + timedelta(days=1)
