"""Tests del inbound_dispatcher (rev. 104, F1-3).

Valida que el adaptador `_order_status_adapter` traduce correctamente
el resultado del handler subyacente al `ToolResult` canónico, y que
`build_inbound_dispatcher` registra el handler en la posición esperada.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import dataclass
from typing import Optional

REPO = Path(__file__).resolve().parents[1]


_TOUCHED_KEYS = ("tools", "tools.dispatcher", "tools.order_status_tool",
                 "tools.image_send_tool", "tools.shipping_quote_tool",
                 "tools.inbound_dispatcher")


def _load_dispatcher_modules():
    """Carga aislada de tools.dispatcher + tools.inbound_dispatcher.

    Snapshot de `sys.modules` antes de mutar para que `_restore_modules`
    pueda revertir y no contaminar tests downstream.
    """
    import types

    snapshot = {k: sys.modules.get(k) for k in _TOUCHED_KEYS}

    fake_tools = types.ModuleType("tools")
    fake_tools.__path__ = [str(REPO / "services/ai-orchestrator/tools")]
    sys.modules["tools"] = fake_tools

    disp_path = REPO / "services/ai-orchestrator/tools/dispatcher.py"
    disp_spec = importlib.util.spec_from_file_location(
        "tools.dispatcher", str(disp_path)
    )
    disp_mod = importlib.util.module_from_spec(disp_spec)
    sys.modules["tools.dispatcher"] = disp_mod
    disp_spec.loader.exec_module(disp_mod)

    # Stub `tools.order_status_tool` para no requerir DB real ni dependencias.
    @dataclass
    class _FakeOrderStatusResult:
        handled: bool
        response_text: Optional[str] = None
        requires_human: bool = False

    fake_os_tool = types.ModuleType("tools.order_status_tool")

    async def _fake_handle(*, supabase, tenant_id, conversation_id, query_text):
        # Devuelve "handled" si el query menciona "pedido", para diferenciar.
        if "pedido" in (query_text or "").lower():
            return _FakeOrderStatusResult(
                handled=True,
                response_text=f"status para {query_text}",
                requires_human=False,
            )
        return _FakeOrderStatusResult(handled=False)

    fake_os_tool.handle_order_status_if_applicable = _fake_handle
    sys.modules["tools.order_status_tool"] = fake_os_tool

    # Stub `tools.image_send_tool`.
    @dataclass
    class _FakeImageSendResult:
        handled: bool
        image_link: Optional[str] = None
        image_caption: Optional[str] = None
        response_text: Optional[str] = None

    fake_img_tool = types.ModuleType("tools.image_send_tool")

    async def _fake_img_handle(*, supabase, tenant_id, conversation_id,
                               query_text, recent_messages):
        if "foto" in (query_text or "").lower():
            return _FakeImageSendResult(
                handled=True,
                image_link="https://cdn.example/jabon.jpg",
                image_caption="Jabón natural",
            )
        return _FakeImageSendResult(handled=False)

    fake_img_tool.handle_image_request_if_applicable = _fake_img_handle
    sys.modules["tools.image_send_tool"] = fake_img_tool

    # Stub `tools.shipping_quote_tool`.
    @dataclass
    class _FakeShippingResult:
        handled: bool
        response_text: Optional[str] = None
        requires_human: bool = False

    fake_sh_tool = types.ModuleType("tools.shipping_quote_tool")

    async def _fake_sh_handle(*, supabase, tenant_id, conversation_id, query_text):
        if "envio" in (query_text or "").lower() or "envío" in (query_text or "").lower():
            return _FakeShippingResult(
                handled=True,
                response_text=f"quote para [{query_text}]",
            )
        return _FakeShippingResult(handled=False)

    fake_sh_tool.handle_shipping_quote_if_applicable = _fake_sh_handle
    sys.modules["tools.shipping_quote_tool"] = fake_sh_tool

    inbd_path = REPO / "services/ai-orchestrator/tools/inbound_dispatcher.py"
    inbd_spec = importlib.util.spec_from_file_location(
        "tools.inbound_dispatcher", str(inbd_path)
    )
    inbd_mod = importlib.util.module_from_spec(inbd_spec)
    sys.modules["tools.inbound_dispatcher"] = inbd_mod
    inbd_spec.loader.exec_module(inbd_mod)

    return disp_mod, inbd_mod, snapshot


def _restore_modules(snapshot):
    """Revierte `sys.modules` al snapshot tomado en `_load_dispatcher_modules`."""
    for k, prev in snapshot.items():
        if prev is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = prev


class InboundDispatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.disp_mod, cls.inbd_mod, cls._snapshot = _load_dispatcher_modules()

    @classmethod
    def tearDownClass(cls):
        _restore_modules(cls._snapshot)

    def _ctx(self, *, content, metadata=None):
        return self.disp_mod.ToolContext(
            supabase=None,
            tenant_id="t1",
            conversation_id="c1",
            contact_id=None,
            contact_record={},
            content=content,
            history=[],
            catalog=[],
            display_state="",
            metadata=metadata or {},
        )

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_builder_registers_handlers_in_order(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        # Orden: image_send → shipping_quote → order_status.
        # `known_customer_confirmation` quedó disponible como adapter en
        # `inbound_dispatcher.py` pero NO se registra: la confirmación de
        # datos del cliente conocido ocurre en READY_FOR_SUMMARY (post
        # cart-build + cotización), no al inicio del buying_intent.
        self.assertEqual(
            d.registered_tools,
            ["image_send", "shipping_quote", "order_status"],
        )

    def test_image_request_wins_over_shipping(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        # "foto del jabón enviado a Bogotá" — image debe ganar a shipping.
        ctx = self._ctx(content="¿tienes foto del jabón enviado a Bogotá?")
        result, name = self._run(d.dispatch(ctx))
        self.assertTrue(result.handled)
        self.assertEqual(name, "image_send")
        self.assertEqual(result.meta.get("image_link"), "https://cdn.example/jabon.jpg")
        self.assertEqual(result.meta.get("image_caption"), "Jabón natural")

    def test_shipping_quote_handled_when_no_skip(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        ctx = self._ctx(content="¿cuánto vale el envío a Medellín?")
        result, name = self._run(d.dispatch(ctx))
        self.assertTrue(result.handled)
        self.assertEqual(name, "shipping_quote")
        self.assertIn("quote para", result.response_text)

    def test_shipping_quote_skipped_via_metadata(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        # Recolección PII activa — shipping_quote se corto-circuita aunque
        # el inbound mencione envío.
        ctx = self._ctx(
            content="envío a Medellín",
            metadata={"skip_shipping_quote": True},
        )
        result, name = self._run(d.dispatch(ctx))
        self.assertFalse(result.handled)
        self.assertIsNone(name)

    def test_shipping_query_override_used(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        # `shipping_query_override` reemplaza al `content` en el handler.
        ctx = self._ctx(
            content="bla bla",
            metadata={"shipping_query_override": "cotizar envío a Cali"},
        )
        result, name = self._run(d.dispatch(ctx))
        self.assertTrue(result.handled)
        self.assertEqual(name, "shipping_quote")
        self.assertIn("Cali", result.response_text)

    def test_dispatcher_handles_order_status_query(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        ctx = self._ctx(content="¿estado de mi pedido?")
        result, name = self._run(d.dispatch(ctx))
        self.assertTrue(result.handled)
        self.assertEqual(name, "order_status")
        self.assertIn("status para", result.response_text)
        self.assertEqual(result.meta.get("tool"), "order_status")

    def test_dispatcher_skips_unrelated_query(self):
        d = self.inbd_mod.build_inbound_dispatcher()
        ctx = self._ctx(content="¿tienen aceites de coco?")
        result, name = self._run(d.dispatch(ctx))
        self.assertFalse(result.handled)
        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main()
