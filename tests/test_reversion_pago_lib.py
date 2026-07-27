"""La reversión del pago: vocabulario legal y plazos.

Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51 (Decreto 587 de 2016), verificados el
2026-07-26 en texto oficial. Lo que se prueba acá es que no volvamos a escribir un plazo
a mano ni a prometer un derecho que no existe — los dos bugs de #192.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from lib.festivos_colombia import TZ_COLOMBIA  # noqa: E402
from lib.reversion_pago import (  # noqa: E402
    CAUSALES,
    CAUSALES_FORMALES,
    QUEJA_DIAS_HABILES,
    TRAMITE_DIAS_HABILES,
    admite_reversion,
    dias_habiles_restantes,
    texto_constancia,
    vence_plazo_de_queja,
    vence_tramite,
)


# ─── Las causales son las de la norma, ni una más ───────────────────────────

def test_son_exactamente_las_cinco_del_articulo():
    """Art. 2.2.2.51.2 enumera cinco. Una sexta sería una causal inventada, y una menos
    sería un derecho recortado."""
    assert set(CAUSALES) == {
        "fraude", "operacion_no_solicitada", "producto_no_recibido",
        "producto_no_corresponde", "producto_defectuoso",
    }
    assert set(CAUSALES_FORMALES) == set(CAUSALES)


def test_la_version_formal_cita_el_numeral():
    """La constancia la lee un banco. Cada causal tiene que ser rastreable al numeral."""
    for clave, texto in CAUSALES_FORMALES.items():
        assert "num." in texto, clave


# ─── Dónde NO procede ───────────────────────────────────────────────────────

@pytest.mark.parametrize("forma", ["cod", "COD", "efectivo", "cash", " Efectivo "])
def test_contra_entrega_en_efectivo_no_admite_reversion(forma):
    """Art. 2.2.2.51.1: no procede sobre pagos por canales presenciales. Decirle a quien
    pagó en efectivo que puede pedir reversión sería prometerle un derecho que no tiene —
    el error exacto de #192."""
    ok, motivo = admite_reversion(forma)
    assert ok is False and motivo == "pago_no_electronico"


@pytest.mark.parametrize("forma", ["wompi", "card", "tarjeta_credito", "pse"])
def test_el_pago_electronico_si_admite(forma):
    assert admite_reversion(forma)[0] is True


def test_sin_forma_de_pago_no_se_afirma_nada():
    """Fail-closed: la constancia afirma hechos, no supuestos."""
    for v in (None, "", "   "):
        ok, motivo = admite_reversion(v)
        assert ok is False and motivo == "forma_de_pago_desconocida"


# ─── Los plazos, calculados y no escritos a mano ────────────────────────────

def test_el_plazo_de_queja_salta_el_fin_de_semana():
    # Lunes 2026-07-06 + 5 hábiles = lunes 2026-07-13 (sáb y dom no cuentan).
    assert vence_plazo_de_queja(date(2026, 7, 6)) == date(2026, 7, 13)


def test_el_plazo_de_queja_salta_los_festivos():
    """El 20 de julio (fijo, no se traslada) cae lunes en 2026: un plazo que arranca el
    viernes 17 no puede vencer contando ese lunes como hábil."""
    assert date(2026, 7, 20).weekday() == 0
    assert vence_plazo_de_queja(date(2026, 7, 17)) == date(2026, 7, 27)


def test_el_tramite_del_emisor_son_quince_habiles():
    """Art. 2.2.2.51.8. No corre contra nosotros: sirve para saber cuándo dejó de ser
    razonable esperar."""
    assert TRAMITE_DIAS_HABILES == 15
    # Lunes 6 de julio + 15 hábiles = martes 28: el 20 de julio es festivo y no cuenta.
    assert vence_tramite(date(2026, 7, 6)) == date(2026, 7, 28)


def test_los_dias_restantes_se_vuelven_negativos_cuando_vence():
    inicio = date(2026, 7, 6)
    assert dias_habiles_restantes(inicio, hoy=date(2026, 7, 6)) == QUEJA_DIAS_HABILES
    assert dias_habiles_restantes(inicio, hoy=date(2026, 7, 13)) == 0
    assert dias_habiles_restantes(inicio, hoy=date(2026, 7, 20)) < 0


