"""M18 — cobertura adicional para services/api/routers/conversations.py.

Complementa a los tests existentes (test_api_conversations_contract,
test_conversations_outbound_queue, test_send_message_24h_window,
test_tenant_isolation_inbox, test_inbound_media_proxy) cubriendo paths NO
ejercitados:

- get_inbound_media: 502 (MediaDownloadError), fallback de mime desde DB,
  409 por excepción en _get_tenant_wa_access_token.
- get_inbox_stats: 500.
- list_conversations: filtro status válido, preview last_message, 500.
- get_conversation: 404, orden desc + truncado a 50 mensajes, 500.
- get_conversation_messages: 404, happy, 500.
- update_conversation_status: replay idempotente, 404 + abort, 500 + abort.
- send_agent_message: 422 vacío/largo, 404, 400 no-takeover, 500 insert,
  502 enqueue fallido (marca last_error), parseo queue_data lista-de-dict,
  500 por excepción, replay.
- _check_24h_window_or_raise: created_at como datetime naive (no str).
- Notas (list/create/patch/delete): 401, 404, 403, 422, happy paths, 500.
- rerun_last_inbound: 404 conv, 409 status, 404 sin inbound, happy clone, 500.
- send_agent_image: 422 URL/caption, 404, 400, happy, 502.
- get_conversation_cart + shape_cart: 404, sin cart, happy con títulos, 500.
- get_conversation_context: 404, happy completo (contacto/orders/products/
  cart/claims), quote stale, pending, sin cart, orders tolerante a error, 500.

Patrón: unittest + MagicMock (igual que los archivos hermanos), imports con
sys.path relativo portable.
"""
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from routers import conversations  # noqa: E402

TENANT = "11111111-1111-1111-1111-111111111111"
CONV = "conv-1"


# ─── Fakes ────────────────────────────────────────────────────────────────────


