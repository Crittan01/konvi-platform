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
    0, str(Path(__file__).resolve().parents[2] / "services" / "ai-orchestrator"),
)


def _load_env_if_available() -> bool:
    """Carga .env.local si existe (para SUPABASE creds). Retorna True si OK."""
    candidates = [
        Path(__file__).resolve().parents[2] / "apps/web/.env.local",
        Path(__file__).resolve().parents[2] / ".env",
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
    key = os.environ.get("SUPABASE_SECRET_KEY") or ""
    # BLOQUE H: rechazar valores centinela dummy. Muchos tests hacen
    # `os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")`
    # para poder importar módulos del orchestrator; en el suite completo esa
    # key dummy filtra a este módulo (orden de colección) y hacía que el probe
    # intentara conectar a Supabase con credencial inválida → 401 ERROR en vez
    # de skip limpio. Una service key real (sb_secret_...) es larga (>40).
    _DUMMY_KEYS = {"service-role", "service_role", "test", "test-secret", "x"}
    if key in _DUMMY_KEYS or len(key) < 40:
        return False
    return bool(os.environ.get("SUPABASE_URL") and key)


_DB_AVAILABLE = _load_env_if_available()


_SCHEMA_PROBE_MARKER = "__test_schema_probe__"


def _get_real_columns(table: str) -> set[str]:
    """Lee columnas reales de la tabla.

    Estrategia:
      1. SELECT * LIMIT 1 — si hay datos, leer keys del primer row.
      2. Si vacía, intentar un probe-insert con campos canónicos por tabla,
         leer las keys del row recién insertado y borrarlo. Confinado al
         test (que ya requiere creds prod).

    Retorna None si no se puede determinar el schema (test se skipea).
    """
    from supabase import create_client
    # BLOQUE H (review Fable): envolver la conexión/SELECT en try/except → un
    # fallo de red o de creds produce skip limpio (return None), NO 5 ERROR que
    # tornarían rojo el suite/validate.sh. El test valida schema cuando la DB
    # está accesible; cuando no, se salta.
    try:
        sb = create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SECRET_KEY"],
        )
        res = sb.table(table).select("*").limit(1).execute()
    except Exception:
        return None
    if res.data:
        return set(res.data[0].keys())
    # Tabla vacía — probe insert + delete. Para tablas con FK a tenants
    # y conversations, buscamos IDs reales de la DB para que el probe
    # sea aceptado por el constraint.
    if table == "agentic_shadow_log":
        try:
            conv = (
                sb.table("conversations")
                .select("id, tenant_id")
                .limit(1).execute()
            )
            if not conv.data:
                return None
            probe_row = {
                "tenant_id": conv.data[0]["tenant_id"],
                "conversation_id": conv.data[0]["id"],
                "inbound_text": _SCHEMA_PROBE_MARKER,
            }
        except Exception:
            return None
    else:
        return None
    try:
        inserted = sb.table(table).insert(probe_row).execute()
        if not inserted.data:
            return None
        cols = set(inserted.data[0].keys())
        # Cleanup probe.
        sb.table(table).delete().eq("inbound_text", _SCHEMA_PROBE_MARKER).execute()
        return cols
    except Exception:
        return None


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
            "agentic_shadow_log",
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

    def test_persist_turn_audit_keys_match_schema(self):
        """Rev. 107: _persist_turn_audit (shadow + cutover) debe escribir
        keys que existan en agentic_shadow_log. Bug detectado en KAIU
        2026-05-23 (conv bde83d84): la tabla quedó vacía aunque hubo turns
        agentic porque dispatcher solo escribía en shadow (no cutover).
        Este test valida que tras la migración 20260528, ambos modes
        escriben con shape compatible."""
        from agentic.dispatcher import _persist_turn_audit
        from dataclasses import dataclass, field

        @dataclass
        class _FakeResult:
            outbound_text: str = "test"
            tool_calls_executed: int = 1
            tool_call_log: list = field(default_factory=list)
            truncated: bool = False
            truncated_reason: str | None = None
            error: str | None = None
            finish_reason: str | None = "STOP"

        sb = _SupabaseWriteCapture()
        for mode in ("shadow", "cutover"):
            _persist_turn_audit(
                sb,
                mode=mode,
                message_id="msg-1",
                tenant_id="00000000-0000-0000-0000-000000000001",
                conversation_id="00000000-0000-0000-0000-000000000002",
                inbound_text="hola",
                result=_FakeResult(),
                elapsed_s=1.2,
                final_text="hola back" if mode == "cutover" else None,
                invariant_outcome="OK" if mode == "cutover" else None,
                invariant_name=None,
                system_prompt_chars=500,
                history_turns=3,
            )
        # 2 inserts capturados (uno por mode).
        captured = sb.captured_inserts.get("agentic_shadow_log", [])
        self.assertEqual(
            len(captured), 2,
            f"esperaba 2 inserts (shadow+cutover), encontró {len(captured)}",
        )
        for ins in captured:
            self._assert_keys_subset(
                "agentic_shadow_log", ins,
                f"_persist_turn_audit(mode={ins.get('mode')})",
            )
        # Validar que las columnas críticas de trazabilidad están presentes.
        modes_inserted = {ins["mode"] for ins in captured}
        self.assertEqual(modes_inserted, {"shadow", "cutover"})
        for ins in captured:
            self.assertIn("finish_reason", ins)
            self.assertEqual(ins["finish_reason"], "STOP")

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
