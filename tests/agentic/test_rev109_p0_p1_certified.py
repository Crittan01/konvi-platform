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


# ─── Aterrizaje multi-agente: matriz comportamiento por #agentes ──────────


class TestMultiAgentFallback:
    """Decisión 1 (A): default absorbe lo que no tiene rol especialista.
    Decisión 3 (B): router clasifica per-turn, re-enruta silenciosamente.

    4 escenarios de configuración del tenant + verifica garantía:
    cada mensaje SIEMPRE recibe un agente (default o especialista).
    """

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from agentic.agent_router import select_agent_for_inbound
        self._select = select_agent_for_inbound

    def test_caso_1_solo_default_recibe_todo(self):
        """Tenant con solo Sara Ventas. Sara recibe ventas/soporte/reclamos/marketing."""
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
        ]
        # Ventas → Sara
        assert self._select(inbound_text="quiero comprar jabón", agents=agents)["name"] == "Sara"
        # Soporte → Sara (no hay especialista)
        assert self._select(inbound_text="¿dónde está mi pedido?", agents=agents)["name"] == "Sara"
        # Reclamos → Sara
        assert self._select(inbound_text="vino defectuoso", agents=agents)["name"] == "Sara"
        # Marketing → Sara
        assert self._select(inbound_text="tienen promo?", agents=agents)["name"] == "Sara"

    def test_caso_2_default_mas_soporte(self):
        """Sara (default) + Andrés (support). Reclamos y marketing caen en Sara."""
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Andrés", "role": "support", "is_default": False},
        ]
        assert self._select(inbound_text="quiero comprar", agents=agents)["name"] == "Sara"
        assert self._select(inbound_text="tracking", agents=agents)["name"] == "Andrés"
        # Reclamos: no hay Carolina → cae al default (Sara)
        assert self._select(inbound_text="vino defectuoso", agents=agents)["name"] == "Sara"
        # Marketing: no hay → default Sara
        assert self._select(inbound_text="hay promo?", agents=agents)["name"] == "Sara"

    def test_caso_3_default_mas_reclamos(self):
        """Sara (default) + Carolina (claims). Soporte y marketing caen en Sara."""
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Carolina", "role": "claims", "is_default": False},
        ]
        assert self._select(inbound_text="comprar 2 jabones", agents=agents)["name"] == "Sara"
        # Tracking: no hay Andrés → default Sara
        assert self._select(inbound_text="dónde está mi pedido", agents=agents)["name"] == "Sara"
        # Reclamo: Carolina
        assert self._select(inbound_text="vino defectuoso", agents=agents)["name"] == "Carolina"
        assert self._select(inbound_text="quiero retracto", agents=agents)["name"] == "Carolina"

    def test_caso_4_los_4_roles_matriz_completa(self):
        """Cobertura total: cada intent va a su especialista."""
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Andrés", "role": "support", "is_default": False},
            {"name": "María", "role": "marketing", "is_default": False},
            {"name": "Carolina", "role": "claims", "is_default": False},
        ]
        assert self._select(inbound_text="quiero comprar", agents=agents)["name"] == "Sara"
        assert self._select(inbound_text="dónde está mi pedido", agents=agents)["name"] == "Andrés"
        assert self._select(inbound_text="hay promo?", agents=agents)["name"] == "María"
        assert self._select(inbound_text="vino defectuoso", agents=agents)["name"] == "Carolina"

    def test_router_per_turn_no_per_conversation(self):
        """Decisión 3 — el router clasifica CADA mensaje, no por sesión.
        Si el cliente cambia de tema, el agente cambia silenciosamente."""
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Andrés", "role": "support", "is_default": False},
        ]
        # Turno 1: cliente quiere comprar → Sara
        t1 = self._select(inbound_text="quiero 1 jabón coco", agents=agents)
        assert t1["name"] == "Sara"
        # Turno 2: cliente pregunta tracking (cambió tema) → Andrés
        t2 = self._select(inbound_text="¿dónde está mi pedido?", agents=agents)
        assert t2["name"] == "Andrés"
        # Turno 3: vuelve a compras → Sara de nuevo
        t3 = self._select(inbound_text="agrega otro jabón", agents=agents)
        assert t3["name"] == "Sara"

    def test_fallback_for_roles_default_4_roles_backward_compat(self):
        # Default seedeado con los 4 roles → comportamiento previo:
        # cualquier role no-especialista cae al default (NO handoff).
        from agentic.agent_router import select_agent_for_inbound
        agents = [
            {
                "name": "Sara", "role": "sales", "is_default": True,
                "fallback_for_roles": [
                    "sales", "support", "marketing", "claims",
                ],
            },
            {"name": "Lucy", "role": "support", "is_default": False},
        ]
        # Inbound de claims (no hay especialista) → Sara con 4 roles cubre.
        chosen = select_agent_for_inbound(
            inbound_text="vino defectuoso quiero garantía", agents=agents,
        )
        assert chosen["name"] == "Sara"
        assert not chosen.get("_needs_human_handoff")

    def test_fallback_for_roles_excluye_claims_dispara_handoff(self):
        # Operador desmarcó "claims" del default → handoff humano para
        # reclamos (escalación legal consciente, no LLM).
        from agentic.agent_router import select_agent_for_inbound
        agents = [
            {
                "name": "Sara", "role": "sales", "is_default": True,
                "fallback_for_roles": ["sales", "support", "marketing"],
            },
            {"name": "Lucy", "role": "support", "is_default": False},
        ]
        chosen = select_agent_for_inbound(
            inbound_text="quiero devolución el producto llegó dañado",
            agents=agents,
        )
        assert chosen["_needs_human_handoff"] is True
        assert chosen["name"] == "Asistente"
        assert chosen["tools_allowed"] == []  # bloqueado de tools

    def test_fallback_for_roles_especialista_existe_no_dispara_handoff(self):
        # Si HAY especialista, fallback_for_roles es irrelevante.
        # El especialista atiende su role sin consultar fallback.
        from agentic.agent_router import select_agent_for_inbound
        agents = [
            {
                "name": "Sara", "role": "sales", "is_default": True,
                "fallback_for_roles": [],  # default no cubre nada
            },
            {"name": "Carlos", "role": "claims", "is_default": False},
        ]
        chosen = select_agent_for_inbound(
            inbound_text="quiero devolución urgente", agents=agents,
        )
        assert chosen["name"] == "Carlos"
        assert not chosen.get("_needs_human_handoff")

    def test_coupons_block_lista_cupones_activos(self):
        # Bug A.0.1 UAT 2026-05-28: agente afirmaba "no hay promos" sin
        # consultar DB. Fix: inyectar cupones al system prompt + regla
        # anti-hallu. Test verifica que cupones reales lleguen al prompt.
        from agentic.system_prompt import build_system_prompt
        coupons = [
            {
                "code": "KAIU15", "discount_type": "percent",
                "discount_value": 15, "max_redemptions": 10,
                "redemptions_count": 0, "valid_until": "2026-06-27 11:56:20",
            },
        ]
        prompt = build_system_prompt(
            tenant_name="KAIU", catalog=[], contact_record={},
            active_coupons=coupons,
        )
        assert "CUPONES ACTIVOS DEL TENANT" in prompt
        assert "**KAIU15**" in prompt
        assert "15% de descuento" in prompt
        assert "10 usos disponibles" in prompt
        assert "vigente hasta 2026-06-27" in prompt
        # Regla anti-hallu presente
        assert "NUNCA inventes códigos" in prompt
        assert "Si NO está listado arriba, NO existe" in prompt

    def test_coupons_block_sin_cupones_responde_honestamente(self):
        from agentic.system_prompt import build_system_prompt
        prompt = build_system_prompt(
            tenant_name="KAIU", catalog=[], contact_record={},
            active_coupons=[],
        )
        # Sin cupones: regla explícita NO inventar
        assert "ninguno hoy" in prompt
        assert "NO inventes códigos" in prompt

    def test_coupons_block_renderiza_tipo_fixed_amount(self):
        from agentic.system_prompt import build_system_prompt
        prompt = build_system_prompt(
            tenant_name="KAIU", catalog=[], contact_record={},
            active_coupons=[{
                "code": "PROMO5K", "discount_type": "fixed_amount",
                "discount_value": 500000, "valid_until": "2026-12-31",
            }],
        )
        assert "**PROMO5K**" in prompt
        # 500000 cents = $5.000 COP
        assert "$5.000 COP de descuento" in prompt

    def test_coupons_block_renderiza_free_shipping(self):
        from agentic.system_prompt import build_system_prompt
        prompt = build_system_prompt(
            tenant_name="KAIU", catalog=[], contact_record={},
            active_coupons=[{
                "code": "FREESHIP", "discount_type": "free_shipping",
                "valid_until": "2026-12-31",
            }],
        )
        assert "**FREESHIP**" in prompt
        assert "envío gratis" in prompt

    def test_dispatcher_skip_opted_out_placeholder(self):
        # placeholder reordering
        pass


