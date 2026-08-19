"""
Tests: KB Tool — RAG, fallback y format_kb_for_prompt
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"))

from tools.kb_tool import (
    format_kb_for_prompt,
    get_tenant_kb_rag,
    _fallback_kb,
    CATEGORY_LABELS,
)
from llm_embed import get_embedding_model_version  # BLOQUE G-3: guard de drift

TENANT_ID = "tenant-abc"


def _mock_supabase(docs: list[dict]) -> MagicMock:
    sb = MagicMock()
    # fallback chain: .table().select().eq().eq().order().limit().execute()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value.data = docs
    # rpc chain: .rpc().execute()
    sb.rpc.return_value.execute.return_value.data = docs
    return sb


class TestFormatKbForPrompt(unittest.TestCase):

    def test_empty_returns_empty_string(self):
        self.assertEqual(format_kb_for_prompt([]), "")

    def test_single_doc_formats_correctly(self):
        # Rev. 71 — canónicas: politicas (plural), productos (plural).
        docs = [{"title": "Política de envíos", "content": "Enviamos en 3 días.", "category": "politicas"}]
        result = format_kb_for_prompt(docs)
        self.assertIn("Políticas", result)
        self.assertIn("Política de envíos", result)
        self.assertIn("Enviamos en 3 días.", result)

    def test_groups_by_category(self):
        docs = [
            {"title": "FAQ 1", "content": "Resp 1", "category": "faq"},
            {"title": "Política 1", "content": "Texto pol", "category": "politicas"},
            {"title": "FAQ 2", "content": "Resp 2", "category": "faq"},
        ]
        result = format_kb_for_prompt(docs)
        self.assertIn("Preguntas frecuentes", result)
        self.assertIn("Políticas", result)
        faq_pos = result.index("Preguntas frecuentes")
        pol_pos = result.index("Políticas")
        self.assertNotEqual(faq_pos, pol_pos)

    def test_unknown_category_falls_back_to_capitalized(self):
        docs = [{"title": "Doc", "content": "Contenido", "category": "custom_cat"}]
        result = format_kb_for_prompt(docs)
        self.assertIn("Custom_cat", result)

    def test_all_known_categories_have_labels(self):
        # Rev. 71 — 6 canónicas: faq, negocio, politicas, productos, envios, pagos.
        for cat in ["faq", "negocio", "politicas", "productos", "envios", "pagos"]:
            docs = [{"title": "T", "content": "C", "category": cat}]
            result = format_kb_for_prompt(docs)
            self.assertIn(CATEGORY_LABELS[cat], result)


class TestFallbackKb(unittest.TestCase):

    def test_returns_data_from_supabase(self):
        docs = [{"title": "Doc", "content": "Cont", "category": "faq"}]
        sb = _mock_supabase(docs)
        result = _fallback_kb(sb, TENANT_ID)
        self.assertEqual(result, docs)

    def test_returns_empty_list_on_no_data(self):
        sb = _mock_supabase([])
        result = _fallback_kb(sb, TENANT_ID)
        self.assertEqual(result, [])


class TestGetTenantKbRag(unittest.IsolatedAsyncioTestCase):

    async def test_empty_query_uses_fallback(self):
        sb = _mock_supabase([{"title": "T", "content": "C", "category": "faq"}])
        result = await get_tenant_kb_rag(sb, TENANT_ID, "")
        sb.rpc.assert_not_called()
        self.assertEqual(len(result), 1)

    async def test_no_api_key_uses_fallback(self):
        sb = _mock_supabase([{"title": "T", "content": "C", "category": "faq"}])
        with patch("tools.kb_tool.GEMINI_API_KEY", ""):
            result = await get_tenant_kb_rag(sb, TENANT_ID, "¿Cuánto demora el envío?")
        sb.rpc.assert_not_called()
        self.assertEqual(len(result), 1)

    async def test_rag_path_calls_rpc(self):
        # Rev. 71 — el query NO debe disparar trigger léxico de categoría
        # (envío/pago/etc.), para que el flow sea solo semántico sin boost.
        docs = [{"title": "Hola", "content": "Saludo", "category": "faq"}]
        sb = _mock_supabase(docs)
        mock_vector = [0.1] * 3072
        with patch("tools.kb_tool.GEMINI_API_KEY", "test-key"), \
             patch("tools.kb_tool._embed_query_vector", return_value=mock_vector):
            result = await get_tenant_kb_rag(sb, TENANT_ID, "buenas, una pregunta general")
        sb.rpc.assert_called_once_with(
            "match_kb_documents",
            {
                "query_embedding": mock_vector,
                "match_threshold": 0.5,
                "match_count": 3,
                "t_id": TENANT_ID,
                "p_model_version": get_embedding_model_version(),
            }
        )
        self.assertEqual(result, docs)

    async def test_rag_no_results_falls_back(self):
        fallback_doc = [{"title": "Fallback", "content": "F", "category": "general"}]
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value.data = []
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = fallback_doc
        with patch("tools.kb_tool.GEMINI_API_KEY", "test-key"), \
             patch("tools.kb_tool._embed_query_vector", return_value=[0.1] * 3072):
            result = await get_tenant_kb_rag(sb, TENANT_ID, "pregunta cualquiera")
        self.assertEqual(result, fallback_doc)

    async def test_rpc_exception_falls_back(self):
        fallback_doc = [{"title": "F", "content": "C", "category": "faq"}]
        sb = MagicMock()
        sb.rpc.return_value.execute.side_effect = RuntimeError("pgvector error")
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
            .order.return_value.limit.return_value.execute.return_value.data = fallback_doc
        with patch("tools.kb_tool.GEMINI_API_KEY", "test-key"), \
             patch("tools.kb_tool._embed_query_vector", return_value=[0.1] * 3072):
            result = await get_tenant_kb_rag(sb, TENANT_ID, "pregunta")
        self.assertEqual(result, fallback_doc)


if __name__ == "__main__":
    unittest.main()
