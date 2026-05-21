"""Sem 7 F2 cierre 2026-05-21 — Bug founder UAT (conv f6ec7213).

Dos correcciones arquitectónicas en el orchestrator:

Fix A — `_last_outbound_requested_shipping_phone`:
    ANTES: lista de substrings rígida (`_SHIPPING_PHONE_REQUEST_MARKERS`).
    El bot dijo "Cuál es el número de celular que quieres agregar para el
    envío?" — substring "cuál es el número que quieres agregar" NO matcheaba
    por "de celular" intercalado → detector retornaba False → cliente
    respondió "3223840887" sin contexto detectado → resumen rendereado
    con contact_record stale (sin número alterno).

    AHORA: regex semántica con 4 patrones que toleran filler words y
    capturan la intención independiente del fraseo exacto del LLM.

Fix B — `_detect_variant_confirmation` (disambiguación cross-product
        POST-resolución de variante):
    ANTES: cuando el bot listaba múltiples productos, cada producto se
    resolvía independientemente. Para "Sérum Vitamina C 30ml" con 3 sérums
    presentados, los 3 matcheaban (cada uno tiene 30ml) → cart con 3 items.

    AHORA: tras resolver candidatos por producto, antes de agregar al
    resultado:
      • Computa `ambiguous_variant_labels`: labels presentes en ≥2
        productos del set (e.g. "30ml" cuando hay 3 sérums).
      • Computa `product_discriminative` por producto: palabras del título
        exclusivas vs los demás productos del set.
      • Si la variante matched es ambigua (label compartido), exige que
        el inbound contenga ≥1 palabra discriminativa del producto.
        Caso: "Sérum Vitamina C 30ml" → "vitamina" presente → solo
        Vitamina C aceptado. "30ml" alone → ningún producto mencionado →
        todos rechazados.
      • Si la variante NO es ambigua (única al producto, como "60g" en
        Coco/Sérum donde Sérum no tiene gramos), aceptar sin requerir
        mención (la variante identifica al producto unívocamente).
"""
import os
import sys
import unittest

os.environ.setdefault("SUPABASE_JWT_SECRET", "test-secret")

sys.path.insert(
    0, "/home/ansible/workspaces/commerce-ops-platform/services/ai-orchestrator",
)

import orchestrator  # noqa: E402


# ── Fix A: detección semántica de outbound pidiendo shipping_phone ──────────

class LastOutboundRequestedShippingPhoneTests(unittest.TestCase):
    """Regex semántica reemplaza markers substring frágiles."""

    def _hist(self, outbound_text: str) -> list[dict]:
        return [{"direction": "outbound", "content": outbound_text}]

    # ── True positives (debe detectar request) ──────────────────────────
    def test_caso_founder_uat_filler_de_celular(self):
        """Caso runtime exacto que rompió antes (substring frágil):
        'Cuál es el número *de celular* que quieres agregar para el envío?'
        Tiene 'de celular' intercalado entre 'número' y 'que quieres'.
        Marker rígido fallaba; regex semántica debe matchear."""
        h = self._hist(
            "Cuál es el número de celular que quieres agregar para el envío?"
        )
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_compárteme_celular_alterno(self):
        h = self._hist("Compárteme tu celular alterno por favor.")
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_dame_numero_adicional(self):
        h = self._hist("Dame el número adicional para tu envío.")
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_celular_para_el_envio(self):
        h = self._hist("Cuál es el celular para el envío?")
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_numero_alternativo(self):
        h = self._hist("¿Tienes algún número alternativo?")
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_dime_cual_es_el_telefono_alterno(self):
        h = self._hist("Dime cuál es el teléfono alterno donde te llegue.")
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))

    # ── True negatives (NO debe detectar request) ──────────────────────
    def test_outbound_informativo_envio_a_celular_no_es_request(self):
        """Outbound informativo NO debe interpretarse como petición de
        número. 'Te envío tu link a tu celular' es bot enviando algo, NO
        bot pidiendo el celular del cliente."""
        h = self._hist("Te envío tu link de pago a tu celular.")
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_saludo_no_matchea(self):
        h = self._hist("Buenas noches! ¿En qué te puedo ayudar?")
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_resumen_no_matchea(self):
        h = self._hist("📋 Resumen de tu pedido. Total: $67.570")
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_pregunta_consent_no_matchea(self):
        h = self._hist("¿Estás de acuerdo? SÍ o NO.")
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_pregunta_email_no_matchea(self):
        h = self._hist("¿Cuál es tu correo electrónico?")
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone(h))

    # ── Edge cases ──────────────────────────────────────────────────────
    def test_history_vacio_retorna_false(self):
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone([]))

    def test_history_solo_inbound_retorna_false(self):
        h = [{"direction": "inbound", "content": "Compárteme tu celular alterno"}]
        # Inbound, no outbound → False.
        self.assertFalse(orchestrator._last_outbound_requested_shipping_phone(h))

    def test_acepta_acentos(self):
        """Acentos: el normalizador los strip; regex usa forma sin acentos."""
        h = self._hist("¿Cuál es el número de celular para la entrega?")
        self.assertTrue(orchestrator._last_outbound_requested_shipping_phone(h))


