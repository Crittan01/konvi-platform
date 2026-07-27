"""La única puerta por la que sale un mensaje que el cliente no pidió.

Existe porque los caminos de envío proactivo tenían cada uno sus propios controles, y esos
controles habían divergido:

  • el recordatorio de pago solo miraba `human_takeover`, así que un cliente que escribió
    STOP recibía "ya no recibirás mensajes nuestros" y le seguía llegando;
  • el HSM sí filtraba la revocación → dos caminos, dos reglas, la misma persona;
  • el carrito abandonado (MARKETING, con descuento) se autorizaba con el consentimiento
    TRANSACCIONAL, que es justo lo que la Ley 2300 art. 5 par. 2 prohíbe.

Lo que estas pruebas fijan es la diferencia entre las dos categorías. Confundirlas fue la
causa de fondo.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))

from lib.festivos_colombia import TZ_COLOMBIA  # noqa: E402
from lib.outbound_gate import Categoria, puede_enviar_proactivo  # noqa: E402

TENANT = "11111111-1111-1111-1111-111111111111"
CONTACT = "22222222-2222-2222-2222-222222222222"
CONV = "33333333-3333-3333-3333-333333333333"

#: Martes 21-jul-2026, 10:00 en Bogotá: día y hora hábiles para contacto comercial.
EN_VENTANA = datetime(2026, 7, 21, 10, 0, tzinfo=TZ_COLOMBIA)


class _Q:
    def __init__(self, sb, tabla):
        self._sb, self._t = sb, tabla

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._sb.revienta:
            raise RuntimeError("db caída")
        if self._t == "conversations":
            return type("R", (), {"data": [{"contact_id": CONTACT}] if self._sb.hay_conv else []})()
        return type("R", (), {"data": [self._sb.contacto] if self._sb.contacto else []})()


class _FakeSB:
    def __init__(self, contacto=None, *, revienta=False, hay_conv=True):
        self.contacto = contacto
        self.revienta = revienta
        self.hay_conv = hay_conv

    def table(self, t):
        return _Q(self, t)


def _contacto(**over):
    base = {"consent_revoked_at": None, "consent_comercial_at": None,
            "consent_comercial_revoked_at": None}
    base.update(over)
    return base


def _gate(sb, categoria, **kw):
    return puede_enviar_proactivo(
        sb, tenant_id=TENANT, categoria=categoria,
        contact_id=kw.pop("contact_id", CONTACT), ahora=kw.pop("ahora", EN_VENTANA), **kw,
    )


# ─── Lo transaccional ───────────────────────────────────────────────────────

def test_lo_transaccional_pasa_sin_consentimiento_comercial():
    """Confirmar un pedido o avisar la guía ejecuta el contrato que el cliente inició: no
    es publicidad y no necesita consentimiento comercial ni horario."""
    d = _gate(_FakeSB(_contacto()), Categoria.TRANSACCIONAL)
    assert d.permitido


def test_lo_transaccional_tampoco_tiene_horario():
    """Un domingo a las 23:00 se puede avisar que llegó el pedido."""
    domingo = datetime(2026, 7, 26, 23, 0, tzinfo=TZ_COLOMBIA)
    assert _gate(_FakeSB(_contacto()), Categoria.TRANSACCIONAL, ahora=domingo).permitido


def test_pero_la_revocacion_lo_bloquea_IGUAL():
    """EL BUG QUE ESTO CIERRA. Nuestro texto de baja dice "ya no recibirás mensajes
    nuestros": es una promesa absoluta y se cumple absoluta. El recordatorio de pago le
    seguía llegando a quien escribió STOP."""
    sb = _FakeSB(_contacto(consent_revoked_at="2026-07-01T00:00:00Z"))
    d = _gate(sb, Categoria.TRANSACCIONAL)
    assert not d.permitido
    assert d.motivo == "consentimiento_revocado"


# ─── Lo comercial ───────────────────────────────────────────────────────────

def test_lo_comercial_NO_pasa_con_el_consentimiento_transaccional():
    """Ley 2300 art. 5 par. 2: aceptar que traten tus datos para procesar tu pedido NO es
    aceptar publicidad. El carrito abandonado se autorizaba con `consent_given`."""
    d = _gate(_FakeSB(_contacto()), Categoria.COMERCIAL)
    assert not d.permitido
    assert d.motivo == "sin_consentimiento_comercial"


def test_lo_comercial_pasa_con_consentimiento_explicito_y_en_horario():
    sb = _FakeSB(_contacto(consent_comercial_at="2026-07-01T00:00:00Z"))
    assert _gate(sb, Categoria.COMERCIAL).permitido


def test_revocar_el_comercial_lo_bloquea():
    sb = _FakeSB(_contacto(consent_comercial_at="2026-07-01T00:00:00Z",
                           consent_comercial_revoked_at="2026-07-10T00:00:00Z"))
    assert not _gate(sb, Categoria.COMERCIAL).permitido


def test_revocar_habeas_data_bloquea_tambien_lo_comercial():
    """Quien pide no ser contactado no debe recibir publicidad, tenga o no consentimiento
    comercial vigente."""
    sb = _FakeSB(_contacto(consent_comercial_at="2026-07-01T00:00:00Z",
                           consent_revoked_at="2026-07-05T00:00:00Z"))
    d = _gate(sb, Categoria.COMERCIAL)
    assert not d.permitido and d.motivo == "consentimiento_revocado"


# ─── El horario, solo para lo comercial ─────────────────────────────────────

@pytest.mark.parametrize("cuando,esperado", [
    (datetime(2026, 7, 26, 20, 0, tzinfo=TZ_COLOMBIA), "horario_domingo"),
    (datetime(2026, 7, 20, 10, 0, tzinfo=TZ_COLOMBIA), "horario_dia_festivo"),
    (datetime(2026, 7, 21, 22, 0, tzinfo=TZ_COLOMBIA), "horario_fuera_de_horario_7_19"),
    (datetime(2026, 7, 25, 16, 0, tzinfo=TZ_COLOMBIA), "horario_fuera_de_horario_8_15"),
])
def test_fuera_de_la_ventana_no_sale_publicidad(cuando, esperado):
    """El control anterior estaba APAGADO en render.yaml y, aun encendido, solo miraba la
    hora: un domingo a las 20:00 pasaba."""
    sb = _FakeSB(_contacto(consent_comercial_at="2026-07-01T00:00:00Z"))
    d = _gate(sb, Categoria.COMERCIAL, ahora=cuando)
    assert not d.permitido and d.motivo == esperado


# ─── Fail-closed ────────────────────────────────────────────────────────────

def test_si_no_se_puede_verificar_NO_se_envia():
    """Un mensaje que no sale se reintenta; uno que sale sin derecho no se recoge."""
    d = _gate(_FakeSB(_contacto(), revienta=True), Categoria.TRANSACCIONAL)
    assert not d.permitido and d.motivo == "no_pude_verificar_consentimiento"


def test_un_contacto_inexistente_tampoco_pasa():
    d = _gate(_FakeSB(None), Categoria.TRANSACCIONAL)
    assert not d.permitido


def test_sin_destinatario_identificable_no_pasa():
    d = puede_enviar_proactivo(
        _FakeSB(_contacto()), tenant_id=TENANT,
        categoria=Categoria.TRANSACCIONAL, ahora=EN_VENTANA,
    )
    assert not d.permitido and d.motivo == "sin_destinatario_identificable"


def test_sin_tenant_no_pasa():
    d = puede_enviar_proactivo(
        _FakeSB(_contacto()), tenant_id="", categoria=Categoria.TRANSACCIONAL,
        contact_id=CONTACT,
    )
    assert not d.permitido


# ─── Resolver por conversación ──────────────────────────────────────────────

def test_se_puede_pasar_la_conversacion_en_vez_del_contacto():
    """El recordatorio de pago tiene la conversación a mano, no el contacto."""
    sb = _FakeSB(_contacto())
    d = puede_enviar_proactivo(
        sb, tenant_id=TENANT, categoria=Categoria.TRANSACCIONAL,
        conversation_id=CONV, ahora=EN_VENTANA,
    )
    assert d.permitido


def test_una_conversacion_sin_contacto_no_pasa():
    sb = _FakeSB(_contacto(), hay_conv=False)
    d = puede_enviar_proactivo(
        sb, tenant_id=TENANT, categoria=Categoria.TRANSACCIONAL,
        conversation_id=CONV, ahora=EN_VENTANA,
    )
    assert not d.permitido


# ─── La decisión lleva su motivo ────────────────────────────────────────────

def test_la_decision_dice_por_que_en_castellano():
    """Un bloqueo sin motivo registrable es indistinguible de un mensaje perdido."""
    sb = _FakeSB(_contacto())
    d = _gate(sb, Categoria.COMERCIAL)
    assert d.detalle and "Ley 2300" in d.detalle


def test_la_decision_se_puede_usar_como_booleano():
    assert bool(_gate(_FakeSB(_contacto()), Categoria.TRANSACCIONAL))
    assert not bool(_gate(_FakeSB(_contacto()), Categoria.COMERCIAL))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ─── Quien nunca dijo que sí ────────────────────────────────────────────────

def test_nunca_haber_autorizado_no_es_lo_mismo_que_no_haber_revocado():
    """`consent_revoked_at` cubre a quien dijo que no DESPUÉS. Esto cubre a quien nunca
    dijo que sí, que hasta el 2026-07-27 pasaba el gate.

    Lo destapó un test del carrito abandonado cuyo nombre decía "sin consent" y que solo
    fallaba DENTRO del horario de contacto de la Ley 2300 — o sea que el reloj tapaba el
    hueco media jornada.
    """
    sb = _FakeSB(_contacto(consent_given=False,
                           consent_comercial_at="2026-01-01T00:00:00Z"))
    d = _gate(sb, Categoria.COMERCIAL)
    assert not d
    assert d.motivo == "sin_consentimiento_de_datos"


def test_lo_transaccional_sigue_saliendo_sin_ese_consentimiento():
    """Un mensaje transaccional ejecuta el contrato que el cliente inició al escribirnos.
    Bloquear la confirmación de su propio pedido por una casilla que aún no marcó lo
    dejaría sin saber qué compró."""
    sb = _FakeSB(_contacto(consent_given=False))
    assert _gate(sb, Categoria.TRANSACCIONAL)


def test_un_consentimiento_que_no_se_pudo_leer_no_bloquea_por_si_solo():
    """Fail-closed no puede volverse fail-siempre: si el SELECT no trajo la columna, el
    valor es None —"no lo sé"— y tratarlo como "no autorizó" cortaría envíos legítimos.
    La ausencia de la FILA sí bloquea, y eso ya tiene su propio test."""
    sb = _FakeSB(_contacto(consent_comercial_at="2026-01-01T00:00:00Z"))
    assert _gate(sb, Categoria.COMERCIAL)


def test_el_gate_pide_la_columna_que_evalua():
    """Si el SELECT deja de traer `consent_given`, la guarda se vuelve muerta en silencio:
    siempre vería None."""
    import inspect

    import lib.outbound_gate as gate
    assert "consent_given" in inspect.getsource(gate._cargar_contacto)
