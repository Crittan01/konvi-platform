"""El barrido que avisa cuando un pedido dice dos precios distintos a la vez.

La suma de los ítems más el envío menos el descuento debería dar el total que se cobra.
Cuando no da, el pedido se contradice — y Ley 1480 art. 26 es explícita: en ese caso el
consumidor solo está obligado al menor.

No es hipotético: `confirm_rate` bajaba la tarifa real de envío y no recalculaba el total
(cerrado en #175). Nadie se enteraba salvo que alguien mirara ese pedido en concreto.

El cálculo vive en SQL (tests/dbharness/test_order_money.py fija dónde está la raya entre
ruido de redondeo y error de dinero). Acá se prueba que el worker lo mire y lo grite.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "ai-orchestrator"))

if "vault_helper" not in sys.modules:
    _stub = type(sys)("vault_helper")
    _stub.VaultHelper = type("_V", (), {"__init__": lambda self, sb: None})
    _stub.resolve_secret = lambda v, c, f: c.get(f, "")
    sys.modules["vault_helper"] = _stub


class _FakeSB:
    def __init__(self, filas, revienta=False):
        self._filas, self._revienta = filas, revienta
        self.llamadas: list = []

    def table(self, _n):
        raise AssertionError("el barrido no debe tocar tablas: el cálculo vive en la RPC")

    def rpc(self, nombre, params=None):
        if self._revienta:
            raise RuntimeError("function public.rpc_find_incoherent_orders does not exist")
        self.llamadas.append((nombre, params))
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": self._filas})()})()


def _fila(**over):
    base = {
        "order_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "22222222-2222-2222-2222-222222222222",
        "status": "confirmed", "total_registrado": 60000,
        "total_calculado": 68000, "diferencia": 8000,
    }
    base.update(over)
    return base


def _worker(sb):
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
    os.environ.setdefault("SUPABASE_SECRET_KEY", "stub_key")
    import supabase as _sp
    saved = sys.modules.get("worker")
    try:
        with patch.object(_sp, "create_client", return_value=sb):
            sys.modules.pop("worker", None)
            import worker as _w
            inst = _w.OrchestratorWorker()
            inst.supabase = sb
            inst._order_coherence_enabled = True
            inst._last_order_coherence_at = 0.0
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr(inst):
    asyncio.run(inst._check_order_coherence_if_due())


# ─── Lo que hace ────────────────────────────────────────────────────────────

def test_grita_cuando_un_pedido_no_cuadra(caplog):
    sb = _FakeSB([_fila()])
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)
    assert inst._metrics["incoherent_orders_detected"] == 1
    assert any("no cuadran" in r.getMessage() for r in caplog.records)


def test_dice_de_cuanto_es_la_diferencia(caplog):
    """Saber que "algo está mal" no sirve: hay que poder decidir si son 8.000 pesos o 3."""
    sb = _FakeSB([_fila(diferencia=8000)])
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "8000" in texto and "60000" in texto and "68000" in texto


def test_cuenta_todos_los_encontrados():
    sb = _FakeSB([_fila(order_id=f"{i}" * 8) for i in range(1, 4)])
    _, inst = _worker(sb)
    _correr(inst)
    assert inst._metrics["incoherent_orders_detected"] == 3


def test_una_fila_sin_datos_no_tumba_el_resto(caplog):
    sb = _FakeSB([{"order_id": None, "tenant_id": None}, _fila()])
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)   # no debe lanzar
    assert inst._metrics["incoherent_orders_detected"] == 2


# ─── Lo que NO hace ─────────────────────────────────────────────────────────

def test_sin_incoherencias_no_dice_nada(caplog):
    sb = _FakeSB([])
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)
    assert inst._metrics["incoherent_orders_detected"] == 0
    assert [r for r in caplog.records if r.levelname == "ERROR"] == []


def test_apagado_por_flag_no_consulta():
    sb = _FakeSB([_fila()])
    _, inst = _worker(sb)
    inst._order_coherence_enabled = False
    _correr(inst)
    assert sb.llamadas == []


def test_sin_la_migracion_avisa_pero_no_rompe(caplog):
    """El worker puede desplegarse antes que la migración; el ciclo no puede caerse por eso."""
    sb = _FakeSB([], revienta=True)
    _, inst = _worker(sb)
    with caplog.at_level("WARNING"):
        _correr(inst)   # no debe lanzar
    assert inst._metrics["incoherent_orders_detected"] == 0


def test_no_barre_dos_veces_seguidas():
    sb = _FakeSB([_fila()])
    _, inst = _worker(sb)
    _correr(inst)
    _correr(inst)
    assert len(sb.llamadas) == 1, "el intervalo mínimo no se respetó"


def test_el_calculo_no_se_duplica_en_python():
    """Que el worker NO sume ítems por su cuenta es el punto: hay 5 caminos a 'confirmed'
    en 3 servicios, y una fórmula repetida es una que se desincroniza."""
    sb = _FakeSB([_fila()])
    _, inst = _worker(sb)
    _correr(inst)   # _FakeSB.table() revienta si el worker intenta calcular por su cuenta
    assert sb.llamadas[0][0] == "rpc_find_incoherent_orders"


def test_la_ventana_es_configurable():
    sb = _FakeSB([])
    mod, inst = _worker(sb)
    _correr(inst)
    params = sb.llamadas[0][1]
    assert params["p_window_hours"] == mod.ORDER_COHERENCE_WINDOW_HOURS
    assert params["p_limit"] == mod.ORDER_COHERENCE_BATCH


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
