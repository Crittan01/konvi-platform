"""Escalation gates — detección explícita de petición humana.

Rev. 104 (F1-1 batch 3) — extraído de orchestrator.py.

`detect_human_request_intent`: el cliente pide EXPLÍCITAMENTE atención humana.
Conservador: solo dispara con frases inequívocas. Casos como "tengo una duda"
o "ayúdame" NO matchean (son consultas normales).

Razón del detector: protege la petición legítima de escalación contra el
guard anti-escalación-espuria del orchestrator (que existe para bloquear
`requires_human=True` espurio en CATALOG_MODE/NEEDS_*). Este detector marca
un flag `force_human_request` que sobrevive a TODOS los guards.

Public API:
  • `detect_human_request_intent(text) -> bool`
  • Constantes: `HUMAN_REQUEST_PATTERNS` (regex precompilados).

Tests: `tests/test_safety_escalation.py`.
"""
from __future__ import annotations

import re


# ─── Patrones canónicos ─────────────────────────────────────────────────────

HUMAN_REQUEST_PATTERNS: tuple[re.Pattern, ...] = (
    # "Hablar con un asesor / humano / persona / agente"
    re.compile(
        r"\b(?:hablar|hable|comunicar(?:me)?|comunique(?:me)?|comuniqueme|"
        r"pasar(?:me)?|paseme|pasame|pásame|atender(?:me)?|atiendame|atiéndame)\s+"
        r"(?:con\s+)?(?:un|una|el|la|otro|otra)?\s*"
        r"(?:asesor|asesora|humano|humana|persona|agente|alguien|"
        r"vendedor|vendedora|representante|gestor|gestora|consultor|"
        r"consultora|operador|operadora|servicio\s+al\s+cliente)\b",
        re.IGNORECASE,
    ),
    # "Quiero / necesito un asesor / humano"
    re.compile(
        r"\b(?:quiero|necesito|requiero|deseo|preciso|busco|solicito)\s+"
        r"(?:hablar\s+con\s+)?(?:un|una|el|la)?\s*"
        r"(?:asesor|asesora|humano|humana|persona\s+real|agente|"
        r"vendedor|vendedora|representante|operador|"
        r"atenci[oó]n\s+humana|atenci[oó]n\s+personal|atenci[oó]n\s+personalizada|"
        r"ayuda\s+(?:de\s+)?(?:un|una)?\s*(?:asesor|persona|humano|alguien))\b",
        re.IGNORECASE,
    ),
    # Frases compuestas
    re.compile(
        r"\b(?:atenci[oó]n\s+humana|asesor\s+real|persona\s+real|"
        r"humano\s+real|operador\s+humano|hablar\s+con\s+alguien|"
        r"contactar(?:me)?\s+con\s+(?:un|una)?\s*(?:asesor|humano|persona|agente)|"
        r"que\s+me\s+llame|llamame\s+un|ll[aá]meme\s+un)\b",
        re.IGNORECASE,
    ),
)


# ─── Public detector ────────────────────────────────────────────────────────

def detect_human_request_intent(text: str) -> bool:
    """True si el cliente pide EXPLÍCITAMENTE atención humana.

    Conservador: solo dispara con frases inequívocas. Casos como "tengo
    una duda" o "ayúdame" NO matchean (son consultas normales que el bot
    debe atender).
    """
    if not text:
        return False
    return any(p.search(text) for p in HUMAN_REQUEST_PATTERNS)
