"""Tests de paridad cross-layer: writes de tools agentic vs schema real DB.

Rev. 107. Cierra deuda detectada por bug `consent_audit_log.consent_given`
(commit 43fd0e0): yo escribí insert con columnas que NO existían en el
schema real. El test fallaba al runtime (PGRST204) y rompía Habeas Data
compliance.

Este test parametrizado verifica para cada tool que hace `.insert()` o
`.update()`:
  1. Captura el dict que el tool envía a Supabase (mock proxy).
  2. Lee el schema real de la tabla destino (SELECT * LIMIT 1).
  3. Asserts que `dict.keys() ⊆ real_columns`.

Si Supabase no está accesible (CI sin .env), el test se skipea con
`unittest.skipUnless(...)`. En dev local con .env válido, corre.

NO valida los VALORES — solo las KEYS. Validación de valores requeriría
runtime real (futuro: smoke test E2E con DB sandbox).
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")
sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)


def _load_env_if_available() -> bool:
    """Carga .env.local si existe (para SUPABASE creds). Retorna True si OK."""
    candidates = [
        Path("/home/ansible/workspaces/commerce-ops-platform/apps/web/.env.local"),
        Path("/home/ansible/workspaces/commerce-ops-platform/.env"),
    ]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            if "=" not in line or line.strip().startswith("#"):
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v:
                os.environ.setdefault(k, v)
        # Normalizar nombre SUPABASE_URL.
        os.environ.setdefault(
            "SUPABASE_URL",
            os.environ.get("NEXT_PUBLIC_SUPABASE_URL", ""),
        )
    return bool(
        os.environ.get("SUPABASE_URL")
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )


_DB_AVAILABLE = _load_env_if_available()


def _get_real_columns(table: str) -> set[str]:
    """Lee columnas reales de la tabla via SELECT * LIMIT 1."""
    from supabase import create_client
    sb = create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_SERVICE_ROLE_KEY"],
    )
    res = sb.table(table).select("*").limit(1).execute()
    if not res.data:
        # Tabla vacía — intentar leer schema desde information_schema via RPC.
        # Si no hay forma, retorna None para skipear el test.
        return None
    return set(res.data[0].keys())


class _SupabaseWriteCapture:
    """Mock chain-aware que captura cada .insert(d) / .update(d).

    Usage:
        sb = _SupabaseWriteCapture()
        # ... tool.execute(args, ctx_con_sb) ...
        sb.captured_inserts['table_name']  # list of dicts
    """

    def __init__(self):
        self.captured_inserts: dict[str, list[dict]] = {}
        self.captured_updates: dict[str, list[dict]] = {}
        self._table_stack = []

    def table(self, name):
        self._current_table = name
        return self

    def insert(self, data):
        self.captured_inserts.setdefault(self._current_table, []).append(
            data if isinstance(data, dict) else {}
        )
        return _ChainStub()

    def update(self, data):
        self.captured_updates.setdefault(self._current_table, []).append(
            data if isinstance(data, dict) else {}
        )
        return _ChainStub()

    def select(self, *a, **kw):
        return _SelectStub(self)


class _ChainStub:
    """Stub que acepta cualquier método .eq().limit().execute() etc."""

    def __getattr__(self, _name):
        return self

    def __call__(self, *a, **kw):
        return self

    def execute(self):
        return MagicMock(data=[])


class _SelectStub:
    def __init__(self, parent):
        self.parent = parent

    def __getattr__(self, _name):
        return self

    def __call__(self, *a, **kw):
        return self

    def execute(self):
        return MagicMock(data=None)


@unittest.skipUnless(
    _DB_AVAILABLE,
    "SUPABASE creds no disponibles — skip cross-layer schema validation. "
    "Para correr en local: copia .env desde apps/web/.env.local al root.",
)
class ToolWritesSchemaParityTests(unittest.TestCase):
    """Para cada tool agentic que escribe a DB, validar que las keys
    coinciden con el schema real."""

    @classmethod
    def setUpClass(cls):
        # Pre-cargar schemas de tablas tocadas por tools agentic.
        cls.real_schemas = {}
        tables = [
            "pii_access_log",
            "consent_audit_log",
            "contacts",
            "conversations",
            "messages",
        ]
        for t in tables:
            cls.real_schemas[t] = _get_real_columns(t)

    def _assert_keys_subset(self, table: str, written_dict: dict, ctx: str):
        """Helper de assertion: keys del dict ⊆ columnas reales."""
        real_cols = self.real_schemas.get(table)
        if real_cols is None:
            self.skipTest(f"Tabla {table} vacía en DB — no se puede validar schema")
        written_keys = set(written_dict.keys())
        extra = written_keys - real_cols
        self.assertFalse(
            extra,
            f"[{ctx}] Tool escribe a {table} keys que NO existen en DB: "
            f"{extra}. Schema real: {sorted(real_cols)}",
        )

    def test_record_consent_keys_match_schema(self):
        """RecordConsentTool escribe contacts.update + consent_audit_log.insert."""
        import agentic.tools.contact  # noqa: F401 — register
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext

        tool = get_tool("record_consent")
        sb = _SupabaseWriteCapture()
        ctx = ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            contact_id="00000000-0000-0000-0000-000000000003",
            supabase=sb, extras={}, logger=MagicMock(),
        )
        args = tool.args_schema(given=True, consent_text="Sí")
        import asyncio
        asyncio.new_event_loop().run_until_complete(tool.execute(args, ctx))

        # Verificar contacts.update.
        for upd in sb.captured_updates.get("contacts", []):
            self._assert_keys_subset("contacts", upd, "record_consent.update(contacts)")
        # Verificar consent_audit_log.insert.
        for ins in sb.captured_inserts.get("consent_audit_log", []):
            self._assert_keys_subset(
                "consent_audit_log", ins,
                "record_consent.insert(consent_audit_log)",
            )

    def test_escalate_to_human_keys_match_schema(self):
        """EscalateToHumanTool escribe conversations.update + messages.insert."""
        import agentic.tools.escalation  # noqa: F401
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext

        tool = get_tool("escalate_to_human")
        sb = _SupabaseWriteCapture()
        ctx = ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            contact_id=None, supabase=sb, extras={}, logger=MagicMock(),
        )
        args = tool.args_schema(reason="Cliente solicita asesor humano")
        import asyncio
        asyncio.new_event_loop().run_until_complete(tool.execute(args, ctx))

        for upd in sb.captured_updates.get("conversations", []):
            self._assert_keys_subset(
                "conversations", upd, "escalate_to_human.update(conversations)",
            )
        for ins in sb.captured_inserts.get("messages", []):
            self._assert_keys_subset(
                "messages", ins, "escalate_to_human.insert(messages)",
            )

    def test_save_email_keys_match_schema(self):
        """SaveEmailTool escribe contacts.update (no toca pii_access_log)."""
        import agentic.tools.contact  # noqa: F401
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext

        tool = get_tool("save_email")
        if tool is None:
            self.skipTest("save_email tool no registrado")

        # Mock chain-aware: contacts.select() → consent_given=True para que
        # _verify_consent_or_fail pase; contacts.update() captura el dict.
        class _MockSb(_SupabaseWriteCapture):
            def table(self, name):
                self._current_table = name
                if name == "contacts":
                    return _ContactsSelectStub(self)
                return self

        class _ContactsSelectStub:
            def __init__(self, parent):
                self.parent = parent
            def select(self, *a, **kw):
                return self
            def eq(self, *a, **kw):
                return self
            def single(self):
                return self
            def execute(self):
                return MagicMock(data={"consent_given": True})
            def update(self, data):
                self.parent.captured_updates.setdefault(
                    "contacts", []
                ).append(data)
                return _ChainStub()

        sb = _MockSb()
        ctx = ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            contact_id="00000000-0000-0000-0000-000000000003",
            supabase=sb, extras={}, logger=MagicMock(),
        )
        args = tool.args_schema(value="test@example.com")
        import asyncio
        asyncio.new_event_loop().run_until_complete(tool.execute(args, ctx))

        # save_email solo escribe contacts.update con {"email": <value>}.
        # NO toca pii_access_log (eso es exclusivo de get_contact_info).
        self.assertTrue(
            sb.captured_updates.get("contacts"),
            "save_email no ejecutó contacts.update — verificar mock o flow",
        )
        for upd in sb.captured_updates.get("contacts", []):
            self._assert_keys_subset(
                "contacts", upd, "save_email.update(contacts)",
            )

    def test_get_contact_info_keys_match_schema(self):
        """GetContactInfoTool escribe pii_access_log.insert (audit Habeas Data)."""
        import agentic.tools.contact  # noqa: F401
        from agentic.tools.registry import get_tool
        from agentic.tools.base import ToolContext

        tool = get_tool("get_contact_info")
        if tool is None:
            self.skipTest("get_contact_info tool no registrado")

        class _MockSb(_SupabaseWriteCapture):
            def table(self, name):
                self._current_table = name
                if name == "contacts":
                    return _ContactsReadStub(self)
                return self

        class _ContactsReadStub:
            def __init__(self, parent):
                self.parent = parent
            def select(self, *a, **kw):
                return self
            def eq(self, *a, **kw):
                return self
            def single(self):
                return self
            def execute(self):
                return MagicMock(data={
                    "id": "00000000-0000-0000-0000-000000000003",
                    "consent_given": True,
                    "email": "test@example.com",
                    "name": "Test",
                    "phone": "573000000000",
                    "shipping_phone": None,
                    "document_type": "CC",
                    "document_number": "12345678",
                    "address": "Cra 1 # 2-3",
                })

        sb = _MockSb()
        ctx = ToolContext(
            tenant_id="00000000-0000-0000-0000-000000000001",
            conversation_id="00000000-0000-0000-0000-000000000002",
            contact_id="00000000-0000-0000-0000-000000000003",
            supabase=sb, extras={}, logger=MagicMock(),
        )
        args = tool.args_schema()
        import asyncio
        asyncio.new_event_loop().run_until_complete(tool.execute(args, ctx))

        for ins in sb.captured_inserts.get("pii_access_log", []):
            self._assert_keys_subset(
                "pii_access_log", ins, "get_contact_info.insert(pii_access_log)",
            )


if __name__ == "__main__":
    unittest.main()
