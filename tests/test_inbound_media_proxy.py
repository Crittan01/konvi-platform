"""
BLOQUE E — endpoint proxy de media inbound (conversations.py get_inbound_media).

Verifica el AISLAMIENTO (seguridad) + el flujo:
  · media_id que NO pertenece a un mensaje del tenant → 404 (un operador no baja media de otro
    tenant aunque adivine el id).
  · media_id del tenant pero WhatsApp no conectado / sin token → 409.
  · media_id del tenant + token → 200 con el binario + Content-Type del mime.
"""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routers.conversations as conv  # noqa: E402

TENANT = "tenant-1"
OTHER = "tenant-2"


class _Q:
    def __init__(self, tables, name):
        self.tables, self.name, self._f = tables, name, []
    def select(self, *a, **k):
        return self
    def eq(self, c, v):
        self._f.append((c, v)); return self
    def limit(self, n):
        return self
    def single(self):
        self._single = True; return self
    def execute(self):
        rows = [r for r in self.tables.get(self.name, []) if all(r.get(c) == v for c, v in self._f)]
        if getattr(self, "_single", False):
            return SimpleNamespace(data=(rows[0] if rows else None))
        return SimpleNamespace(data=rows)


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
    def table(self, name):
        return _Q(self.tables, name)


def _make_app(tables):
    app = FastAPI()
    app.include_router(conv.router, prefix="/api/v1/conversations")
    fake = _FakeSupabase(tables)
    app.dependency_overrides[conv.get_current_tenant] = lambda: TENANT
    app.dependency_overrides[conv.get_service_client] = lambda: fake
    return TestClient(app, raise_server_exceptions=True)


# Mensaje media del tenant-1 + una integración WhatsApp conectada con token en claro.
def _tables(connected=True, token="WA_TOKEN", media_owner=TENANT):
    return {
        "messages": [
            {"id": "m1", "tenant_id": media_owner, "media_id": "MID-123", "media_mime": "image/jpeg"},
        ],
        "tenant_integrations": [
            {
                "tenant_id": TENANT, "provider": "whatsapp",
                "status": "connected" if connected else "disconnected",
                "credentials": {"access_token": token} if token else {},
            },
        ],
    }


class InboundMediaProxyTest(unittest.TestCase):
    def test_media_id_not_in_tenant_returns_404(self):
        # El media pertenece a OTHER tenant → la query tenant-scoped no lo encuentra.
        client = _make_app(_tables(media_owner=OTHER))
        with patch("vault_helper.VaultHelper", MagicMock()):
            r = client.get("/api/v1/conversations/media/MID-123")
        self.assertEqual(r.status_code, 404)

    def test_unknown_media_id_returns_404(self):
        client = _make_app(_tables())
        with patch("vault_helper.VaultHelper", MagicMock()):
            r = client.get("/api/v1/conversations/media/DOES-NOT-EXIST")
        self.assertEqual(r.status_code, 404)

    def test_no_whatsapp_token_returns_409(self):
        client = _make_app(_tables(connected=False))
        with patch("vault_helper.VaultHelper", MagicMock()):
            r = client.get("/api/v1/conversations/media/MID-123")
        self.assertEqual(r.status_code, 409)

    def test_safe_image_served_inline(self):
        client = _make_app(_tables())
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch("integrations.meta_media.fetch_media_bytes",
                   new=AsyncMock(return_value=(b"\xff\xd8\xff-binary", "image/jpeg"))):
            r = client.get("/api/v1/conversations/media/MID-123")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "image/jpeg")
        self.assertEqual(r.headers.get("content-disposition"), "inline")
        self.assertEqual(r.content, b"\xff\xd8\xff-binary")
        self.assertIn("private", r.headers.get("cache-control", ""))
        self.assertEqual(r.headers.get("x-content-type-options"), "nosniff")

    def test_active_mime_forced_to_octet_stream_attachment(self):
        # XSS: un "documento" HTML/SVG del cliente NUNCA debe servirse inline como su tipo activo.
        for active_mime in ("text/html", "image/svg+xml", "application/xhtml+xml"):
            client = _make_app(_tables())
            with patch("vault_helper.VaultHelper", MagicMock()), \
                 patch("integrations.meta_media.fetch_media_bytes",
                       new=AsyncMock(return_value=(b"<script>alert(1)</script>", active_mime))):
                r = client.get("/api/v1/conversations/media/MID-123")
            self.assertEqual(r.status_code, 200, active_mime)
            self.assertEqual(r.headers["content-type"], "application/octet-stream", active_mime)
            self.assertIn("attachment", r.headers.get("content-disposition", ""), active_mime)


if __name__ == "__main__":
    unittest.main()