class _Chain:
    """Chain Supabase fake: data distinta por verbo (select/insert/update).

    `raise_on` fuerza RuntimeError en execute() para ejercitar los catch-all 500
    y los bloques tolerantes (orders/products del context).
    """

    def __init__(self, select_data=None, insert_data=None, update_data=None, raise_on=()):
        self._data = {"select": select_data, "insert": insert_data, "update": update_data}
        self._raise_on = set(raise_on)
        self._verb = "select"
        self.eq_calls: list[tuple] = []
        self.order_calls: list[tuple] = []
        self.insert_payloads: list = []
        self.update_payloads: list = []

    def select(self, *a, **k):
        self._verb = "select"
        return self

    def insert(self, payload, *a, **k):
        self._verb = "insert"
        self.insert_payloads.append(payload)
        return self

    def update(self, payload, *a, **k):
        self._verb = "update"
        self.update_payloads.append(payload)
        return self

    def eq(self, key, val):
        self.eq_calls.append((key, val))
        return self

    def neq(self, *a, **k):
        return self

    def or_(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def ilike(self, *a, **k):
        return self

    def order(self, *a, **k):
        self.order_calls.append((a, k))
        return self

    def limit(self, *a, **k):
        return self

    def offset(self, *a, **k):
        return self

    def range(self, *a, **k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self._verb in self._raise_on:
            raise RuntimeError(f"forced error on {self._verb}")
        return SimpleNamespace(data=self._data.get(self._verb))


class _Supabase:
    """Cliente Supabase fake: config por tabla + rpc stub con data variable."""

    def __init__(self, tables=None, rpc_data=1, rpc_raise=False):
        self._tables = tables or {}
        self._chains: dict[str, _Chain] = {}
        self.rpc_calls: list[tuple] = []
        self._rpc_data = rpc_data
        self._rpc_raise = rpc_raise

    def table(self, name):
        if name not in self._chains:
            cfg = self._tables.get(name, [])
            if isinstance(cfg, dict):
                self._chains[name] = _Chain(
                    select_data=cfg.get("select"),
                    insert_data=cfg.get("insert"),
                    update_data=cfg.get("update"),
                    raise_on=cfg.get("raise_on", ()),
                )
            else:  # shorthand: lista => data del select
                self._chains[name] = _Chain(select_data=cfg)
        return self._chains[name]

    def rpc(self, fn, payload):
        self.rpc_calls.append((fn, payload))
        rpc_data, rpc_raise = self._rpc_data, self._rpc_raise

        class _R:
            def execute(self):
                if rpc_raise:
                    raise RuntimeError("rpc boom")
                return SimpleNamespace(data=rpc_data)

        return _R()


def _idem_patches(replay=None):
    """Parchea el stack de idempotencia del router (begin/finalize/abort/fingerprint)."""
    return (
        patch("routers.conversations.begin_idempotency", return_value=(MagicMock(), replay)),
        patch("routers.conversations.finalize_idempotency"),
        patch("routers.conversations.abort_idempotency"),
        patch("routers.conversations.payload_fingerprint", return_value="fp"),
    )


def _request():
    return SimpleNamespace(headers={})


def _recent_iso(hours=1):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ─── get_inbound_media ────────────────────────────────────────────────────────


class InboundMediaCoverageTests(unittest.IsolatedAsyncioTestCase):
    def _supabase(self, media_mime="image/png"):
        return _Supabase({
            "messages": [{"id": "m1", "media_mime": media_mime}],
            "tenant_integrations": {
                "select": {"credentials": {"access_token": "WA_TOKEN"}, "status": "connected"},
            },
        })

    async def test_meta_download_error_returns_502(self):
        from integrations.meta_media import MediaDownloadError

        sb = self._supabase()
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch("integrations.meta_media.fetch_media_bytes",
                   new=AsyncMock(side_effect=MediaDownloadError("boom"))):
            with self.assertRaises(HTTPException) as ctx:
                await conversations.get_inbound_media("MID-1", tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 502)

    async def test_mime_falls_back_to_db_media_mime(self):
        """Si Meta no devuelve mime, se usa el media_mime persistido del mensaje."""
        sb = self._supabase(media_mime="image/png")
        with patch("vault_helper.VaultHelper", MagicMock()), \
             patch("integrations.meta_media.fetch_media_bytes",
                   new=AsyncMock(return_value=(b"\x89PNG-bytes", None))):
            resp = await conversations.get_inbound_media("MID-1", tenant_id=TENANT, supabase=sb)
        self.assertEqual(resp.media_type, "image/png")
        self.assertEqual(resp.headers["Content-Disposition"], "inline")

    async def test_integrations_query_exception_means_no_token_409(self):
        """_get_tenant_wa_access_token traga excepciones → "" → 409 limpio."""
        sb = _Supabase({
            "messages": [{"id": "m1", "media_mime": "image/jpeg"}],
            "tenant_integrations": {"select": None, "raise_on": ("select",)},
        })
        with self.assertRaises(HTTPException) as ctx:
            await conversations.get_inbound_media("MID-1", tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 409)


# ─── get_inbox_stats / list_conversations ────────────────────────────────────


class ListAndStatsCoverageTests(unittest.TestCase):
    def test_stats_db_error_returns_500(self):
        sb = _Supabase({"conversations": {"select": None, "raise_on": ("select",)}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_inbox_stats(tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_list_applies_valid_status_filter(self):
        sb = _Supabase({"conversations": []})
        conversations.list_conversations(
            tenant_id=TENANT, supabase=sb, status="closed",
            agentic_state=None, limit=10, offset=5,
        )
        eq_calls = sb.table("conversations").eq_calls
        self.assertIn(("status", "closed"), eq_calls)
        self.assertIn(("tenant_id", TENANT), eq_calls)

    def test_list_builds_last_message_preview_from_most_recent(self):
        """Mensajes llegan desordenados: el preview debe ser el más reciente."""
        sb = _Supabase({"conversations": [{
            "id": "c-1", "customer_phone": "573001112233", "status": "bot_active",
            "created_at": "2026-04-22T10:00:00Z", "last_interaction_at": "2026-04-22T11:00:00Z",
            "messages": [
                {"content": "viejo", "direction": "inbound", "created_at": "2026-04-22T09:00:00Z"},
                {"content": "nuevo", "direction": "outbound", "created_at": "2026-04-22T11:00:00Z"},
            ],
        }]})
        result = conversations.list_conversations(
            tenant_id=TENANT, supabase=sb, status=None,
            agentic_state=None, limit=30, offset=0,
        )
        self.assertEqual(result[0]["last_message"]["content"], "nuevo")
        self.assertNotIn("messages", result[0])

    def test_list_without_messages_sets_preview_none(self):
        sb = _Supabase({"conversations": [{
            "id": "c-1", "customer_phone": "573001112233", "status": "bot_active",
            "created_at": "2026-04-22T10:00:00Z", "last_interaction_at": "2026-04-22T11:00:00Z",
            "messages": [],
        }]})
        result = conversations.list_conversations(
            tenant_id=TENANT, supabase=sb, status=None,
            agentic_state=None, limit=30, offset=0,
        )
        self.assertIsNone(result[0]["last_message"])

    def test_list_db_error_returns_500(self):
        sb = _Supabase({"conversations": {"select": None, "raise_on": ("select",)}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.list_conversations(
                tenant_id=TENANT, supabase=sb, status=None,
                agentic_state=None, limit=30, offset=0,
            )
        self.assertEqual(ctx.exception.status_code, 500)


# ─── get_conversation / get_conversation_messages ────────────────────────────


class GetConversationCoverageTests(unittest.TestCase):
    def test_get_conversation_not_found_404(self):
        sb = _Supabase({"conversations": {"select": None}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_conversation_sorts_desc_and_truncates_to_50(self):
        msgs = [
            {"id": f"m-{i}", "created_at": f"2026-01-01T00:00:{i:02d}"}
            for i in range(55)
        ]
        sb = _Supabase({"conversations": {"select": {
            "id": CONV, "customer_phone": "573001112233", "status": "bot_active",
            "messages": msgs,
        }}})
        result = conversations.get_conversation(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(len(result["messages"]), 50)
        self.assertEqual(result["messages"][0]["id"], "m-54")  # más reciente primero
        self.assertEqual(result["messages"][-1]["id"], "m-5")

    def test_get_conversation_db_error_returns_500(self):
        sb = _Supabase({"conversations": {"select": None, "raise_on": ("select",)}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_get_messages_conv_not_found_404(self):
        sb = _Supabase({"conversations": {"select": None}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation_messages(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_get_messages_happy_path_ascending(self):
        sb = _Supabase({
            "conversations": {"select": {"id": CONV}},
            "messages": [{"id": "m-1"}, {"id": "m-2"}],
        })
        result = conversations.get_conversation_messages(
            CONV, limit=100, offset=10, tenant_id=TENANT, supabase=sb,
        )
        self.assertEqual([m["id"] for m in result], ["m-1", "m-2"])
        # Orden cronológico ASC (el chat se lee de arriba a abajo).
        args, kwargs = sb.table("messages").order_calls[0]
        self.assertEqual(args, ("created_at",))
        self.assertFalse(kwargs.get("desc", True))

    def test_get_messages_db_error_returns_500(self):
        sb = _Supabase({
            "conversations": {"select": {"id": CONV}},
            "messages": {"select": None, "raise_on": ("select",)},
        })
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation_messages(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 500)


# ─── update_conversation_status ───────────────────────────────────────────────


class UpdateStatusCoverageTests(unittest.TestCase):
    def test_idempotent_replay_returns_recorded_response(self):
        begin_p, fin_p, abort_p, fp_p = _idem_patches(
            replay={"status_code": 200, "body": {"id": CONV, "status": "closed"}}
        )
        with begin_p, fin_p, abort_p, fp_p:
            result = conversations.update_conversation_status(
                conversation_id=CONV,
                body=conversations.ConversationStatusUpdate(status="closed"),
                request=_request(), tenant_id=TENANT, supabase=_Supabase(),
            )
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["idempotency-replayed"], "true")

    def test_not_found_returns_404_and_aborts_idempotency(self):
        sb = _Supabase({"conversations": {"update": []}})
        begin_p, fin_p, abort_p, fp_p = _idem_patches()
        with begin_p, fin_p, abort_p as abort_m, fp_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.update_conversation_status(
                    conversation_id=CONV,
                    body=conversations.ConversationStatusUpdate(status="closed"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 404)
        # El router aborta inline (antes del raise) Y de nuevo en el
        # `except HTTPException` — doble abort sobre la misma sesión
        # (idempotente en la práctica; se reporta como observación).
        self.assertGreaterEqual(abort_m.call_count, 1)

    def test_db_error_returns_500_and_aborts(self):
        sb = _Supabase({"conversations": {"update": None, "raise_on": ("update",)}})
        begin_p, fin_p, abort_p, fp_p = _idem_patches()
        with begin_p, fin_p, abort_p as abort_m, fp_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.update_conversation_status(
                    conversation_id=CONV,
                    body=conversations.ConversationStatusUpdate(status="closed"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 500)
        abort_m.assert_called_once()


# ─── _check_24h_window_or_raise — ramas de parseo no-str ─────────────────────


class WindowParseCoverageTests(unittest.TestCase):
    def test_naive_datetime_object_is_treated_as_utc(self):
        """created_at como datetime (no str) y sin tzinfo → se asume UTC."""
        naive_recent = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
        sb = _Supabase({"messages": [{"created_at": naive_recent}]})
        self.assertIsNone(conversations._check_24h_window_or_raise(sb, TENANT, CONV))

    def test_aware_datetime_object_outside_window_raises(self):
        aware_old = datetime.now(timezone.utc) - timedelta(hours=30)
        sb = _Supabase({"messages": [{"created_at": aware_old}]})
        with self.assertRaises(HTTPException) as ctx:
            conversations._check_24h_window_or_raise(sb, TENANT, CONV)
        self.assertEqual(ctx.exception.detail["code"], "WINDOW_EXPIRED")


# ─── send_agent_message ───────────────────────────────────────────────────────


class SendAgentMessageCoverageTests(unittest.TestCase):
    def _supabase(self, conv_status="human_takeover", insert_data=None, **kw):
        if insert_data is None:
            insert_data = [{
                "id": "m-out-1", "tenant_id": TENANT, "conversation_id": CONV,
                "direction": "outbound", "content": "hola", "processing_status": "pending",
            }]
        return _Supabase({
            "conversations": {"select": {
                "id": CONV, "customer_phone": "573001112233",
                "status": conv_status, "tenant_id": TENANT,
            }},
            "messages": {
                "select": [{"created_at": _recent_iso(1)}],
                "insert": insert_data,
            },
        }, **kw)

    def _send(self, text="hola", sb=None):
        begin_p, fin_p, abort_p, fp_p = _idem_patches()
        with begin_p, fin_p, abort_p, fp_p:
            return conversations.send_agent_message(
                conversation_id=CONV,
                body=conversations.AgentMessageRequest(text=text),
                request=_request(), tenant_id=TENANT,
                supabase=sb if sb is not None else self._supabase(),
            )

    def test_empty_text_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            conversations.send_agent_message(
                conversation_id=CONV,
                body=conversations.AgentMessageRequest(text="   "),
                request=_request(), tenant_id=TENANT, supabase=_Supabase(),
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_text_over_4096_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            conversations.send_agent_message(
                conversation_id=CONV,
                body=conversations.AgentMessageRequest(text="x" * 4097),
                request=_request(), tenant_id=TENANT, supabase=_Supabase(),
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_conversation_not_found_returns_404(self):
        sb = _Supabase({"conversations": {"select": None}})
        with self.assertRaises(HTTPException) as ctx:
            self._send(sb=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_not_human_takeover_returns_400(self):
        sb = self._supabase(conv_status="bot_active")
        with self.assertRaises(HTTPException) as ctx:
            self._send(sb=sb)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_insert_without_data_returns_500(self):
        sb = self._supabase(insert_data=[])
        with self.assertRaises(HTTPException) as ctx:
            self._send(sb=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_enqueue_failure_marks_message_failed_and_returns_502(self):
        sb = self._supabase(rpc_data=0)
        with self.assertRaises(HTTPException) as ctx:
            self._send(sb=sb)
        self.assertEqual(ctx.exception.status_code, 502)
        updates = sb.table("messages").update_payloads
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["last_error"], "queue_enqueue_failed")
        self.assertEqual(updates[0]["processing_status"], "failed")

    def test_queue_data_list_of_dict_is_unwrapped(self):
        """pgmq puede devolver [{'msg_id': N}] — el router debe desenvolverlo."""
        sb = self._supabase(rpc_data=[{"msg_id": 42}])
        result = self._send(sb=sb)
        self.assertTrue(result["queued"])
        self.assertEqual(result["queue_message_id"], 42)

    def test_rpc_exception_returns_500(self):
        sb = self._supabase(rpc_raise=True)
        with self.assertRaises(HTTPException) as ctx:
            self._send(sb=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_idempotent_replay(self):
        begin_p, fin_p, abort_p, fp_p = _idem_patches(
            replay={"status_code": 200, "body": {"queued": True, "queue_message_id": 9}}
        )
        with begin_p, fin_p, abort_p, fp_p:
            result = conversations.send_agent_message(
                conversation_id=CONV,
                body=conversations.AgentMessageRequest(text="hola"),
                request=_request(), tenant_id=TENANT, supabase=self._supabase(),
            )
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.headers["idempotency-replayed"], "true")


# ─── Notas privadas ───────────────────────────────────────────────────────────


class NotesCoverageTests(unittest.IsolatedAsyncioTestCase):
    def _jwt(self, user_id="u-1", role="operator"):
        return (
            patch("dependencies.auth._extract_jwt_payload", return_value={"sub": user_id}),
            patch("dependencies.auth.get_current_role", new=AsyncMock(return_value=role)),
        )

    # -- list --
    async def test_list_notes_conv_not_found_404(self):
        sb = _Supabase({"conversations": []})
        with self.assertRaises(HTTPException) as ctx:
            conversations.list_conversation_notes(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_list_notes_happy(self):
        sb = _Supabase({
            "conversations": [{"id": CONV}],
            "conversation_notes": [
                {"id": "n-1", "content": "pinned", "is_pinned": True},
                {"id": "n-2", "content": "normal", "is_pinned": False},
            ],
        })
        result = conversations.list_conversation_notes(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(len(result), 2)

    # -- create --
    async def test_create_note_without_user_id_returns_401(self):
        jwt_p, role_p = self._jwt(user_id=None)
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.create_conversation_note(
                    conversation_id=CONV,
                    body=conversations.NoteCreate(content="hola"),
                    request=_request(), tenant_id=TENANT, supabase=_Supabase(),
                )
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_create_note_empty_returns_422(self):
        jwt_p, role_p = self._jwt()
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.create_conversation_note(
                    conversation_id=CONV,
                    body=conversations.NoteCreate(content="   "),
                    request=_request(), tenant_id=TENANT, supabase=_Supabase(),
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_create_note_over_2000_returns_422(self):
        jwt_p, role_p = self._jwt()
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.create_conversation_note(
                    conversation_id=CONV,
                    body=conversations.NoteCreate(content="x" * 2001),
                    request=_request(), tenant_id=TENANT, supabase=_Supabase(),
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_create_note_conv_not_found_404(self):
        jwt_p, role_p = self._jwt()
        sb = _Supabase({"conversations": []})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.create_conversation_note(
                    conversation_id=CONV,
                    body=conversations.NoteCreate(content="nota"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_create_note_happy_inserts_author_and_content(self):
        jwt_p, role_p = self._jwt(user_id="u-1")
        sb = _Supabase({
            "conversations": [{"id": CONV}],
            "conversation_notes": {"insert": [{"id": "n-1", "content": "nota"}]},
        })
        with jwt_p, role_p:
            result = conversations.create_conversation_note(
                conversation_id=CONV,
                body=conversations.NoteCreate(content=" nota ", is_pinned=True),
                request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertEqual(result["id"], "n-1")
        payload = sb.table("conversation_notes").insert_payloads[0]
        self.assertEqual(payload["author_user_id"], "u-1")
        self.assertEqual(payload["content"], "nota")  # strip aplicado
        self.assertTrue(payload["is_pinned"])
        self.assertEqual(payload["tenant_id"], TENANT)

    async def test_create_note_insert_without_data_returns_500(self):
        jwt_p, role_p = self._jwt()
        sb = _Supabase({
            "conversations": [{"id": CONV}],
            "conversation_notes": {"insert": []},
        })
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                conversations.create_conversation_note(
                    conversation_id=CONV,
                    body=conversations.NoteCreate(content="nota"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 500)

    # -- patch --
    async def test_patch_note_not_found_404(self):
        jwt_p, role_p = self._jwt()
        sb = _Supabase({"conversation_notes": []})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.patch_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    patch=conversations.NotePatch(content="x"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_patch_note_forbidden_for_non_author_operator(self):
        jwt_p, role_p = self._jwt(user_id="u-1", role="operator")
        sb = _Supabase({"conversation_notes": [{"id": "n-1", "author_user_id": "u-2"}]})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.patch_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    patch=conversations.NotePatch(content="x"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_patch_note_empty_content_returns_422(self):
        jwt_p, role_p = self._jwt(user_id="u-1")
        sb = _Supabase({"conversation_notes": [{"id": "n-1", "author_user_id": "u-1"}]})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.patch_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    patch=conversations.NotePatch(content="   "),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_patch_note_over_2000_returns_422(self):
        jwt_p, role_p = self._jwt(user_id="u-1")
        sb = _Supabase({"conversation_notes": [{"id": "n-1", "author_user_id": "u-1"}]})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.patch_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    patch=conversations.NotePatch(content="x" * 2001),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_patch_note_nothing_to_update_returns_422(self):
        jwt_p, role_p = self._jwt(user_id="u-1")
        sb = _Supabase({"conversation_notes": [{"id": "n-1", "author_user_id": "u-1"}]})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.patch_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    patch=conversations.NotePatch(),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_patch_note_author_can_update(self):
        jwt_p, role_p = self._jwt(user_id="u-1", role="operator")
        sb = _Supabase({
            "conversation_notes": {
                "select": [{"id": "n-1", "author_user_id": "u-1"}],
                "update": [{"id": "n-1", "content": "nuevo"}],
            },
        })
        with jwt_p, role_p:
            result = await conversations.patch_conversation_note(
                conversation_id=CONV, note_id="n-1",
                patch=conversations.NotePatch(content=" nuevo ", is_pinned=True),
                request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertEqual(result["content"], "nuevo")
        update = sb.table("conversation_notes").update_payloads[0]
        self.assertEqual(update["content"], "nuevo")
        self.assertTrue(update["is_pinned"])

    async def test_patch_note_privileged_non_author_can_update(self):
        """owner/manager pueden editar notas ajenas."""
        jwt_p, role_p = self._jwt(user_id="u-1", role="manager")
        sb = _Supabase({
            "conversation_notes": {
                "select": [{"id": "n-1", "author_user_id": "u-2"}],
                "update": [{"id": "n-1", "is_pinned": True}],
            },
        })
        with jwt_p, role_p:
            result = await conversations.patch_conversation_note(
                conversation_id=CONV, note_id="n-1",
                patch=conversations.NotePatch(is_pinned=True),
                request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertTrue(result["is_pinned"])

    async def test_patch_note_update_without_data_returns_500(self):
        jwt_p, role_p = self._jwt(user_id="u-1")
        sb = _Supabase({
            "conversation_notes": {
                "select": [{"id": "n-1", "author_user_id": "u-1"}],
                "update": [],
            },
        })
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.patch_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    patch=conversations.NotePatch(content="x"),
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 500)

    # -- delete --
    async def test_delete_note_not_found_404(self):
        jwt_p, role_p = self._jwt()
        sb = _Supabase({"conversation_notes": []})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.delete_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_delete_note_forbidden_for_non_author_operator(self):
        jwt_p, role_p = self._jwt(user_id="u-1", role="operator")
        sb = _Supabase({"conversation_notes": [{"author_user_id": "u-2"}]})
        with jwt_p, role_p:
            with self.assertRaises(HTTPException) as ctx:
                await conversations.delete_conversation_note(
                    conversation_id=CONV, note_id="n-1",
                    request=_request(), tenant_id=TENANT, supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_delete_note_soft_deletes_with_deleted_at(self):
        jwt_p, role_p = self._jwt(user_id="u-1")
        sb = _Supabase({"conversation_notes": [{"author_user_id": "u-1"}]})
        with jwt_p, role_p:
            result = await conversations.delete_conversation_note(
                conversation_id=CONV, note_id="n-1",
                request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertIsNone(result)
        update = sb.table("conversation_notes").update_payloads[0]
        self.assertIn("deleted_at", update)


# ─── rerun_last_inbound ───────────────────────────────────────────────────────


class RerunCoverageTests(unittest.TestCase):
    def _supabase(self, conv_status="bot_active", inbound=None, insert_data=None):
        if inbound is None:
            inbound = [{
                "id": "m-old", "content": "hola", "content_type": "text",
                "media_url": None, "created_at": _recent_iso(2),
            }]
        if insert_data is None:
            insert_data = [{"id": "m-new"}]
        return _Supabase({
            "conversations": [{"id": CONV, "status": conv_status}],
            "messages": {"select": inbound, "insert": insert_data},
        })

    def test_conv_not_found_404(self):
        sb = _Supabase({"conversations": []})
        with self.assertRaises(HTTPException) as ctx:
            conversations.rerun_last_inbound(
                CONV, request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_not_bot_active_returns_409(self):
        sb = self._supabase(conv_status="human_takeover")
        with self.assertRaises(HTTPException) as ctx:
            conversations.rerun_last_inbound(
                CONV, request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_no_inbound_returns_404(self):
        sb = self._supabase(inbound=[])
        with self.assertRaises(HTTPException) as ctx:
            conversations.rerun_last_inbound(
                CONV, request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_happy_clones_inbound_as_pending_with_rerun_payload(self):
        sb = self._supabase()
        result = conversations.rerun_last_inbound(
            CONV, request=_request(), tenant_id=TENANT, supabase=sb,
        )
        self.assertEqual(result["rerun_message_id"], "m-new")
        self.assertEqual(result["source_message_id"], "m-old")
        self.assertEqual(result["status"], "queued")
        clone = sb.table("messages").insert_payloads[0]
        self.assertEqual(clone["processing_status"], "pending")
        self.assertFalse(clone["processed"])
        self.assertEqual(clone["direction"], "inbound")
        self.assertTrue(clone["payload"]["_rerun"])
        self.assertEqual(clone["payload"]["_rerun_source_msg_id"], "m-old")
        self.assertEqual(clone["tenant_id"], TENANT)

    def test_insert_without_data_returns_500(self):
        sb = self._supabase(insert_data=[])
        with self.assertRaises(HTTPException) as ctx:
            conversations.rerun_last_inbound(
                CONV, request=_request(), tenant_id=TENANT, supabase=sb,
            )
        self.assertEqual(ctx.exception.status_code, 500)


# ─── send_agent_image ─────────────────────────────────────────────────────────


class SendAgentImageCoverageTests(unittest.TestCase):
    URL = "https://cdn.example.supabase.co/storage/v1/object/public/tenant-media/img.jpg"

    def _supabase(self, conv_status="human_takeover", **kw):
        return _Supabase({
            "conversations": {"select": {
                "id": CONV, "customer_phone": "573001112233",
                "status": conv_status, "tenant_id": TENANT,
            }},
            "messages": {
                "select": [{"created_at": _recent_iso(1)}],
                "insert": [{
                    "id": "m-img-1", "content_type": "image",
                    "content": "[imagen]", "media_url": self.URL,
                }],
            },
        }, **kw)

    def _send_image(self, image_url=None, caption=None, sb=None):
        begin_p, fin_p, abort_p, fp_p = _idem_patches()
        with begin_p, fin_p, abort_p, fp_p:
            return conversations.send_agent_image(
                conversation_id=CONV,
                body=conversations.AgentImageRequest(
                    image_url=image_url if image_url is not None else self.URL,
                    caption=caption,
                ),
                request=_request(), tenant_id=TENANT,
                supabase=sb if sb is not None else self._supabase(),
            )

    def test_non_https_url_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(image_url="http://insecure.example.com/img.jpg")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_caption_over_1024_returns_422(self):
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(caption="x" * 1025)
        self.assertEqual(ctx.exception.status_code, 422)

    def test_conversation_not_found_returns_404(self):
        sb = _Supabase({"conversations": {"select": None}})
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(sb=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_not_human_takeover_returns_400(self):
        sb = self._supabase(conv_status="bot_active")
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(sb=sb)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_happy_path_enqueues_image_with_caption_payload(self):
        sb = self._supabase(rpc_data=7)
        result = self._send_image(caption="foto del producto", sb=sb)
        self.assertTrue(result["queued"])
        self.assertEqual(result["queue_message_id"], 7)
        fn, payload = sb.rpc_calls[0]
        self.assertEqual(fn, "enqueue_whatsapp_outbound_message")
        self.assertEqual(payload["p_message"]["image_link"], self.URL)
        self.assertEqual(payload["p_message"]["image_caption"], "foto del producto")

    def test_happy_path_without_caption_uses_placeholder_content(self):
        sb = self._supabase()
        result = self._send_image(sb=sb)
        self.assertTrue(result["queued"])
        insert = sb.table("messages").insert_payloads[0]
        self.assertEqual(insert["content"], "[imagen]")
        self.assertEqual(insert["content_type"], "image")
        self.assertEqual(insert["media_url"], self.URL)

    def test_enqueue_failure_marks_failed_and_returns_502(self):
        sb = self._supabase(rpc_data=[])
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(sb=sb)
        self.assertEqual(ctx.exception.status_code, 502)
        updates = sb.table("messages").update_payloads
        self.assertEqual(updates[0]["last_error"], "queue_enqueue_failed")

    def test_insert_without_data_returns_500(self):
        sb = _Supabase({
            "conversations": {"select": {
                "id": CONV, "customer_phone": "573001112233",
                "status": "human_takeover", "tenant_id": TENANT,
            }},
            "messages": {
                "select": [{"created_at": _recent_iso(1)}],
                "insert": [],
            },
        })
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(sb=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_rpc_exception_returns_500(self):
        sb = self._supabase(rpc_raise=True)
        with self.assertRaises(HTTPException) as ctx:
            self._send_image(sb=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_queue_data_list_of_dict_is_unwrapped(self):
        sb = self._supabase(rpc_data=[{"msg_id": 33}])
        result = self._send_image(sb=sb)
        self.assertEqual(result["queue_message_id"], 33)

    def test_idempotent_replay(self):
        begin_p, fin_p, abort_p, fp_p = _idem_patches(
            replay={"status_code": 200, "body": {"queued": True, "queue_message_id": 5}}
        )
        with begin_p, fin_p, abort_p, fp_p:
            result = conversations.send_agent_image(
                conversation_id=CONV,
                body=conversations.AgentImageRequest(image_url=self.URL),
                request=_request(), tenant_id=TENANT, supabase=self._supabase(),
            )
        self.assertIsInstance(result, JSONResponse)
        self.assertEqual(result.headers["idempotency-replayed"], "true")


# ─── get_conversation_cart / shape_cart ───────────────────────────────────────


class CartCoverageTests(unittest.TestCase):
    def test_shape_cart_defaults_currency_and_maps_titles(self):
        shaped = conversations.shape_cart(
            {"id": "cart-1", "status": "open"},
            [{"id": "i-1", "product_id": "p-1", "variation_id": "v-1",
              "quantity": 2, "unit_price_cents": 500}],
            {"p-1": "Zapatos"},
        )
        self.assertEqual(shaped["currency"], "COP")
        self.assertEqual(shaped["items"][0]["product_title"], "Zapatos")
        self.assertIsNone(shaped["subtotal_cents"])

    def test_cart_conv_not_found_404(self):
        sb = _Supabase({"conversations": {"select": None}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation_cart(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_cart_empty_when_no_cart_rows(self):
        sb = _Supabase({
            "conversations": {"select": {"id": CONV}},
            "conversation_carts": [],
        })
        result = conversations.get_conversation_cart(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(result, {"id": None, "status": None, "items": []})

    def test_cart_happy_path_with_items_and_titles(self):
        sb = _Supabase({
            "conversations": {"select": {"id": CONV}},
            "conversation_carts": [{
                "id": "cart-1", "status": "open", "currency": "COP",
                "subtotal_cents": 10000, "shipping_cents": 5000,
                "discount_cents": 0, "total_cents": 15000,
                "coupon_code": None, "requires_requote": False, "shipping_meta": {},
            }],
            "conversation_cart_items": [{
                "id": "i-1", "product_id": "p-1", "variation_id": "v-1",
                "quantity": 1, "unit_price_cents": 10000,
            }],
            "products": [{"id": "p-1", "title": "Zapatos"}],
        })
        result = conversations.get_conversation_cart(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(result["id"], "cart-1")
        self.assertEqual(result["total_cents"], 15000)
        self.assertEqual(result["items"][0]["product_title"], "Zapatos")

    def test_cart_db_error_returns_500(self):
        sb = _Supabase({"conversations": {"select": None, "raise_on": ("select",)}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation_cart(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 500)


# ─── get_conversation_context ─────────────────────────────────────────────────


class ContextCoverageTests(unittest.TestCase):
    def _base_tables(self, **overrides):
        tables = {
            "conversations": {"select": {
                "id": CONV, "customer_phone": "+57 3125835649", "status": "bot_active",
            }},
            "contacts": [{
                "id": "ct-1", "name": "Ana", "phone": "573125835649",
                "email": "ana@example.com",
            }],
            "orders": [{
                "id": "o-1", "status": "paid", "total_amount": 100,
                "shipping_cost": 0, "created_at": "2026-05-01T00:00:00Z",
                "conversation_id": CONV, "contact_id": "ct-1",
                "order_items": [{"id": "oi-1"}, {"id": "oi-2"}],
            }],
            "products": [
                {"id": "p-1", "title": "Zapatos", "status": "active",
                 "product_variations": [{"id": "v-1", "stock_quantity": 2}]},
                {"id": "p-2", "title": "Bolso", "status": "active",
                 "product_variations": [{"id": "v-2", "stock_quantity": 10}]},
            ],
            "conversation_carts": [{
                "id": "cart-1", "status": "open",
                "subtotal_cents": 10000, "shipping_cents": 5000,
                "total_cents": 15000, "shipping_meta": {"carrier_label": "Aveonline"},
                "requires_requote": False, "discount_cents": 1000,
                "coupon_code": "AHORRA10", "payment_method": "cod",
            }],
            "conversation_cart_items": [{
                "id": "ci-1", "product_id": "p-1", "variation_id": "v-1",
                "quantity": 2, "unit_price_cents": 5000,
                "created_at": "2026-05-01T00:00:00Z",
            }],
            "product_variations": [{
                "id": "v-1", "attributes": {"Color": "Rojo"}, "sku": "SKU-1",
            }],
            "messages": [],
            "claims": [{
                "id": "cl-1", "ticket_number": "T-1", "status": "open",
                "reason": "producto roto", "created_at": "2026-05-01T00:00:00Z",
            }],
        }
        tables.update(overrides)
        return tables

    def test_conv_not_found_returns_404(self):
        sb = _Supabase({"conversations": {"select": None}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_full_context_happy_path(self):
        sb = _Supabase(self._base_tables())
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)

        self.assertEqual(result["contact"]["id"], "ct-1")
        self.assertEqual(result["recent_orders"][0]["items_count"], 2)
        self.assertNotIn("order_items", result["recent_orders"][0])
        self.assertEqual(result["product_count"], 2)
        self.assertEqual(result["low_stock_count"], 1)  # p-1 con stock_total=2
        self.assertEqual(result["products"][0]["stock_total"], 2)
        self.assertEqual(len(result["open_claims"]), 1)

        cart = result["active_cart"]
        self.assertIsNotNone(cart)
        self.assertEqual(cart["shipping_status"], "active")  # shipping>0 sin requote
        self.assertEqual(cart["shipping_cents"], 5000)
        self.assertEqual(cart["carrier_name"], "Aveonline")
        # total = subtotal + envío - descuento (Rev. 109 BUG 35).
        self.assertEqual(cart["total_cents"], 10000 + 5000 - 1000)
        self.assertEqual(cart["discount_cents"], 1000)
        self.assertEqual(cart["payment_method"], "cod")
        self.assertEqual(cart["items"][0]["title"], "Zapatos")
        self.assertEqual(cart["items"][0]["variant_label"], "Rojo")
        self.assertEqual(cart["items"][0]["sku"], "SKU-1")

    def test_stale_quote_uses_last_quote_from_history(self):
        """requires_requote + quote en history → shipping_status 'stale' con el
        último valor cotizado (Rev. 103)."""
        quote = "Opciones de envío:\n*Económica*: Coordinadora | $12.500\n*Express*: Servi | $20.000"
        sb = _Supabase(self._base_tables(
            conversation_carts=[{
                "id": "cart-1", "status": "open",
                "subtotal_cents": 10000, "shipping_cents": 0,
                "total_cents": 10000, "shipping_meta": {},
                "requires_requote": True, "discount_cents": 0,
                "coupon_code": None, "payment_method": "credit",
            }],
            messages=[{"content": quote, "created_at": "2026-05-01T00:00:00Z"}],
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        cart = result["active_cart"]
        self.assertEqual(cart["shipping_status"], "stale")
        self.assertEqual(cart["shipping_cents"], 12500 * 100)
        self.assertEqual(cart["carrier_name"], "Coordinadora")
        self.assertEqual(cart["total_cents"], 10000 + 12500 * 100)

    def test_cart_without_quote_is_pending(self):
        sb = _Supabase(self._base_tables(
            conversation_carts=[{
                "id": "cart-1", "status": "open",
                "subtotal_cents": 10000, "shipping_cents": 0,
                "total_cents": 10000, "shipping_meta": {},
                "requires_requote": False, "discount_cents": 0,
                "coupon_code": None, "payment_method": None,
            }],
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        cart = result["active_cart"]
        self.assertEqual(cart["shipping_status"], "pending")
        self.assertEqual(cart["shipping_cents"], 0)
        self.assertEqual(cart["payment_method"], "credit")  # default

    def test_no_open_cart_returns_none(self):
        sb = _Supabase(self._base_tables(conversation_carts=[]))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertIsNone(result["active_cart"])

    def test_orders_error_is_tolerated(self):
        """Fallo cargando pedidos NO rompe el context (warning + lista vacía)."""
        sb = _Supabase(self._base_tables(
            orders={"select": None, "raise_on": ("select",)},
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(result["recent_orders"], [])
        self.assertEqual(result["contact"]["id"], "ct-1")  # el resto sigue OK

    def test_without_phone_skips_contact_and_claims(self):
        sb = _Supabase(self._base_tables(
            conversations={"select": {
                "id": CONV, "customer_phone": None, "status": "bot_active",
            }},
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertIsNone(result["contact"])
        self.assertEqual(result["open_claims"], [])

    def test_top_level_error_returns_500(self):
        sb = _Supabase({"conversations": {"select": None, "raise_on": ("select",)}})
        with self.assertRaises(HTTPException) as ctx:
            conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(ctx.exception.status_code, 500)

    def test_products_error_is_tolerated(self):
        """Fallo cargando catálogo → products vacío, contact/orders OK.
        Side effect real: el lookup de títulos del cart usa la MISMA tabla
        products → también cae en el catch del cart y active_cart queda None."""
        sb = _Supabase(self._base_tables(
            products={"select": None, "raise_on": ("select",)},
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(result["products"], [])
        self.assertEqual(result["product_count"], 0)
        self.assertEqual(result["low_stock_count"], 0)
        self.assertEqual(result["contact"]["id"], "ct-1")
        self.assertEqual(result["recent_orders"][0]["items_count"], 2)
        self.assertIsNone(result["active_cart"])

    def test_cart_error_is_tolerated(self):
        """Fallo cargando conversation_carts → active_cart None sin romper."""
        sb = _Supabase(self._base_tables(
            conversation_carts={"select": None, "raise_on": ("select",)},
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertIsNone(result["active_cart"])
        self.assertEqual(result["contact"]["id"], "ct-1")

    def test_claims_error_is_tolerated(self):
        sb = _Supabase(self._base_tables(
            claims={"select": None, "raise_on": ("select",)},
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        self.assertEqual(result["open_claims"], [])

    def test_quote_without_requote_and_zero_shipping_is_active(self):
        """cart.shipping_cents=0 sin requote + quote en history → usa el quote
        como 'active' (referencia del último valor cotizado)."""
        quote = "*Económica*: Coordinadora | $12.500"
        sb = _Supabase(self._base_tables(
            conversation_carts=[{
                "id": "cart-1", "status": "open",
                "subtotal_cents": 10000, "shipping_cents": 0,
                "total_cents": 10000, "shipping_meta": {},
                "requires_requote": False, "discount_cents": 0,
                "coupon_code": None, "payment_method": "credit",
            }],
            messages=[{"content": quote, "created_at": "2026-05-01T00:00:00Z"}],
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        cart = result["active_cart"]
        self.assertEqual(cart["shipping_status"], "active")
        self.assertEqual(cart["shipping_cents"], 12500 * 100)

    def test_quote_with_unparseable_price_is_skipped(self):
        """Precio que matchea pero no parsea a int → ValueError interno → se
        sigue buscando en las líneas/mensajes siguientes."""
        bad = "*Económica*: X | $.,,"          # matchea [\d.,]+ pero int('') falla
        good = "*Económica*: Coordinadora | $9.900"
        sb = _Supabase(self._base_tables(
            conversation_carts=[{
                "id": "cart-1", "status": "open",
                "subtotal_cents": 10000, "shipping_cents": 0,
                "total_cents": 10000, "shipping_meta": {},
                "requires_requote": True, "discount_cents": 0,
                "coupon_code": None, "payment_method": "credit",
            }],
            messages=[
                {"content": bad, "created_at": "2026-05-02T00:00:00Z"},
                {"content": good, "created_at": "2026-05-01T00:00:00Z"},
            ],
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        cart = result["active_cart"]
        self.assertEqual(cart["shipping_cents"], 9900 * 100)
        self.assertEqual(cart["carrier_name"], "Coordinadora")

    def test_quote_query_error_is_tolerated(self):
        """Fallo en la query de messages (last quote) → quote 0, cart sigue."""
        sb = _Supabase(self._base_tables(
            conversation_carts=[{
                "id": "cart-1", "status": "open",
                "subtotal_cents": 10000, "shipping_cents": 5000,
                "total_cents": 15000, "shipping_meta": {},
                "requires_requote": False, "discount_cents": 0,
                "coupon_code": None, "payment_method": "credit",
            }],
            messages={"select": None, "raise_on": ("select",)},
        ))
        result = conversations.get_conversation_context(CONV, tenant_id=TENANT, supabase=sb)
        cart = result["active_cart"]
        self.assertEqual(cart["shipping_status"], "active")  # shipping del cart
        self.assertEqual(cart["shipping_cents"], 5000)


if __name__ == "__main__":
    unittest.main()
