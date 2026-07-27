"""Los endpoints de reversión del pago sobre un reclamo.

Ley 1480 art. 51 + Decreto 1074 cap. 2.2.2.51. Lo que se prueba acá es la traducción: que
el operador reciba un mensaje que le sirva cuando la figura NO aplica, en vez de un error
de constraint. Las reglas de fondo viven en tests/dbharness/test_reversion_pago.py.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routers.claims as claims  # noqa: E402
from dependencies.auth import (  # noqa: E402
    get_current_role, get_current_tenant, get_service_client,
)
from dependencies.security import RL_WRITE_DEFAULT  # noqa: E402

TENANT = "tenant-1"

CONSTANCIA = {
    "id": "rv1", "claim_id": "cl1", "tenant_id": TENANT, "radicado": "RV-000042",
    "causal": "producto_defectuoso", "valor": 68000,
    "constancia": {"radicado": "RV-000042", "causal": "producto_defectuoso"},
}


class _Q:
    def __init__(self, filas):
        self.filas = filas
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def maybe_single(self): return self
    def execute(self): return SimpleNamespace(data=list(self.filas))


class _FakeSB:
    """Devuelve lo que la RPC diría, y lo que la tabla tendría después."""

    def __init__(self, *, motivo=None, filas=None, mov=None):
        self.motivo = motivo
        self.filas = filas if filas is not None else ([] if motivo else [CONSTANCIA])
        self.mov = mov or {"doble_pago": False, "motivo": None}
        self.rpcs = []

    def table(self, _n):
        return _Q(self.filas)

    def rpc(self, nombre, params=None):
        self.rpcs.append((nombre, params))
        if nombre == "rpc_registrar_reversion":
            datos = [{"id": "rv1", "radicado": "RV-000042",
                      "ya_existia": False, "motivo": self.motivo}]
        elif nombre == "rpc_registrar_movimiento_reversion":
            datos = [self.mov]
        else:
            datos = []
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=datos))


def _client(sb, role="manager"):
    app = FastAPI()
    app.include_router(claims.router, prefix="/api/v1/claims")
    app.dependency_overrides[get_current_tenant] = lambda: TENANT
    app.dependency_overrides[get_service_client] = lambda: sb
    app.dependency_overrides[get_current_role] = lambda: role
    app.dependency_overrides[RL_WRITE_DEFAULT] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


BODY = {"causal": "producto_defectuoso", "razones": "me llegó roto", "valor": 68000,
        "instrumento": "Visa terminada en 4242", "bien_a_disposicion": True}


class ReversionApiTest(unittest.TestCase):

    def test_radicar_devuelve_la_constancia(self):
        sb = _FakeSB()
        r = _client(sb).post("/api/v1/claims/cl1/reversion", json=BODY)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["radicado"], "RV-000042")

    def test_una_causal_inventada_se_rechaza_diciendo_cuales_son(self):
        """Las cinco del art. 2.2.2.51.2. Un 422 opaco obligaría al operador a adivinar."""
        r = _client(_FakeSB()).post(
            "/api/v1/claims/cl1/reversion", json={**BODY, "causal": "no_me_gusto"})
        self.assertEqual(r.status_code, 422)
        self.assertIn("2.2.2.51.2", r.json()["detail"])

    def test_contra_entrega_explica_por_que_no_procede(self):
        """No basta con negar: el operador necesita saber que el camino es el reembolso."""
        sb = _FakeSB(motivo="pago_no_electronico")
        r = _client(sb).post("/api/v1/claims/cl1/reversion", json=BODY)
        self.assertEqual(r.status_code, 409)
        d = r.json()["detail"]
        self.assertIn("2.2.2.51.1", d)
        self.assertIn("reembolso", d.lower())

    def test_un_reclamo_que_no_existe_da_404_no_409(self):
        """"No existe" y "existe pero no aplica" son cosas distintas."""
        sb = _FakeSB(motivo="reclamo_inexistente")
        self.assertEqual(
            _client(sb).post("/api/v1/claims/cl1/reversion", json=BODY).status_code, 404)

    def test_pedir_mas_de_lo_pagado_se_explica(self):
        sb = _FakeSB(motivo="valor_excede_el_pedido")
        r = _client(sb).post("/api/v1/claims/cl1/reversion", json=BODY)
        self.assertEqual(r.status_code, 422)
        self.assertIn("2.2.2.51.8", r.json()["detail"])

    def test_sin_forma_de_pago_no_se_radica(self):
        sb = _FakeSB(motivo="forma_de_pago_desconocida")
        self.assertEqual(
            _client(sb).post("/api/v1/claims/cl1/reversion", json=BODY).status_code, 409)

    def test_el_valor_debe_ser_positivo(self):
        r = _client(_FakeSB()).post("/api/v1/claims/cl1/reversion", json={**BODY, "valor": 0})
        self.assertEqual(r.status_code, 422)

    def test_las_razones_no_pueden_ir_vacias(self):
        """Art. 2.2.2.51.5 num. 1 exige "manifestación expresa de las razones"."""
        r = _client(_FakeSB()).post("/api/v1/claims/cl1/reversion", json={**BODY, "razones": ""})
        self.assertEqual(r.status_code, 422)

    def test_leer_una_reversion_inexistente_da_404(self):
        self.assertEqual(
            _client(_FakeSB(filas=[])).get("/api/v1/claims/cl1/reversion").status_code, 404)

    def test_registrar_movimiento_por_una_via_inventada_se_rechaza(self):
        r = _client(_FakeSB()).post("/api/v1/claims/cl1/reversion/movimiento",
                                    json={"via": "nequi", "valor": 1000})
        self.assertEqual(r.status_code, 422)

    def test_registrar_movimiento_pasa_la_via_y_el_valor(self):
        sb = _FakeSB()
        r = _client(sb).post("/api/v1/claims/cl1/reversion/movimiento",
                             json={"via": "reembolso_directo", "valor": 68000})
        self.assertEqual(r.status_code, 200, r.text)
        llamada = [p for n, p in sb.rpcs if n == "rpc_registrar_movimiento_reversion"][0]
        self.assertEqual(llamada["p_via"], "reembolso_directo")
        self.assertEqual(llamada["p_valor"], 68000)

    def test_un_operador_de_solo_lectura_no_radica(self):
        """Emitir una constancia es un acto jurídico del vendedor, no una consulta."""
        r = _client(_FakeSB(), role="viewer").post("/api/v1/claims/cl1/reversion", json=BODY)
        self.assertIn(r.status_code, (401, 403))

    def test_el_instrumento_no_admite_un_numero_de_tarjeta_largo(self):
        """Se guarda un DESCRIPTOR. Un PAN completo crearía una obligación PCI que este
        sistema no asume."""
        r = _client(_FakeSB()).post(
            "/api/v1/claims/cl1/reversion", json={**BODY, "instrumento": "4" * 200})
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
