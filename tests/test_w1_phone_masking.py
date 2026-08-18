"""W1 (auditoría 2026-07-13) — enmascaramiento de teléfono en logs (Ley 1581).

Tras S8 (2026-08-17) el error-tracking externo y su scrubber `_scrub_event`
salieron del repo; lo que sigue vigente y se certifica aquí es el masking en
el ORIGEN: `whatsapp_sender._mask_phone` (los logs de stdout son la fuente de
verdad de errores — el teléfono completo NUNCA debe aparecer).
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]


class MaskPhoneTests(unittest.TestCase):
    def test_mask(self):
        sys.path.insert(0, str(REPO / "services" / "ai-orchestrator"))
        from whatsapp_sender import _mask_phone
        self.assertEqual(_mask_phone("573125835649"), "***5649")
        self.assertEqual(_mask_phone(""), "?")


class WhatsappSuccessPathMaskingTests(unittest.IsolatedAsyncioTestCase):
    """Review W1 Fix2: el camino de ÉXITO (alto volumen) enmascara el teléfono en logs."""

    async def test_send_message_success_enmascara(self):
        from unittest.mock import AsyncMock
        sys.path.insert(0, str(REPO / "services" / "ai-orchestrator"))
        import whatsapp_sender as ws
        phone = "573001234567"
        resp = MagicMock(status_code=200)
        resp.json.return_value = {"messages": [{"id": "wamid.OK"}]}
        client = MagicMock()
        client.post = AsyncMock(return_value=resp)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=client)
        cm.__aexit__ = AsyncMock(return_value=False)
        with patch.object(ws, "_get_tenant_wa_credentials", return_value=("PID", "TOKEN")), \
             patch.object(ws.httpx, "AsyncClient", return_value=cm), \
             self.assertLogs("orchestrator.whatsapp_sender", level="INFO") as cap:
            mid = await ws.send_whatsapp_message("t1", MagicMock(), phone, text="hola")
        self.assertEqual(mid, "wamid.OK")
        joined = "\n".join(cap.output)
        self.assertNotIn(phone, joined)   # teléfono completo NUNCA en logs de éxito
        self.assertIn("***4567", joined)  # forma enmascarada presente


if __name__ == "__main__":
    unittest.main()
