"""El barrido que emite los comprobantes y anula los que quedaron colgados.

Ley 1480 art. 50 lit. d) obliga a remitir acuse de recibo del pedido a más tardar el día
calendario siguiente. Hoy el comprador no recibe ningún documento.

Las reglas SQL (cuándo un pedido es emitible, cuándo se anula) las fija
tests/dbharness/test_receipt_lifecycle.py. Acá se prueba lo que el worker HACE con cada
respuesta — y sobre todo que un pedido con cifras que no cuadran NO produzca documento
pero SÍ produzca alerta.
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
    """Responde por nombre de RPC. Registra qué se llamó y con qué."""

    def __init__(self, *, pendientes=None, emision=None, colgados=None, revienta=None):
        self.pendientes = pendientes if pendientes is not None else []
        self.emision = emision or {"numero": "CP-000001", "ya_existia": False, "motivo": None}
        self.colgados = colgados or []
        self.revienta = revienta or set()
        self.llamadas: list = []

    def table(self, _n):
        raise AssertionError("el barrido no debe tocar tablas: todo pasa por las RPC")

    def rpc(self, nombre, params=None):
        self.llamadas.append((nombre, params))
        if nombre in self.revienta:
            raise RuntimeError(f"{nombre} no existe")
        datos = {
            "rpc_find_orders_pending_receipt": self.pendientes,
            "rpc_issue_receipt": [self.emision],
            "rpc_find_receipts_to_void": self.colgados,
            "rpc_void_receipt": [{"anulado": True}],
        }.get(nombre, [])
        return type("R", (), {"execute": lambda _s: type("D", (), {"data": datos})()})()

    def nombres(self):
        return [n for n, _ in self.llamadas]


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
            inst._receipt_enabled = True
            inst._last_receipt_at = 0.0
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr(inst):
    asyncio.run(inst._issue_receipts_if_due())


PEND = [{"order_id": ORDER, "tenant_id": TENANT, "confirmado_hace_min": 30}]


# ─── Emisión ────────────────────────────────────────────────────────────────

def test_emite_el_comprobante_de_un_pedido_pendiente(caplog):
    sb = _FakeSB(pendientes=PEND)
    _, inst = _worker(sb)
    with caplog.at_level("INFO"):
        _correr(inst)
    assert inst._metrics["receipts_issued"] == 1
    assert any("CP-000001" in r.getMessage() for r in caplog.records)


def test_pasa_el_pedido_y_el_tenant_correctos():
    """Sin el tenant, emitir sería cross-tenant."""
    sb = _FakeSB(pendientes=PEND)
    _, inst = _worker(sb)
    _correr(inst)
    params = dict(sb.llamadas)["rpc_issue_receipt"]
    assert params == {"p_order_id": ORDER, "p_tenant_id": TENANT}


def test_lo_ya_emitido_no_se_cuenta_dos_veces():
    sb = _FakeSB(pendientes=PEND, emision={"numero": "CP-000001", "ya_existia": True, "motivo": None})
    _, inst = _worker(sb)
    _correr(inst)
    assert inst._metrics["receipts_issued"] == 0


def test_sin_pendientes_no_emite_nada():
    sb = _FakeSB(pendientes=[])
    _, inst = _worker(sb)
    _correr(inst)
    assert "rpc_issue_receipt" not in sb.nombres()
    assert inst._metrics["receipts_issued"] == 0


# ─── La guarda de coherencia ────────────────────────────────────────────────

def test_un_pedido_con_cifras_que_no_cuadran_no_produce_documento(caplog):
    """Ley 1480 art. 26: ante dos precios el consumidor solo debe el menor. Documentar
    una contradicción es peor que no documentar."""
    sb = _FakeSB(pendientes=PEND,
                 emision={"numero": None, "ya_existia": False, "motivo": "cifras_incoherentes"})
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)
    assert inst._metrics["receipts_issued"] == 0
    assert inst._metrics["receipts_blocked_incoherent"] == 1


def test_pero_sí_produce_alerta(caplog):
    """No emitir en silencio sería el peor de los dos mundos: sin documento y sin aviso."""
    sb = _FakeSB(pendientes=PEND,
                 emision={"numero": None, "ya_existia": False, "motivo": "cifras_incoherentes"})
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "no cuadran" in texto and "art. 26" in texto


def test_otro_motivo_no_se_confunde_con_incoherencia(caplog):
    sb = _FakeSB(pendientes=PEND,
                 emision={"numero": None, "ya_existia": False, "motivo": "pedido_inexistente"})
    _, inst = _worker(sb)
    with caplog.at_level("WARNING"):
        _correr(inst)
    assert inst._metrics["receipts_blocked_incoherent"] == 0
    assert inst._metrics["receipts_issued"] == 0


# ─── Anulación de los colgados ──────────────────────────────────────────────

def test_anula_los_comprobantes_de_pedidos_cancelados(caplog):
    sb = _FakeSB(colgados=[{"order_id": ORDER, "tenant_id": TENANT,
                            "numero": "CP-000007", "estado_pedido": "cancelled"}])
    _, inst = _worker(sb)
    with caplog.at_level("WARNING"):
        _correr(inst)
    assert inst._metrics["receipts_voided"] == 1
    assert "rpc_void_receipt" in sb.nombres()


def test_la_anulacion_dice_que_fue_reconciliacion():
    """Distinguirlo de la anulación en vivo permite saber que el trigger falló."""
    sb = _FakeSB(colgados=[{"order_id": ORDER, "tenant_id": TENANT, "numero": "CP-7"}])
    _, inst = _worker(sb)
    _correr(inst)
    assert "reconciliación" in dict(sb.llamadas)["rpc_void_receipt"]["p_reason"]


def test_sin_colgados_no_anula_nada():
    sb = _FakeSB()
    _, inst = _worker(sb)
    _correr(inst)
    assert "rpc_void_receipt" not in sb.nombres()


# ─── Degradación ────────────────────────────────────────────────────────────

def test_un_fallo_emitiendo_no_frena_a_los_demas(caplog):
    sb = _FakeSB(pendientes=[
        {"order_id": ORDER, "tenant_id": TENANT},
        {"order_id": ORDER.replace("1", "3"), "tenant_id": TENANT},
    ])
    llamadas = {"n": 0}
    original = sb.rpc

    def _rpc(nombre, params=None):
        if nombre == "rpc_issue_receipt":
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                sb.llamadas.append((nombre, params))
                raise RuntimeError("timeout")
        return original(nombre, params)

    sb.rpc = _rpc
    _, inst = _worker(sb)
    with caplog.at_level("ERROR"):
        _correr(inst)
    assert inst._metrics["receipts_issued"] == 1, "el segundo pedido igual debe emitirse"


def test_fila_incompleta_se_saltea():
    sb = _FakeSB(pendientes=[{"order_id": None, "tenant_id": None}, {"order_id": ORDER, "tenant_id": TENANT}])
    _, inst = _worker(sb)
    _correr(inst)
    assert inst._metrics["receipts_issued"] == 1


def test_sin_la_migracion_avisa_pero_no_rompe():
    """El worker puede desplegarse antes que la migración."""
    sb = _FakeSB(revienta={"rpc_find_orders_pending_receipt"})
    _, inst = _worker(sb)
    _correr(inst)   # no debe lanzar
    assert inst._metrics["receipts_issued"] == 0


def test_si_falla_buscar_colgados_lo_ya_emitido_se_conserva():
    sb = _FakeSB(pendientes=PEND, revienta={"rpc_find_receipts_to_void"})
    _, inst = _worker(sb)
    _correr(inst)
    assert inst._metrics["receipts_issued"] == 1


def test_apagado_por_flag_no_hace_nada():
    sb = _FakeSB(pendientes=PEND)
    _, inst = _worker(sb)
    inst._receipt_enabled = False
    _correr(inst)
    assert sb.llamadas == []


def test_no_barre_dos_veces_seguidas():
    sb = _FakeSB(pendientes=PEND)
    _, inst = _worker(sb)
    _correr(inst)
    n = len(sb.llamadas)
    _correr(inst)
    assert len(sb.llamadas) == n


def test_el_margen_de_espera_es_configurable_y_no_cero():
    """Si fuera 0, en contra entrega se intentaría emitir antes de que existan los ítems y
    el comprobante nunca saldría."""
    sb = _FakeSB()
    mod, inst = _worker(sb)
    _correr(inst)
    params = dict(sb.llamadas)["rpc_find_orders_pending_receipt"]
    assert params["p_min_age_minutes"] == mod.RECEIPT_MIN_AGE_MINUTES
    assert params["p_min_age_minutes"] >= 5, "margen demasiado corto para el camino COD"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
