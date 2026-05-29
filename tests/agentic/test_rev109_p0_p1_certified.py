"""Tests regresión P0+P1 certificados sesión UAT live 2026-05-28.

Cubre los fixes implementados en commits b539930..fdd7f80:
  • P0 #1 — PaymentMethodPhrasing CASE C (no duplicar "pago online")
  • P0 #2 — CouponDiscountInSummary (línea descuento en resumen)
  • P0 #3 — Resumen canónico con PII Ley 1480
  • P0 #4 — Envío a tercero + cascada BUGs 41/42/42b

Tests son función pura sobre helpers de invariantes (sin DB, sin LLM).
Ejecutables aislados con `pytest tests/agentic/test_rev109_p0_p1_certified.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))


# ─── P0 #1 — PaymentMethodPhrasing CASE C ──────────────────────────────────


class TestP01PaymentMethodPhrasing:
    """BUG 38c — bot decía 'online ... pago online efectivo' (contradictorio)."""

    def setup_method(self):
        from agentic.invariants.payment_coherence import (
            _is_malformed_payment_question,
            _build_explicit_question,
        )
        self._detect = _is_malformed_payment_question
        self._rewrite = _build_explicit_question

    def test_caso_uat_original_detectado(self):
        bad = (
            "Cómo prefieres pagar: *online* (tarjeta, PSE o Nequi) o "
            "*pago online* (efectivo al recibir el paquete)?"
        )
        assert self._detect(bad) is True

    def test_caso_canonico_no_rewrite(self):
        good = (
            "Cómo prefieres pagar: *online* (tarjeta, PSE o Nequi) o "
            "*contra entrega* (efectivo al recibir el paquete)?"
        )
        assert self._detect(good) is False

    def test_outbound_no_pago_no_false_positive(self):
        assert self._detect("Tu pedido fue confirmado.") is False

    def test_solo_pago_online_sin_contradiccion(self):
        assert self._detect("Para pagar online te envío el link Wompi.") is False

    def test_rewrite_canonico_correcto(self):
        canonical = self._rewrite(['cod', 'online_wompi'])
        assert "Pago online" in canonical
        assert "Contra entrega" in canonical


# ─── P0 #2 — CouponDiscountInSummary ────────────────────────────────────────


class TestP02CouponDiscountInSummary:

    def setup_method(self):
        from agentic.invariants.summary_coherence import (
            _outbound_mentions_discount,
            _build_canonical_summary,
        )
        self._mentions = _outbound_mentions_discount
        self._build = _build_canonical_summary

    def test_outbound_con_descuento(self):
        text = (
            "Subtotal: $54.000\nEnvío: $9.000\n"
            "Descuento KAIU15: -$8.100\nTotal: $54.900"
        )
        assert self._mentions(text) is True

    def test_outbound_sin_descuento(self):
        text = "Subtotal: $18.000\nEnvío: $9.000\nTotal: $27.000"
        assert self._mentions(text) is False

    def test_descuento_sin_valor_no_match(self):
        assert self._mentions("Tu pedido tiene un descuento aplicado.") is False

    def test_variante_cupon(self):
        assert self._mentions("Cupón KAIU15 aplicado: -$8.100 COP") is True

    def test_builder_incluye_linea_descuento(self):
        cart = {
            'items': [],
            'subtotal_cents': 5400000,
            'shipping_cents': 900000,
            'discount_cents': 810000,
            'coupon_code': 'KAIU15',
            'total_cents': 5490000,
        }
        out = self._build(cart, {'carrier': 'Servientrega'})
        assert "Descuento KAIU15" in out
        assert "-$8.100" in out
        assert "$54.900" in out

    def test_builder_sin_cupon_omite_linea(self):
        cart = {
            'items': [], 'subtotal_cents': 1800000,
            'shipping_cents': 900000, 'discount_cents': 0,
            'total_cents': 2700000,
        }
        out = self._build(cart, {'carrier': 'Servientrega'})
        assert "Descuento" not in out


# ─── P0 #3 — Resumen canónico con PII Ley 1480 ──────────────────────────────


class TestP03ResumenConPII:

    def setup_method(self):
        from agentic.invariants.summary_coherence import (
            _build_canonical_summary, _format_phone, _format_address_compact,
        )
        self._build = _build_canonical_summary
        self._fmt_phone = _format_phone
        self._fmt_addr = _format_address_compact

    def test_format_phone_co_canonical(self):
        assert self._fmt_phone("573125835649") == "+57 312 583 5649"

    def test_format_phone_no_co_passthrough(self):
        # No-CO digits → return raw.
        assert self._fmt_phone("12345") == "12345"

    def test_format_address_edificio_apto(self):
        addr = {
            'street': 'Calle 100 #15-20',
            'apartment': '502',
            'neighborhood': 'Chico Norte',
            'city': 'Bogota',
            'building_type': 'edificio',
        }
        out = self._fmt_addr(addr)
        assert "Calle 100 #15-20" in out
        assert "Apto 502" in out
        assert "Chico Norte" in out
        assert "Bogota" in out

    def test_resumen_titular_completo(self):
        contact = {
            'name': 'Cristian Tobon',
            'email': 'crittan01@gmail.com',
            'phone': '573125835649',
            'shipping_phone': '573125835649',
            'document_type': 'CC',
            'document_number': '1018502222',
            'address': {
                'city': 'Bogota', 'street': 'Calle 100 #15-20',
                'apartment': '502', 'neighborhood': 'Chico Norte',
                'building_type': 'edificio',
            },
        }
        cart = {
            'items': [], 'subtotal_cents': 5400000,
            'shipping_cents': 900000, 'discount_cents': 810000,
            'coupon_code': 'KAIU15', 'total_cents': 5490000,
        }
        out = self._build(cart, {'carrier': 'Servientrega'}, contact=contact)
        assert "Cristian Tobon" in out
        assert "crittan01@gmail.com" in out
        assert "+57 312 583 5649" in out
        assert "CC 1018502222" in out
        assert "Calle 100 #15-20" in out
        assert "Apto 502" in out


# ─── P0 #4 — Envío a tercero ────────────────────────────────────────────────


class TestP04EnvioATercero:

    def setup_method(self):
        from agentic.invariants.summary_coherence import (
            _build_canonical_summary, _outbound_distinguishes_recipient,
        )
        from agentic.shipping_recipient_intent_resolver import (
            detect_recipient_intent,
        )
        self._build = _build_canonical_summary
        self._distinguishes = _outbound_distinguishes_recipient
        self._detect_intent = detect_recipient_intent

    def test_intent_es_para_mi_mama(self):
        """Intent detection — extrae al menos document + phone. Name
        depende del regex tolerante; asserts focused en datos críticos."""
        text = (
            "Hola, quiero 1 jabon coco 60g y es para mi mama: "
            "Maria Tobon, CC 51234567, Cel 3009876543"
        )
        match = self._detect_intent(text)
        assert match is not None
        assert match.document_type == "CC"
        assert match.document_number == "51234567"
        assert "3009876543" in (match.phone or "")

    def test_intent_envio_a_oficina(self):
        match = self._detect_intent("Envíalo a mi oficina, dirección Cra 50")
        assert match is not None

    def test_intent_para_mi_no_detected(self):
        match = self._detect_intent("Es para mí, quiero 3 jabones de coco")
        assert match is None

    def test_resumen_tercero_distingue_titular_receptor(self):
        contact = {
            'name': 'Cristian Tobon',
            'email': 'crittan01@gmail.com',
            'phone': '573125835649',
        }
        cart = {
            'items': [], 'subtotal_cents': 5400000,
            'shipping_cents': 1593000, 'discount_cents': 810000,
            'coupon_code': 'KAIU15', 'total_cents': 6183000,
        }
        shipping_meta = {
            'carrier': 'Coordinadora',
            'recipient': {
                'name': 'Maria Tobon',
                'phone': '+57 300 987 6543',
                'document_type': 'CC',
                'document_number': '51234567',
                'address': {
                    'street': 'Carrera 50 #20-30',
                    'neighborhood': 'Laureles',
                    'city': 'Medellín',
                    'building_type': 'casa',
                },
            },
        }
        out = self._build(cart, shipping_meta, contact=contact)
        assert "Paga (titular)" in out
        assert "Cristian Tobon" in out
        assert "Recibe (destinatario)" in out
        assert "Maria Tobon" in out
        assert "+57 300 987 6543" in out
        assert "CC 51234567" in out
        assert "Carrera 50 #20-30" in out
        assert "Medellín" in out
        # Helper detecta el patrón en el output.
        assert self._distinguishes(out) is True

    def test_resumen_sin_recipient_no_distingue(self):
        contact = {'name': 'Cristian Tobon'}
        cart = {
            'items': [], 'subtotal_cents': 1800000,
            'shipping_cents': 900000, 'discount_cents': 0,
            'total_cents': 2700000,
        }
        out = self._build(cart, {'carrier': 'Servientrega'}, contact=contact)
        assert "Paga (titular)" not in out
        assert "Recibe (destinatario)" not in out


# ─── Cascada — Empty promise sin contenido (BUG 42) ─────────────────────────


class TestBUG42EmptyPromiseDeep:
    """BUG 42 — promesa pura sin contenido (aunque tools corrieron)."""

    def setup_method(self):
        from agentic.invariants.empty_promise import (
            _is_pure_promise_without_content, _has_empty_promise,
        )
        self._is_pure = _is_pure_promise_without_content
        self._has_promise = _has_empty_promise

    def test_caso_uat_pura_promesa(self):
        text = (
            "Permíteme un momento, voy a verificar tus datos. "
            "Te confirmo en seguida."
        )
        assert self._has_promise(text) is True
        assert self._is_pure(text) is True

    def test_promesa_con_contenido_util_no_pure(self):
        # Requiere pattern de promesa real ("déjame", "permíteme", "voy a")
        # + contenido sustantivo (precio).
        text = (
            "Déjame revisar tu pedido: total $54.000 con descuento "
            "KAIU15. ¿Confirmas?"
        )
        assert self._has_promise(text) is True
        # NO es pura porque tiene precio + pregunta.
        assert self._is_pure(text) is False

    def test_lista_productos_no_pure(self):
        text = (
            "Déjame revisar opciones:\n"
            "* COORDINADORA: $15.930\n"
            "* SERVIENTREGA: $17.950\n"
            "¿Cuál prefieres?"
        )
        assert self._has_promise(text) is True
        assert self._is_pure(text) is False


# ─── Discount detector helper ───────────────────────────────────────────────


class TestOutboundDistinguishesRecipient:

    def setup_method(self):
        from agentic.invariants.summary_coherence import (
            _outbound_distinguishes_recipient,
        )
        self._distinguishes = _outbound_distinguishes_recipient

    def test_recibe_destinatario_detected(self):
        text = "Recibe (destinatario):\n* Nombre: Maria"
        assert self._distinguishes(text) is True

    def test_paga_titular_detected(self):
        text = "Paga (titular): Cristian"
        assert self._distinguishes(text) is True

    def test_solo_datos_envio_no_distinguishes(self):
        text = "Datos de envío:\n* Nombre: Cristian"
        assert self._distinguishes(text) is False


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ─── BUG 41 — Cupón rechazo enriquecido (mínimo + cuánto falta) ─────────────


class TestBUG41CouponRejectionEnriched:
    """BUG 41 — bot decía solo 'no alcanza el mínimo' sin especificar."""

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "api" / "lib"))
        from coupons import validate_coupon_applicable
        self._validate = validate_coupon_applicable
        self._coupon = {
            'id': 'x', 'code': 'KAIU15', 'discount_type': 'percent',
            'discount_value': 15, 'is_active': True,
            'min_subtotal_cents': 4000000, 'max_redemptions': 10,
            'redemptions_count': 0, 'valid_from': None, 'valid_until': None,
        }

    def test_min_no_met_message_includes_code_min_actual_falta(self):
        r = self._validate(self._coupon, subtotal_cents=1800000)
        msg = r.user_message
        assert "KAIU15" in msg
        assert "$40.000" in msg
        assert "$18.000" in msg
        assert "$22.000" in msg

    def test_min_met_returns_ok(self):
        r = self._validate(self._coupon, subtotal_cents=5400000)
        assert r.ok is True
        assert r.reason == "ok"

    def test_inactive_coupon_includes_code(self):
        c = {**self._coupon, 'code': 'PRUEBA10', 'is_active': False}
        r = self._validate(c, subtotal_cents=5400000)
        assert "PRUEBA10" in r.user_message

    def test_not_found_fallback_generic(self):
        r = self._validate({}, subtotal_cents=5400000)
        assert "no encontrado" in r.user_message.lower()


# ─── Backlog #1 — Retracto categories multi-tenant ──────────────────────────


class TestBacklog1RetractoEligibility:

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from lib.retracto import check_retracto_eligibility, format_excluded_message
        self._check = check_retracto_eligibility
        self._format = format_excluded_message

    def _mock_sb(self, items):
        class MockResult:
            def __init__(self, data): self.data = data
        class MockQuery:
            def __init__(self, items): self.items = items
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def execute(self): return MockResult(self.items)
        class MockSupabase:
            def __init__(self, items): self.items = items
            def table(self, t): return MockQuery(self.items)
        return MockSupabase(items)

    def test_kaiu_cosmetica_excluida(self):
        sb = self._mock_sb([{
            'title': 'Jabón Coco', 'quantity': 1, 'product_id': 'x',
            'products': {
                'retracto_excluded': True,
                'retracto_excluded_reason': 'cosmética uso íntimo (Art. 47 parágrafo)',
            },
        }])
        r = self._check(sb, order_id='abc', tenant_id='tkaiu')
        assert r.eligible is False
        assert len(r.excluded_items) == 1
        assert 'cosmética uso íntimo' in r.reasons[0]

    def test_tienda_tech_software_excluido(self):
        sb = self._mock_sb([{
            'title': 'License Pro', 'quantity': 1, 'product_id': 'y',
            'products': {
                'retracto_excluded': True,
                'retracto_excluded_reason': 'software descargado/activado (Art. 47 parágrafo)',
            },
        }])
        r = self._check(sb, order_id='abc', tenant_id='ttech')
        assert r.eligible is False
        assert 'software' in r.reasons[0]

    def test_textil_retracto_aplica(self):
        sb = self._mock_sb([{
            'title': 'Camiseta', 'quantity': 2, 'product_id': 'z',
            'products': {
                'retracto_excluded': False, 'retracto_excluded_reason': None,
            },
        }])
        r = self._check(sb, order_id='abc', tenant_id='ttextil')
        assert r.eligible is True
        assert r.excluded_items == []


# ─── Backlog #2 — Multi-agente per-tenant ───────────────────────────────────


class TestBacklog2MultiAgente:

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from lib.tenant_agents import get_active_agent
        self._get = get_active_agent

    def _mock_sb(self, rows):
        class MockResult:
            def __init__(self, data): self.data = data
        class MockQuery:
            def __init__(self, rows): self.rows = rows
            def select(self, *a, **k): return self
            def eq(self, *a, **k): return self
            def limit(self, *a, **k): return self
            def execute(self): return MockResult(self.rows)
        class MockSupabase:
            def __init__(self, rows): self.rows = rows
            def table(self, t): return MockQuery(self.rows)
        return MockSupabase(rows)

    def test_kaiu_sara_camila(self):
        sb = self._mock_sb([{
            'id': 'a1', 'name': 'Sara Camila', 'role': 'sales',
            'pitch': 'asesora de KAIU Living Natural',
            'tone': 'cordial español Colombia', 'is_default': True,
        }])
        a = self._get(sb, tenant_id='tkaiu')
        assert a['name'] == 'Sara Camila'
        assert 'KAIU' in a['pitch']

    def test_tienda_tech_agente_personalizado(self):
        sb = self._mock_sb([{
            'id': 'a2', 'name': 'Andrés Tech', 'role': 'support',
            'pitch': 'asesor técnico Tech X',
            'tone': 'directo profesional', 'is_default': True,
        }])
        a = self._get(sb, tenant_id='ttech')
        assert a['name'] == 'Andrés Tech'
        assert a['role'] == 'support'

    def test_tenant_sin_config_fallback(self):
        sb = self._mock_sb([])
        a = self._get(sb, tenant_id='tnoconfig')
        assert a['name'] == 'Sara Camila'  # fallback

    def test_db_error_fallback(self):
        class MockSupabaseError:
            def table(self, t):
                raise RuntimeError("relation does not exist")
        a = self._get(MockSupabaseError(), tenant_id='tx')
        assert a['name'] == 'Sara Camila'


# ─── Backlog #3 — Channel Registry pluggable ────────────────────────────────


class TestBacklog3ChannelRegistry:

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "api"))
        from lib.channels import (
            get_channel_adapter, register_channel,
            list_registered_channels, ChannelAdapter,
            InboundMessage, OutboundResult, ComplianceVerdict,
        )
        self._get = get_channel_adapter
        self._register = register_channel
        self._list = list_registered_channels
        self._Protocol = ChannelAdapter
        self._OutboundResult = OutboundResult
        self._InboundMessage = InboundMessage
        self._ComplianceVerdict = ComplianceVerdict

    def test_stubs_pre_registrados(self):
        channels = self._list()
        for required in ['whatsapp', 'meli', 'telegram', 'web', 'messenger', 'instagram']:
            assert required in channels

    def test_lookup_existente(self):
        wa = self._get("whatsapp")
        assert wa is not None
        assert wa.channel_name() == "whatsapp"

    def test_lookup_case_insensitive(self):
        wa = self._get("WhatsApp")
        assert wa is not None

    def test_lookup_no_registrado(self):
        assert self._get("tiktok") is None

    def test_custom_adapter_sobreescribe_stub(self):
        OutboundResult = self._OutboundResult
        InboundMessage = self._InboundMessage
        ComplianceVerdict = self._ComplianceVerdict

        class WebAdapter:
            def channel_name(self): return "web"
            def parse_inbound(self, payload):
                return InboundMessage(
                    channel="web", tenant_id=payload["tenant_id"],
                    external_message_id=payload["msg_id"],
                    sender_id=payload["session"],
                    content=payload.get("text", ""),
                )
            async def send_outbound(self, **kwargs):
                return OutboundResult(ok=True, external_message_id="web-123")
            def verify_signature(self, **kwargs): return True
            async def compliance_check(self, **kwargs):
                return ComplianceVerdict(ok=True)

        custom = WebAdapter()
        assert isinstance(custom, self._Protocol)
        self._register("web", custom)
        assert self._get("web").channel_name() == "web"


# ─── Auditoría arquitectónica + ADR-0017 Multi-agent ────────────────────────


class TestAuditNoHardcodedVertical:
    """Audit fix — system_prompt no asume vertical (multi-vertical agnóstico)."""

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from agentic.system_prompt import build_system_prompt, _render_philosophy_block
        self._build = build_system_prompt
        self._philosophy = _render_philosophy_block

    def test_default_pitch_no_asume_cosmetica(self):
        # Tenant sin pitch ni philosophy — bot NO debe decir cosmética.
        prompt = self._build(
            tenant_name="Tech X",
            tenant_pitch=None,
            tenant_business_pitch=None,
            tenant_tone=None,
            agent_name="Carolina Tech",
        )
        assert "cosmética" not in prompt.lower()
        assert "artesanal natural" not in prompt.lower()
        # Debe usar fallback agnóstico.
        assert "Tech X" in prompt
        assert "Carolina Tech" in prompt

    def test_pitch_custom_es_respetado(self):
        prompt = self._build(
            tenant_name="Tech X",
            tenant_pitch=None,
            tenant_business_pitch="soluciones de software B2B",
            tenant_tone=None,
            agent_name="Carolina",
        )
        assert "soluciones de software B2B" in prompt
        assert "cosmética" not in prompt.lower()

    def test_philosophy_se_inyecta(self):
        block = self._philosophy({
            "mision": "Llevar tecnología al alcance de PyMEs colombianas.",
            "vision": "Ser el SaaS líder en LATAM.",
            "valores": "Innovación, eficiencia, soporte",
        })
        assert "Misión" in block
        assert "Visión" in block
        assert "Valores" in block
        assert "Llevar tecnología" in block

    def test_philosophy_vacia_retorna_vacio(self):
        assert self._philosophy(None) == ""
        assert self._philosophy({}) == ""
        assert self._philosophy({"mision": "", "vision": "", "valores": ""}) == ""


class TestADR0017AgentTemplates:
    """ADR-0017 — templates por rol."""

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from lib.agent_templates import (
            AGENT_TEMPLATES, get_template, render_skeleton, list_roles, is_valid_role,
        )
        self._TEMPLATES = AGENT_TEMPLATES
        self._get = get_template
        self._render = render_skeleton
        self._list = list_roles
        self._valid = is_valid_role

    def test_5_roles_canonicos(self):
        assert set(self._list()) == {"sales", "support", "marketing", "claims", "custom"}

    def test_sales_tools_incluye_add_to_cart(self):
        t = self._get("sales")
        assert "add_to_cart" in (t.get("tools_allowed") or [])
        assert "generate_payment_link" in (t.get("tools_allowed") or [])

    def test_support_no_tiene_add_to_cart(self):
        t = self._get("support")
        tools = t.get("tools_allowed") or []
        assert "add_to_cart" not in tools
        assert "generate_payment_link" not in tools
        # Support sí puede leer + escalar.
        assert "get_recent_orders" in tools
        assert "escalate_to_human" in tools

    def test_render_skeleton_inyecta_name_tenant(self):
        out = self._render("sales", agent_name="Sara Camila", tenant_name="KAIU")
        assert "Sara Camila" in out
        assert "KAIU" in out

    def test_role_invalido_fallback_custom(self):
        t = self._get("inexistente_xyz")
        assert t == self._TEMPLATES["custom"]

    def test_is_valid_role(self):
        assert self._valid("sales") is True
        assert self._valid("invalid") is False


class TestADR0017AgentRouter:
    """ADR-0017 — router pre-LLM clasificador."""

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from agentic.agent_router import (
            classify_intent_to_role, select_agent_for_inbound,
        )
        self._classify = classify_intent_to_role
        self._select = select_agent_for_inbound

    def test_claims_keyword_detected(self):
        assert self._classify("Quiero reclamar mi pedido") == "claims"
        assert self._classify("El producto vino defectuoso") == "claims"
        assert self._classify("Quiero retracto") == "claims"
        assert self._classify("No me llegó el envío") == "claims"

    def test_support_keyword_detected(self):
        assert self._classify("¿Dónde está mi pedido?") == "support"
        assert self._classify("Quiero tracking") == "support"
        assert self._classify("¿Cuándo llega?") == "support"

    def test_marketing_keyword_detected(self):
        assert self._classify("¿Tienen promo?") == "marketing"
        assert self._classify("¿Hay descuento?") == "marketing"

    def test_default_sales(self):
        assert self._classify("Quiero comprar 1 jabón") == "sales"
        assert self._classify("Hola") == "sales"

    def test_select_single_agent_backward_compat(self):
        agents = [{"name": "Sara Camila", "role": "sales", "is_default": True}]
        result = self._select(inbound_text="Hola", agents=agents)
        assert result["name"] == "Sara Camila"

    def test_select_multi_routes_to_support(self):
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Andrés", "role": "support", "is_default": False},
        ]
        result = self._select(
            inbound_text="¿Dónde está mi pedido?", agents=agents,
        )
        assert result["name"] == "Andrés"

    def test_select_fallback_to_default_if_no_match(self):
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Andrés", "role": "support", "is_default": False},
        ]
        # No hay agente de marketing → fallback al default Sara.
        result = self._select(
            inbound_text="¿Hay promo?", agents=agents,
        )
        assert result["name"] == "Sara"

    def test_select_empty_agents_safe_fallback(self):
        result = self._select(inbound_text="Hola", agents=[])
        assert result["name"] == "Sara Camila"  # defensive default
