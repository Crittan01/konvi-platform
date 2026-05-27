"""Invariant: completitud al presentar una categoría del catálogo.

Rev. 108 (founder UAT 2026-05-27 crítico):
  Cliente preguntó "Quiero ver los sérums". Bot listó SOLO 1 sérum
  (Vitamina C) cuando DB tiene 3 activos (+ Bakuchiol, + Ácido Hialurónico).
  LLM hallucination de OMISIÓN — no es bug de código, es comportamiento
  no-determinístico de Gemini bajo context window saturado.

Solución arquitectónica:
  Detectar si outbound presenta una categoría completa (ej. "estos son
  los sérums") y verificar que TODOS los productos activos de esa
  categoría aparecen en el texto. Si falta alguno → REWRITE con lista
  completa derivada del catálogo (DB-first, NO LLM).

Pattern espejo: `payment_mode_coherence`, `cart_state_coherence`. NO
machetazo — detección determinística + rewrite con datos reales.

Categorías detectadas (heurísticas):
  • "los sérums" / "el sérum" / "sérums disponibles" → categoría=Sérum
  • "los jabones" / "jabones artesanales" / "jabón disponible" → Jabón
  • "los aceites" / "aceites esenciales" / "aceites vegetales" → Aceite
  • "los kits" / "kits disponibles" → Kit

Activación:
  • Outbound tiene anchor de presentación de lista ("tenemos estos",
    "disponibles", "estas son las opciones", bullets con $ etc.)
  • Y outbound NO presenta TODOS los productos de esa categoría
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# Mapeo categoria → patterns para detectar mención + función de match producto.
# Cada entry: (display_label, intent_patterns, product_match_lambda)
_CATEGORIES = [
    # Sérums
    (
        "sérum",
        [
            re.compile(r"\bs[eé]rum(?:es|s)?\b", re.IGNORECASE),
        ],
        lambda title: "serum" in title.lower() or "sérum" in title.lower(),
    ),
    # Jabones
    (
        "jabón",
        [
            re.compile(r"\bjab[oó]n(?:es)?\b", re.IGNORECASE),
        ],
        lambda title: "jabon" in title.lower() or "jabón" in title.lower(),
    ),
    # Aceites (incluye vegetales y esenciales)
    (
        "aceite",
        [
            re.compile(r"\baceites?\b", re.IGNORECASE),
        ],
        lambda title: "aceite" in title.lower(),
    ),
    # Kits
    (
        "kit",
        [
            re.compile(r"\bkits?\b", re.IGNORECASE),
        ],
        lambda title: "kit" in title.lower(),
    ),
]


# Anchors que indican "estoy presentando una categoría/lista" (no un solo producto).
_CATEGORY_PRESENTATION_ANCHORS = (
    re.compile(r"\b(?:tenemos|aqu[ií]\s+est[aá]n|estos?\s+son|estas?\s+son)\b", re.IGNORECASE),
    re.compile(r"\bopciones?\s+disponibles?\b", re.IGNORECASE),
    re.compile(r"\b(?:te\s+(?:cuento|presento|muestro)\s+(?:lo|las|los|todas))\b", re.IGNORECASE),
    re.compile(r"\bdisponibles?\b", re.IGNORECASE),
    # Indicios de lista con precios
    re.compile(r"\n\s*[\*\-•]\s+[\*_]?[A-Z]", re.MULTILINE),
)


def _outbound_presents_category_list(text: str) -> bool:
    """True si el outbound parece presentar una lista de categoría."""
    if not text:
        return False
    return any(p.search(text) for p in _CATEGORY_PRESENTATION_ANCHORS)


def _detect_category_intent(text: str) -> Optional[tuple]:
    """Detecta qué categoría se está presentando.

    Returns (category_label, match_lambda) si encuentra, None si no.
    """
    if not text:
        return None
    for label, patterns, match_fn in _CATEGORIES:
        for p in patterns:
            if p.search(text):
                return (label, match_fn)
    return None


def _products_in_text(catalog: list[dict], text: str, match_fn) -> tuple[list[dict], list[dict]]:
    """Para los productos de la categoría, separa los que SÍ aparecen
    en el texto vs los que faltan.

    Returns: (present, missing) lists of catalog product dicts.
    """
    text_lower = (text or "").lower()
    matched_in_cat = [p for p in catalog if match_fn(str(p.get("title") or ""))]
    present, missing = [], []
    for p in matched_in_cat:
        title = str(p.get("title") or "").lower()
        # Match: title literal o palabra significativa
        title_words = [w for w in title.split() if len(w) > 4 and w not in ("artesanal", "natural", "esencial")]
        if title in text_lower:
            present.append(p)
        elif title_words and any(w in text_lower for w in title_words):
            present.append(p)
        else:
            missing.append(p)
    return present, missing


def _build_replacement(category_label: str, missing: list[dict], present: list[dict]) -> str:
    """Construye outbound COMPACTO (rev. 108 founder UX 2026-05-27).

    Formato: nombre producto + variantes (labels), SIN precios.
    Cliente pide precios cuando le interese un producto específico.
    Reduce saturación visual + tokens al LLM downstream.
    """
    all_products = sorted(present + missing, key=lambda p: str(p.get("title") or ""))
    lines = [f"Tenemos estos *{category_label}s*:", ""]
    for p in all_products:
        title = str(p.get("title") or "Producto")
        variants = p.get("variants") or []
        clean_labels = [
            str(v.get("label") or "")
            for v in variants
            if v.get("label") and float(v.get("price") or 0) > 0
        ]
        if not clean_labels:
            lines.append(f"* *{title}*")
        else:
            lines.append(f"* *{title}* ({', '.join(clean_labels)})")
    lines.append("")
    lines.append("¿Cuál te interesa? Te paso precios y detalles del que elijas.")
    return "\n".join(lines)


class CategoryCompletenessInvariant:
    """Asegura que cuando el bot presenta una categoría, lista TODOS
    los productos activos de esa categoría.

    Si el LLM omite algún producto (alucinación de omisión por context
    window saturado o bias), reescribe con la lista completa.
    """

    name = "category_completeness"

    async def validate(
        self,
        *,
        candidate_text: str,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str],
        supabase: Any,
        tool_call_log: list[dict],
        inbound_text: str = "",
    ) -> InvariantResult:
        if not candidate_text:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
            )

        # 1. ¿Outbound parece presentar una categoría/lista?
        if not _outbound_presents_category_list(candidate_text):
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="outbound no presenta lista de categoría",
            )

        # 2. ¿Qué categoría está presentando?
        intent = _detect_category_intent(candidate_text)
        if not intent:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="outbound no menciona categoría específica conocida",
            )
        category_label, match_fn = intent

        # 3. Solo aplicar si el cliente PIDIÓ ver la categoría (anti
        # falso-positivo: bot puede mencionar "los sérums" sin que cliente
        # haya pedido la categoría completa).
        client_asked_category = False
        if inbound_text:
            for _, patterns, _ in _CATEGORIES:
                for p in patterns:
                    if p.search(inbound_text):
                        client_asked_category = True
                        break
                if client_asked_category:
                    break

        if not client_asked_category:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="cliente no pidió ver categoría completa en este turno",
            )

        # 4. Cargar catálogo del tenant para comparar.
        try:
            from tools.catalog_tool import get_tenant_catalog
            catalog = await get_tenant_catalog(supabase, tenant_id)
        except Exception:
            catalog = []

        if not catalog:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason="catálogo vacío — no validable",
            )

        # 5. Comparar productos presentes vs faltantes.
        present, missing = _products_in_text(catalog, candidate_text, match_fn)

        if not missing:
            return InvariantResult(
                outcome=InvariantOutcome.OK, invariant_name=self.name,
                reason=f"todos los productos de categoría '{category_label}' "
                f"presentes ({len(present)}/{len(present) + len(missing)})",
            )

        # 6. Hay productos faltantes → REWRITE con lista completa.
        replacement = _build_replacement(category_label, missing, present)
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                f"LLM omitió {len(missing)} productos de categoría "
                f"'{category_label}': {[str(p.get('title')) for p in missing]}. "
                f"Rewrite con catálogo completo."
            ),
        )
