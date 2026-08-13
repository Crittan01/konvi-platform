"""Sem 7 F2 cierre 2026-05-21 — 2 fixes arquitectónicos:

1. **Documento parcial slot-filling** (Bug founder UAT conv 099bb891):
   Cliente dice "Cédula de Ciudadanía" SIN número → conductor antes no
   persistía. AHORA: extractor de tipo-solo + persistencia parcial +
   auto-asignación de number cuando type ya está e inbound es dígitos.

2. **Queue fairness round-robin por tenant** (pregunta arquitectónica
   founder): worker ANTES tomaba FIFO global → tenant con 100 msgs
   bloqueaba a tenant con 1. AHORA: round-robin intercala tenants.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"),
)

from slot_extractors import (  # noqa: E402
    extract_document,
    extract_document_type_only,
    extract_all_slots,
)
from worker import _round_robin_dequeue_by_tenant  # noqa: E402


# ── 1. Document type-only extractor ───────────────────────────────────────

class ExtractDocumentTypeOnlyTests(unittest.TestCase):

    def test_cedula_de_ciudadania_returns_cc(self):
        """Variante coloquial CO que el LLM no mapeaba."""
        self.assertEqual(extract_document_type_only("Cedula de Ciudadania"), "CC")
        self.assertEqual(extract_document_type_only("Cédula de Ciudadanía"), "CC")

    def test_cedula_sola_returns_cc(self):
        self.assertEqual(extract_document_type_only("Cedula"), "CC")
        self.assertEqual(extract_document_type_only("Cédula"), "CC")

    def test_cc_sigla_returns_cc(self):
        self.assertEqual(extract_document_type_only("CC"), "CC")
        self.assertEqual(extract_document_type_only("cc"), "CC")

    def test_extranjeria_returns_ce(self):
        self.assertEqual(extract_document_type_only("Cédula de Extranjería"), "CE")
        self.assertEqual(extract_document_type_only("CE"), "CE")
        self.assertEqual(extract_document_type_only("Extranjería"), "CE")

    def test_tarjeta_identidad_returns_ti(self):
        self.assertEqual(extract_document_type_only("Tarjeta de Identidad"), "TI")
        self.assertEqual(extract_document_type_only("TI"), "TI")

    def test_pasaporte_returns_pp(self):
        self.assertEqual(extract_document_type_only("Pasaporte"), "PP")
        self.assertEqual(extract_document_type_only("passport"), "PP")
        self.assertEqual(extract_document_type_only("PP"), "PP")

    def test_nit_returns_nit(self):
        self.assertEqual(extract_document_type_only("NIT"), "NIT")
        self.assertEqual(extract_document_type_only("nit"), "NIT")

    def test_specificity_order_extranjeria_over_cedula(self):
        """`cedula de extranjeria` debe mapearse a CE, no CC.
        Demuestra orden de regla 'más específico primero'."""
        self.assertEqual(
            extract_document_type_only("cedula de extranjeria"), "CE",
        )

    def test_no_match_returns_none(self):
        self.assertIsNone(extract_document_type_only("Hola, qué tal"))
        self.assertIsNone(extract_document_type_only("Bogota"))
        self.assertIsNone(extract_document_type_only(""))


class ExtractAllSlotsDocumentPartialTests(unittest.TestCase):
    """`extract_all_slots` debe llenar `document_type` solo cuando llega
    sin número."""

    def test_par_completo_llena_ambos(self):
        out = extract_all_slots("CC 1032414179")
        self.assertEqual(out.get("document_type"), "CC")
        self.assertEqual(out.get("document_number"), "1032414179")

    def test_solo_tipo_llena_type_only(self):
        out = extract_all_slots("Cedula de Ciudadania")
        self.assertEqual(out.get("document_type"), "CC")
        self.assertNotIn("document_number", out)

    def test_solo_dígitos_no_llena_doc(self):
        """Solo dígitos sin tipo NO debe extraer document (ambiguo —
        podría ser teléfono, valor, etc.). El conductor lo asigna como
        document_number SOLO cuando contact ya tiene document_type."""
        out = extract_all_slots("1032414179")
        self.assertNotIn("document_type", out)
        self.assertNotIn("document_number", out)


# ── 2. Round-robin fairness por tenant ────────────────────────────────────

class RoundRobinDequeueTests(unittest.TestCase):

    def _msg(self, tid: str, mid: str) -> dict:
        return {"tenant_id": tid, "id": mid, "conversation_id": f"c-{mid}"}

    def test_single_tenant_preserves_fifo(self):
        """Con 1 tenant, comportamiento idéntico a FIFO legacy."""
        pending = [self._msg("A", f"m{i}") for i in range(5)]
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        self.assertEqual([m["id"] for m in out], ["m0", "m1", "m2", "m3", "m4"])

    def test_two_tenants_interleave(self):
        """Tenant A con 3 msgs, tenant B con 2 → intercala: A0,B0,A1,B1,A2."""
        pending = [
            self._msg("A", "a0"), self._msg("A", "a1"), self._msg("A", "a2"),
            self._msg("B", "b0"), self._msg("B", "b1"),
        ]
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        self.assertEqual(
            [m["id"] for m in out],
            ["a0", "b0", "a1", "b1", "a2"],
        )

    def test_unfair_tenant_does_not_block_others(self):
        """Tenant A con 100 msgs, tenant B con 1 → B NO espera 100 turns.
        Output incluye B en posición 2 (justo después del primer A)."""
        pending = [self._msg("A", f"a{i}") for i in range(100)]
        pending.append(self._msg("B", "b0"))
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        ids = [m["id"] for m in out]
        # Primer msg de B debe estar en los primeros 2 elementos.
        self.assertEqual(ids[1], "b0")
        # El resto son de A (FIFO interno).
        for i in [0, 2, 3, 4, 5, 6, 7, 8, 9]:
            self.assertTrue(ids[i].startswith("a"))

    def test_max_total_respected(self):
        pending = [self._msg("A", f"a{i}") for i in range(50)]
        out = _round_robin_dequeue_by_tenant(pending, max_total=5)
        self.assertEqual(len(out), 5)

    def test_empty_pending_returns_empty(self):
        self.assertEqual(_round_robin_dequeue_by_tenant([], max_total=10), [])

    def test_tenant_order_preserved(self):
        """Si pending viene ordenado por created_at, los primeros tenants
        en aparecer mantienen prioridad inicial en round-robin."""
        pending = [
            self._msg("B", "b0"),  # B aparece primero (más viejo)
            self._msg("A", "a0"),
            self._msg("B", "b1"),
            self._msg("A", "a1"),
        ]
        out = _round_robin_dequeue_by_tenant(pending, max_total=10)
        # B es el primero en first-seen → primer slot.
        self.assertEqual([m["id"] for m in out], ["b0", "a0", "b1", "a1"])


if __name__ == "__main__":
    unittest.main()
