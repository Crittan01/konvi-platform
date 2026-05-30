"""Phone canonicalization — fuente única de verdad cross-service (rev. 104, F0-4).

Forma canónica = **digits-only** (sin `+`, sin espacios). Alineada con:
  • WhatsApp Cloud API (Meta `wa_id` viene sin `+`).
  • Connector WhatsApp (`db_persistence._normalize_phone` ya guarda digits-only).
  • MeLi inbound (orden import normaliza a digits para `contacts.phone`).

Excepción explícita: Wompi `customer_data` requiere E.164 (`+digits`) — la
conversión local vive en `to_wompi_format` y se aplica solo dentro del cliente
Wompi en el momento de armar el payload.

⚠️  ESTE ARCHIVO ES IDÉNTICO al de `services/ai-orchestrator/lib/phone.py`.
    El test `tests/test_phone_helpers_pact.py` valida que ambos hashen igual.
    Cualquier cambio: actualizar AMBOS + verificar el pact test.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

# Constantes Colombia (default tenant operativo).
_CO_COUNTRY_CODE = "57"
_CO_CELL_LENGTH = 10           # cel local: 3001234567 (10 dígitos)
_CANONICAL_LENGTH = 12         # con prefix CO: 573001234567 (2 + 10 = 12)


def to_canonical(raw: Optional[str]) -> Optional[str]:
    """Normaliza a forma canónica digits-only (E.164 sin '+').

    Reglas:
      • Strip todo char no-dígito.
      • 10 dígitos empezando con '3' → prepend '57' (cel CO inferido).
      • 11 dígitos empezando con '57' → ya canónico.
      • 13 dígitos empezando con '5757' (legacy data quality bug) → drop primer '57'.
      • Otros 11-15 dígitos → return as-is (extranjero, mejor preservar que descartar).
      • Vacío / inválido / <10 dígitos → None.

    Ejemplos:
      '+57 312 583 5649' → '573125835649'
      '3125835649'       → '573125835649'
      '57 3125835649'    → '573125835649'
      '+573125835649'    → '573125835649'
      '5757312...' (12)  → '57312...'      (corrige duplicación legacy)
      ''                 → None
      'abc'              → None
      None               → None
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if not digits:
        return None
    # CO sin prefix (cel local).
    if len(digits) == _CO_CELL_LENGTH and digits[0] == "3":
        return _CO_COUNTRY_CODE + digits
    # CO con prefix (canon).
    if len(digits) == _CANONICAL_LENGTH and digits.startswith(_CO_COUNTRY_CODE):
        return digits
    # Legacy bug: doble prefix 5757... (visto en data MeLi histórica).
    if (
        len(digits) == _CANONICAL_LENGTH + 2
        and digits.startswith(_CO_COUNTRY_CODE * 2)
    ):
        return digits[len(_CO_COUNTRY_CODE):]
    # Extranjero u otro: preservar si tiene longitud razonable E.164 (8-15 dígitos
    # según ITU-T E.164, pero clampamos a 11-15 para excluir locales sin prefix).
    if 11 <= len(digits) <= 15:
        return digits
    return None


def to_e164(canonical: Optional[str]) -> Optional[str]:
    """Canonical → E.164 con '+'. Idempotente: si ya tiene '+', lo deja."""
    if not canonical:
        return None
    return canonical if canonical.startswith("+") else f"+{canonical}"


def hash_phone(canonical: Optional[str]) -> str:
    """SHA256(canonical) — invariante a formato.

    Útil para audit logs / phone_hash columns donde el plaintext no debe
    persistirse. Acepta cualquier cosa, normaliza primero a canonical para
    que el hash sea estable independiente del formato de entrada.
    """
    canonical = to_canonical(canonical) if canonical else None
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def is_valid_co(canonical: Optional[str]) -> bool:
    """True si es phone CO válido: 11 dígitos, empieza con '57'."""
    if not canonical:
        return False
    return (
        len(canonical) == _CANONICAL_LENGTH
        and canonical.startswith(_CO_COUNTRY_CODE)
    )


# ─── Aliases semánticos por destino ──────────────────────────────────────────
# Cada destino documenta su contrato; el alias hace explícita la intención.

def to_db_format(raw: Optional[str]) -> Optional[str]:
    """Forma para `contacts.phone`, `messages.customer_phone`, `conversations.customer_phone`.

    DB canon = digits-only. Aplicar SIEMPRE antes de upsert/insert.
    """
    return to_canonical(raw)


def to_meta_wa_format(raw: Optional[str]) -> Optional[str]:
    """Forma para Meta WhatsApp Cloud API (`messages.to`, `wa_id`).

    Meta espera digits-only sin '+'.
    """
    return to_canonical(raw)


def to_wompi_format(raw: Optional[str]) -> Optional[str]:
    """Forma para Wompi `customer_data.phone_number` (E.164 con '+').

    Wompi requiere E.164 estricto.
    """
    canonical = to_canonical(raw)
    if not canonical:
        return None
    return to_e164(canonical)


def to_display_format(raw: Optional[str]) -> Optional[str]:
    """Forma legible al cliente final: '+57 312 583 5649'.

    Solo CO. Para otros países devuelve `to_e164(canonical)` sin spaces.
    """
    canonical = to_canonical(raw)
    if not canonical:
        return None
    if not is_valid_co(canonical):
        return to_e164(canonical)
    cc = canonical[:len(_CO_COUNTRY_CODE)]
    rest = canonical[len(_CO_COUNTRY_CODE):]
    return f"+{cc} {rest[:3]} {rest[3:6]} {rest[6:]}"