import asyncio


class TestFakeEscalationInvariant:
    """Fix founder 2026-05-28 "super delicado" — LLM dice promesa de
    escalación sin invocar tool → cliente queda sin atención. Invariant
    detecta y fuerza el side-effect real."""

    def test_fake_escalation_detect_phrases(self):
        # Fix founder 2026-05-28 "super delicado": LLM dice "te paso con
        # un especialista" sin invocar escalate_to_human → fake escalation.
        from agentic.invariants.fake_escalation import detects_escalation_promise
        # Variantes que debe detectar
        assert detects_escalation_promise("Te paso con un especialista") is True
        assert detects_escalation_promise("te conecto con mi equipo") is True
        assert detects_escalation_promise("Voy a escalar tu caso") is True
        assert detects_escalation_promise("Debo escalar esto urgente") is True
        assert detects_escalation_promise(
            "Lo mejor es que un especialista te ayude con esto"
        ) is True
        assert detects_escalation_promise(
            "Mi equipo se contactará contigo pronto"
        ) is True
        assert detects_escalation_promise(
            "Te contactará un asesor"
        ) is True
        # Frases inocentes que NO deben matchear (info producto, etc.)
        assert detects_escalation_promise(
            "Nuestro jabón es excelente para piel sensible"
        ) is False
        assert detects_escalation_promise(
            "Tu pedido va en camino, llegará mañana"
        ) is False

    def test_fake_escalation_invariant_forces_real_escalation(self):
        return asyncio.run(self._test_invariant_forces_real_escalation())

    async def _test_invariant_forces_real_escalation(self):
        # Si el LLM promete escalación PERO no llamó el tool, el invariant
        # debe (a) ejecutar el update real de status, (b) preservar el texto
        # (la promesa ahora es válida porque el side-effect ocurrió).
        from agentic.invariants.fake_escalation import FakeEscalationInvariant
        from agentic.invariants.base import InvariantOutcome

        captured_updates = []

        class FakeQuery:
            def __init__(self, store, table_name):
                self._store = store
                self._table = table_name
                self._payload = None
            def update(self, payload):
                self._payload = payload
                return self
            def insert(self, payload):
                self._payload = payload
                self._store.append(("insert", self._table, payload))
                return self
            def eq(self, *args, **kwargs):
                return self
            def execute(self):
                if self._payload is not None and not any(
                    e[0] == "insert" for e in self._store
                ) or self._payload and "status" in self._payload:
                    self._store.append(("update", self._table, self._payload))
                return type("R", (), {"data": [{"id": "fake"}]})()

        class FakeSupabase:
            def __init__(self, store):
                self._store = store
            def table(self, name):
                return FakeQuery(self._store, name)

        inv = FakeEscalationInvariant()
        result = await inv.validate(
            candidate_text="Te paso con un especialista de mi equipo.",
            tenant_id="0fb0777e-aaaa-bbbb-cccc-dddddddddddd",
            conversation_id="abc12345-0000-0000-0000-000000000000",
            contact_id=None,
            supabase=FakeSupabase(captured_updates),
            tool_call_log=[],  # crucial: LLM NO llamó escalate_to_human
        )
        # Invariant pasa OK pero ejecutó el side-effect
        assert result.outcome == InvariantOutcome.OK
        assert result.invariant_name == "fake_escalation"
        # Verificar que llamó update con status='human_takeover'
        update_calls = [c for c in captured_updates if c[0] == "update"]
        assert len(update_calls) >= 1
        assert update_calls[0][1] == "conversations"
        assert update_calls[0][2].get("status") == "human_takeover"

    def test_fake_escalation_skips_if_tool_invoked(self):
        return asyncio.run(self._test_skips_if_tool_invoked())

    async def _test_skips_if_tool_invoked(self):
        # Si el LLM SÍ invocó escalate_to_human, el invariant no debe
        # ejecutar side-effect duplicado.
        from agentic.invariants.fake_escalation import FakeEscalationInvariant
        from agentic.invariants.base import InvariantOutcome

        captured = []

        class FakeSupabase:
            def table(self, name):
                captured.append(name)
                return self
            def update(self, *a, **kw): return self
            def insert(self, *a, **kw): return self
            def eq(self, *a, **kw): return self
            def execute(self):
                return type("R", (), {"data": []})()

        result = await FakeEscalationInvariant().validate(
            candidate_text="Te conecto con un especialista.",
            tenant_id="t1", conversation_id="c1", contact_id=None,
            supabase=FakeSupabase(),
            tool_call_log=[{"tool": "escalate_to_human", "success": True}],
        )
        assert result.outcome == InvariantOutcome.OK
        # NO debió tocar DB (tool ya hizo el side-effect)
        assert len(captured) == 0

    def test_fake_escalation_skips_if_no_promise(self):
        return asyncio.run(self._test_skips_if_no_promise())

    async def _test_skips_if_no_promise(self):
        # Si el outbound no contiene frase de escalación, OK sin tocar DB.
        from agentic.invariants.fake_escalation import FakeEscalationInvariant
        from agentic.invariants.base import InvariantOutcome

        class FakeSupabase:
            def table(self, name):
                raise AssertionError("DB no debe ser tocada")

        result = await FakeEscalationInvariant().validate(
            candidate_text="Tu jabón de coco cuesta $24.000.",
            tenant_id="t1", conversation_id="c1", contact_id=None,
            supabase=FakeSupabase(),
            tool_call_log=[],
        )
        assert result.outcome == InvariantOutcome.OK


