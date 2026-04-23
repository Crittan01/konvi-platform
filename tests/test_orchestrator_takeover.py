import os
import sys
import types
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator")

import orchestrator


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def single(self, *_args, **_kwargs):
        return self

    def upsert(self, *_args, **_kwargs):
        return self

    def insert(self, *_args, **_kwargs):
        return self

    def update(self, *_args, **_kwargs):
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class OrchestratorTakeoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_human_takeover_skips_auto_response(self):
        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="human_takeover"),
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=MagicMock(),
                message_id="m-1",
                tenant_id="t-1",
                conversation_id="c-1",
                content="hola",
                content_type="text",
            )

        send_msg.assert_not_called()
        mark_processing.assert_called_once()
        self.assertEqual(mark_processing.call_args.kwargs["skip_reason"], "human_takeover_active")

    async def test_closed_skips_auto_response(self):
        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="closed"),
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=MagicMock(),
                message_id="m-2",
                tenant_id="t-1",
                conversation_id="c-1",
                content="hola",
                content_type="text",
            )

        send_msg.assert_not_called()
        mark_processing.assert_called_once()
        self.assertEqual(mark_processing.call_args.kwargs["skip_reason"], "closed_conversation")

    async def test_non_text_escalates_to_human_takeover(self):
        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(orchestrator, "_set_conversation_status") as set_status,
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=MagicMock(),
                message_id="m-3",
                tenant_id="t-1",
                conversation_id="c-1",
                content="[Imagen recibida]",
                content_type="image",
            )

        send_msg.assert_not_called()
        set_status.assert_called_once_with(ANY, "c-1", "human_takeover")
        mark_processing.assert_called_once()
        self.assertEqual(mark_processing.call_args.kwargs["skip_reason"], "non_text_requires_human")

    async def test_bot_active_can_process_and_send(self):
        supabase = MagicMock()

        def table_side_effect(name):
            if name == "tenants":
                return _Query([{"name": "Tenant Test"}])
            if name == "conversations":
                return _Query([{"customer_phone": "573001112233"}])
            if name == "contacts":
                return _Query([])
            if name == "messages":
                return _Query([{"id": "out-1"}])
            return _Query([])

        supabase.table.side_effect = table_side_effect

        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = types.SimpleNamespace(
            text='{"should_respond": true, "response_text": "Hola", "confidence": 0.9, "requires_human": false, "intent_detected": "greeting"}'
        )

        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(orchestrator, "get_tenant_catalog", new_callable=AsyncMock, return_value=[]),
            patch.object(orchestrator, "get_tenant_kb_rag", new_callable=AsyncMock, return_value=[]),
            patch.object(orchestrator, "_get_conversation_history", new_callable=AsyncMock, return_value=[]),
            patch.object(orchestrator, "_get_tenant_ai_agent", new_callable=AsyncMock, return_value={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": False}),
            patch.object(orchestrator, "format_kb_for_prompt", return_value=""),
            patch.object(orchestrator, "_get_genai_client", return_value=fake_client),
            patch.object(orchestrator, "validate_orchestrator_output", return_value=True),
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock, return_value=True) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=supabase,
                message_id="m-4",
                tenant_id="t-1",
                conversation_id="c-1",
                content="hola",
                content_type="text",
            )

        send_msg.assert_awaited_once()
        self.assertEqual(mark_processing.call_args.kwargs["processing_status"], "processed")

    async def test_shipping_quote_short_circuits_llm(self):
        supabase = MagicMock()

        def table_side_effect(name):
            if name == "conversations":
                return _Query([{"customer_phone": "573001112233"}])
            if name == "messages":
                return _Query([{"id": "out-2"}])
            return _Query([])

        supabase.table.side_effect = table_side_effect

        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(
                orchestrator,
                "handle_shipping_quote_if_applicable",
                new_callable=AsyncMock,
                return_value=types.SimpleNamespace(
                    handled=True,
                    response_text="Desde Bogota te cotizo...",
                    requires_human=False,
                ),
            ) as shipping_tool,
            patch.object(orchestrator, "_get_genai_client") as genai_client,
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock, return_value=True) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=supabase,
                message_id="m-5",
                tenant_id="t-1",
                conversation_id="c-1",
                content="Cuanto vale el envio?",
                content_type="text",
            )

        shipping_tool.assert_awaited_once()
        genai_client.assert_not_called()
        send_msg.assert_awaited_once()
        self.assertEqual(mark_processing.call_args.kwargs["processing_status"], "processed")

    async def test_simple_greeting_short_circuits_llm(self):
        supabase = MagicMock()

        def table_side_effect(name):
            if name == "conversations":
                return _Query([{"customer_phone": "573001112233"}])
            if name == "messages":
                return _Query([{"id": "out-greet-1"}])
            return _Query([])

        supabase.table.side_effect = table_side_effect

        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(
                orchestrator,
                "handle_shipping_quote_if_applicable",
                new_callable=AsyncMock,
                return_value=types.SimpleNamespace(
                    handled=False,
                    response_text=None,
                    requires_human=False,
                ),
            ),
            patch.object(orchestrator, "_get_genai_client") as genai_client,
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock, return_value=True) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=supabase,
                message_id="m-greet-1",
                tenant_id="t-1",
                conversation_id="c-1",
                content="Hola",
                content_type="text",
            )

        genai_client.assert_not_called()
        send_msg.assert_awaited_once()
        self.assertEqual(mark_processing.call_args.kwargs["processing_status"], "processed")

    async def test_acknowledgement_short_circuits_llm(self):
        supabase = MagicMock()

        def table_side_effect(name):
            if name == "conversations":
                return _Query([{"customer_phone": "573001112233"}])
            if name == "messages":
                return _Query([{"id": "out-ack-1"}])
            return _Query([])

        supabase.table.side_effect = table_side_effect

        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(
                orchestrator,
                "handle_shipping_quote_if_applicable",
                new_callable=AsyncMock,
                return_value=types.SimpleNamespace(
                    handled=False,
                    response_text=None,
                    requires_human=False,
                ),
            ),
            patch.object(orchestrator, "_get_genai_client") as genai_client,
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock, return_value=True) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=supabase,
                message_id="m-ack-1",
                tenant_id="t-1",
                conversation_id="c-1",
                content="Muchas gracias",
                content_type="text",
            )

        genai_client.assert_not_called()
        send_msg.assert_awaited_once()
        self.assertEqual(mark_processing.call_args.kwargs["processing_status"], "processed")

    async def test_smalltalk_safeguard_ignores_llm_requires_human(self):
        supabase = MagicMock()

        def table_side_effect(name):
            if name == "tenants":
                return _Query([{"name": "Tenant Test"}])
            if name == "conversations":
                return _Query([{"customer_phone": "573001112233"}])
            if name == "contacts":
                return _Query([])
            if name == "messages":
                return _Query([{"id": "out-guard-1"}])
            return _Query([])

        supabase.table.side_effect = table_side_effect

        fake_client = MagicMock()
        fake_client.models.generate_content.return_value = types.SimpleNamespace(
            text='{"should_respond": true, "response_text": null, "confidence": 0.9, "requires_human": true, "intent_detected": "other"}'
        )

        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(
                orchestrator,
                "handle_shipping_quote_if_applicable",
                new_callable=AsyncMock,
                return_value=types.SimpleNamespace(handled=False, response_text=None, requires_human=False),
            ),
            patch.object(orchestrator, "_detect_deterministic_smalltalk_intent", side_effect=[None, "greeting"]),
            patch.object(orchestrator, "get_tenant_catalog", new_callable=AsyncMock, return_value=[]),
            patch.object(orchestrator, "get_tenant_kb_rag", new_callable=AsyncMock, return_value=[]),
            patch.object(orchestrator, "_get_conversation_history", new_callable=AsyncMock, return_value=[]),
            patch.object(orchestrator, "_get_tenant_ai_agent", new_callable=AsyncMock, return_value={"name": "Bot", "role_description": "Ayuda", "strict_guardrails": False}),
            patch.object(orchestrator, "format_kb_for_prompt", return_value=""),
            patch.object(orchestrator, "_get_genai_client", return_value=fake_client),
            patch.object(orchestrator, "_set_conversation_status") as set_status,
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock, return_value=True) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=supabase,
                message_id="m-guard-1",
                tenant_id="t-1",
                conversation_id="c-1",
                content="Hola bot",
                content_type="text",
            )

        send_msg.assert_awaited_once()
        set_status.assert_not_called()
        self.assertEqual(mark_processing.call_args.kwargs["processing_status"], "processed")

    async def test_shipping_quote_can_escalate_human_takeover(self):
        supabase = MagicMock()

        def table_side_effect(name):
            if name == "conversations":
                return _Query([{"customer_phone": "573001112233"}])
            if name == "messages":
                return _Query([{"id": "out-3"}])
            return _Query([])

        supabase.table.side_effect = table_side_effect

        with (
            patch.object(orchestrator, "_get_conversation_status", return_value="bot_active"),
            patch.object(
                orchestrator,
                "handle_shipping_quote_if_applicable",
                new_callable=AsyncMock,
                return_value=types.SimpleNamespace(
                    handled=True,
                    response_text="No pude cotizar envio",
                    requires_human=True,
                ),
            ),
            patch.object(orchestrator, "_set_conversation_status") as set_status,
            patch.object(orchestrator, "_mark_message_processing") as mark_processing,
            patch.object(orchestrator, "send_whatsapp_message", new_callable=AsyncMock, return_value=True) as send_msg,
        ):
            await orchestrator.build_and_run_orchestration(
                supabase=supabase,
                message_id="m-6",
                tenant_id="t-1",
                conversation_id="c-1",
                content="cotizar envio",
                content_type="text",
            )

        send_msg.assert_awaited_once()
        set_status.assert_called_once_with(ANY, "c-1", "human_takeover")
        self.assertEqual(mark_processing.call_args.kwargs["processing_status"], "processed")


if __name__ == "__main__":
    unittest.main()
