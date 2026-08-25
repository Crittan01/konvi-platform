"""Unit tests de `konvi_domain.claims` (Track 5 M2.4).

Cubre la lógica de dominio extraída del router (mismas reglas, mensajes y
secuencias): create unificado (reason cerrado + reason_detail + dedup +
titularidad por actor + unión de eventos), get/list/list_by_contact, transition
(FSM: refunded FINAL, write-once, reapertura owner, no-op) y reversión
(delegación RPC + traducción de motivos). Los tests heredados del router
(test_claim_refund_capture / test_claim_reversion_api / test_claim_create_rbac)
certifican el adaptador end-to-end; acá va el servicio a pelo.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from konvi_domain import Actor, Channel, DomainError, ErrorCode, Role
from konvi_domain.claims import (
    CLAIM_LIST_SELECT,
    ClaimCreateInput,
    ClaimPorts,
    ClaimTransitionInput,
    ReversionInput,
    create_claim,
    get_claim,
    list_claims,
    list_claims_by_contact,
    read_reversion,
    register_reversion,
    register_reversion_movement,
    transition_claim,
)

TENANT = "t1"


# ─── Supabase falso: filtros eq/in_ aplicados de verdad + trigger de ticket ──

class _Q:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._filters = []
        self._op = "select"
        self._payload = None
        self._select = None
        self._single = False
        self._limit = None

    def select(self, cols, *a, **k):
        self._op = "select"
        self._select = cols
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

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def maybe_single(self):
        self._single = True
        return self

    def _matched(self):
        rows = [dict(r) for r in self._sb.tables.get(self._table, [])]
        for op, c, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if str(r.get(c)) == str(v)]
            elif op == "in":
                rows = [r for r in rows if r.get(c) in v]
        return rows

    def execute(self):
        sb = self._sb
        sb.queries.append({
            "table": self._table, "op": self._op,
            "select": self._select, "filters": list(self._filters),
        })
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", f"{self._table}-{len(sb.tables.get(self._table, [])) + 1}")
            if self._table == "claims":
                # Trigger set_claim_ticket_number (secuencial per-tenant).
                tickets = [r.get("ticket_number") or 0 for r in sb.tables.get("claims", [])]
                row.setdefault("ticket_number", (max(tickets) if tickets else 0) + 1)
            sb.tables.setdefault(self._table, []).append(row)
            sb.inserts.append((self._table, dict(row)))
            return SimpleNamespace(data=[row])
        if self._op == "update":
            matched_keys = [
                (op, c, v) for op, c, v in self._filters if op == "eq"
            ]
            updated = []
            for r in sb.tables.get(self._table, []):
                if all(str(r.get(c)) == str(v) for _op, c, v in matched_keys):
                    r.update(self._payload)
                    updated.append(dict(r))
            return SimpleNamespace(data=updated)
        rows = self._matched()
        if self._single:
            return SimpleNamespace(data=(rows[0] if rows else None))
        if self._limit is not None:
            rows = rows[: self._limit]
        return SimpleNamespace(data=rows)


class _Sb:
    def __init__(self, tables=None, rpc_results=None):
        self.tables = tables or {}
        self.queries = []
        self.inserts = []
        self.rpcs = []
        self._rpc_results = rpc_results or {}

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params=None):
        self.rpcs.append((name, params))
        datos = self._rpc_results.get(name, [])
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=datos))


# ─── Helpers ─────────────────────────────────────────────────────────────────

_ORDER = {
    "id": "o1", "tenant_id": TENANT, "contact_id": "c1", "status": "delivered",
    "conversation_id": "conv-1",
}


def _actor(role=Role.OWNER, contact_id=None, channel=Channel.CONSOLE):
    return Actor(channel=channel, tenant_id=TENANT, role=role, contact_id=contact_id)


def _ports():
    calls = {"operator": [], "client": []}
    return calls, ClaimPorts(
        notify_operator_new_claim=lambda text: calls["operator"].append(text),
        notify_client_outcome=lambda claim: calls["client"].append(dict(claim)),
    )


def _create_input(**kw):
    base = {"order_id": "o1", "reason": "defective"}
    base.update(kw)
    return ClaimCreateInput(**base)


# ─── claims.create ───────────────────────────────────────────────────────────

class CreateClaimTests(unittest.TestCase):
    def test_create_happy_path_inserta_y_dispara_eventos(self):
        sb = _Sb({"orders": [_ORDER]})
        calls, ports = _ports()
        res = create_claim(
            sb, tenant_id=TENANT,
            input=_create_input(reason_detail="llegó roto", requested_amount=50000),
            actor=_actor(Role.OPERATOR), ports=ports,
        )
        self.assertTrue(res.created)
        self.assertEqual(res.http_status, 201)
        claim = res.claim
        self.assertEqual(claim["status"], "open")
        self.assertEqual(claim["reason"], "defective")
        self.assertEqual(claim["reason_detail"], "llegó roto")
        self.assertEqual(claim["requested_amount"], 50000)
        self.assertEqual(claim["customer_id"], "c1")  # derivado del pedido
        self.assertEqual(claim["ticket_number"], 1)
        # claim_audit en la conversación DE LA ORDEN.
        audits = [p for t, p in sb.inserts if t == "messages"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["conversation_id"], "conv-1")
        self.assertEqual(audits[0]["content_type"], "claim_audit")
        self.assertEqual(audits[0]["payload"]["reason"], "defective")
        self.assertEqual(audits[0]["payload"]["reason_detail"], "llegó roto")
        # Telegram operador con el texto espejo del bot.
        self.assertEqual(len(calls["operator"]), 1)
        self.assertIn("Nuevo reclamo #1", calls["operator"][0])
        self.assertIn("defective — llegó roto", calls["operator"][0])
        self.assertIn("$50,000", calls["operator"][0])
        self.assertEqual(res.events[0].name, "claim.created")

    def test_dedup_devuelve_existente_sin_insertar(self):
        sb = _Sb({
            "orders": [_ORDER],
            "claims": [{
                "id": "cl-9", "tenant_id": TENANT, "order_id": "o1",
                "customer_id": "c1", "status": "investigating", "ticket_number": 9,
            }],
        })
        calls, ports = _ports()
        res = create_claim(
            sb, tenant_id=TENANT, input=_create_input(), actor=_actor(), ports=ports,
        )
        self.assertFalse(res.created)
        self.assertEqual(res.http_status, 200)
        self.assertEqual(res.claim["id"], "cl-9")
        self.assertTrue(res.body()["deduplicated"])
        self.assertEqual([i for i in sb.inserts if i[0] == "claims"], [])
        self.assertEqual(calls["operator"], [])
        self.assertEqual(res.events[0].name, "claim.deduplicated")

    def test_dedup_lookup_fallido_crea_igual(self):
        """Lookup defensivo (patrón del bot): la dedup falla → se crea."""
        class _BoomClaims(_Sb):
            def table(self, name):
                q = super().table(name)
                if name == "claims":
                    def _boom(*a, **k):
                        raise RuntimeError("db glitch")
                    q.select = _boom  # solo el SELECT de la dedup falla; el insert pasa
                return q
        sb = _BoomClaims({"orders": [_ORDER]})
        res = create_claim(sb, tenant_id=TENANT, input=_create_input(), actor=_actor())
        self.assertTrue(res.created)

    def test_reason_invalida_422(self):
        sb = _Sb({"orders": [_ORDER]})
        with self.assertRaises(DomainError) as ctx:
            create_claim(sb, tenant_id=TENANT, input=_create_input(reason="no_me_gusto"), actor=_actor())
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)
        self.assertIn("Motivo inválido", ctx.exception.message)

    def test_pedido_inexistente_404(self):
        sb = _Sb({"orders": []})
        with self.assertRaises(DomainError) as ctx:
            create_claim(sb, tenant_id=TENANT, input=_create_input(), actor=_actor())
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(ctx.exception.message, "Pedido no encontrado para este tenant")

    def test_customer_solo_sobre_pedidos_suyos(self):
        sb = _Sb({"orders": [_ORDER]})  # el pedido es de c1
        # customer=c2 no ve el pedido → NOT_FOUND (anti-IDOR/PII del bot).
        with self.assertRaises(DomainError) as ctx:
            create_claim(
                sb, tenant_id=TENANT, input=_create_input(),
                actor=_actor(Role.CUSTOMER, contact_id="c2", channel=Channel.BOT),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        # customer=c1 (titular) sí radica.
        res = create_claim(
            sb, tenant_id=TENANT, input=_create_input(),
            actor=_actor(Role.CUSTOMER, contact_id="c1", channel=Channel.BOT),
        )
        self.assertTrue(res.created)
        self.assertEqual(res.claim["customer_id"], "c1")

    def test_customer_sin_contact_id_forbidden(self):
        sb = _Sb({"orders": [_ORDER]})
        with self.assertRaises(DomainError) as ctx:
            create_claim(
                sb, tenant_id=TENANT, input=_create_input(),
                actor=_actor(Role.CUSTOMER, contact_id=None, channel=Channel.BOT),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.FORBIDDEN)

    def test_sin_conversacion_en_pedido_se_omite_claim_audit(self):
        """messages.conversation_id es NOT NULL: pedido MeLi/manual → solo audit_log."""
        sb = _Sb({"orders": [{**_ORDER, "conversation_id": None}]})
        calls, ports = _ports()
        res = create_claim(sb, tenant_id=TENANT, input=_create_input(), actor=_actor(), ports=ports)
        self.assertTrue(res.created)
        self.assertEqual([i for i in sb.inserts if i[0] == "messages"], [])
        self.assertEqual(len(calls["operator"]), 1)  # el Telegram sí sale

    def test_reason_detail_trim_y_max_500(self):
        sb = _Sb({"orders": [_ORDER]})
        res = create_claim(
            sb, tenant_id=TENANT,
            input=_create_input(reason_detail="  " + "x" * 600 + "  "),
            actor=_actor(),
        )
        self.assertEqual(len(res.claim["reason_detail"]), 500)

    def test_customer_id_del_body_gana_al_del_pedido(self):
        sb = _Sb({"orders": [_ORDER]})
        res = create_claim(
            sb, tenant_id=TENANT, input=_create_input(customer_id="c9"), actor=_actor(),
        )
        self.assertEqual(res.claim["customer_id"], "c9")


# ─── Lecturas ────────────────────────────────────────────────────────────────

_CLAIM = {
    "id": "cl1", "tenant_id": TENANT, "order_id": "o1", "customer_id": "c1",
    "status": "open", "reason": "defective", "ticket_number": 7,
}


class ReadClaimTests(unittest.TestCase):
    def test_get_por_id(self):
        sb = _Sb({"claims": [_CLAIM]})
        row = get_claim(sb, tenant_id=TENANT, actor=_actor(), claim_id="cl1")
        self.assertEqual(row["id"], "cl1")

    def test_get_por_ticket_customer_solo_los_suyos(self):
        sb = _Sb({"claims": [_CLAIM]})
        row = get_claim(
            sb, tenant_id=TENANT,
            actor=_actor(Role.CUSTOMER, contact_id="c1", channel=Channel.BOT),
            ticket_number=7,
        )
        self.assertEqual(row["id"], "cl1")
        # El ticket de OTRO cliente no se encuentra (fail-closed, P0 del bot).
        with self.assertRaises(DomainError) as ctx:
            get_claim(
                sb, tenant_id=TENANT,
                actor=_actor(Role.CUSTOMER, contact_id="c2", channel=Channel.BOT),
                ticket_number=7,
            )
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)

    def test_get_customer_sin_contact_forbidden(self):
        sb = _Sb({"claims": [_CLAIM]})
        with self.assertRaises(DomainError) as ctx:
            get_claim(
                sb, tenant_id=TENANT,
                actor=_actor(Role.CUSTOMER, contact_id=None, channel=Channel.BOT),
                ticket_number=7,
            )
        self.assertEqual(ctx.exception.code, ErrorCode.FORBIDDEN)

    def test_get_no_encontrado_404(self):
        sb = _Sb({"claims": []})
        with self.assertRaises(DomainError) as ctx:
            get_claim(sb, tenant_id=TENANT, actor=_actor(), claim_id="nope")
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)

    def test_list_con_filtros_y_embeds(self):
        sb = _Sb({"claims": [
            _CLAIM,
            {**_CLAIM, "id": "cl2", "status": "resolved", "ticket_number": 8},
        ]})
        rows = list_claims(sb, tenant_id=TENANT, actor=_actor(), status="open")
        self.assertEqual([r["id"] for r in rows], ["cl1"])
        q = sb.queries[-1]
        self.assertEqual(q["select"], CLAIM_LIST_SELECT)
        self.assertIn("orders(id, total_amount, payment_method)", q["select"])
        self.assertIn("contacts(id, name, phone)", q["select"])
        self.assertIn("reason_detail", q["select"])
        with self.assertRaises(DomainError) as ctx:
            list_claims(sb, tenant_id=TENANT, actor=_actor(), status="in_progress")
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)

    def test_list_by_contact(self):
        sb = _Sb({"claims": [
            _CLAIM,
            {**_CLAIM, "id": "cl2", "customer_id": "c2", "ticket_number": 8},
        ]})
        rows = list_claims_by_contact(sb, tenant_id=TENANT, contact_id="c1", actor=_actor())
        self.assertEqual([r["id"] for r in rows], ["cl1"])


# ─── claims.transition (FSM) ─────────────────────────────────────────────────

class TransitionClaimTests(unittest.TestCase):
    def _sb_con(self, status, **extra):
        return _Sb({"claims": [{**_CLAIM, "status": status, **extra}]})

    def test_refunded_exige_monto(self):
        sb = self._sb_con("resolved")
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(status="refunded"), actor=_actor(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)
        self.assertIn("monto reembolsado real", ctx.exception.message)

    def test_refunded_captura_monto_y_fecha(self):
        sb = self._sb_con("investigating")
        calls, ports = _ports()
        row = transition_claim(
            sb, tenant_id=TENANT, claim_id="cl1",
            input=ClaimTransitionInput(status="refunded", refunded_amount=300),
            actor=_actor(), ports=ports,
        )
        self.assertEqual(row["refunded_amount"], 300)
        self.assertIsNotNone(row["refunded_at"])
        # refunded NO es outcome F-5 → no notifica al cliente.
        self.assertEqual(calls["client"], [])

    def test_refunded_es_final(self):
        for target in ("resolved", "rejected", "open"):
            sb = self._sb_con("refunded")
            with self.assertRaises(DomainError) as ctx:
                transition_claim(
                    sb, tenant_id=TENANT, claim_id="cl1",
                    input=ClaimTransitionInput(status=target), actor=_actor(),
                )
            self.assertEqual(ctx.exception.code, ErrorCode.CONFLICT, target)

    def test_reapertura_solo_owner_y_desde_reabrible(self):
        # manager no puede reabrir.
        sb = self._sb_con("rejected")
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(status="open"), actor=_actor(Role.MANAGER),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.FORBIDDEN)
        # owner desde 'resolved' (no reabrible) → 409.
        sb = self._sb_con("resolved")
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(status="open"), actor=_actor(Role.OWNER),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.CONFLICT)
        # owner desde 'rejected' → reabre.
        sb = self._sb_con("rejected")
        row = transition_claim(
            sb, tenant_id=TENANT, claim_id="cl1",
            input=ClaimTransitionInput(status="open"), actor=_actor(Role.OWNER),
        )
        self.assertEqual(row["status"], "open")

    def test_outcome_real_notifica_una_sola_vez(self):
        sb = self._sb_con("investigating")
        calls, ports = _ports()
        row = transition_claim(
            sb, tenant_id=TENANT, claim_id="cl1",
            input=ClaimTransitionInput(status="resolved", resolution_notes="Repuesto"),
            actor=_actor(), ports=ports,
        )
        self.assertEqual(row["status"], "resolved")
        self.assertEqual(len(calls["client"]), 1)
        self.assertEqual(calls["client"][0]["status"], "resolved")
        # No-op mismo-status: la transición pasa pero NO re-notifica.
        calls["client"].clear()
        transition_claim(
            sb, tenant_id=TENANT, claim_id="cl1",
            input=ClaimTransitionInput(status="resolved"), actor=_actor(), ports=ports,
        )
        self.assertEqual(calls["client"], [])

    def test_patch_solo_notas_no_notifica(self):
        sb = self._sb_con("investigating")
        calls, ports = _ports()
        row = transition_claim(
            sb, tenant_id=TENANT, claim_id="cl1",
            input=ClaimTransitionInput(resolution_notes="nota interna"),
            actor=_actor(), ports=ports,
        )
        self.assertEqual(row["resolution_notes"], "nota interna")
        self.assertEqual(calls["client"], [])

    def test_correccion_monto_write_once(self):
        # refunded con monto NULL → se setea (backfill histórico).
        sb = self._sb_con("refunded", refunded_amount=None)
        row = transition_claim(
            sb, tenant_id=TENANT, claim_id="cl1",
            input=ClaimTransitionInput(refunded_amount=250), actor=_actor(),
        )
        self.assertEqual(row["refunded_amount"], 250)
        self.assertEqual(row["status"], "refunded")
        # Con monto ya registrado → 409 (write-once).
        sb = self._sb_con("refunded", refunded_amount=100)
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(refunded_amount=999), actor=_actor(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.CONFLICT)
        # En no-refunded → 422.
        sb = self._sb_con("investigating")
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(refunded_amount=250), actor=_actor(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)

    def test_sin_campos_422(self):
        sb = self._sb_con("open")
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(), actor=_actor(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)
        self.assertEqual(ctx.exception.message, "Sin campos a actualizar")

    def test_no_encontrado_404(self):
        sb = _Sb({"claims": []})
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="nope",
                input=ClaimTransitionInput(status="resolved"), actor=_actor(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)

    def test_status_invalido_422(self):
        sb = self._sb_con("open")
        with self.assertRaises(DomainError) as ctx:
            transition_claim(
                sb, tenant_id=TENANT, claim_id="cl1",
                input=ClaimTransitionInput(status="in_progress"), actor=_actor(),
            )
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)


# ─── Reversión (delegación RPC) ──────────────────────────────────────────────

_CONSTANCIA = {
    "id": "rv1", "claim_id": "cl1", "tenant_id": TENANT, "radicado": "RV-000042",
    "causal": "producto_defectuoso", "valor": 68000,
}


class ReversionTests(unittest.TestCase):
    def _input(self, **kw):
        base = {"causal": "producto_defectuoso", "razones": "me llegó roto", "valor": 68000}
        base.update(kw)
        return ReversionInput(**base)

    def test_radica_con_params_exactos_y_devuelve_constancia(self):
        sb = _Sb(
            {"payment_reversal_requests": [_CONSTANCIA]},
            rpc_results={"rpc_registrar_reversion": [{"id": "rv1", "motivo": None}]},
        )
        out = register_reversion(sb, tenant_id=TENANT, claim_id="cl1", input=self._input(
            instrumento="Visa terminada en 4242", bien_a_disposicion=True,
        ))
        self.assertEqual(out["radicado"], "RV-000042")
        name, params = sb.rpcs[0]
        self.assertEqual(name, "rpc_registrar_reversion")
        self.assertEqual(params["p_claim_id"], "cl1")
        self.assertEqual(params["p_tenant_id"], TENANT)
        self.assertEqual(params["p_causal"], "producto_defectuoso")
        self.assertEqual(params["p_razones"], "me llegó roto")
        self.assertEqual(params["p_valor"], 68000)
        self.assertTrue(params["p_bien_a_disposicion"])

    def test_causal_invalida_422_antes_de_la_rpc(self):
        sb = _Sb({})
        with self.assertRaises(DomainError) as ctx:
            register_reversion(sb, tenant_id=TENANT, claim_id="cl1", input=self._input(causal="no_me_gusto"))
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)
        self.assertIn("2.2.2.51.2", ctx.exception.message)
        self.assertEqual(sb.rpcs, [])

    def test_motivos_mapean_a_http_status_heredado(self):
        for motivo, status, code in (
            ("reclamo_inexistente", 404, ErrorCode.NOT_FOUND),
            ("reclamo_sin_pedido", 409, ErrorCode.CONFLICT),
            ("pago_no_electronico", 409, ErrorCode.CONFLICT),
            ("forma_de_pago_desconocida", 409, ErrorCode.CONFLICT),
            ("valor_excede_el_pedido", 422, ErrorCode.VALIDATION),
        ):
            sb = _Sb({}, rpc_results={"rpc_registrar_reversion": [{"motivo": motivo}]})
            with self.assertRaises(DomainError) as ctx:
                register_reversion(sb, tenant_id=TENANT, claim_id="cl1", input=self._input())
            self.assertEqual(ctx.exception.http_status, status, motivo)
            self.assertEqual(ctx.exception.code, code, motivo)

    def test_movimiento_via_invalida_422(self):
        sb = _Sb({"payment_reversal_requests": [_CONSTANCIA]})
        with self.assertRaises(DomainError) as ctx:
            register_reversion_movement(
                sb, tenant_id=TENANT, claim_id="cl1", via="nequi", valor=1000,
            )
        self.assertEqual(ctx.exception.code, ErrorCode.VALIDATION)

    def test_movimiento_registra_via_y_valor(self):
        sb = _Sb(
            {"payment_reversal_requests": [_CONSTANCIA]},
            rpc_results={"rpc_registrar_movimiento_reversion": [{"doble_pago": False, "motivo": None}]},
        )
        out = register_reversion_movement(
            sb, tenant_id=TENANT, claim_id="cl1", via="reembolso_directo", valor=68000,
        )
        self.assertEqual(out["radicado"], "RV-000042")
        name, params = sb.rpcs[0]
        self.assertEqual(name, "rpc_registrar_movimiento_reversion")
        self.assertEqual(params["p_reversal_id"], "rv1")
        self.assertEqual(params["p_via"], "reembolso_directo")
        self.assertEqual(params["p_valor"], 68000)

    def test_movimiento_con_motivo_422(self):
        sb = _Sb(
            {"payment_reversal_requests": [_CONSTANCIA]},
            rpc_results={"rpc_registrar_movimiento_reversion": [{"motivo": "valor_excede_reversion"}]},
        )
        with self.assertRaises(DomainError) as ctx:
            register_reversion_movement(
                sb, tenant_id=TENANT, claim_id="cl1", via="reembolso_directo", valor=1,
            )
        self.assertEqual(ctx.exception.http_status, 422)

    def test_leer_sin_reversion_404(self):
        sb = _Sb({"payment_reversal_requests": []})
        with self.assertRaises(DomainError) as ctx:
            read_reversion(sb, tenant_id=TENANT, claim_id="cl1")
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)
        self.assertEqual(
            ctx.exception.message,
            "Este reclamo no tiene una solicitud de reversión radicada",
        )


if __name__ == "__main__":
    unittest.main()
