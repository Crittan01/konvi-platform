"""OLA 0 (audit) — rate-limit del webhook Wompi (path de dinero).

Era el ÚNICO webhook sin rate-limit (aveonline/meli sí lo tienen) → flood =
amplificación de DB + saturación del threadpool en el path de pago. Se añadió
webhook_rate_limit_check per-IP (bucket 'webhook.wompi', 200/60s, fail-open).
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

import routers.wompi_webhook as wh  # noqa: E402


def _req(ip="1.2.3.4"):
    r = MagicMock()
    r.headers = {"x-forwarded-for": ip}
    r.client = MagicMock(host=ip)

    async def _json():
        return {"event": "transaction.updated", "data": {}}
    r.json = _json
    return r


class WompiWebhookRateLimitTests(unittest.IsolatedAsyncioTestCase):

    async def test_flood_recibe_429(self):
        with patch.object(wh, "_get_service_client", return_value=MagicMock()), \
             patch.object(wh, "webhook_rate_limit_check", return_value=(False, 42)):
            bg = MagicMock()
            resp = await wh.wompi_webhook(_req(), bg)
        self.assertEqual(resp.status_code, 429)
        bg.add_task.assert_not_called()  # no procesa si rate-limited

    async def test_permitido_procesa_y_200(self):
        with patch.object(wh, "_get_service_client", return_value=MagicMock()), \
             patch.object(wh, "webhook_rate_limit_check", return_value=(True, 0)):
            bg = MagicMock()
            resp = await wh.wompi_webhook(_req(), bg)
        self.assertEqual(resp.status_code, 200)
        bg.add_task.assert_called_once()  # encola el procesamiento

    async def test_limiter_error_fail_open(self):
        """Si el limiter revienta, NO se dropea el webhook de pago (fail-open)."""
        with patch.object(wh, "_get_service_client", return_value=MagicMock()), \
             patch.object(wh, "webhook_rate_limit_check", side_effect=RuntimeError("limiter down")):
            bg = MagicMock()
            resp = await wh.wompi_webhook(_req(), bg)
        self.assertEqual(resp.status_code, 200)
        bg.add_task.assert_called_once()


if __name__ == "__main__":
    unittest.main()