class DetectShippingPhoneUpdateContextualTests(unittest.TestCase):
    """`_detect_shipping_phone_update` debe disparar cuando outbound previo
    pidió shipping_phone (vía regex Fix A) y cliente respondió solo dígitos."""

    def test_caso_founder_uat_inbound_digitos_post_request(self):
        """Caso runtime: outbound pide shipping phone; cliente responde
        '3223840887' (10 dígitos, sin keyword)."""
        history = [
            {"direction": "outbound",
             "content": "Cuál es el número de celular que quieres agregar para el envío?"},
        ]
        out = orchestrator._detect_shipping_phone_update("3223840887", history)
        self.assertEqual(out, "3223840887")

    def test_inbound_digitos_sin_contexto_outbound_no_extrae(self):
        """Sin pregunta previa, dígitos solos NO son shipping_phone update
        (defensa contra falsos positivos)."""
        history = [
            {"direction": "outbound", "content": "Hola, en qué te ayudo?"},
        ]
        out = orchestrator._detect_shipping_phone_update("3223840887", history)
        self.assertIsNone(out)

    def test_inbound_con_keyword_extrae_sin_contexto_outbound(self):
        """Keyword en inbound: extrae sin importar outbound previo."""
        history = []
        out = orchestrator._detect_shipping_phone_update(
            "celular alternativo: 3223840887", history,
        )
        self.assertEqual(out, "3223840887")


# ── Fix B: discriminative-filter aplica siempre con opt-in ──────────────────

