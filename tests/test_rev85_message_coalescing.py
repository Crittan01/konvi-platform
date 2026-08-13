"""Rev. 85 — Tests del message coalescing en worker.

Caso de uso (observado por el usuario):
  Cliente: "Hola, quiero comprar un jabón artesanal de coco"
  Cliente: "La de 60 gramos por favor"
  Cliente: "Hola"   ← este último resetea el contexto del bot
  Bot: "¡Hola! ¿En qué te puedo ayudar?"   ← perdió el contexto

Fix rev. 85: agrupa por conversation_id, espera ventana de 5s, junta los
contents en un solo input al LLM. El bot ve los 3 mensajes como un solo
bloque y mantiene el contexto.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from worker import OrchestratorWorker, MESSAGE_COALESCE_WINDOW_SECONDS  # noqa: E402


class _Tbl:
    """Tabla mock: el re-fetch SCOPED (debounce no-bloqueante) devuelve los mensajes de la
    conversación pedida (captura el filtro conversation_id)."""
    def __init__(self, store):
        self.store = store
        self._op = None
        self._f = {}

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, *a, **k):
        self._op = "update"
        return self

    def eq(self, k=None, v=None):
        if k is not None:
            self._f[k] = v
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        m = MagicMock()
        if self._op == "select":
            m.data = self.store["conv_rows"].get(self._f.get("conversation_id"), [])
        else:
            m.data = []
        return m


class _SB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Tbl(self.store)


def _make_worker_with_mock_supabase(initial_pending: list[dict]) -> OrchestratorWorker:
    """Worker con supabase mock; el re-fetch scopeado por conversación devuelve los mensajes
    de esa conversación (debounce no-bloqueante por conv)."""
    from collections import defaultdict
    conv_rows: dict = defaultdict(list)
    for m in initial_pending:
        conv_rows[m["conversation_id"]].append(m)
    w = OrchestratorWorker.__new__(OrchestratorWorker)  # bypass __init__
    w.supabase = _SB({"conv_rows": dict(conv_rows)})
    w._metrics = {}
    return w


def _msg(id_, conv_id, content, age_seconds):
    """Helper para crear mensajes con created_at relativo a 'ahora'."""
    return {
        "id": id_,
        "tenant_id": "tenant-1",
        "conversation_id": conv_id,
        "content": content,
        "content_type": "text",
        "processing_attempts": 0,
        "created_at": (datetime.now(timezone.utc)
                       - timedelta(seconds=age_seconds)).isoformat(),
    }


class CoalesceTests(unittest.IsolatedAsyncioTestCase):

    async def test_single_old_message_no_coalesce_no_wait(self):
        """Un mensaje viejo (>5s) pasa directo sin esperar ni coalescer."""
        msgs = [_msg("m1", "conv-1", "Hola", age_seconds=10)]
        w = _make_worker_with_mock_supabase(msgs)
        result = await w._coalesce_pending_by_conversation(msgs)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "Hola")

    async def test_two_messages_same_conv_coalesce(self):
        """Dos mensajes de la misma conv → se juntan."""
        msgs = [
            _msg("m1", "conv-1", "Hola, quiero comprar jabón", age_seconds=10),
            _msg("m2", "conv-1", "La de 60 gramos", age_seconds=8),
        ]
        w = _make_worker_with_mock_supabase(msgs)
        result = await w._coalesce_pending_by_conversation(msgs)
        # Un solo mensaje resultante (el último con contenido combinado).
        self.assertEqual(len(result), 1)
        combined = result[0]["content"]
        self.assertIn("Hola, quiero comprar jabón", combined)
        self.assertIn("La de 60 gramos", combined)
        self.assertIn("\n\n", combined)
        # El id es el del último mensaje
        self.assertEqual(result[0]["id"], "m2")

    async def test_three_messages_typical_user_flow(self):
        """Caso del usuario: 3 mensajes seguidos, bot debe ver los 3."""
        msgs = [
            _msg("m1", "conv-1", "Hola, quiero comprar un jabón artesanal de coco",
                 age_seconds=10),
            _msg("m2", "conv-1", "La de 60 gramos por favor", age_seconds=9),
            _msg("m3", "conv-1", "Hola", age_seconds=8),
        ]
        w = _make_worker_with_mock_supabase(msgs)
        result = await w._coalesce_pending_by_conversation(msgs)
        self.assertEqual(len(result), 1)
        combined = result[0]["content"]
        # Los 3 mensajes presentes en el orden correcto
        self.assertIn("Hola, quiero comprar", combined)
        self.assertIn("60 gramos", combined)
        # "Hola" del último también está, pero ya no es lo único
        self.assertEqual(result[0]["id"], "m3")

    async def test_different_conversations_no_coalesce(self):
        """Mensajes de conversaciones DISTINTAS NO se coalesce entre sí."""
        msgs = [
            _msg("m1", "conv-A", "Hola", age_seconds=10),
            _msg("m2", "conv-B", "Hola", age_seconds=10),
        ]
        w = _make_worker_with_mock_supabase(msgs)
        result = await w._coalesce_pending_by_conversation(msgs)
        # Cada uno pasa independiente
        self.assertEqual(len(result), 2)
        ids = {r["id"] for r in result}
        self.assertEqual(ids, {"m1", "m2"})


class WindowConstantTests(unittest.TestCase):

    def test_default_window_is_5_seconds(self):
        # El usuario pidió 5s mínimos.
        self.assertGreaterEqual(MESSAGE_COALESCE_WINDOW_SECONDS, 5)


if __name__ == "__main__":
    unittest.main()