class TestClaimsTools:
    """Rev. 109 founder 2026-05-28 — tool `create_claim` cierra el gap
    del agente Reclamos. Antes solo escalaba; ahora registra ticket +
    notifica + le da al cliente número de referencia."""

    def test_create_claim_tool_registered(self):
        import sys
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        # Asegura módulo cargado
        import agentic.tools.claims  # noqa
        from agentic.tools.registry import _TOOLS
        assert "create_claim" in _TOOLS
        assert "get_claim_status" in _TOOLS

    def test_create_claim_args_schema(self):
        from agentic.tools.claims import CreateClaimArgs
        # Válido
        args = CreateClaimArgs(order_id="abc-uuid", reason="producto dañado")
        assert args.order_id == "abc-uuid"
        assert args.requested_amount is None
        # Con monto
        args2 = CreateClaimArgs(
            order_id="x", reason="defectuoso", requested_amount=50000,
        )
        assert args2.requested_amount == 50000

    def test_create_claim_args_validation_reason_too_short(self):
        import pytest
        from agentic.tools.claims import CreateClaimArgs
        with pytest.raises(Exception):  # ValidationError
            CreateClaimArgs(order_id="x", reason="ab")  # min_length=3

    def test_get_claim_status_args_schema(self):
        from agentic.tools.claims import GetClaimStatusArgs
        args = GetClaimStatusArgs(ticket_number=42)
        assert args.ticket_number == 42

    def test_get_claim_status_args_rejects_negative(self):
        import pytest
        from agentic.tools.claims import GetClaimStatusArgs
        with pytest.raises(Exception):
            GetClaimStatusArgs(ticket_number=0)  # ge=1

    def test_create_claim_tool_returns_failure_when_order_not_found(self):
        import asyncio
        from agentic.tools.base import ToolContext
        from agentic.tools.claims import CreateClaimTool, CreateClaimArgs

        class FakeQuery:
            def __init__(self):
                self.data = []
            def select(self, *_): return self
            def eq(self, *_): return self
            def limit(self, *_): return self
            def execute(self):
                return type("R", (), {"data": []})()

        class FakeSupabase:
            def table(self, name):
                return FakeQuery()

        ctx = ToolContext(
            tenant_id="t1", conversation_id="c1", contact_id="ct1",
            supabase=FakeSupabase(),
        )
        args = CreateClaimArgs(
            order_id="non-existent", reason="producto dañado",
        )
        result = asyncio.run(CreateClaimTool().execute(args, ctx))
        assert result.success is False
        assert result.data["code"] == "CLAIM_ORDER_NOT_FOUND"

    def test_claims_role_template_includes_create_claim_tool(self):
        from lib.agent_templates import get_template
        claims = get_template("claims")
        assert "create_claim" in (claims.get("tools_allowed") or [])
        assert "get_claim_status" in (claims.get("tools_allowed") or [])
        # Mantiene escalate_to_human para casos complejos
        assert "escalate_to_human" in (claims.get("tools_allowed") or [])

    def test_sales_role_can_also_create_claim(self):
        # Ventas también: si el cliente reporta reclamo en medio de
        # compra, evitamos handoff cruzando a Carolina.
        from lib.agent_templates import get_template
        sales = get_template("sales")
        assert "create_claim" in (sales.get("tools_allowed") or [])

    def test_claims_skeleton_mentions_create_claim(self):
        # Skeleton actualizado: ya NO dice "siempre escala". Ahora
        # instruye usar create_claim ANTES de escalar.
        from lib.agent_templates import _CLAIMS_SKELETON
        assert "create_claim" in _CLAIMS_SKELETON
        assert "get_claim_status" in _CLAIMS_SKELETON
        # Y el escalado queda condicional (no "SIEMPRE")
        assert "SIEMPRE escala al operador humano" not in _CLAIMS_SKELETON


