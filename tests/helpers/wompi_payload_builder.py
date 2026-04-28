"""
Builder de payloads Wompi para testing.

Genera eventos webhook `transaction.updated` con firma SHA256 válida
usando una events_key de prueba.

Uso:
    payload = WompiPayloadBuilder().with_approved_txn(
        txn_id="txn-123",
        payment_link_id="plink-123",
        amount_in_cents=13500000,
    ).build()

    # La firma ya está embebida en payload["signature"]["checksum"]
"""
import hashlib
from typing import Any, Optional


TEST_EVENTS_KEY = "test-events-key-wompi-12345"


class WompiPayloadBuilder:
    """Fluent builder para payloads de webhook Wompi."""

    def __init__(self, events_key: str = TEST_EVENTS_KEY):
        self._events_key = events_key
        self._event = "transaction.updated"
        self._timestamp = 1714089600  # fixed default for determinism in tests
        self._txn_id = "txn-default"
        self._txn_status = "APPROVED"
        self._payment_link_id: Optional[str] = "plink-default"
        self._reference = "ref-default"
        self._amount_in_cents = 150_000
        self._properties = [
            "data.transaction.id",
            "data.transaction.status",
            "data.transaction.amount_in_cents",
        ]

    def with_event(self, event: str) -> "WompiPayloadBuilder":
        self._event = event
        return self

    def with_timestamp(self, timestamp: int) -> "WompiPayloadBuilder":
        self._timestamp = timestamp
        return self

    def with_txn(self, *, txn_id: str, status: str, amount_in_cents: int) -> "WompiPayloadBuilder":
        self._txn_id = txn_id
        self._txn_status = status
        self._amount_in_cents = amount_in_cents
        return self

    def with_approved_txn(
        self,
        *,
        txn_id: str = "txn-approved",
        payment_link_id: str = "plink-approved",
        reference: str = "ref-approved",
        amount_in_cents: int = 135_000,
    ) -> "WompiPayloadBuilder":
        self._txn_id = txn_id
        self._txn_status = "APPROVED"
        self._payment_link_id = payment_link_id
        self._reference = reference
        self._amount_in_cents = amount_in_cents
        return self

    def with_declined_txn(
        self,
        *,
        txn_id: str = "txn-declined",
        payment_link_id: str = "plink-declined",
        amount_in_cents: int = 135_000,
    ) -> "WompiPayloadBuilder":
        self._txn_id = txn_id
        self._txn_status = "DECLINED"
        self._payment_link_id = payment_link_id
        self._amount_in_cents = amount_in_cents
        return self

    def with_no_signature_properties(self) -> "WompiPayloadBuilder":
        self._properties = []
        return self

    def with_custom_properties(self, properties: list[str]) -> "WompiPayloadBuilder":
        self._properties = properties
        return self

    def _compute_checksum(self, payload: dict) -> str:
        """Computa el checksum SHA256 desde ROOT del payload — igual que Wompi en producción."""
        parts = []
        for prop in self._properties:
            val: object = payload  # traversal desde ROOT del payload completo
            for key in prop.split("."):
                val = val.get(key, "") if isinstance(val, dict) else ""
            parts.append(str(val))
        concat = "".join(parts) + str(self._timestamp) + self._events_key
        return hashlib.sha256(concat.encode()).hexdigest().upper()

    def build(self) -> dict[str, Any]:
        data = {
            "transaction": {
                "id": self._txn_id,
                "status": self._txn_status,
                "payment_link_id": self._payment_link_id,
                "reference": self._reference,
                "amount_in_cents": self._amount_in_cents,
            }
        }
        # Construir payload completo primero para computar checksum desde ROOT
        payload: dict[str, Any] = {
            "event": self._event,
            "timestamp": self._timestamp,
            "data": data,
        }
        checksum = self._compute_checksum(payload)
        payload["signature"] = {"properties": self._properties, "checksum": checksum}
        return payload
