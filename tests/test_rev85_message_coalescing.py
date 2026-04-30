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

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

from worker import OrchestratorWorker, MESSAGE_COALESCE_WINDOW_SECONDS  # noqa: E402


def _make_worker_with_mock_supabase(initial_pending: list[dict]) -> OrchestratorWorker:
    """Crea un worker con supabase mock que retorna `initial_pending` en re-fetch."""
    sb = MagicMock()
    sb.table.return_value.update.return_value.in_.return_value.execute.return_value = MagicMock(data=[])
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=initial_pending
    )
    w = OrchestratorWorker.__new__(OrchestratorWorker)  # bypass __init__
    w.supabase = sb
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
