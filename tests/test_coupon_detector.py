"""Tests detector cupones (rev. 105 Sem 6 I.2.2 / ADR-0015 D1+D2).

Cubre:
  1. Apply con verbos (tengo/aplicar/agregar/usar/poner/...) + código
  2. Apply noun-code (cupón XYZ / código XYZ)
  3. Apply bare-code con noun presente y código único
  4. Remove (quitar/remover/eliminar/sin cupón)
  5. False positives (sin intent cupón)
  6. Ambigüedad (multi-código uppercase) → None
  7. Edge cases (None, vacío, plurales, tildes)
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_detector():
    if "_coupon_detector" in sys.modules:
        return sys.modules["_coupon_detector"]
    spec = importlib.util.spec_from_file_location(
        "_coupon_detector",
        REPO_ROOT / "services" / "ai-orchestrator" / "lib" / "coupon_detector.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_coupon_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


det = _load_detector()


# ─── Apply con verbos ────────────────────────────────────────────────────────

class ApplyWithVerbTests(unittest.TestCase):
    def test_tengo_el_cupon_codigo(self):
        r = det.detect_coupon_intent("tengo el cupón PROMO10")
        self.assertIsNotNone(r)
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "PROMO10")

    def test_aplicar_codigo(self):
        r = det.detect_coupon_intent("aplicar DESCUENTO50")
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "DESCUENTO50")

    def test_agregar_cupon(self):
        r = det.detect_coupon_intent("agregar cupón BIENVENIDO")
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "BIENVENIDO")

    def test_usar_codigo_descuento(self):
        r = det.detect_coupon_intent("quiero usar el código de descuento ENVIOGRATIS")
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "ENVIOGRATIS")

    def test_pon_el_cupon(self):
        r = det.detect_coupon_intent("pon el cupón VERANO20")
        self.assertEqual(r.code, "VERANO20")

    def test_sin_tildes(self):
        # 'cupon' sin tilde también funciona.
        r = det.detect_coupon_intent("tengo el cupon PROMO10")
        self.assertEqual(r.code, "PROMO10")


# ─── Apply noun-code (sin verbo) ─────────────────────────────────────────────

class ApplyNounCodeTests(unittest.TestCase):
    def test_cupon_codigo(self):
        r = det.detect_coupon_intent("cupón PROMO10")
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "PROMO10")

    def test_codigo_xyz(self):
        r = det.detect_coupon_intent("código MIGUSTO")
        self.assertEqual(r.code, "MIGUSTO")

    def test_promo_xyz(self):
        r = det.detect_coupon_intent("promo NAVIDAD2026")
        self.assertEqual(r.code, "NAVIDAD2026")

    def test_descuento_xyz(self):
        r = det.detect_coupon_intent("descuento PROMO10")
        self.assertEqual(r.code, "PROMO10")


# ─── Apply bare-code con noun presente ───────────────────────────────────────

class ApplyBareCodeTests(unittest.TestCase):
    def test_unique_uppercase_code_with_noun(self):
        # "tengo PROMO10 y quiero..." — noun + único código → apply.
        r = det.detect_coupon_intent("tengo PROMO10 y quiero comprar")
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "PROMO10")

    def test_no_noun_no_intent(self):
        # Solo "PROMO10" sin mención de cupón → no es intent.
        r = det.detect_coupon_intent("PROMO10 sería buen nombre")
        self.assertIsNone(r)

    def test_multiple_codes_ambiguity(self):
        # Múltiples uppercase tokens → ambigüedad, NO retornar.
        r = det.detect_coupon_intent("cupón PROMO10 o TEMPORADA20?")
        # Acá el primer match noun-code "cupón PROMO10" SÍ debe ganar
        # antes que llegue a bare-code (ver prioridad reglas).
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "PROMO10")

    def test_only_bare_codes_ambiguity_returns_none(self):
        # Sin verbo y sin noun-adyacente, múltiples codes → None.
        r = det.detect_coupon_intent("hay cupones tipo PROMO10 o ENVIOGRATIS?")
        # "cupones tipo PROMO10" — noun adyacente a "tipo" no a PROMO10
        # entonces el noun_code pattern NO matchea "tipo PROMO10".
        # bare-code finds 2 → None.
        # Pero esta línea es ambigua semánticamente — el cliente está
        # consultando, no aplicando. Acceptable que retorne None.
        self.assertIsNone(r)


# ─── Remove ──────────────────────────────────────────────────────────────────

class RemoveIntentTests(unittest.TestCase):
    def test_quita_el_cupon(self):
        r = det.detect_coupon_intent("quita el cupón")
        self.assertEqual(r.intent, "remove")
        self.assertIsNone(r.code)

    def test_remover_descuento(self):
        r = det.detect_coupon_intent("remover descuento")
        self.assertEqual(r.intent, "remove")

    def test_eliminar_promo(self):
        r = det.detect_coupon_intent("eliminar promo")
        self.assertEqual(r.intent, "remove")

    def test_sin_cupon(self):
        r = det.detect_coupon_intent("sin cupón por favor")
        self.assertEqual(r.intent, "remove")

    def test_sin_descuento(self):
        r = det.detect_coupon_intent("mejor sin descuento")
        self.assertEqual(r.intent, "remove")

    def test_sacar_cupon(self):
        r = det.detect_coupon_intent("saca el cupón")
        self.assertEqual(r.intent, "remove")

    def test_cancelar_descuento(self):
        r = det.detect_coupon_intent("cancela el descuento")
        self.assertEqual(r.intent, "remove")


# ─── False positives ─────────────────────────────────────────────────────────

class NoIntentTests(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(det.detect_coupon_intent(""))
        self.assertIsNone(det.detect_coupon_intent(None))
        self.assertIsNone(det.detect_coupon_intent("   "))

    def test_normal_purchase_message(self):
        r = det.detect_coupon_intent("quiero 2 jabones de coco")
        self.assertIsNone(r)

    def test_greeting(self):
        r = det.detect_coupon_intent("hola buenas tardes")
        self.assertIsNone(r)

    def test_passive_mention_no_intent(self):
        # "el cupón se aplicó" es PASIVO — el cliente describe estado,
        # no pide aplicar. Pero el regex puede matchear "aplicó" (apply
        # verb) + cupón. Edge case: validar no hay falso positive.
        # En la realidad, el detector dirá apply; pero como NO HAY código
        # en el texto, retorna None.
        r = det.detect_coupon_intent("el cupón se aplicó perfecto")
        self.assertIsNone(r)

    def test_random_uppercase_word_no_noun(self):
        r = det.detect_coupon_intent("voy a CASA luego")
        self.assertIsNone(r)

    def test_filename_uppercase_no_intent(self):
        r = det.detect_coupon_intent("envía el PDF por favor")
        self.assertIsNone(r)

    def test_question_about_coupons_no_code(self):
        r = det.detect_coupon_intent("¿tienen cupones disponibles?")
        # Hay noun pero ningún código uppercase → None.
        self.assertIsNone(r)


# ─── Edge cases ──────────────────────────────────────────────────────────────

class EdgeCasesTests(unittest.TestCase):
    def test_lowercase_code_not_detected(self):
        # Códigos lowercase NO se detectan. Convención: códigos siempre
        # mayúsculas (PROMO10, no promo10). Esto evita matchear palabras
        # comunes.
        r = det.detect_coupon_intent("tengo el cupón promo10")
        # 'promo10' tiene 'p' minúscula → bare-code no matchea, noun-code
        # tampoco → None.
        self.assertIsNone(r)

    def test_short_code_too_short(self):
        # Mínimo 3 chars (regex {2,29} after first char = 3 total min).
        r = det.detect_coupon_intent("cupón AB")
        self.assertIsNone(r)

    def test_with_dashes_underscores(self):
        r = det.detect_coupon_intent("tengo el cupón BLACK-FRIDAY")
        self.assertEqual(r.code, "BLACK-FRIDAY")
        r2 = det.detect_coupon_intent("código MARKET_2026")
        self.assertEqual(r2.code, "MARKET_2026")

    def test_plurals_tolerated(self):
        # cupones, descuentos, códigos.
        r = det.detect_coupon_intent("tienen cupones tipo PROMO10")
        # noun "cupones" presente, único bare-code → apply.
        self.assertEqual(r.intent, "apply")
        self.assertEqual(r.code, "PROMO10")

    def test_common_word_filtered(self):
        # "OK" / "SI" / "NO" en uppercase no son códigos.
        r = det.detect_coupon_intent("cupón SI por favor")
        # SI está en _COMMON_TOKENS → filtrado. Sin candidates → None.
        self.assertIsNone(r)

    def test_remove_first_priority(self):
        # Orden: REMOVE antes que APPLY. Si el msg menciona "quitar cupón"
        # y también un código, retornar REMOVE.
        r = det.detect_coupon_intent("quita el cupón PROMO10")
        # Por orden de reglas: REMOVE_PATTERN matchea primero "quita el
        # cupón" → retorna remove. El código no se extrae (intent claro).
        self.assertEqual(r.intent, "remove")


if __name__ == "__main__":
    unittest.main()
