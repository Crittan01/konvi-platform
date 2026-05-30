"""Tests del fsm/resolver — comportamiento idéntico al monolito (rev. 104, F1-2).

Carga el package `fsm` aislado vía `sys.path` + cleanup para no contaminar
otros tests del proyecto que también puedan importar módulos `fsm`.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_FSM_PARENT = REPO / "services/ai-orchestrator"


def _clean_fsm_modules():
    for mod in list(sys.modules):
        if mod == "fsm" or mod.startswith("fsm."):
            del sys.modules[mod]


def _load_fsm():
    """Importa fsm como package limpio. Llamar al inicio de cada TestCase
    para garantizar estado fresco."""
    _clean_fsm_modules()
    if str(_FSM_PARENT) not in sys.path:
        sys.path.insert(0, str(_FSM_PARENT))
    from fsm import resolver as r  # noqa: E402
    return r


class DetermineTransactionalStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _load_fsm()

    def test_no_contact(self):
        self.assertEqual(self.r.determine_transactional_state(None), "NEEDS_CONSENT")
        self.assertEqual(self.r.determine_transactional_state({}), "NEEDS_CONSENT")

    def test_no_consent(self):
        self.assertEqual(
            self.r.determine_transactional_state({"consent_given": False}),
            "NEEDS_CONSENT",
        )

    def test_consent_no_email(self):
        self.assertEqual(
            self.r.determine_transactional_state({"consent_given": True}),
            "NEEDS_EMAIL",
        )

    def test_email_no_name(self):
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com",
            }),
            "NEEDS_NAME",
        )

    def test_name_no_document(self):
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com", "name": "Cristian",
            }),
            "NEEDS_DOCUMENT",
        )

    def test_partial_document(self):
        # Solo type sin number → NEEDS_DOCUMENT.
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com", "name": "C",
                "document_type": "CC",
            }),
            "NEEDS_DOCUMENT",
        )
        # Solo number sin type → NEEDS_DOCUMENT.
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com", "name": "C",
                "document_number": "123",
            }),
            "NEEDS_DOCUMENT",
        )

    def test_document_complete_no_address(self):
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com", "name": "C",
                "document_type": "CC", "document_number": "1032414179",
            }),
            "NEEDS_DIRECTION",
        )

    def test_address_empty_dict_treated_as_missing(self):
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com", "name": "C",
                "document_type": "CC", "document_number": "1032414179",
                "address": {},
            }),
            "NEEDS_DIRECTION",
        )

    def test_full_pii_ready(self):
        self.assertEqual(
            self.r.determine_transactional_state({
                "consent_given": True, "email": "x@y.com", "name": "C",
                "document_type": "CC", "document_number": "1032414179",
                "address": {
                    "street": "Calle 1", "city": "Bogotá",
                    "neighborhood": "Chapinero",  # P6 opción C.
                    "building_type": "casa",
                },
            }),
            "READY_FOR_SUMMARY",
        )


class ResolveDisplayStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _load_fsm()

    def _full_pii(self):
        return {
            "consent_given": True, "email": "x@y.com", "name": "C",
            "document_type": "CC", "document_number": "1032414179",
            "address": {
                "street": "Calle 1", "city": "Bogotá",
                "neighborhood": "Chapinero",  # P6 opción C: obligatorio residencial.
                "building_type": "casa",
            },
        }

    def test_no_buying_intent_catalog_mode(self):
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record=self._full_pii(),
                buying_intent=False,
                shipping_quoted=True,
                carrier_selected=True,
                order_confirm_pending=False,
            ),
            "CATALOG_MODE",
        )

    def test_buying_no_shipping_quoted(self):
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record=self._full_pii(),
                buying_intent=True,
                shipping_quoted=False,
                carrier_selected=False,
                order_confirm_pending=False,
            ),
            "NEEDS_SHIPPING_CITY",
        )

    def test_shipping_no_carrier(self):
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record=self._full_pii(),
                buying_intent=True,
                shipping_quoted=True,
                carrier_selected=False,
                order_confirm_pending=False,
            ),
            "AWAITING_CARRIER_SELECTION",
        )

    def test_pii_collection_blocks_confirmation(self):
        # Sin email pero order_confirm_pending → debe ir a NEEDS_EMAIL.
        partial = {"consent_given": True}
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record=partial,
                buying_intent=True,
                shipping_quoted=True,
                carrier_selected=True,
                order_confirm_pending=True,
            ),
            "NEEDS_EMAIL",
        )

    def test_full_pii_with_confirm_pending(self):
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record=self._full_pii(),
                buying_intent=True,
                shipping_quoted=True,
                carrier_selected=True,
                order_confirm_pending=True,
            ),
            "AWAITING_ORDER_CONFIRMATION",
        )

    def test_full_pii_ready_for_summary(self):
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record=self._full_pii(),
                buying_intent=True,
                shipping_quoted=True,
                carrier_selected=True,
                order_confirm_pending=False,
            ),
            "READY_FOR_SUMMARY",
        )

    def test_no_consent_priority_over_carrier(self):
        # Sin consent pero shipping+carrier — debe ir a NEEDS_CONSENT.
        self.assertEqual(
            self.r.resolve_display_state(
                contact_record={"consent_given": False},
                buying_intent=True,
                shipping_quoted=True,
                carrier_selected=True,
                order_confirm_pending=False,
            ),
            "NEEDS_CONSENT",
        )


class HasRealAddressDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = _load_fsm()

    def test_none_or_empty(self):
        self.assertFalse(self.r._has_real_address_data(None))
        self.assertFalse(self.r._has_real_address_data({}))
        self.assertFalse(self.r._has_real_address_data("not a dict"))

    def test_missing_street(self):
        self.assertFalse(self.r._has_real_address_data({"city": "Bogotá"}))

    def test_missing_city(self):
        self.assertFalse(self.r._has_real_address_data({"street": "Calle 1"}))

    def test_both_present(self):
        # Rev. 104 — el resolver delega a fsm.address.has_real_address_data
        # que también requiere building_type.
        # Sem 7 F2 cierre 2026-05-20 — P6 opción C: barrio obligatorio
        # en residencial (casa).
        self.assertTrue(self.r._has_real_address_data({
            "street": "Calle 1", "city": "Bogotá",
            "neighborhood": "Chapinero",
            "building_type": "casa",
        }))

    def test_empty_strings_treated_as_missing(self):
        self.assertFalse(self.r._has_real_address_data({
            "street": "  ", "city": "Bogotá",
        }))


if __name__ == "__main__":
    unittest.main()
