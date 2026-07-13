"""W1 (auditoría 2026-07-13) — enforcement de scrub PII antes de Sentry (Ley 1581).

Antes `_before_send` filtraba rutas/4xx pero NO limpiaba PII de message/exception/
breadcrumbs → un logger.error con teléfono/email llegaba crudo a Sentry (violación
Habeas Data). Se añadió `_scrub_event` (redacta teléfono COL / email recursivamente)
al before_send + before_breadcrumb, en los 3 servicios. También _mask_phone al origen
en whatsapp_sender.
"""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[1]


def _load_obs(service):
    path = REPO / "services" / service / "observability.py"
    spec = importlib.util.spec_from_file_location(f"_obs_{service.replace('-', '_')}", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class SentryPiiScrubTests(unittest.TestCase):

    def setUp(self):
        self.obs = _load_obs("ai-orchestrator")

    def test_redacta_telefono_col(self):
        out = self.obs._scrub_str("timeout al enviar a 573125835649 ok")
        self.assertNotIn("573125835649", out)
        self.assertIn("[phone]", out)
        # también +57...
        self.assertNotIn("3125835649", self.obs._scrub_str("to=+573125835649"))

    def test_redacta_email(self):
        out = self.obs._scrub_str("fallo para crittan01@gmail.com")
        self.assertNotIn("crittan01@gmail.com", out)
        self.assertIn("[email]", out)

    def test_scrub_event_recursivo(self):
        event = {
            "message": "cliente 573125835649",
            "exception": {"values": [{"value": "error con crittan01@gmail.com"}]},
            "breadcrumbs": {"values": [{"message": "envío a 573001234567"}]},
            "extra": {"nested": ["573009998877", "ok"]},
        }
        scrubbed = self.obs._scrub_event(event)
        s = str(scrubbed)
        for pii in ("573125835649", "crittan01@gmail.com", "573001234567", "573009998877"):
            self.assertNotIn(pii, s, f"PII no redactada: {pii}")

    def test_no_rompe_strings_sin_pii(self):
        self.assertEqual(self.obs._scrub_str("orden 42 procesada en 3s"), "orden 42 procesada en 3s")

    def test_before_send_scrubbea(self):
        # el hook real debe redactar (no solo la función interna)
        ev = self.obs._before_send({"message": "to 573125835649", "request": {}}, {})
        self.assertNotIn("573125835649", str(ev))

    def test_los_3_servicios_tienen_scrubber(self):
        for svc in ("ai-orchestrator", "api", "connector-whatsapp"):
            obs = _load_obs(svc)
            self.assertNotIn("573125835649", obs._scrub_str("x 573125835649"))


class PhoneSeparatorTests(unittest.TestCase):
    """Review W1: el móvil COL con separadores (forma humana) también se redacta."""

    def setUp(self):
        self.obs = _load_obs("api")

    def test_redacta_formatos_con_separadores(self):
        for raw in ("300 123 4567", "300-123-4567", "(300) 123-4567", "300.123.4567",
                    "+57 300 123 4567", "300 1234567"):
            out = self.obs._scrub_str(f"cliente dejó {raw} como contacto")
            self.assertIn("[phone]", out, f"no redactó: {raw!r} -> {out!r}")
            # ningún trío de dígitos móvil sobrevive
            import re
            self.assertNotRegex(out.replace("[phone]", ""), r"3\d{2}[\s.()\-]?\d{3}", f"PII residual en {out!r}")

    def test_contiguo_e164_sigue_redactando(self):
        self.assertNotIn("573125835649", self.obs._scrub_str("to=573125835649"))

    def test_no_falsos_positivos(self):
        for raw in ("orden 42 en 3s", "id 30012345678901", "ref 1234567890", "producto 300 uds"):
            self.assertNotIn("[phone]", self.obs._scrub_str(raw), f"falso-positivo: {raw!r}")


class BreadcrumbScrubViaBeforeSendTests(unittest.TestCase):
    """Review W1 Fix3: sin before_breadcrumb, before_send igual escruba breadcrumbs."""

    def setUp(self):
        self.obs = _load_obs("api")

    def test_before_send_escruba_breadcrumbs(self):
        ev = {"message": "ok", "breadcrumbs": {"values": [{"message": "envío a 573001234567"}]}}
        out = self.obs._before_send(ev, {})
        self.assertNotIn("573001234567", str(out))

    def test_before_breadcrumb_no_registrado(self):
        # la función se removió (before_send cubre el caso)
        self.assertFalse(hasattr(self.obs, "_scrub_breadcrumb"))


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
