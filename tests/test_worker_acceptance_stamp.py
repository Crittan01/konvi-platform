"""El barrido que registra la aceptación del pedido.

Ley 1480 art. 50 lit. d): la aceptación debe ser "expresa, inequívoca y verificable por
la autoridad competente". Las reglas SQL (cuál mensaje cuenta, idempotencia, aislamiento
por tenant) las fija tests/dbharness/test_evidencia_contractual.py. Acá se prueba lo que
el worker HACE con cada respuesta, y sobre todo que este barrido NO dependa del flag de
comprobantes: son dos obligaciones distintas del mismo artículo, y acoplarlas haría que
apagar los comprobantes apagara en silencio la prueba de la aceptación.
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

ORDER = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"


class _FakeSB:
    def __init__(self, *, pendientes=None, respuesta=None, revienta=None):
        self.pendientes = pendientes if pendientes is not None else [
            {"order_id": ORDER, "tenant_id": TENANT}]
        self.respuesta = respuesta if respuesta is not None else {
            "estampado": True, "motivo": None}
        self.revienta = revienta or set()
        self.llamadas: list = []

    def table(self, _n):
        raise AssertionError("el barrido no debe tocar tablas: todo pasa por las RPC")

    def rpc(self, nombre, params=None):
        self.llamadas.append((nombre, params))
        if nombre in self.revienta:
            raise RuntimeError(f"{nombre} falló")
        datos = {
            "rpc_find_orders_pending_acceptance": self.pendientes,
            "rpc_stamp_order_acceptance": [self.respuesta],
        }.get(nombre, [])
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": datos})()})()

    def nombres(self):
        return [n for n, _ in self.llamadas]


def _worker(sb):
    os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://stub.test")
    os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "stub_key")
    import supabase as _sp
    saved = sys.modules.get("worker")
    try:
        with patch.object(_sp, "create_client", return_value=sb):
            sys.modules.pop("worker", None)
            import worker as _w
            inst = _w.OrchestratorWorker()
            inst.supabase = sb
            inst._acceptance_enabled = True
            inst._last_acceptance_at = 0.0
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr(inst):
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        inst._stamp_acceptances_if_due())


def test_estampa_y_lo_cuenta():
    sb = _FakeSB()
    _, inst = _worker(sb)
    _correr(inst)
    assert "rpc_stamp_order_acceptance" in sb.nombres()
    assert inst._metrics["acceptances_stamped"] == 1


def test_no_depende_del_flag_de_comprobantes():
    """EL PUNTO DE SEPARARLOS. Apagar la emisión de comprobantes no puede apagar el
    registro de la aceptación: son obligaciones distintas."""
    sb = _FakeSB()
    _, inst = _worker(sb)
    inst._receipt_enabled = False
    _correr(inst)
    assert inst._metrics["acceptances_stamped"] == 1


def test_un_pedido_ya_estampado_no_se_reescribe_ni_alarma():
    sb = _FakeSB(respuesta={"estampado": False, "motivo": "ya_estampada"})
    _, inst = _worker(sb)
    _correr(inst)
    assert inst._metrics["acceptances_stamped"] == 0
    assert inst._metrics["acceptances_unstampable"] == 0


def test_un_pedido_sin_mensaje_del_cliente_queda_registrado(caplog):
    """No se inventa una aceptación, pero tampoco se calla: si esto pasa seguido, algo
    está creando pedidos sin que medie manifestación del comprador."""
    sb = _FakeSB(respuesta={"estampado": False, "motivo": "sin_mensaje_del_cliente"})
    _, inst = _worker(sb)
    with caplog.at_level("WARNING"):
        _correr(inst)
    assert inst._metrics["acceptances_unstampable"] == 1
    assert "sin mensaje del cliente" in caplog.text


def test_si_falla_un_pedido_los_demas_siguen():
    class _SB(_FakeSB):
        def rpc(self, nombre, params=None):
            self.llamadas.append((nombre, params))
            if nombre == "rpc_stamp_order_acceptance" and params["p_order_id"] == ORDER:
                raise RuntimeError("timeout")
            datos = {
                "rpc_find_orders_pending_acceptance": self.pendientes,
                "rpc_stamp_order_acceptance": [{"estampado": True, "motivo": None}],
            }.get(nombre, [])
            return type("R", (), {"execute": lambda _s: type("D", (), {"data": datos})()})()

    otro = "33333333-3333-3333-3333-333333333333"
    sb = _SB(pendientes=[{"order_id": ORDER, "tenant_id": TENANT},
                         {"order_id": otro, "tenant_id": TENANT}])
    _, inst = _worker(sb)
    _correr(inst)
    assert inst._metrics["acceptances_stamped"] == 1


def test_si_el_buscador_falla_no_revienta_el_worker():
    sb = _FakeSB(revienta={"rpc_find_orders_pending_acceptance"})
    _, inst = _worker(sb)
    _correr(inst)          # no debe propagar
    assert "rpc_stamp_order_acceptance" not in sb.nombres()


def test_apagado_por_flag_no_hace_nada():
    sb = _FakeSB()
    _, inst = _worker(sb)
    inst._acceptance_enabled = False
    _correr(inst)
    assert sb.llamadas == []


def test_respeta_su_intervalo():
    """El barrido corre en cada ciclo del worker (segundos); sin la guarda golpearía la
    base cientos de veces por minuto para no encontrar nada."""
    sb = _FakeSB()
    _, inst = _worker(sb)
    _correr(inst)
    n = len(sb.llamadas)
    _correr(inst)
    assert len(sb.llamadas) == n


def test_pasa_la_ventana_y_el_diferimiento_configurados():
    sb = _FakeSB()
    w, inst = _worker(sb)
    _correr(inst)
    _, params = sb.llamadas[0]
    assert params["p_min_age_minutes"] == w.ACCEPTANCE_MIN_AGE_MINUTES
    assert params["p_window_days"] == w.ACCEPTANCE_WINDOW_DAYS
    assert params["p_limit"] == w.ACCEPTANCE_BATCH


def test_esta_registrado_en_el_ciclo_del_worker():
    """Un barrido que existe pero nadie llama es un barrido que no existe.
    G9: el ciclo itera las tuplas module-level _INBOUND_JOBS/_MAINTENANCE_JOBS;
    el registro vive ahí (lo ejecutan tanto _poll_cycle como los loops)."""
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "worker.py").read_text()
    assert '("acceptance_stamp", "_stamp_acceptances_if_due")' in fuente
