"""El interruptor de contra entrega de la consola tiene que servir para algo.

EL BUG, verificado en producción el 2026-07-27:
`tenant_carriers.supports_cod` es la casilla que el comerciante mueve en la consola —"con
esta transportadora sí tengo recaudo pactado"— y nace en `false` porque es un opt-in
explícito post-onboarding. Pero `_resolve_cod` solo leía `cod_override`, que la consola
NUNCA escribe. La casilla era decorativa.

Consecuencia real: KAIU tiene ENVIA con `supports_cod=false` y el bot se la ofreció a una
clienta para un pedido contra entrega. Si la elige, el paquete sale y nadie recauda.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

from lib.carrier_capabilities import _resolve_cod  # noqa: E402


# ─── El caso que rompió ─────────────────────────────────────────────────────

def test_el_comerciante_puede_QUITAR_una_transportadora_del_recaudo():
    """EL CASO REAL. La canónica dice que ENVIA recauda; KAIU dice que con ella no tiene
    recaudo pactado. Manda el comerciante."""
    assert _resolve_cod(True, None, True, tenant_supports_cod=False) is False


def test_y_la_que_si_pacto_sigue_disponible():
    assert _resolve_cod(True, None, True, tenant_supports_cod=True) is True


# ─── Lo que el opt-in NO puede hacer ────────────────────────────────────────

def test_marcar_la_casilla_no_INVENTA_una_capacidad_que_no_existe():
    """Una transportadora que la canónica dice que no recauda no empieza a hacerlo porque
    alguien marque una casilla en la consola. El opt-in quita, no inventa."""
    assert _resolve_cod(False, None, True, tenant_supports_cod=True) is False


def test_para_forzar_contra_la_canonica_esta_el_override():
    """`cod_override` sigue teniendo la última palabra, en las dos direcciones."""
    assert _resolve_cod(False, "force_enable", True, tenant_supports_cod=False) is True
    assert _resolve_cod(True, "force_disable", True, tenant_supports_cod=True) is False


# ─── Compatibilidad con lo que ya existía ───────────────────────────────────

def test_sin_fila_del_tenant_manda_la_canonica_como_antes():
    """`None` es "el tenant no tiene fila para este carrier", que NO es lo mismo que
    "el tenant dijo que no". Distinguirlos es lo que evita romper a quien nunca configuró
    carriers."""
    assert _resolve_cod(True, None, True, tenant_supports_cod=None) is True
    assert _resolve_cod(False, None, True, tenant_supports_cod=None) is False


def test_el_switch_maestro_del_tenant_sigue_ganandole_a_todo():
    """Un comerciante que apaga contra entrega de una vez no tiene que tocar carrier por
    carrier."""
    for opt_in in (True, False, None):
        assert _resolve_cod(True, "force_enable", False, tenant_supports_cod=opt_in) is False


def test_la_firma_vieja_sigue_funcionando():
    """Hay llamadores fuera de este módulo; el parámetro nuevo es opcional."""
    assert _resolve_cod(True, None, True) is True


# ─── Que la columna llegue de verdad ────────────────────────────────────────

@pytest.mark.parametrize("modulo", [
    "services/api/lib/carrier_capabilities.py",
    "services/ai-orchestrator/lib/carrier_capabilities.py",
])
def test_las_consultas_traen_la_columna_que_ahora_se_evalua(modulo):
    """Si el SELECT deja de pedir `supports_cod`, la regla nueva se vuelve muerta en
    silencio: siempre vería None y caería al comportamiento viejo. Es exactamente el modo
    de falla que tuvo el gate de comunicaciones con `consent_given`."""
    fuente = (REPO_ROOT / modulo).read_text()
    selects = [ln for ln in fuente.splitlines()
               if ".select(" in ln and "cod_override" in ln]
    assert selects, "no encontré las consultas a tenant_carriers"
    for ln in selects:
        assert "supports_cod" in ln, ln


def test_las_dos_copias_del_modulo_no_divergen():
    """`services/api` y `services/ai-orchestrator` no se pueden importar entre sí, así que
    el módulo está duplicado. Si divergen, el bot y la consola deciden distinto sobre el
    mismo pedido."""
    a = (REPO_ROOT / "services/api/lib/carrier_capabilities.py").read_text()
    b = (REPO_ROOT / "services/ai-orchestrator/lib/carrier_capabilities.py").read_text()
    assert a == b, "las dos copias de carrier_capabilities divergieron"