class TestNotificationSourceUnified:
    """Rev. 109 founder 2026-05-28 — unificar canales. notify_escalation_async
    ahora lee de `notification_settings` (no `tenant_integrations`).
    Single source of truth con dispatch_human_takeover_event."""

    def test_notify_uses_notification_settings_not_tenant_integrations(self):
        import sys
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        if "telegram_notifications" in sys.modules:
            del sys.modules["telegram_notifications"]
        import inspect
        from telegram_notifications import notify_escalation_async
        source = inspect.getsource(notify_escalation_async)
        # Lee de notification_settings
        assert "notification_settings" in source
        # NO debe leer de tenant_integrations (path A deprecado)
        assert "tenant_integrations" not in source


class TestHumanTakeoverSLA:
    """Fix founder 2026-05-28 — SLA tracker: si el bot escala y nadie
    responde en X horas, alerta operador. Cierra el loop "super delicado"."""

    def test_sla_constants_configurable_via_env(self):
        # Constantes deben estar definidas y ser configurables.
        import importlib
        import sys
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        if "worker" in sys.modules:
            del sys.modules["worker"]
        worker = importlib.import_module("worker")
        # Valores default razonables
        assert worker.HUMAN_TAKEOVER_SLA_HOURS >= 1
        assert worker.HUMAN_TAKEOVER_SLA_HOURS <= 24
        assert worker.HUMAN_TAKEOVER_SLA_CHECK_INTERVAL_SECONDS >= 60

    def test_sla_method_registered_in_poll_cycle(self):
        # _check_human_takeover_sla_if_due debe estar en la clase y ser
        # invocado en _poll_cycle.
        import sys, inspect
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        if "worker" in sys.modules:
            import importlib
            importlib.reload(sys.modules["worker"])
        from worker import OrchestratorWorker
        assert hasattr(OrchestratorWorker, "_check_human_takeover_sla_if_due")
        # Verifica que el método se invoca en _poll_cycle
        source = inspect.getsource(OrchestratorWorker._poll_cycle)
        assert "_check_human_takeover_sla_if_due" in source


