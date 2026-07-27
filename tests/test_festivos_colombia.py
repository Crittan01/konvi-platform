"""Festivos colombianos y horario de contacto de la Ley 2300.

Existe porque varias obligaciones se cuentan en días hábiles o excluyen festivos y no había
forma de calcularlos: la ventana de retracto (5 días hábiles, art. 47), la reversión del
pago (Decreto 1074 art. 2.2.2.51.8) y el horario de contacto comercial eran incalculables.

Se implementa la REGLA de la Ley 51 de 1983 y no una tabla de fechas, porque una tabla
caduca en silencio: el 1 de enero siguiente el sistema empieza a tratar festivos como
hábiles y nadie se entera.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

from lib.festivos_colombia import (  # noqa: E402
    TZ_COLOMBIA,
    dias_habiles_entre,
    domingo_de_pascua,
    es_festivo,
    es_habil,
    festivos,
    proxima_ventana_de_contacto,
    puede_contactar_comercialmente,
    sumar_dias_habiles,
)


# ─── La regla de traslado (Ley Emiliani) ────────────────────────────────────

def test_los_festivos_fijos_NO_se_trasladan():
    """1-ene, 1-may, 20-jul, 7-ago, 8-dic y 25-dic se quedan donde caen."""
    assert es_festivo(date(2026, 1, 1))    # jueves
    assert es_festivo(date(2026, 12, 8))   # martes
    assert es_festivo(date(2026, 5, 1))    # viernes


def test_los_trasladables_se_corren_al_lunes_siguiente():
    """Reyes es el 6 de enero; en 2026 cae martes, así que el festivo es el lunes 12."""
    assert not es_festivo(date(2026, 1, 6)), "el 6 en sí NO es festivo si no cae lunes"
    assert es_festivo(date(2026, 1, 12))
    assert date(2026, 1, 12).weekday() == 0


def test_uno_que_YA_cae_lunes_no_se_mueve():
    """San Pedro y San Pablo (29-jun) cae lunes en 2026: se queda."""
    assert date(2026, 6, 29).weekday() == 0
    assert es_festivo(date(2026, 6, 29))


def test_uno_que_cae_domingo_tambien_va_al_lunes():
    """Ley 51 literal: "Cuando las mencionadas festividades caigan en domingo, el descanso
    remunerado igualmente se trasladará al lunes". Todos los Santos 2026 cae domingo 1-nov."""
    assert date(2026, 11, 1).weekday() == 6
    assert not es_festivo(date(2026, 11, 1))
    assert es_festivo(date(2026, 11, 2))


# ─── Los móviles derivados de la Pascua ─────────────────────────────────────

def test_la_pascua_se_calcula_bien():
    """Fechas conocidas del domingo de Resurrección."""
    assert domingo_de_pascua(2026) == date(2026, 4, 5)
    assert domingo_de_pascua(2027) == date(2027, 3, 28)
    assert domingo_de_pascua(2024) == date(2024, 3, 31)


def test_jueves_y_viernes_santo_NO_se_trasladan():
    """Son los dos móviles que se quedan donde caen."""
    assert es_festivo(date(2026, 4, 2))   # jueves santo
    assert es_festivo(date(2026, 4, 3))   # viernes santo


def test_ascension_corpus_y_sagrado_corazon_SI_se_trasladan():
    """Los tres caen entre semana y por la regla van al lunes."""
    for d in (date(2026, 5, 18), date(2026, 6, 8), date(2026, 6, 15)):
        assert es_festivo(d), d
        assert d.weekday() == 0


def test_colombia_tiene_dieciocho_festivos_salvo_colision():
    """Se calculan 18, pero DOS pueden caer el mismo día y el año queda con 17.

    No es un borde teórico: en 2025 San Pedro y San Pablo (29-jun, domingo) se corrió al
    lunes 30, y el Sagrado Corazón cayó ese mismo lunes. Colombia tuvo 17 festivos ese año.
    La primera versión de este test asumía 18 siempre y la equivocada era la aserción, no
    el código."""
    for anio in (2025, 2026, 2027, 2028, 2035):
        n = len(festivos(anio))
        assert n in (17, 18), f"{anio}: {n}"


def test_la_colision_de_2025_esta_bien_resuelta():
    """Un solo festivo ese lunes, no dos entradas duplicadas."""
    assert es_festivo(date(2025, 6, 30))
    assert len(festivos(2025)) == 17


def test_la_regla_sirve_para_cualquier_anio():
    """Lo que una tabla precalculada no puede hacer."""
    assert len(festivos(2035)) >= 17
    assert es_festivo(date(2035, 1, 1))


# ─── Días hábiles ───────────────────────────────────────────────────────────

def test_un_habil_no_es_finde_ni_festivo():
    assert es_habil(date(2026, 7, 21))        # martes normal
    assert not es_habil(date(2026, 7, 25))    # sábado
    assert not es_habil(date(2026, 7, 26))    # domingo
    assert not es_habil(date(2026, 7, 20))    # festivo (20 de julio)


def test_sumar_habiles_salta_findes_y_festivos():
    """5 días hábiles desde el viernes 17-jul-2026: el lunes 20 es festivo, así que la
    cuenta se corre. Es la ventana del retracto (art. 47)."""
    assert sumar_dias_habiles(date(2026, 7, 17), 5) == date(2026, 7, 27)


def test_sumar_cero_o_negativo_devuelve_el_mismo_dia():
    d = date(2026, 7, 21)
    assert sumar_dias_habiles(d, 0) == d
    assert sumar_dias_habiles(d, -3) == d