class DetectVariantConfirmationCrossProductDisambiguationTests(unittest.TestCase):
    """Test del caso founder UAT (conv f6ec7213): bot listó 3 sérums; cliente
    dijo 'Sérum de Vitamina C de 30ml' — debe agregar EXACTAMENTE 1 item
    (Vitamina C), NO los 3 (cada uno tiene variante 30ml).

    La disambiguación vive en `_detect_variant_confirmation` (orquestador
    cross-product), no en `_resolve_variant_from_inbound` (resolver por
    producto). Esto preserva el comportamiento legítimo del caso
    Coco+Sérum donde "60g" matchea Coco unívocamente (Sérum no tiene
    variante en gramos)."""

    _SERUMS = [
        {
            "id": "p-serum-hialuronico",
            "title": "Sérum de Ácido Hialurónico",
            "variants": [
                {"id": "v-h-15", "label": "15ml", "price": 58000,
                 "attributes": {"size": "15ml"}},
                {"id": "v-h-30", "label": "30ml", "price": 92000,
                 "attributes": {"size": "30ml"}},
            ],
        },
        {
            "id": "p-serum-bakuchiol",
            "title": "Sérum de Bakuchiol (Retinol Natural)",
            "variants": [
                {"id": "v-b-15", "label": "15ml", "price": 65000,
                 "attributes": {"size": "15ml"}},
                {"id": "v-b-30", "label": "30ml", "price": 105000,
                 "attributes": {"size": "30ml"}},
            ],
        },
        {
            "id": "p-serum-vitamina-c",
            "title": "Sérum de Vitamina C",
            "variants": [
                {"id": "v-c-15", "label": "15ml", "price": 52000,
                 "attributes": {"size": "15ml"}},
                {"id": "v-c-30", "label": "30ml", "price": 85000,
                 "attributes": {"size": "30ml"}},
            ],
        },
    ]

    _OUTBOUND_PRESENTING_SERUMS = (
        "Entendido, Cristian. Qué bueno que quieres agregar un sérum facial.\n\n"
        "Tenemos estos:\n"
        "* *Sérum de Ácido Hialurónico* — 15ml por *$58.000* · 30ml por *$92.000*\n"
        "* *Sérum de Bakuchiol (Retinol Natural)* — 15ml por *$65.000* · 30ml por *$105.000*\n"
        "* *Sérum de Vitamina C* — 15ml por *$52.000* · 30ml por *$85.000*\n\n"
        "Cuál presentación y cuántas unidades te gustaría llevar?"
    )

    def _history(self):
        return [
            {"direction": "inbound", "content": "Puedo agregar un Serum facial?"},
            {"direction": "outbound", "content": self._OUTBOUND_PRESENTING_SERUMS},
        ]

    def test_caso_founder_uat_vitamina_c_30ml_solo_matchea_uno(self):
        """Caso runtime exacto: '`Sérum de Vitamina C de 30ml`' → 1 match."""
        result = orchestrator._detect_variant_confirmation(
            "Sérum de Vitamina C de 30ml",
            self._history(),
            self._SERUMS,
        )
        self.assertEqual(len(result), 1,
                         f"Esperado 1 match, obtuvo {len(result)}: {result}")
        self.assertEqual(result[0]["product_id"], "p-serum-vitamina-c")
        self.assertEqual(result[0]["variation_id"], "v-c-30")
        self.assertEqual(result[0]["quantity"], 1)

    def test_bakuchiol_30ml_solo_bakuchiol(self):
        result = orchestrator._detect_variant_confirmation(
            "Sérum de Bakuchiol 30ml", self._history(), self._SERUMS,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_id"], "p-serum-bakuchiol")

    def test_hialuronico_15ml_solo_hialuronico(self):
        result = orchestrator._detect_variant_confirmation(
            "Sérum de Ácido Hialurónico 15ml", self._history(), self._SERUMS,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_id"], "p-serum-hialuronico")

    def test_solo_30ml_sin_nombre_de_producto_rechaza_todos(self):
        """Inbound ambiguo ('30ml' sin nombre) → 0 matches (defensivo)."""
        result = orchestrator._detect_variant_confirmation(
            "30ml", self._history(), self._SERUMS,
        )
        self.assertEqual(result, [])


class DetectVariantConfirmationCrossProductPreserveCoco60gTests(unittest.TestCase):
    """Regresión: el caso Coco+Sérum donde '60 gramos' es unívoco para
    Coco (Sérum solo tiene ml) DEBE seguir resolviendo. La disambiguación
    cross-product solo aplica cuando la variante matched es AMBIGUA
    (label compartido entre productos)."""

    _COCO = {
        "id": "p-coco",
        "title": "Jabón Artesanal de Coco",
        "variants": [
            {"id": "v-60g", "label": "60g", "price": 18000,
             "attributes": {"size": "60g"}},
            {"id": "v-100g", "label": "100g", "price": 24000,
             "attributes": {"size": "100g"}},
        ],
    }
    _SERUM_C = {
        "id": "p-serum-c",
        "title": "Sérum de Vitamina C",
        "variants": [
            {"id": "v-15ml", "label": "15ml", "price": 52000,
             "attributes": {"size": "15ml"}},
            {"id": "v-30ml", "label": "30ml", "price": 85000,
             "attributes": {"size": "30ml"}},
        ],
    }

    def _history(self):
        outbound = (
            "Para los Jabones Artesanales de Coco:\n"
            "* 60g por $18.000\n* 100g por $24.000\n\n"
            "Y para el Sérum de Vitamina C:\n"
            "* 15ml por $52.000\n* 30ml por $85.000"
        )
        return [
            {"direction": "inbound", "content": "quiero coco y serum"},
            {"direction": "outbound", "content": outbound},
        ]

    def test_60_gramos_resuelve_solo_coco_aunque_no_mencione_nombre(self):
        """`60g` es ÚNICO a Coco (Sérum no tiene variantes en gramos).
        El inbound no menciona 'coco' explícitamente pero la variante
        misma identifica el producto unívocamente — debe matchear."""
        result = orchestrator._detect_variant_confirmation(
            "60 gramos por favor", self._history(),
            [self._COCO, self._SERUM_C],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_id"], "p-coco")
        self.assertEqual(result[0]["variation_id"], "v-60g")

    def test_30_ml_resuelve_solo_serum(self):
        """`30ml` es ÚNICO a Sérum (Coco no tiene variantes en ml)."""
        result = orchestrator._detect_variant_confirmation(
            "30 ml", self._history(),
            [self._COCO, self._SERUM_C],
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["product_id"], "p-serum-c")


if __name__ == "__main__":
    unittest.main()
