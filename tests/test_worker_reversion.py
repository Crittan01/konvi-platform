"""El barrido que entrega la constancia de reversión y grita cuando se pagó dos veces.

Decreto 1074 art. 2.2.2.51.4: el proveedor "deberá emitir constancia" de la queja. Pero
emitirla y dejarla en una tabla no cumple nada: el art. 2.2.2.51.7 num. 6 se la exige al
consumidor como contenido de la notificación a SU banco. Si no la tiene en la mano, no
puede ejercer el derecho.

Las reglas de la base (radicación, idempotencia, detección del doble pago) las fija
tests/dbharness/test_reversion_pago.py. Acá se prueba qué HACE el worker.
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

REV = "11111111-1111-1111-1111-111111111111"
TENANT = "22222222-2222-2222-2222-222222222222"
CONV = "33333333-3333-3333-3333-333333333333"

CONSTANCIA = {
    "radicado": "RV-000042",
    "presentada_co": "26/07/2026 15:30 (hora Colombia)",
    "causal": "producto_defectuoso",
    "valor": 68000,
    "vendedor": {"nombre": "KAIU"},
}


class _FakeSB:
    def __init__(self, *, pendientes=None, dobles=None, telefono="+573001112233",
                 marca=True, revienta=None, dentro_de_csw=True):
        self.pendientes = pendientes if pendientes is not None else [{
            "reversal_id": REV, "tenant_id": TENANT, "conversation_id": CONV,
            "radicado": "RV-000042", "constancia": CONSTANCIA,
            # La ventana de servicio de 24h de Meta. La calcula el buscador, igual que
            # para el acuse del comprobante.
            "dentro_de_csw": dentro_de_csw,
        }]
        self.dobles = dobles if dobles is not None else []
        self.telefono = telefono
        self.marca = marca
        self.revienta = revienta or set()
        self.llamadas: list = []
        self.mensajes: list = []

    def table(self, nombre):
        sb = self

        class _Q:
            def __init__(self): self._t = nombre
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def insert(self, payload):
                sb.mensajes.append(payload)
                return self
            def execute(self):
                if self._t == "conversations":
                    data = [{"customer_phone": sb.telefono}] if sb.telefono else [{}]
                    return type("D", (), {"data": data})()
                return type("D", (), {"data": []})()
        return _Q()

    def rpc(self, nombre, params=None):
        self.llamadas.append((nombre, params))
        if nombre in self.revienta:
            raise RuntimeError(f"{nombre} falló")
        datos = {
            "rpc_find_constancias_por_entregar": self.pendientes,
            "rpc_find_dobles_pagos_sin_avisar": self.dobles,
            "rpc_mark_constancia_entregada": self.marca,
            "rpc_mark_doble_pago_avisado": self.marca,
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
            inst._reversal_enabled = True
            inst._last_reversal_at = 0.0
            return _w, inst
    finally:
        if saved is not None:
            sys.modules["worker"] = saved


def _correr(w, inst, *, meta_id="wamid.OK", telegram=None, notify_ok=True):
    async def _send(**kw):
        _send.enviados.append(kw)
        return meta_id
    _send.enviados = []
    telegram = telegram if telegram is not None else []

    async def _notify(sb, **kw):
        telegram.append(kw)
        return notify_ok

    mod = type(sys)("telegram_notifications")
    mod.notify_escalation_async = _notify
    sys.modules["telegram_notifications"] = mod
    import worker_commerce_crons as _wcc  # G12: los métodos movidos resuelven
    # el sender desde el namespace del MIXIN — el patch va ahí.
    with patch.object(_wcc, "send_whatsapp_message", _send):
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            inst._sweep_reversals_if_due())
    return _send.enviados, telegram


# ─── La constancia llega ────────────────────────────────────────────────────

def test_la_constancia_se_entrega_al_comprador():
    """EL PUNTO. Sin la constancia en la mano, el consumidor no puede notificar a su banco
    (art. 2.2.2.51.7 num. 6) y el derecho queda en el papel."""
    sb = _FakeSB()
    w, inst = _worker(sb)
    enviados, _ = _correr(w, inst)
    assert len(enviados) == 1
    assert "RV-000042" in enviados[0]["text"]
    assert inst._metrics["reversal_constancias_sent"] == 1


def test_el_texto_lleva_fecha_y_causal():
    """Contenido mínimo del art. 2.2.2.51.4."""
    sb = _FakeSB()
    w, inst = _worker(sb)
    enviados, _ = _correr(w, inst)
    t = enviados[0]["text"]
    assert "26/07/2026 15:30" in t and "defectuoso" in t


def test_queda_registrada_en_la_conversacion():
    """Si no queda en `messages`, el operador que abra el chat no ve que se emitió."""
    sb = _FakeSB()
    w, inst = _worker(sb)
    _correr(w, inst)
    assert any("RV-000042" in (m.get("content") or "") for m in sb.mensajes)


def test_si_no_sale_no_se_marca_y_se_reintenta():
    """Darla por perdida al primer fallo le cerraría el trámite al consumidor."""
    sb = _FakeSB()
    w, inst = _worker(sb)
    _correr(w, inst, meta_id=None)
    assert "rpc_mark_constancia_entregada" not in sb.nombres()
    assert inst._metrics["reversal_constancias_sent"] == 0


def test_sin_telefono_se_marca_fallida_y_no_gira_para_siempre():
    sb = _FakeSB(telefono=None)
    w, inst = _worker(sb)
    _correr(w, inst)
    marcas = [p for n, p in sb.llamadas if n == "rpc_mark_constancia_entregada"]
    assert marcas and marcas[0]["p_fallida"] == "sin_telefono"


def test_si_otro_tick_gano_la_carrera_no_se_duplica_el_mensaje():
    sb = _FakeSB(marca=False)
    w, inst = _worker(sb)
    _correr(w, inst)
    assert sb.mensajes == []
    assert inst._metrics["reversal_constancias_sent"] == 0


# ─── El doble pago ──────────────────────────────────────────────────────────

def _doble():
    return [{"reversal_id": REV, "tenant_id": TENANT, "radicado": "RV-000042",
             "reembolso": 68000, "reversion": 68000}]


def test_el_doble_pago_se_avisa_al_equipo():
    """Art. 2.2.2.51.10: la norma contempla que el comerciante pague dos veces y que el
    consumidor deba devolverlo. Sin aviso sería invisible — nadie está mirando las dos
    cosas al tiempo."""
    sb = _FakeSB(pendientes=[], dobles=_doble())
    w, inst = _worker(sb)
    _, telegram = _correr(w, inst)
    assert len(telegram) == 1
    assert "RV-000042" in telegram[0]["reason"]
    assert "2.2.2.51.10" in telegram[0]["reason"]
    assert inst._metrics["reversal_double_payments"] == 1


def test_si_el_aviso_falla_no_se_marca():
    """Un doble pago que nadie ve es plata perdida: se reintenta."""
    sb = _FakeSB(pendientes=[], dobles=_doble())
    w, inst = _worker(sb)

    async def _revienta(_sb, **kw):
        raise RuntimeError("telegram caído")
    mod = type(sys)("telegram_notifications")
    mod.notify_escalation_async = _revienta
    sys.modules["telegram_notifications"] = mod

    async def _send(**kw):
        return "wamid.X"
    import worker_commerce_crons as _wcc  # G12: los métodos movidos resuelven
    # el sender desde el namespace del MIXIN — el patch va ahí.
    with patch.object(_wcc, "send_whatsapp_message", _send):
        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
            inst._sweep_reversals_if_due())
    assert "rpc_mark_doble_pago_avisado" not in sb.nombres()


# ─── Robustez del barrido ───────────────────────────────────────────────────

def test_apagado_por_flag_no_hace_nada():
    sb = _FakeSB()
    w, inst = _worker(sb)
    inst._reversal_enabled = False
    _correr(w, inst)
    assert sb.llamadas == []


def test_respeta_su_intervalo():
    sb = _FakeSB()
    w, inst = _worker(sb)
    _correr(w, inst)
    n = len(sb.llamadas)
    _correr(w, inst)
    assert len(sb.llamadas) == n


def test_si_falla_el_buscador_de_constancias_igual_revisa_los_dobles_pagos():
    """Son dos obligaciones independientes: que una consulta falle no puede tapar la otra."""
    sb = _FakeSB(revienta={"rpc_find_constancias_por_entregar"}, dobles=_doble())
    w, inst = _worker(sb)
    _, telegram = _correr(w, inst)
    assert len(telegram) == 1


def test_esta_registrado_en_el_ciclo_del_worker():
    # G9: el registro vive en las tuplas module-level _INBOUND_JOBS/_MAINTENANCE_JOBS
    # (ejecutadas por _poll_cycle y por los loops separados de run()).
    fuente = (REPO_ROOT / "services" / "ai-orchestrator" / "worker.py").read_text()
    assert '("reversal_constancias", "_sweep_reversals_if_due")' in fuente


# ─── La ventana de 24h de Meta ──────────────────────────────────────────────

def test_fuera_de_la_ventana_no_se_manda_a_ciegas():
    """Escenario previsto por la norma: la queja entra por teléfono (art. 2.2.2.51.4 —
    "cualquiera fuere el medio"), el operador la radica desde la consola, y el último
    mensaje del comprador fue hace tres días.

    Antes: Meta rechazaba el free-form con 131047, `send_whatsapp_message` devolvía None
    sin lanzar, el worker no marcaba nada y reintentaba cada 300 s **para siempre** — 288
    POST fallidos por día, sin métrica ni alerta.
    """
    sb = _FakeSB(dentro_de_csw=False)
    w, inst = _worker(sb)
    enviados, _ = _correr(w, inst)
    assert enviados == [], "se intentó mandar free-form fuera de la ventana"
    marcas = [p for n, p in sb.llamadas if n == "rpc_mark_constancia_entregada"]
    assert marcas and marcas[0]["p_fallida"] == "fuera_de_ventana_csw"
    assert inst._metrics["reversal_constancias_failed"] == 1


def test_la_cola_no_queda_tapada_por_las_que_no_se_pueden_entregar():
    """El buscador ordena por fecha de emisión: si las no entregables no salen de la cola,
    acumuladas 50 tapan a las nuevas que sí eran entregables."""
    sb = _FakeSB(pendientes=[
        {"reversal_id": "vieja", "tenant_id": TENANT, "conversation_id": CONV,
         "radicado": "RV-000001", "constancia": CONSTANCIA, "dentro_de_csw": False},
        {"reversal_id": REV, "tenant_id": TENANT, "conversation_id": CONV,
         "radicado": "RV-000042", "constancia": CONSTANCIA, "dentro_de_csw": True},
    ])
    w, inst = _worker(sb)
    enviados, _ = _correr(w, inst)
    assert len(enviados) == 1                      # la entregable sí salió
    assert inst._metrics["reversal_constancias_sent"] == 1
    assert inst._metrics["reversal_constancias_failed"] == 1


# ─── El aviso que no se avisó ───────────────────────────────────────────────

def test_si_telegram_no_esta_configurado_NO_se_marca_como_avisado():
    """`notify_escalation_async` no lanza: devuelve False cuando el tenant no tiene el
    canal habilitado — el estado por defecto de un tenant nuevo. Marcarlo igual sacaba la
    fila de la cola PARA SIEMPRE y nadie se enteraba de que se pagó dos veces."""
    sb = _FakeSB(pendientes=[], dobles=_doble())
    w, inst = _worker(sb)
    _, telegram = _correr(w, inst, notify_ok=False)
    assert len(telegram) == 1                       # se intentó
    assert "rpc_mark_doble_pago_avisado" not in sb.nombres()
    assert inst._metrics["reversal_double_payments"] == 0


def test_el_latido_va_dentro_de_los_dos_loops_nuevos():
    """`run()` late una vez por ciclo y /health corta a los 120 s. Un lote de 50 envíos a
    Meta con timeout de 10 s pasa ese umbral y Render reinicia el worker a mitad del
    barrido; al reiniciar arranca por las mismas filas. Los demás loops con I/O de red ya
    laten por ítem."""
    import ast
    # G12: `_deliver_reversal_constancias` vive ahora en worker_commerce_crons.py
    # (mixin). El guardián lee AMBOS archivos — la propiedad (latido por ítem
    # en el for del barrido) se verifica dondequiera que viva el método.
    arboles = [
        ast.parse((REPO_ROOT / "services" / "ai-orchestrator" / f).read_text())
        for f in ("worker.py", "worker_commerce_crons.py")
    ]

    def late_dentro_del_for(nombre):
        for arbol in arboles:
            for n in ast.walk(arbol):
                if isinstance(n, ast.AsyncFunctionDef) and n.name == nombre:
                    for f in ast.walk(n):
                        if not isinstance(f, ast.For):
                            continue
                        for st in f.body:
                            if (isinstance(st, ast.Assign)
                                    and any(isinstance(t, ast.Attribute)
                                            and t.attr == "last_heartbeat_ts" for t in st.targets)):
                                return True
        return False

    for barrido in ("_deliver_reversal_constancias", "_stamp_acceptances_if_due"):
        assert late_dentro_del_for(barrido), f"{barrido} no late por ítem"