def test_contar_habiles_entre_dos_fechas():
    assert dias_habiles_entre(date(2026, 7, 17), date(2026, 7, 27)) == 5
    assert dias_habiles_entre(date(2026, 7, 21), date(2026, 7, 21)) == 0


def test_contar_al_reves_da_negativo():
    assert dias_habiles_entre(date(2026, 7, 27), date(2026, 7, 17)) == -5


# ─── El horario de contacto comercial (Ley 2300 art. 5 par. 3 → art. 3) ────

def _en(anio, mes, dia, hora):
    return datetime(anio, mes, dia, hora, 0, tzinfo=TZ_COLOMBIA)


def test_entre_semana_de_7_a_19():
    assert puede_contactar_comercialmente(_en(2026, 7, 21, 7))[0]
    assert puede_contactar_comercialmente(_en(2026, 7, 21, 18))[0]
    assert not puede_contactar_comercialmente(_en(2026, 7, 21, 6))[0]
    assert not puede_contactar_comercialmente(_en(2026, 7, 21, 19))[0], "19:00 ya está fuera"


def test_el_sabado_tiene_ventana_propia_mas_corta():
    """8:00-15:00, no la misma que entre semana."""
    assert puede_contactar_comercialmente(_en(2026, 7, 25, 8))[0]
    assert puede_contactar_comercialmente(_en(2026, 7, 25, 14))[0]
    assert not puede_contactar_comercialmente(_en(2026, 7, 25, 7))[0]
    assert not puede_contactar_comercialmente(_en(2026, 7, 25, 15))[0]


def test_el_domingo_esta_prohibido_a_cualquier_hora():
    """El control anterior solo miraba la hora: un domingo a las 20:00 pasaba."""
    for hora in (8, 12, 18, 20):
        ok, motivo = puede_contactar_comercialmente(_en(2026, 7, 26, hora))
        assert not ok and motivo == "domingo", hora


def test_los_festivos_tambien():
    """20 de julio de 2026, lunes festivo: en horario laboral pero prohibido."""
    ok, motivo = puede_contactar_comercialmente(_en(2026, 7, 20, 10))
    assert not ok and motivo == "dia_festivo"


def test_el_motivo_se_devuelve_para_poder_registrarlo():
    """Un mensaje que no sale y no deja rastro del porqué es indistinguible de uno perdido."""
    _, motivo = puede_contactar_comercialmente(_en(2026, 7, 21, 22))
    assert motivo.startswith("fuera_de_horario")


def test_la_zona_horaria_es_explicita():
    """El servidor corre en UTC: un domingo a las 20:00 en Bogotá son las 01:00 del lunes
    en UTC. Sin fijar la zona, el gate dejaría pasar el mensaje prohibido."""
    domingo_noche_bogota = datetime(2026, 7, 26, 20, 0, tzinfo=TZ_COLOMBIA)
    en_utc = domingo_noche_bogota.astimezone(ZoneInfo("UTC"))
    assert en_utc.weekday() == 0, "en UTC ya es lunes"
    assert not puede_contactar_comercialmente(en_utc)[0], "pero en Colombia sigue siendo domingo"


# ─── Reprogramar en vez de descartar ────────────────────────────────────────

def test_la_proxima_ventana_salta_el_domingo():
    prox = proxima_ventana_de_contacto(_en(2026, 7, 26, 10))   # domingo
    assert prox.date() == date(2026, 7, 27) and prox.hour == 7


def test_la_proxima_ventana_salta_el_festivo():
    """Sábado 18-jul 16:00 → el domingo no, el lunes 20 es festivo → martes 21."""
    prox = proxima_ventana_de_contacto(_en(2026, 7, 18, 16))
    assert prox.date() == date(2026, 7, 21)


def test_si_ya_estamos_en_ventana_la_proxima_es_ahora():
    prox = proxima_ventana_de_contacto(_en(2026, 7, 21, 10))
    assert prox.date() == date(2026, 7, 21) and prox.hour == 10


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ─── Todo alineado a hora Colombia ──────────────────────────────────────────

def test_ahora_colombia_trae_la_zona_puesta():
    """Nunca un datetime naive: el servidor corre en UTC y un naive se interpreta ahí."""
    from lib.festivos_colombia import ahora_colombia
    a = ahora_colombia()
    assert a.tzinfo is not None
    assert a.utcoffset().total_seconds() == -5 * 3600


def test_hoy_colombia_no_siempre_es_hoy_en_utc():
    """Cinco horas al día son días distintos. Un pedido del sábado a las 20:00 en Colombia
    ya es domingo en UTC — y el domingo está prohibido para contacto comercial."""
    from lib.festivos_colombia import a_hora_colombia
    sabado_noche = datetime(2026, 7, 25, 20, 0, tzinfo=TZ_COLOMBIA)
    en_utc = sabado_noche.astimezone(ZoneInfo("UTC"))
    assert en_utc.date() == date(2026, 7, 26), "en UTC ya es domingo"
    assert a_hora_colombia(en_utc).date() == date(2026, 7, 25), "en Colombia sigue siendo sábado"


def test_un_naive_se_asume_colombiano_no_utc():
    """Adivinar que era UTC sería peor que ser explícito: produciría un corrimiento mudo."""
    from lib.festivos_colombia import a_hora_colombia
    naive = datetime(2026, 7, 21, 10, 0)
    assert a_hora_colombia(naive).hour == 10
    assert a_hora_colombia(naive).tzinfo is not None
