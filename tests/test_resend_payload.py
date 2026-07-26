"""El payload que de verdad se le manda a Resend.

Los tests de los correos mockean `_send_email_via_resend` entero, así que la CONSTRUCCIÓN
del payload no la ejercita nadie. Se descubrió mutando: quitar `payload["reply_to"] = ...`
dejaba 40 pruebas en verde. Este archivo cierra ese hueco — mockea el transporte HTTP, no
la función.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(ORCH) not in sys.path:
    sys.path.insert(0, str(ORCH))
if "vault_helper" not in sys.modules:
    sys.modules["vault_helper"] = type(sys)("vault_helper")

import notifications as n  # noqa: E402


class _Resp:
    def __init__(self, status=200):
        self.status_code = status
        self.text = "ok"


def _enviar(**kw):
    """Manda de verdad por el camino real y devuelve el payload que salió al transporte."""
    capturado = {}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None):
            capturado["url"] = url
            capturado["payload"] = json
            capturado["headers"] = headers
            return _Resp()

    with patch.object(n, "RESEND_API_KEY", "re_test"), \
         patch.object(n.httpx, "AsyncClient", lambda **k: _Client()):
        ok = asyncio.run(n._send_email_via_resend(**kw))
    capturado["ok"] = ok
    return capturado


BASE = dict(to="ana@example.com", subject="Comprobante CP-1", html="<p>hola</p>")


def test_el_reply_to_viaja_en_el_payload():
    """Sin esto, el comprador que responde su comprobante le escribe a `noreply@` de la
    plataforma — un buzón que nadie lee — en vez de al vendedor. Ley 1480 art. 50 lit. a)."""
    c = _enviar(**BASE, reply_to="hola@kaiu.co")
    assert c["payload"]["reply_to"] == "hola@kaiu.co"


def test_sin_reply_to_la_clave_NO_se_manda():
    """Un `reply_to` vacío o nulo podría hacer que Resend rechace el envío entero."""
    c = _enviar(**BASE)
    assert "reply_to" not in c["payload"]


def test_el_campo_es_snake_case():
    """Verificado en la doc oficial de Resend: `reply_to`, no `replyTo` (el camelCase es
    del SDK de Node, no de la API)."""
    c = _enviar(**BASE, reply_to="hola@kaiu.co")
    assert "replyTo" not in c["payload"]


def test_lo_minimo_indispensable_siempre_va():
    c = _enviar(**BASE)
    p = c["payload"]
    assert p["to"] == ["ana@example.com"], "Resend espera una lista"
    assert p["subject"] and p["html"] and p["from"]


def test_el_texto_plano_solo_si_existe():
    assert "text" not in _enviar(**BASE)["payload"]
    assert _enviar(**BASE, text="hola")["payload"]["text"] == "hola"


def test_la_idempotencia_viaja_como_header_y_recortada():
    c = _enviar(**BASE, idempotency_key="k" * 400)
    assert len(c["headers"]["Idempotency-Key"]) <= 256


def test_un_status_no_2xx_es_fracaso():
    """El bool significa "¿Resend lo aceptó?". Un 429 de cuota NO puede leerse como éxito."""
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp(429)

    with patch.object(n, "RESEND_API_KEY", "re_test"), \
         patch.object(n.httpx, "AsyncClient", lambda **kw: _Client()):
        assert asyncio.run(n._send_email_via_resend(**BASE)) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