def test_la_noche_del_viernes_sigue_siendo_viernes():
    """EL PUNTO DE LA ZONA HORARIA. El servidor corre en UTC: un hecho ocurrido el viernes
    a las 20:00 en Colombia son las 01:00 UTC del sábado. Contar desde el sábado le
    arranca un día al consumidor."""
    viernes_noche_co = datetime(2026, 7, 10, 20, 0, tzinfo=TZ_COLOMBIA)
    assert viernes_noche_co.astimezone(timezone.utc).date() == date(2026, 7, 11)  # sábado
    # Viernes 10 + 5 hábiles = viernes 17.
    assert vence_plazo_de_queja(viernes_noche_co) == date(2026, 7, 17)


# ─── La constancia ──────────────────────────────────────────────────────────

def _constancia(**kw):
    base = {
        "radicado": "RV-000042",
        "presentada_co": "26/07/2026 15:30 (hora Colombia)",
        "causal": "producto_defectuoso",
        "valor": 68000,
        "es_parcial": False,
        "instrumento": "Visa terminada en 4242",
        "bien_a_disposicion": True,
        "vendedor": {"nombre": "KAIU"},
    }
    base.update(kw)
    return base


def test_la_constancia_dice_fecha_y_causal():
    """Es el contenido MÍNIMO que exige el art. 2.2.2.51.4. Sin eso no sirve para nada."""
    t = texto_constancia(_constancia())
    assert "26/07/2026 15:30" in t
    assert "defectuoso" in t and "num. 5" in t


def test_la_constancia_lleva_el_radicado_y_el_valor():
    t = texto_constancia(_constancia())
    assert "RV-000042" in t
    assert "$68.000" in t


def test_dice_que_la_reversion_la_hace_el_banco_no_nosotros():
    """La confusión entre reembolso y reversión es la causa de fondo. Si el comprador
    cree que nosotros vamos a devolverle la plata, no notifica a su emisor y pierde el
    trámite."""
    t = texto_constancia(_constancia())
    assert "no nosotros" in t.lower() or "no la hacemos" in t.lower()


def test_no_promete_plazo_ni_resultado():
    """No depende de nosotros. Prometerlo repetiría el bug de declararle al comprador
    plazos ajenos."""
    t = texto_constancia(_constancia()).lower()
    for promesa in ("te devolveremos", "recibirás tu dinero", "en 15 días te",
                    "garantizamos"):
        assert promesa not in t


def test_la_parcial_se_dice_explicitamente():
    """Art. 2.2.2.51.3: el consumidor debe expresar de manera clara cuál es el valor. Un
    documento que pida reversar $30.000 de una compra de $68.000 sin decir que es parcial
    parece un error de cuentas."""
    t = texto_constancia(_constancia(es_parcial=True, valor=30000))
    assert "parcial" in t.lower() and "$30.000" in t


def test_la_disposicion_del_bien_queda_escrita():
    """Art. 2.2.2.51.4 inc. 3: es lo que libera al consumidor de la obligación de
    devolver el bien."""
    assert "mismo lugar" in texto_constancia(_constancia(bien_a_disposicion=True))
    assert "mismo lugar" not in texto_constancia(_constancia(bien_a_disposicion=False))


def test_no_revienta_con_una_constancia_incompleta():
    """Una constancia congelada de otra versión no puede tumbar el envío."""
    for c in ({}, {"radicado": "RV-1"}, {"valor": "no-es-un-numero"}):
        assert isinstance(texto_constancia(c), str)


def test_cita_las_dos_normas():
    t = texto_constancia(_constancia())
    assert "1480" in t and "2.2.2.51.4" in t


def test_nadie_escribe_los_plazos_a_mano():
    """Mismo guardián que en `legal_texts`: los números legales viven en una constante, y
    escribirlos en el texto es exactamente cómo se desincronizan.

    Se miran solo los literales que SALEN del módulo. Los docstrings y comentarios citan
    la norma a propósito —"art. 2.2.2.51.8: 15 días hábiles"— y prohibirlos ahí obligaría
    a explicar la ley sin nombrarla, que es peor que el bug que esto previene.
    """
    import ast
    fuente = (Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator" /
              "lib" / "reversion_pago.py").read_text()
    arbol = ast.parse(fuente)
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(arbol)
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and n.body and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)
    }
    salida = [
        n.value for n in ast.walk(arbol)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    for texto in salida:
        assert "5 días hábiles" not in texto, texto
        assert "15 días hábiles" not in texto, texto
