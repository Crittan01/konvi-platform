"""Regresión UAT 2026-07-20 (DEV replicado desde las 224 migraciones).

Tres defectos reproducidos contra el sandbox real (Wompi sandbox + bot en vivo):

  1. `payments` (libro de conciliación) podía contradecir a la orden en AMBAS
     direcciones, porque `_upsert_payment_record` escribe `status` ANTES de los
     guards de monto/estado-terminal y sin máquina de estados:
       a) DECLINED tardío sobre un pago ya aprobado → orden 'confirmed' + pago
          'declined'.  (Wompi reintenta a 30m/3h/24h; con 2 intentos sobre el
          mismo link el txn_id no matchea y el lookup por (order_id, link_id)
          pega en la fila aprobada.)
       b) APPROVED con monto que no corresponde → el guard de monto impide
          confirmar la orden (correcto) pero el ledger igual quedaba 'approved'.

  2. `summary_coherence` no se ejecutaba si el LLM redactaba el total en PROSA
     ("el total con el descuento aplicado es *$167.250*"): `_looks_like_summary`
     exigía el formato etiqueta "Total: $X". Caso real: el bot afirmó $167.250
     con el cart en $147.900 (hizo aritmética sobre un descuento viejo del
     historial) y NINGÚN guard disparó.

  3. El guard de la línea "Descuento" quedaba inalcanzable cuando el outbound no
     traía un total parseable — justo el peor caso (recap de ítems con precios,
     sin total y sin mostrar el descuento aplicado).
"""
import os
import sys
import unittest

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test")

REPO = "/home/ansible/workspaces/konvi-platform"
sys.path.insert(0, f"{REPO}/services/api")

from routers import wompi_webhook  # noqa: E402


