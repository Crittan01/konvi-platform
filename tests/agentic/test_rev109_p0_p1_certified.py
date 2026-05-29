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
