"""Detector intent cupones (Sem 6 I.2.2 / ADR-0015 D1+D2).

Función pura para detectar intent de aplicar/revocar cupón en mensaje
inbound. Sin DB, sin LLM, sin side-effects.

Decisión arquitectónica (ADR-0015 D1):
  Detector pre-LLM con regex (Opción C híbrida del escalation
  2026-05-07). Determinístico, alineado con Plan A.0.1 ("LLM no decide
  verdad transaccional").

Modo de aplicación (ADR-0015 D2):
  Mode A — el detector retorna intent + código; el orchestrator decide
  responder con mensaje corto + esperar nuevo turno del cliente para
  cualquier intent residual ("y quiero 2 jabones"). NO procesa intents
  embebidos en el mismo turno (eso sería Mode B, P3 futuro).

Ejemplos cubiertos:
  - "tengo el cupón PROMO10"          → apply, "PROMO10"
  - "código DESCUENTO50"               → apply, "DESCUENTO50"
  - "promo BIENVENIDO"                 → apply, "BIENVENIDO"
  - "aplicar PROMO10"                  → apply, "PROMO10"
  - "agregar cupón PROMO10"            → apply, "PROMO10"
  - "quita el cupón"                   → remove, None
  - "remover descuento"                → remove, None
  - "sin cupón"                        → remove, None
  - "quiero 2 jabones"                 → None (no es intent cupón)
  - "el cupón se aplicó perfecto"      → None (frase pasiva, no apply)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ── Constantes ───────────────────────────────────────────────────────────────

INTENT_APPLY = "apply"
INTENT_REMOVE = "remove"


@dataclass(frozen=True)
class CouponIntent:
    """Resultado del detector. `code` puede ser None para INTENT_REMOVE."""
    intent: str   # 'apply' | 'remove'
    code: Optional[str]


# ── Regex (compiladas una sola vez) ──────────────────────────────────────────

# Tokens que hablan de cupón/descuento. Tolerante a tildes y plurales.
_COUPON_NOUN = r"cup[oó]n(?:es)?|c[oó]digos?|descuentos?|promos?(?:ci[oó]n(?:es)?)?"

# Verbos APPLY: tener, aplicar, agregar, usar, ingresar, poner, meter...
_APPLY_VERBS = (
    r"tengo|aplica(?:r)?|agrega(?:r)?|usa(?:r)?|ingresa(?:r)?|"
    r"pon(?:er|go)?|met(?:er|o)?|introduc(?:ir|e)|coloca(?:r)?"
)

# Verbos REMOVE: quitar, remover, eliminar, sacar, cancelar...
_REMOVE_VERBS = (
    r"quita(?:r)?|remov(?:er|e)|elimina(?:r)?|saca(?:r)?|"
    r"cancela(?:r)?|borra(?:r)?|deshac(?:er|e)|retir(?:ar|a)"
)

# Patrón "remove" — verbo remove + cupón/descuento opcionalmente.
_REMOVE_PATTERN = re.compile(
    rf"\b(?:{_REMOVE_VERBS})\s+(?:el\s+|la\s+|mi\s+|este\s+)?"
    rf"(?:{_COUPON_NOUN})\b",
    re.IGNORECASE,
)

# Patrón "sin cupón" — explícito de cancelación.
_NO_COUPON_PATTERN = re.compile(
    rf"\bsin\s+(?:{_COUPON_NOUN})\b",
    re.IGNORECASE,
)

# Patrón "tengo/aplicar cupón CÓDIGO" — apply explícito con verbo.
# Verbos APPLY + (opcional 'el cupón'/etc.) + CÓDIGO_uppercase.
# Código: 3-30 chars, letras MAYUS y dígitos (permitimos guiones/underscores).
# IMPORTANTE: usamos (?-i:...) para mantener CODE_TOKEN case-sensitive aún
# cuando el patrón externo lleve flag re.IGNORECASE. Eso garantiza que
# códigos lowercase (e.g. "promo10") NO se confundan con palabras
# comunes en español ("disponibles", "tipo", etc.).
_CODE_TOKEN = r"((?-i:[A-Z][A-Z0-9_-]{2,29}))"

_APPLY_VERB_PATTERN = re.compile(
    rf"\b(?:{_APPLY_VERBS})\s+"
    rf"(?:el\s+|la\s+|un\s+|una\s+|mi\s+)?"
    rf"(?:{_COUPON_NOUN})?\s*"
    rf"(?:de\s+descuento\s+)?"
    rf"{_CODE_TOKEN}\b",
    re.IGNORECASE,
)

# Patrón "cupón CÓDIGO" — sin verbo, solo "cupón XYZ" o "código XYZ".
# Más conservador: pide noun + código adyacente.
_NOUN_CODE_PATTERN = re.compile(
    rf"\b(?:{_COUPON_NOUN})\s+"
    rf"(?:es\s+|seria\s+|sería\s+)?"
    rf"{_CODE_TOKEN}\b",
    re.IGNORECASE,
)

# Patrón fallback "CÓDIGO" solo cuando hay noun cupón EN ALGUNA PARTE
# del mensaje. Esto cubre "tengo PROMO10 y quiero..." o
# "PROMO10? sí ese". Solo se usa si no matchearon los anteriores.
_NOUN_PRESENT_PATTERN = re.compile(
    rf"\b(?:{_COUPON_NOUN})\b",
    re.IGNORECASE,
)
# Bare-code SIN flag IGNORECASE — case-sensitive por construcción.
_BARE_CODE_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9_-]{2,29})\b",
)


# ── Funciones públicas ───────────────────────────────────────────────────────

def detect_coupon_intent(text: Optional[str]) -> Optional[CouponIntent]:
    """Detecta intent de cupón en texto inbound del cliente. Función pura.

    Reglas de prioridad (orden importa):
      1. REMOVE: si el cliente quiere quitar/remover/sacar cupón actual.
         (verbos remove + cupón/descuento, o "sin cupón").
      2. APPLY con verbo: "tengo/aplicar/agregar... [el cupón] CÓDIGO".
      3. APPLY noun-code: "cupón CÓDIGO" o "código CÓDIGO" (sin verbo).
      4. APPLY bare-code: solo si noun cupón presente en el texto Y hay
         exactamente UN código uppercase candidato. Conservador: si hay
         varios candidatos (ambigüedad), retorna None.

    Args:
        text: mensaje del cliente. None/vacío → None.

    Returns:
        CouponIntent o None si no hay intent detectado.
    """
    if not text or not isinstance(text, str):
        return None
    text_stripped = text.strip()
    if not text_stripped:
        return None

    # 1. REMOVE primero (algunos verbos remove + noun pueden parecer apply
    # si se evalúan en otro orden — ej. "quita el cupón" tiene la palabra
    # "cupón" pero NO debe matchear apply).
    if _REMOVE_PATTERN.search(text_stripped):
        return CouponIntent(intent=INTENT_REMOVE, code=None)
    if _NO_COUPON_PATTERN.search(text_stripped):
        return CouponIntent(intent=INTENT_REMOVE, code=None)

    # 2. APPLY con verbo + código.
    m = _APPLY_VERB_PATTERN.search(text_stripped)
    if m:
        code = m.group(1).upper()
        return CouponIntent(intent=INTENT_APPLY, code=code)

    # 3. APPLY noun-code: "cupón CÓDIGO".
    m = _NOUN_CODE_PATTERN.search(text_stripped)
    if m:
        code = m.group(1).upper()
        return CouponIntent(intent=INTENT_APPLY, code=code)

    # 4. APPLY bare-code: solo si noun cupón presente y código único.
    if _NOUN_PRESENT_PATTERN.search(text_stripped):
        # Buscar TODOS los códigos uppercase candidatos.
        # Excluir tokens triviales ("OK", "SI", "NO", etc.) ya filtrados
        # por el regex (mínimo 3 chars).
        candidates = _BARE_CODE_PATTERN.findall(text_stripped)
        # Filtrar tokens demasiado comunes para evitar false positives.
        candidates = [c for c in candidates if c.upper() not in _COMMON_TOKENS]
        if len(candidates) == 1:
            return CouponIntent(intent=INTENT_APPLY, code=candidates[0].upper())
        # Multi-candidates → ambigüedad. NO retornar nada (cliente debe
        # repetir más explícito).

    return None


# Tokens uppercase comunes que NO son códigos (evitar false positives en
# bare-code detection). Lista conservadora — solo lo más obvio.
_COMMON_TOKENS = frozenset({
    "OK", "SI", "NO", "YES", "WHATSAPP", "META", "FB", "IG",
    "URL", "WWW", "HTTP", "HTTPS", "API", "PDF", "JPG", "PNG",
    "USD", "COP", "MXN", "EUR",
})
