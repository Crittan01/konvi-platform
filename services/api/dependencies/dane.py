"""
DANE (Departamento Administrativo Nacional de Estadística) — códigos territoriales CO.

Rev. 72 — centraliza normalización antes duplicada en `routers/shipping.py` y
en `services/ai-orchestrator/tools/shipping_quote_tool.py`. El frontend tenía
una versión propia (`apps/web/lib/...`); ahora el frontend solo formatea
visualmente, la **validación canónica vive aquí** (cierra drift M1).

Convenciones DANE Colombia:
- DIVIPOLA: 5 dígitos (DD MMM) — DD departamento, MMM municipio.
- Envia API: requiere 8 dígitos (DD MMM CCC, expandido con barrio/zona o "000").
- Postal code (Adpostal/472): 6 dígitos generalmente, distinto a DIVIPOLA.

Acepta el DANE tanto en formato 5 como 8. La función expande 5→8 con sufijo "000".
"""
import re
from typing import Optional


def sanitize_dane_code(raw: Optional[str]) -> str:
    """Limpia un DANE dejando únicamente dígitos.
    Ejemplos:
        "11001"        -> "11001"
        "11001-000"    -> "11001000"
        " 11 001 "     -> "11001"
        None           -> ""
    """
    if not raw:
        return ""
    return re.sub(r"\D", "", str(raw))


def co_dane_codes(raw: Optional[str]) -> tuple[str, str]:
    """Normaliza DANE para runtime CO. Retorna (dane5, dane8).

    - Si raw tiene 5 dígitos: dane5 = raw, dane8 = raw + "000".
    - Si raw tiene 8 dígitos: dane5 = primeros 5, dane8 = raw.
    - Otros casos: ambos vacíos.
    """
    digits = sanitize_dane_code(raw)
    if len(digits) == 5:
        return digits, digits + "000"
    if len(digits) == 8:
        return digits[:5], digits
    return "", ""


def is_valid_dane(raw: Optional[str]) -> bool:
    """True si el código limpio tiene 5 u 8 dígitos."""
    digits = sanitize_dane_code(raw)
    return len(digits) in (5, 8)
