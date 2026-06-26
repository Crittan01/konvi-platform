"""Fuente única de formateo de teléfono colombiano (Plan A.4 — helper único).

Antes había una copia local en `tools/known_customer_tool._format_phone_co`.
El bloque CONTEXTO_CLIENTE (`agentic/system_prompt.py`) necesitaba el mismo
formato para el celular del cliente; en vez de duplicar, ambos consumen esta
función. Forma canónica de almacenamiento = digits-only (ver ADR/plan A.4);
este helper SOLO presenta (no canonicaliza ni valida).
"""
from __future__ import annotations

import re


def format_phone_co(phone: str | None) -> str:
    """'573125835649' → '+57 312 583 5649'. Devuelve el input si no matchea CO."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 12 and digits.startswith("57"):
        return f"+57 {digits[2:5]} {digits[5:8]} {digits[8:]}"
    if len(digits) == 10:
        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"
    return phone
