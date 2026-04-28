"""
Utilidades de texto/formato compartidas por orchestrator y tools.

Antes estas funciones estaban duplicadas en:
- orchestrator.py
- tools/shipping_quote_tool.py
- tools/order_status_tool.py

Centralizar evita que cambios en la normalización (ej. tokenizer) requieran
modificar 3-4 archivos y queden inconsistentes.
"""
import re
import unicodedata
from typing import Optional


def normalize_text(text: str) -> str:
    """Normaliza para comparación: lowercase, sin acentos, espacios colapsados.

    Ej: '¡Hola, BUENAS!  ' → 'hola, buenas!'
    """
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(normalized.lower().split())


def tokenize_text(text: str) -> list[str]:
    """Tokeniza texto a lista de palabras alfanuméricas en lowercase sin acentos."""
    return re.findall(r"[a-z0-9]+", normalize_text(text))


def normalize_phone(phone: str) -> str:
    """Normaliza teléfono: elimina '+' y espacios.

    Ej: '+57 312 583 5649' → '573125835649'
    """
    return re.sub(r"[\s+]", "", str(phone or "")).strip()


def safe_float(value: object) -> Optional[float]:
    """Convierte a float de forma segura. None / strings inválidos → None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_pesos(value: object) -> str:
    """Formatea pesos colombianos: 13500 → '$13.500'. Devuelve 'N/D' si no parsea."""
    amount = safe_float(value)
    if amount is None:
        return "N/D"
    return f"${int(round(amount)):,}".replace(",", ".")


def format_cents_cop(cents: int) -> str:
    """Formatea centavos COP a string legible: 1350000 → '$13.500 COP'"""
    pesos = (cents or 0) // 100
    return f"${pesos:,.0f} COP".replace(",", ".")
