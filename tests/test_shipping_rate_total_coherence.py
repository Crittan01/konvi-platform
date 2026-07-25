"""Confirmar la tarifa de envío dejaba el pedido cobrando un total que ya no era el suyo.

`confirm_rate` bajaba la tarifa real a `orders.shipping_cost` con un UPDATE de UNA columna y
dejaba `total_amount` con el envío ESTIMADO adentro. Y `total_amount` es el que se cobra:
`orders.py` arma el link de pago con `amount_in_cents = int(round(total_amount * 100))`.
Nadie lo recalculaba después.

Consecuencia según hacia dónde se moviera la tarifa: el tenant pone la diferencia, o el
cliente paga de más. En contra entrega es peor, porque el transportador cobra el total viejo
en la puerta — y ese es el caso que el UAT de julio ya había olido ("COD quote incoherence").

Aparte del dinero, el pedido quedaba diciendo dos cosas a la vez: ítems + envío − descuento
no daba el total impreso. Ley 1480 art. 26: si al consumidor le aparecen dos precios, solo
está obligado al menor.

La regla que fijan estas pruebas: **nunca cambiar en silencio lo que un cliente ya pagó**.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

API = Path(__file__).resolve().parents[1] / "services" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))


@pytest.fixture
def mod():
    from routers import shipping
    return shipping


class _Tabla:
    def __init__(self, sb, nombre):
        self._sb, self._n = sb, nombre
        self._op = "select"

    def select(self, *a, **k):
        return self

    def update(self, payload):
        self._op = "update"
        self._sb.updates.append((self._n, payload))
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._op == "update":
            return MagicMock(data=[{}])
        return MagicMock(data=self._sb.datos.get(self._n))


class _SB:
    """Devuelve filas por tabla; registra los UPDATE, que es lo que importa medir."""

    def __init__(self, orden, items, pago_aprobado=False):
        self.updates: list = []
        self.datos = {
            "orders": orden,
            "order_items": items,
            "payments": [{"id": "pay-1"}] if pago_aprobado else [],
        }

    def table(self, nombre):
        return _Tabla(self, nombre)


def _orden(**over):
    base = {"id": "ord-1", "status": "pending_payment", "total_amount": 60000.0,
            "shipping_cost": 10000.0, "discount_amount": 0.0}
    base.update(over)
    return base


ITEMS = [{"unit_price": 25000.0, "quantity": 2}]   # subtotal = 50.000


def _sync(mod, sb, envio):
    return mod._sincronizar_envio_en_orden(
        sb, tenant_id="ten-1", order_id="ord-1", nuevo_envio=envio,
    )


def _update_de_orders(sb):
    return [p for t, p in sb.updates if t == "orders"]


# ─── Lo que se arregla ──────────────────────────────────────────────────────

def test_el_total_se_recalcula_con_la_tarifa_real(mod):
    """Subtotal 50.000 + envío real 18.000 = 68.000. Antes quedaba en 60.000 (envío estimado
    de 10.000) y se le cobraba eso al cliente."""
    sb = _SB(_orden(), ITEMS)
    total, aviso = _sync(mod, sb, 18000.0)
    assert total == 68000.0, "el total sigue con el envío estimado adentro"
    assert aviso is None
    assert _update_de_orders(sb) == [{"shipping_cost": 18000.0, "total_amount": 68000.0}]


def test_tambien_cuando_la_tarifa_baja(mod):
    """Si la tarifa real es menor, no recalcular hace que el cliente pague de más."""
    sb = _SB(_orden(), ITEMS)
    total, _ = _sync(mod, sb, 5000.0)
    assert total == 55000.0


def test_el_descuento_se_respeta(mod):
    sb = _SB(_orden(discount_amount=12000.0), ITEMS)
    total, _ = _sync(mod, sb, 8000.0)
    assert total == 46000.0, "50.000 + 8.000 − 12.000"


def test_contra_entrega_es_el_caso_mas_expuesto(mod):
    """Un pedido COD nace 'confirmed' y NO se ha cobrado: el transportador cobra en la puerta.
    Si se mirara el estado en vez del pago, este caso —el más frecuente— quedaría fuera."""
    sb = _SB(_orden(status="confirmed"), ITEMS, pago_aprobado=False)
    total, aviso = _sync(mod, sb, 20000.0)
    assert total == 70000.0, "un COD sin cobrar SÍ debe recalcularse"
    assert aviso is None


# ─── Lo que NO se debe tocar ────────────────────────────────────────────────

def test_un_pedido_ya_pagado_no_se_le_cambia_el_total(mod):
    """Cambiar lo que alguien ya pagó es reescribir la historia. Se avisa y decide un humano."""
    sb = _SB(_orden(status="confirmed"), ITEMS, pago_aprobado=True)
    total, aviso = _sync(mod, sb, 25000.0)
    assert total is None
    assert aviso and "revisión manual" in aviso
    assert _update_de_orders(sb) == [], "no debe tocarse el dinero de un pedido cobrado"


@pytest.mark.parametrize("estado", ["cancelled", "delivered"])
def test_un_pedido_cerrado_tampoco(mod, estado):
    sb = _SB(_orden(status=estado), ITEMS)
    total, aviso = _sync(mod, sb, 25000.0)
    assert total is None and aviso
    assert _update_de_orders(sb) == []


def test_si_la_tarifa_es_la_misma_no_hay_nada_que_conciliar(mod):
    """No ensuciar con avisos un caso donde no cambió nada."""
    sb = _SB(_orden(shipping_cost=10000.0), ITEMS, pago_aprobado=True)
    total, aviso = _sync(mod, sb, 10000.0)
    assert total is None and aviso is None


# ─── Degradación ────────────────────────────────────────────────────────────

def test_el_clamp_en_cero_queda_registrado(mod, caplog):
    """Con un descuento mayor que ítems+envío el total se clampa a 0 y las cifras del pedido
    NO cuadran entre sí. Es el caso que Ley 1480 art. 26 castiga; que no pase callado."""
    sb = _SB(_orden(discount_amount=90000.0), ITEMS)
    with caplog.at_level("WARNING"):
        total, _ = _sync(mod, sb, 10000.0)
    assert total == 0.0
    assert any("no van a cuadrar" in r.getMessage() for r in caplog.records)


def test_si_la_db_falla_no_tumba_la_confirmacion(mod):
    """El envío ya quedó registrado y es un hecho operativo: no se puede perder por esto."""
    sb = _SB(_orden(), ITEMS)

    def _boom(_n):
        t = _Tabla(sb, _n)
        t.execute = lambda: (_ for _ in ()).throw(RuntimeError("db caída"))
        return t

    sb.table = _boom
    total, aviso = _sync(mod, sb, 18000.0)   # no debe lanzar
    assert total is None and aviso is None


def test_orden_de_otro_tenant_no_se_toca(mod):
    """maybe_single sin fila = la orden no es de este tenant (o no existe)."""
    sb = _SB(None, ITEMS)
    total, aviso = _sync(mod, sb, 18000.0)
    assert total is None and aviso is None
    assert _update_de_orders(sb) == []


def test_sin_items_el_total_es_solo_el_envio(mod):
    sb = _SB(_orden(), [])
    total, _ = _sync(mod, sb, 7000.0)
    assert total == 7000.0
