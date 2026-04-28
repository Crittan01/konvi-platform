"""
Tests de validación de firma webhook Wompi.

Cubre:
- Firma correcta (SHA256 simple)
- Firma incorrecta
- Payload sin signature.properties
- Payload sin checksum
- events_key ausente (string vacío)
"""
import sys
import unittest

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/api")
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/tests")

from integrations.wompi_client import verify_event_signature
from helpers.wompi_payload_builder import WompiPayloadBuilder, TEST_EVENTS_KEY


class WompiSignatureTests(unittest.TestCase):

    def test_valid_signature_returns_true(self):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        self.assertTrue(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_invalid_signature_returns_false(self):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        payload["signature"]["checksum"] = "INVALIDCHECKSUM123"
        self.assertFalse(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_missing_properties_returns_false(self):
        payload = WompiPayloadBuilder().with_no_signature_properties().build()
        self.assertFalse(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_missing_checksum_returns_false(self):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        del payload["signature"]["checksum"]
        self.assertFalse(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_empty_events_key_returns_false(self):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        self.assertFalse(verify_event_signature(payload, ""))

    def test_different_event_type_still_validates_signature(self):
        payload = WompiPayloadBuilder().with_event("transaction.created").with_approved_txn().build()
        self.assertTrue(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_case_insensitive_checksum_comparison(self):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        payload["signature"]["checksum"] = payload["signature"]["checksum"].lower()
        self.assertTrue(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_nested_dot_path_resolution(self):
        """Verifica que propiedades anidadas con '.' se resuelvan correctamente en data."""
        builder = WompiPayloadBuilder()
        builder._properties = ["data.transaction.id", "data.transaction.status"]
        payload = builder.with_approved_txn().build()
        self.assertTrue(verify_event_signature(payload, TEST_EVENTS_KEY))

    def test_wrong_events_key_returns_false(self):
        payload = WompiPayloadBuilder().with_approved_txn().build()
        self.assertFalse(verify_event_signature(payload, "wrong_key_xyz"))


if __name__ == "__main__":
    unittest.main()
