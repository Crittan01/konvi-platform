"""G1 (parcial) — PII en logs: teléfonos enmascarados (Habeas Data Ley 1581).

Los logs de stdout (Render) son la fuente de verdad de errores. Estos tests
verifican que los callsites corregidos emiten el teléfono SOLO enmascarado
(últimos 4 dígitos) y que el descarte de mensaje loguea claves/tipos del dict,
nunca valores (teléfono + contenido del mensaje son PII).

Callsites cubiertos:
  - ai-orchestrator/tools/order_status_tool.py::_get_contact_id_by_phone
  - connector-whatsapp/services/db_persistence.py:
      consent lookup (~:158), nueva conversación (~:211), descarte (~:288).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "ai-orchestrator"))
sys.path.insert(0, str(REPO / "services" / "connector-whatsapp"))

from services import db_persistence  # noqa: E402
from tools.order_status_tool import _get_contact_id_by_phone  # noqa: E402
from whatsapp_sender import _mask_phone as _mask_phone_orch  # noqa: E402

_PHONE = "573125834567"  # PII de prueba — nunca debe aparecer completo en logs
_MASKED = "***4567"


class _SelectBoom:
    """Chain Supabase cuyo .execute() lanza (simula DB/Vault caído)."""

    def select(self, *a, **kw): return self
    def eq(self, *a, **kw): return self
    def order(self, *a, **kw): return self
    def limit(self, *a, **kw): return self

    def execute(self):
        raise RuntimeError("db caida")


class _SelectChain:
    """Chain Supabase select/eq/order/limit/execute que devuelve `rows`.
    (Mismo patrón que tests/test_db_persistence_reopen.py.)"""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw): return self
    def eq(self, *a, **kw): return self
    def order(self, *a, **kw): return self
    def limit(self, *a, **kw): return self

    def execute(self):
        out = MagicMock()
        out.data = list(self._rows)
        return out


class _InsertChain:
    """Chain de insert que retorna un id determinado."""

    def __init__(self, new_id):
        self._new_id = new_id

    def insert(self, *a, **kw): return self

    def execute(self):
        out = MagicMock()
        out.data = [{"id": self._new_id}]
        return out


class MaskPhoneUnitTests(unittest.TestCase):
    """Ambos servicios usan la MISMA lógica: últimos 4 dígitos visibles."""

    def test_mask_basico(self):
        self.assertEqual(db_persistence._mask_phone(_PHONE), _MASKED)
        self.assertEqual(_mask_phone_orch(_PHONE), _MASKED)

    def test_mask_vacio_y_none(self):
        for mod_mask in (db_persistence._mask_phone, _mask_phone_orch):
            self.assertEqual(mod_mask(""), "?")
            self.assertEqual(mod_mask(None), "?")


class OrderStatusToolMaskingTests(unittest.TestCase):
    def test_contact_lookup_error_enmascara_phone(self):
        sb = MagicMock()
        sb.table.return_value = _SelectBoom()
        with self.assertLogs("orchestrator.tools.order_status", level="WARNING") as cm:
            result = _get_contact_id_by_phone(sb, "tenant-1", _PHONE)
        self.assertIsNone(result)
        out = "\n".join(cm.output)
        self.assertIn(_MASKED, out)
        self.assertNotIn(_PHONE, out)


class DbPersistenceMaskingTests(unittest.TestCase):
    def _sb_consent_boom_sin_conv(self):
        """Supabase fake: lookup de contacts lanza; conversations select → []
        (no existe conv) e insert crea 'conv-1'. Recorre los dos callsites de
        log con phone del _upsert_conversation."""
        sb = MagicMock()

        def _table(name):
            if name == "contacts":
                return _SelectBoom()
            if name == "conversations":
                chain = MagicMock()
                chain.select = lambda *a, **kw: _SelectChain([])
                chain.insert = lambda *a, **kw: _InsertChain("conv-1")
                return chain
            return MagicMock()

        sb.table = _table
        return sb

    def test_upsert_conversation_enmascara_phone_en_logs(self):
        sb = self._sb_consent_boom_sin_conv()
        with self.assertLogs("services.db_persistence", level="INFO") as cm:
            conv_id = db_persistence._upsert_conversation(sb, "tenant-1", _PHONE)
        self.assertEqual(conv_id, "conv-1")
        out = "\n".join(cm.output)
        # Cubre: warning del consent lookup + info de "Nueva conversación creada".
        self.assertIn(_MASKED, out)
        self.assertNotIn(_PHONE, out)

    def test_mensaje_descartado_loguea_solo_claves_y_tipos(self):
        data = {
            "meta_waba_id": "WABA1",
            "customer_phone": "",  # vacío tras normalize → descarte
            "content": "contenido secreto del cliente",
            "content_type": "text",
            "meta_message_id": "wamid.test",
        }
        with patch.object(db_persistence, "get_supabase", return_value=MagicMock()):
            with self.assertLogs("services.db_persistence", level="WARNING") as cm:
                db_persistence.persist_whatsapp_message(dict(data))
        out = "\n".join(cm.output)
        # NUNCA valores del dict (PII: teléfono + contenido del mensaje)…
        self.assertNotIn("contenido secreto", out)
        self.assertNotIn("WABA1", out)
        # …solo claves y tipos para diagnóstico.
        self.assertIn("customer_phone", out)
        self.assertIn("str", out)


if __name__ == "__main__":
    unittest.main()
