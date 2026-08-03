"""M10 (2026-08-02) — promesa de canal verdadera post-pago.

Fuera de la ventana 24h, Meta rechaza el outbound (131047): prometer la
confirmación "por este chat" era falso. El comprobante SIEMPRE llega por
correo (receipt_email.py; el email es obligatorio en checkout — el FSM
NEEDS_EMAIL no avanza sin él, fsm/resolver.py). Los textos ahora dicen
"por aquí y por correo".
"""
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "internal-secret")
os.environ.setdefault("API_URL", "http://localhost:8001")

sys.path.insert(
    0, "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)

from tools import payment_link_tool

_SERVICE_DIR = pathlib.Path(
    "/home/ansible/workspaces/konvi-platform/services/ai-orchestrator",
)


def _happy_path_client(mock_client_cls):
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    order_resp = MagicMock()
    order_resp.status_code = 201
    order_resp.json.return_value = {"id": "order-123"}
    order_resp.raise_for_status = MagicMock()
    link_resp = MagicMock()
    link_resp.status_code = 200
    link_resp.json.return_value = {
        "checkout_url": "https://checkout.wompi.co/l/plink-123",
        "expires_at": "2026-08-24T20:00:00.000Z",
        "wompi_link_id": "plink-123",
    }
    link_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(side_effect=[order_resp, link_resp])
    mock_client_cls.return_value = mock_client


class ChannelPromiseTextTests(unittest.IsolatedAsyncioTestCase):
    @patch("tools.payment_link_tool.INTERNAL_SERVICE_SECRET", "internal-secret")
    @patch("tools.payment_link_tool.httpx.AsyncClient")
    async def test_payment_link_menciona_correo(self, mock_client_cls):
        """El texto del link de pago promete confirmación por aquí Y por
        correo — nunca solo por el chat."""
        _happy_path_client(mock_client_cls)
        result = await payment_link_tool.handle_payment_link_if_applicable(
            tenant_id="tenant-1",
            contact_id="contact-1",
            conversation_id="conv-1",
            contact_name="Cristian Garzon",
            total_in_cents=200_000,
            shipping_cost_cents=0,
            notes=None,
            supabase=MagicMock(),
        )
        self.assertIsNotNone(result)
        self.assertIn("correo", result.response_text)
        self.assertIn("por aquí", result.response_text)
        self.assertNotIn("por este chat", result.response_text)


class NoChannelPromiseLeftTests(unittest.TestCase):
    """Guard estático: ningún texto outbound de pago vuelve a prometer la
    confirmación solo "por este chat"."""

    def test_sin_promesa_por_este_chat_en_fuentes_outbound(self):
        for rel in ("orchestrator.py", "tools/payment_link_tool.py"):
            src = (_SERVICE_DIR / rel).read_text(encoding="utf-8")
            self.assertNotIn(
                "confirmación por este chat", src,
                f"promesa de canal engañosa reintroducida en {rel}",
            )
            self.assertIn(
                "por aquí y por correo", src,
                f"falta la mención al correo en {rel}",
            )


if __name__ == "__main__":
    unittest.main()