class TestOptOutGate:
    """Fix founder 2026-05-28 — opt-out EN CUALQUIER SITUACIÓN +
    tests adicionales (cupones block, fallback_for_roles edge cases,
    multi-agent caso 0) que requieren select_agent_for_inbound."""

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "ai-orchestrator"))
        from agentic.agent_router import select_agent_for_inbound
        self._select = select_agent_for_inbound

    def test_dispatcher_skip_opted_out_conversation(self):
        # El dispatcher debe skipear conv en opted_out (Habeas Data Ley
        # 1581 ART. 9), incluso si el mensaje del cliente no es STOP.
        from agentic.dispatcher import _SKIP_STATUSES
        assert "opted_out" in _SKIP_STATUSES
        assert "human_takeover" in _SKIP_STATUSES
        assert "closed" in _SKIP_STATUSES

    def test_dispatcher_should_skip_opted_out_returns_true(self):
        from agentic.dispatcher import _should_skip_for_conv_status

        class FakeRes:
            def __init__(self, data): self.data = data

        class FakeTable:
            def __init__(self, status):
                self._status = status
            def select(self, *_): return self
            def eq(self, *_): return self
            def limit(self, *_): return self
            def execute(self):
                return FakeRes([{"status": self._status}])

        class FakeSupabase:
            def __init__(self, status):
                self._status = status
            def table(self, name):
                return FakeTable(self._status)

        # opted_out → skip TRUE (lo que el founder pidió "en cualquier situación")
        assert _should_skip_for_conv_status(FakeSupabase("opted_out"), "any-uuid") is True
        # human_takeover, closed → skip TRUE (pre-existente)
        assert _should_skip_for_conv_status(FakeSupabase("human_takeover"), "any-uuid") is True
        assert _should_skip_for_conv_status(FakeSupabase("closed"), "any-uuid") is True
        # bot_active → skip FALSE (bot procesa)
        assert _should_skip_for_conv_status(FakeSupabase("bot_active"), "any-uuid") is False

    def test_coupons_block_min_subtotal_se_muestra(self):
        from agentic.system_prompt import build_system_prompt
        prompt = build_system_prompt(
            tenant_name="KAIU", catalog=[], contact_record={},
            active_coupons=[{
                "code": "BIG20", "discount_type": "percent",
                "discount_value": 20, "min_subtotal_cents": 10000000,
                "valid_until": "2026-12-31",
            }],
        )
        # 10000000 cents = $100.000 COP
        assert "compra mínima $100.000 COP" in prompt

    def test_fallback_for_roles_none_tratado_como_4_roles(self):
        # Backward-compat 100%: agente sin fallback_for_roles (None/missing)
        # se trata como "cubre los 4 roles" — comportamiento pre-migration.
        from agentic.agent_router import select_agent_for_inbound
        agents = [
            {"name": "Sara", "role": "sales", "is_default": True},
            {"name": "Lucy", "role": "support", "is_default": False},
        ]
        chosen = select_agent_for_inbound(
            inbound_text="cupón black friday descuento", agents=agents,
        )
        assert chosen["name"] == "Sara"
        assert not chosen.get("_needs_human_handoff")

    def test_caso_0_agentes_safe_fallback_sara_camila(self):
        """Edge case — tenant sin agentes (no debería pasar pero defensivo)."""
        result = self._select(inbound_text="hola", agents=[])
        assert result["name"] == "Sara Camila"  # hardcoded backward-compat
        assert result["is_default"] is True


