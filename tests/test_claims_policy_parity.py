"""Paridad de POLÍTICA de reclamos bot↔paquete (Track 5 M2.4 — contrato §6.3).

El bot conserva sus writers CONGELADOS (`services/ai-orchestrator/agentic/tools/
claims.py`) hasta el bloque bot (B-2/M3 los adopta del paquete). Mientras tanto
la duplicación time-boxed tiene ALARMA: este test falla si la semántica del
paquete (`konvi_domain.claims`) diverge de la del bot.

  • Enums: `_VALID_STATUSES` (bot) == `CLAIM_STATUSES` (paquete).
    DRIFT VIVO CONOCIDO (NO se arregla aquí — es deuda del bot para M3): el
    `status_human` del tool (`agentic/tools/claims.py:358-364`) usa el set
    extinto {in_progress, closed}; el enum del paquete es la única referencia
    que esta paridad defiende.
  • create: mismo estado staged → misma decisión de dedup, mismas claves del
    insert compartidas, claim_audit insertado en ambos, notificación de
    operador disparada en ambos. La DIFERENCIA deliberada (decisión founder
    #3) se aserta explícita: el bot escribe free-text en `reason`; el paquete
    escribe `reason` cerrado + `reason_detail`.
  • get: mismo claim staged → el tool por ticket (scoped customer) y el
    paquete ven las mismas filas; customer ajeno → ninguno encuentra.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

_ORCH = Path(__file__).resolve().parents[1] / "services" / "ai-orchestrator"
if str(_ORCH) not in sys.path:
    sys.path.insert(0, str(_ORCH))

from konvi_domain import Actor, Channel, DomainError, Role  # noqa: E402
from konvi_domain.claims import (  # noqa: E402
    CLAIM_STATUSES,
    ClaimCreateInput,
    ClaimPorts,
    create_claim,
    get_claim,
)

# Espejo congelado del BOT (baseline de la paridad — NO se toca hasta B-2/M3).
from agentic.tools.base import ToolContext  # noqa: E402
from agentic.tools.claims import (  # noqa: E402
    _VALID_STATUSES,
    CreateClaimArgs,
    CreateClaimTool,
    GetClaimStatusArgs,
    GetClaimStatusTool,
)

TENANT = "t1"
FREE_TEXT = "llegó dañado, exijo mi dinero de vuelta"


# ─── Supabase falso compartido: filtros eq/in_/limit aplicados de verdad ─────

class _Q:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._filters = []
        self._op = "select"
        self._payload = None
        self._single = False

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, c, v):
        self._filters.append(("eq", c, v))
        return self

    def in_(self, c, vs):
        self._filters.append(("in", c, vs))
        return self

    def limit(self, *a):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        sb = self._sb
        if self._op == "insert":
            row = dict(self._payload)
            if self._table == "claims":
                tickets = [r.get("ticket_number") or 0 for r in sb.tables.get("claims", [])]
                row.setdefault("ticket_number", (max(tickets) if tickets else 0) + 1)
            row.setdefault("id", f"{self._table}-{len(sb.tables.get(self._table, [])) + 1}")
            sb.tables.setdefault(self._table, []).append(row)
            sb.inserts.append((self._table, dict(row)))
            return SimpleNamespace(data=[row])
        rows = [dict(r) for r in sb.tables.get(self._table, [])]
        for op, c, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            elif op == "in":
                rows = [r for r in rows if r.get(c) in v]
        if self._single:
            return SimpleNamespace(data=(rows[0] if rows else None))
        return SimpleNamespace(data=rows[:1] if self._table == "claims" and self._op == "select" else rows)


class _Sb:
    def __init__(self, tables):
        self.tables = tables
        self.inserts = []

    def table(self, name):
        return _Q(self, name)


def _stage(*, with_open_claim: bool):
    tables = {
        "orders": [{
            "id": "o1", "tenant_id": TENANT, "contact_id": "c1",
            "status": "delivered", "total_amount": 120000.0,
            "conversation_id": "conv-1",
        }],
        "claims": [],
        "messages": [],
    }
    if with_open_claim:
        tables["claims"].append({
            "id": "cl-9", "tenant_id": TENANT, "order_id": "o1",
            "customer_id": "c1", "status": "open", "ticket_number": 9,
        })
    return _Sb(tables)


def _ctx(sb):
    return ToolContext(tenant_id=TENANT, conversation_id="conv-1", contact_id="c1", supabase=sb)


def _pkg_actor():
    return Actor(channel=Channel.BOT, tenant_id=TENANT, role=Role.CUSTOMER, contact_id="c1")


# ─── Alarma de enums ─────────────────────────────────────────────────────────

class EnumsParityTests(unittest.TestCase):
    def test_valid_statuses_bot_espeja_paquete(self):
        self.assertIsInstance(_VALID_STATUSES, frozenset)
        self.assertIsInstance(CLAIM_STATUSES, frozenset)
        self.assertEqual(_VALID_STATUSES, CLAIM_STATUSES)


# ─── Paridad create ──────────────────────────────────────────────────────────

class CreateParityTests(unittest.TestCase):
    def _run_bot(self, sb, reason):
        with patch("telegram_notifications.notify_escalation_async", new=AsyncMock()) as tg:
            res = asyncio.run(CreateClaimTool().execute(
                CreateClaimArgs(order_id="o1", reason=reason, requested_amount=50000),
                _ctx(sb),
            ))
        return res, tg

    def _run_pkg(self, sb, *, reason, reason_detail=None):
        calls = {"operator": []}
        ports = ClaimPorts(notify_operator_new_claim=calls["operator"].append)
        res = create_claim(
            sb, tenant_id=TENANT,
            input=ClaimCreateInput(
                order_id="o1", reason=reason, reason_detail=reason_detail,
                requested_amount=50000,
            ),
            actor=_pkg_actor(), ports=ports,
        )
        return res, calls["operator"]

    def test_dedup_misma_decision_sin_insertar(self):
        for writer in ("bot", "paquete"):
            with self.subTest(writer=writer):
                sb = _stage(with_open_claim=True)
                if writer == "bot":
                    res, tg = self._run_bot(sb, FREE_TEXT)
                    self.assertTrue(res.success)
                    self.assertEqual(res.data["claim_id"], "cl-9")
                    self.assertIn("Ya hay un reclamo abierto", res.data["note"])
                    tg.assert_not_called()  # dedup no re-notifica
                else:
                    res, operator = self._run_pkg(sb, reason="defective")
                    self.assertFalse(res.created)
                    self.assertEqual(res.claim["id"], "cl-9")
                    self.assertEqual(operator, [])
                # Ninguno insertó duplicado ni claim_audit.
                self.assertEqual([i for i in sb.inserts if i[0] == "claims"], [])
                self.assertEqual([i for i in sb.inserts if i[0] == "messages"], [])

    def test_create_claves_compartidas_y_eventos(self):
        sb_bot, sb_pkg = _stage(with_open_claim=False), _stage(with_open_claim=False)
        bot_res, tg = self._run_bot(sb_bot, FREE_TEXT)
        pkg_res, operator = self._run_pkg(sb_pkg, reason="defective", reason_detail=FREE_TEXT)

        self.assertTrue(bot_res.success)
        self.assertTrue(pkg_res.created)

        bot_insert = [p for t, p in sb_bot.inserts if t == "claims"][0]
        pkg_insert = [p for t, p in sb_pkg.inserts if t == "claims"][0]
        # Claves compartidas EXACTAS (tenant/order/customer/status/monto).
        for key in ("tenant_id", "order_id", "customer_id", "status", "requested_amount"):
            self.assertEqual(bot_insert[key], pkg_insert[key], key)
        self.assertEqual(bot_insert["status"], "open")
        self.assertEqual(bot_insert["customer_id"], "c1")

        # DIFERENCIA deliberada (founder #3): bot = free-text en reason;
        # paquete = reason cerrado + reason_detail con el free-text.
        self.assertEqual(bot_insert["reason"], FREE_TEXT)
        self.assertNotIn("reason_detail", bot_insert)
        self.assertEqual(pkg_insert["reason"], "defective")
        self.assertEqual(pkg_insert["reason_detail"], FREE_TEXT)

        # claim_audit insertado en AMBOS (misma conversación, mismo content_type).
        for sb in (sb_bot, sb_pkg):
            audits = [p for t, p in sb.inserts if t == "messages"]
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]["conversation_id"], "conv-1")
            self.assertEqual(audits[0]["content_type"], "claim_audit")

        # Notificación de operador disparada en AMBOS.
        tg.assert_called_once()
        self.assertEqual(tg.call_args.kwargs.get("severity"), "info")
        self.assertEqual(len(operator), 1)
        self.assertIn("Nuevo reclamo #", operator[0])


# ─── Paridad get ─────────────────────────────────────────────────────────────

class GetParityTests(unittest.TestCase):
    def _stage_claim(self):
        return _Sb({
            "orders": [],
            "claims": [{
                "id": "cl1", "tenant_id": TENANT, "order_id": "o1",
                "customer_id": "c1", "status": "investigating",
                "reason": "defective", "ticket_number": 7,
                "requested_amount": None, "resolution_notes": None,
                "created_at": "2026-08-25", "updated_at": "2026-08-25",
            }],
            "messages": [],
        })

    def test_mismo_ticket_misma_fila(self):
        sb_bot, sb_pkg = self._stage_claim(), self._stage_claim()
        bot_res = asyncio.run(GetClaimStatusTool().execute(
            GetClaimStatusArgs(ticket_number=7), _ctx(sb_bot),
        ))
        self.assertTrue(bot_res.success)
        pkg_row = get_claim(
            sb_pkg, tenant_id=TENANT, actor=_pkg_actor(), ticket_number=7,
        )
        self.assertEqual(pkg_row["id"], "cl1")
        self.assertEqual(bot_res.data["ticket_number"], pkg_row["ticket_number"])
        self.assertEqual(bot_res.data["status"], pkg_row["status"])

    def test_customer_ajeno_ninguno_encuentra(self):
        sb_bot, sb_pkg = self._stage_claim(), self._stage_claim()
        ctx = ToolContext(tenant_id=TENANT, conversation_id="conv-1", contact_id="c2", supabase=sb_bot)
        bot_res = asyncio.run(GetClaimStatusTool().execute(
            GetClaimStatusArgs(ticket_number=7), ctx,
        ))
        self.assertFalse(bot_res.success)  # CLAIM_NOT_FOUND
        with self.assertRaises(DomainError):
            get_claim(
                sb_pkg, tenant_id=TENANT,
                actor=Actor(channel=Channel.BOT, tenant_id=TENANT, role=Role.CUSTOMER, contact_id="c2"),
                ticket_number=7,
            )


if __name__ == "__main__":
    unittest.main()