# ─────────────────────────── doble de Supabase mínimo ───────────────────────────
class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Encadenable; devuelve la fila fijada y captura el payload de update."""

    def __init__(self, table, sink):
        self._table, self._sink = table, sink
        self._update_payload = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def insert(self, payload):
        self._sink["inserted"] = payload
        return self

    def execute(self):
        if self._update_payload is not None:
            self._sink["updated"] = self._update_payload
            return _Result([])
        return _Result(self._sink["rows"].get(self._table, []))


class _Sb:
    def __init__(self, rows):
        self.sink = {"rows": rows}

    def table(self, name):
        return _Query(name, self.sink)


def _existing_payment(**over):
    row = {
        "id": "pay-1",
        "tenant_id": "t-1",
        "wompi_txn_id": "txn-approved",
        "status": "approved",
        "amount_in_cents": 16_280_000,
    }
    row.update(over)
    return row


class LedgerStateMachineTests(unittest.TestCase):
    """`payments.status` es el libro de conciliación: no debe poder quedar en un
    estado que contradiga lo que realmente pasó."""

    def test_declined_tardio_no_degrada_un_pago_aprobado(self):
        sb = _Sb({"payments": [_existing_payment()]})
        wompi_webhook._upsert_payment_record(
            supabase=sb,
            wompi_txn_id="txn-declined-otro-intento",  # otro intento → no matchea por txn
            wompi_link_id="plink-1",
            order_id="order-1",
            amount_in_cents=16_280_000,
            wompi_status="DECLINED",
            raw_webhook={"e": 1},
        )
        upd = sb.sink["updated"]
        self.assertNotIn("status", upd, "no debe degradar un pago aprobado")
        self.assertNotIn("wompi_status", upd)
        # La auditoría SÍ se conserva: el evento crudo queda registrado.
        self.assertIn("raw_webhook", upd)

    def test_approved_con_monto_distinto_no_marca_aprobado(self):
        sb = _Sb({"payments": [_existing_payment(status="pending", wompi_txn_id=None)]})
        wompi_webhook._upsert_payment_record(
            supabase=sb,
            wompi_txn_id="txn-tampered",
            wompi_link_id="plink-1",
            order_id="order-1",
            amount_in_cents=100_000,          # $1.000 en vez de $162.800
            wompi_status="APPROVED",
            raw_webhook={"e": 2},
        )
        upd = sb.sink["updated"]
        self.assertNotIn("status", upd, "monto no coincide → no se marca aprobado")
        self.assertNotIn("wompi_status", upd)

    def test_approved_con_monto_correcto_si_marca_aprobado(self):
        """Camino feliz intacto: es la transición que confirma la venta."""
        sb = _Sb({"payments": [_existing_payment(status="pending", wompi_txn_id=None)]})
        wompi_webhook._upsert_payment_record(
            supabase=sb,
            wompi_txn_id="txn-ok",
            wompi_link_id="plink-1",
            order_id="order-1",
            amount_in_cents=16_280_000,
            wompi_status="APPROVED",
            raw_webhook={"e": 3},
        )
        upd = sb.sink["updated"]
        self.assertEqual(upd.get("status"), "approved")
        self.assertEqual(upd.get("wompi_status"), "APPROVED")
        self.assertEqual(upd.get("wompi_txn_id"), "txn-ok", "debe completar el txn_id NULL")

    def test_declined_sobre_pago_pendiente_si_se_registra(self):
        """Un rechazo real sobre un pago aún pendiente debe quedar asentado."""
        sb = _Sb({"payments": [_existing_payment(status="pending", wompi_txn_id=None)]})
        wompi_webhook._upsert_payment_record(
            supabase=sb,
            wompi_txn_id="txn-dec",
            wompi_link_id="plink-1",
            order_id="order-1",
            amount_in_cents=16_280_000,
            wompi_status="DECLINED",
            raw_webhook={"e": 4},
        )
        self.assertEqual(sb.sink["updated"].get("status"), "declined")


# ─────────────────────────── summary_coherence ───────────────────────────
sys.path.insert(0, f"{REPO}/services/ai-orchestrator")
from agentic.invariants.summary_coherence import (  # noqa: E402
    _extract_total_cop,
    _looks_like_summary,
)


class TotalEnProsaTests(unittest.TestCase):
    """El total escrito en prosa debe reconocerse igual que 'Total: $X'."""

    CASO_REAL = ("Tu pedido está listo para despacho a *Medellín*. "
                 "El total con el descuento aplicado es *$167.250*.")

    def test_caso_real_del_uat_es_reconocido(self):
        self.assertTrue(_looks_like_summary(self.CASO_REAL))
        self.assertEqual(_extract_total_cop(self.CASO_REAL), 167250)

    def test_variantes_de_prosa(self):
        for texto, esperado in (
            ("El total a pagar es $167.250", 167250),
            ("Quedaría en un total de $77.000 COP", 77000),
            ("Tu total final sería $45.000", 45000),
        ):
            with self.subTest(texto=texto):
                self.assertTrue(_looks_like_summary(texto))
                self.assertEqual(_extract_total_cop(texto), esperado)

    def test_formato_etiqueta_sigue_funcionando(self):
        self.assertEqual(_extract_total_cop("*Total:* *$159.950 COP*"), 159950)

    def test_subtotal_sin_total_dispara_el_invariant(self):
        """Observado en vivo: "Subtotal: *$110.000*" con un cupón vivo dejaba al
        cliente sin ver su descuento. Un subtotal NO es el total afirmado, así que
        sólo habilita la evaluación de coherencia, no una comparación de totales."""
        texto = ("Agregué 1 *Protector Solar Facial SPF 50+* a tu carrito por $65.000.\n"
                 "Subtotal: *$110.000*.")
        self.assertTrue(_looks_like_summary(texto))
        self.assertIsNone(_extract_total_cop(texto), "un subtotal no es un total afirmado")

    def test_recap_de_carrito_sin_total_dispara_el_invariant(self):
        """Es el shape donde se perdía la línea de descuento."""
        recap = ("Tu pedido ahora incluye:\n"
                 "* 1 *Mascarilla Purificante de Arcilla* — *$45.000*\n"
                 "* 1 *Serum Facial Vitamina C 15% (50ml)* — *$129.000*")
        self.assertTrue(_looks_like_summary(recap))
        self.assertIsNone(_extract_total_cop(recap), "no hay total afirmado que validar")

    def test_no_confunde_un_listado_de_catalogo_con_un_resumen(self):
        """Anti-falso-positivo: reescribir una respuesta de catálogo como resumen
        de pedido sería una regresión PEOR que el bug original.

        Los dos primeros casos son REGRESIONES REALES observadas en vivo con una
        versión anterior de este fix: bastaba "tu pedido" + un precio para que el
        invariant reescribiera una respuesta de catálogo como
        "No tengo aún tu pedido confirmado". Lo que distingue a un recap es la
        línea con CANTIDAD, no el posesivo.
        """
        for catalogo in (
            "El Serum Facial Vitamina C 15% está en 30ml a $89.000 y 50ml a "
            "$129.000. ¿Cuál prefieres para tu pedido?",
            "Para tu pedido tenemos el Protector Solar SPF 50+ a $65.000.",
            "Contamos con el Serum Facial Vitamina C 15% desde $89.000 hasta $129.000.",
            "Tenemos Protector Solar SPF 50+ a $65.000 y Mascarilla de Arcilla a $45.000.",
            "En total tenemos 5 productos en el catálogo.",
            "En total tenemos 5 productos en el catálogo desde $45.000.",
            "* *Serum Facial*: $89.000\n* *Protector Solar*: $65.000",
        ):
            with self.subTest(catalogo=catalogo):
                self.assertFalse(_looks_like_summary(catalogo))


if __name__ == "__main__":
    unittest.main()