# ─── Normalización line wraps (UX prompt sugerido) ──────────────────────────


class TestNormalizeLineWraps:
    """Founder UAT: la IA wrappa líneas a 60-70 chars rompiendo oraciones.
    Normalizamos: \\n\\n preservado, \\n+bullet preservado, \\n simple → espacio."""

    def setup_method(self):
        sys.path.insert(0, str(_ROOT / "services" / "api"))
        from routers.ai_agents import _normalize_line_wraps
        self._norm = _normalize_line_wraps

    def test_oracion_partida_se_une(self):
        text = "Eres Andres, especialista en soporte de\nKAIU Living Natural."
        out = self._norm(text)
        assert "soporte de KAIU" in out
        assert "\n" not in out

    def test_separador_parrafo_preservado(self):
        text = "Primer parrafo.\n\nSegundo parrafo."
        out = self._norm(text)
        assert "\n\n" in out

    def test_bullet_preservado(self):
        text = "Reglas:\n• Primera regla\n• Segunda regla"
        out = self._norm(text)
        assert "\n• Primera" in out
        assert "\n• Segunda" in out

    def test_bullet_con_wrap_se_pega(self):
        # Bullet wrappa a la siguiente línea SIN bullet → pegar al bullet
        text = "• Cuando hay problema, valida en el\n  sistema."
        out = self._norm(text)
        assert "valida en el sistema" in out

    def test_numero_lista_preservado(self):
        text = "Pasos:\n1. Primero\n2. Segundo"
        out = self._norm(text)
        assert "\n1. Primero" in out
        assert "\n2. Segundo" in out

    def test_texto_vacio_safe(self):
        assert self._norm("") == ""
        assert self._norm(None) is None


class TestAgentPersonaInjection:
    """Rev. 109 ADR-0017 — el role_description custom del agente activo
    DEBE inyectarse al system prompt cuando viene seteado.

    Cierra gap arquitectónico detectado en cert post-deploy: build_system_prompt
    recibía agent_name (Lucy) pero no su role_description, así Lucy se
    identificaba como Lucy pero pensaba como Sara monolítica. Multi-agente
    solo funciona end-to-end si CADA agente lleva su prompt maestro al runtime.
    """

    def _build(self, *, role_description=None, agent_name="Lucy"):
        from agentic.system_prompt import build_system_prompt
        return build_system_prompt(
            tenant_name="KAIU",
            agent_name=agent_name,
            agent_role_description=role_description,
            catalog=[],
            contact_record={},
        )

    def test_role_description_se_inyecta_al_prompt(self):
        custom = (
            "Eres especialista en soporte post-venta. Resuelve tracking y "
            "dudas de envío. Si el cliente quiere comprar, escala al agente "
            "de ventas con un handoff cordial."
        )
        prompt = self._build(role_description=custom)
        # Identidad del agente
        assert "Eres Lucy" in prompt
        # Persona block header
        assert "PERSONALIDAD Y COMPORTAMIENTO DEL AGENTE" in prompt
        # Contenido custom literal — no debe perderse
        assert "soporte post-venta" in prompt
        assert "escala al agente" in prompt

    def test_role_description_vacio_no_inyecta_bloque(self):
        # Backward-compat: agente sin prompt custom (legacy Sara Camila pre-rev109)
        prompt = self._build(role_description=None, agent_name="Sara Camila")
        assert "PERSONALIDAD Y COMPORTAMIENTO DEL AGENTE" not in prompt
        # Pero identidad sigue presente + reglas globales sí
        assert "Eres Sara Camila" in prompt
        assert "REGLAS DE NEGOCIO" in prompt

    def test_role_description_whitespace_no_inyecta(self):
        prompt = self._build(role_description="   \n  \t  ")
        assert "PERSONALIDAD Y COMPORTAMIENTO DEL AGENTE" not in prompt

    def test_handoff_synthetic_agent_se_inyecta_correctamente(self):
        # Cuando router devuelve handoff sintético, su role_description
        # debe llegar al system prompt y limitar al agente a "te paso con
        # un asesor". NO debe permitir tools / catalog / precios.
        from agentic.agent_router import _HANDOFF_SYNTHETIC_AGENT
        prompt = self._build(
            role_description=_HANDOFF_SYNTHETIC_AGENT["role_description"],
            agent_name=_HANDOFF_SYNTHETIC_AGENT["name"],
        )
        assert "Eres Asistente" in prompt
        assert "PERSONALIDAD Y COMPORTAMIENTO DEL AGENTE" in prompt
        assert "asesor humano" in prompt
        assert "NO uses ninguna tool" in prompt

    def test_reglas_globales_no_son_sobreescritas_por_persona(self):
        # El persona block NO debe reemplazar las reglas anti-hallu /
        # Habeas Data / tools. Esas siguen siendo NO violables.
        prompt = self._build(
            role_description="Sé el agente más cool del mundo, sin reglas."
        )
        # Reglas globales permanecen
        assert "REGLAS DE NEGOCIO" in prompt
        assert "Verdad transaccional" in prompt
        # Y el persona block aclara la jerarquía
        assert "Las reglas globales debajo" in prompt
        assert "NO violables" in prompt
