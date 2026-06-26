"""Invariant determinístico: el bot NUNCA afirma falsamente que un producto está
disponible en SOLO algunas presentaciones (o niega una variante) cuando el
catálogo real tiene MÁS variantes EN STOCK.

Causa raíz (conversación +573125835649, 2026-06-26): en estados post-carrito
(PAYMENT / CARRIER_SELECTION) el prompt OMITE el catálogo (`_NO_CATALOG_STATES`
en agentic/prompt/builder.py). Cuando el cliente pidió agregar un "Sérum de
Vitamina C" a mitad del checkout, el LLM NO tenía las variantes en contexto y
FABRICÓ "solo lo tenemos en 30ml", cuando la 15ml existe con stock=10. Eso viola
el principio #4 del proyecto (el LLM no decide verdad transaccional).

Este guard cierra el hueco en TODO estado FSM: aunque el catálogo no esté en el
prompt, el invariant lo consulta como fuente de verdad y reescribe el claim falso.

Diseño per ADR-0024 (binario/determinístico, NO parser NLP semántico):
  1. Pre-check regex BARATO: ¿el outbound contiene un marcador restrictivo
     ("solo/únicamente/solamente …" o una negación de disponibilidad)? Si NO →
     OK inmediato, sin tocar la DB (mantiene el hot-path rápido).
  2. Si SÍ: cargar catálogo real (get_tenant_catalog) — fuente de verdad.
  3. Identificar el producto mencionado por overlap de tokens significativos
     del título (decidible, sin NLP).
  4. SET difference determinística: variantes EN STOCK del producto vs variantes
     mencionadas en el texto. Si hay variantes en stock NO mencionadas y hay un
     marcador restrictivo → el bot restringió falsamente → REWRITE a la verdad.

NO interviene: outbounds sin marcador restrictivo; productos sin match de título;
productos con ≤1 variante en stock; o cuando TODAS las variantes en stock ya se
mencionan (el bot dijo la verdad completa).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from agentic.invariants.base import InvariantOutcome, InvariantResult
from tools.catalog_contract import CATALOG_VARIATIONS_KEY

# Dos marcadores determinísticos (se evalúan sobre texto YA normalizado, sin
# acentos, por eso no llevan variantes á/é):
#   • EXCLUSIVIDAD ("solo X") → implica que SOLO las variantes mencionadas existen
#     → las variantes en stock NO mencionadas quedan falsamente excluidas.
#   • NEGACIÓN ("no tenemos … <variante>") → niega explícitamente una variante.
# Pre-check barato: si NINGUNO aparece, el outbound no afirma exclusividad → OK sin DB.
_EXCLUSIVITY = re.compile(
    r"\b(?:solo|solamente|unicamente|nada\s+mas)\b"
)
_NEGATION = re.compile(
    r"\bno\s+(?:lo\s+|la\s+)?(?:tenemos|hay|manejamos|manejo|contamos|disponib\w*|"
    r"trabajamos|maneja\w*|tiene|tenia|teniamos|hubo|queda\w*)\b"
)
# Negación + (hasta 30 chars) → si una variante en stock cae en esa ventana, está
# explícitamente negada.
_NEG_WINDOW = 30

_STOPWORDS = frozenset({
    "de", "con", "para", "del", "al", "la", "el", "los", "las", "un", "una",
    "y", "o", "en", "por", "su", "lo",
})


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _norm(s: str) -> str:
    """minúsculas + sin acentos + colapsa espacios + une unidad al número
    ('15 ml' → '15ml') para matching determinístico de etiquetas de variante."""
    t = re.sub(r"\s+", " ", _strip_accents(str(s or "")).lower()).strip()
    return re.sub(r"(\d)\s+(ml|g|gr|kg|lt?|oz|cc)\b", r"\1\2", t)


def _significant_tokens(title: str) -> list[str]:
    """Tokens ≥4 chars del título (sin stopwords) para identificar el producto."""
    return [
        t for t in _norm(title).split()
        if len(t) >= 4 and t not in _STOPWORDS
    ]


def _label_appears(label: str, norm_text: str) -> bool:
    """¿La etiqueta de variante (ej. '15ml') aparece en el texto? Tolerante a
    espacio ('15 ml') comparando ambos sin espacios."""
    nl = _norm(label)
    if not nl:
        return False
    nl_nospace = nl.replace(" ", "")
    text_nospace = norm_text.replace(" ", "")
    return nl in norm_text or nl_nospace in text_nospace


def _fmt_price(price: float) -> str:
    return f"${int(float(price or 0)):,}".replace(",", ".")


class VariantAvailabilityAssertionInvariant:
    """Reescribe claims falsos de exclusividad de presentación/variante."""

    name = "variant_availability_assertion"

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
        ok = InvariantResult(outcome=InvariantOutcome.OK, invariant_name=self.name)
        if not candidate_text or not candidate_text.strip():
            return ok

        norm_text = _norm(candidate_text)

        # (1) Pre-check barato: sin exclusividad NI negación no hay claim restrictivo.
        exclusivity = bool(_EXCLUSIVITY.search(norm_text))
        neg_ends = [m.end() for m in _NEGATION.finditer(norm_text)]
        if not exclusivity and not neg_ends:
            return ok

        # (2) Catálogo real — fuente de verdad (solo se consulta si pasó el pre-check).
        try:
            from tools.catalog_tool import get_tenant_catalog
            catalog = await get_tenant_catalog(supabase, tenant_id)
        except Exception:
            return ok  # ante fallo de DB no rompemos el outbound (degradación segura)
        if not catalog:
            return ok

        # (3) Identificar el producto mencionado por overlap de tokens del título.
        matched = None
        best_overlap = 0
        for product in catalog:
            sig = _significant_tokens(str(product.get("title") or ""))
            if not sig:
                continue
            overlap = sum(1 for t in sig if t in norm_text)
            # Match fuerte: TODOS los tokens significativos del título presentes.
            if overlap == len(sig) and overlap > best_overlap:
                matched, best_overlap = product, overlap
        if matched is None:
            return ok

        # (4) Variantes EN STOCK del producto vs mencionadas en el texto.
        variants = matched.get(CATALOG_VARIATIONS_KEY) or []
        in_stock = [
            v for v in variants
            if int(v.get("stock") or 0) > 0
            and str(v.get("label") or "").strip()
            and float(v.get("price") or 0) > 0
        ]
        if len(in_stock) <= 1:
            return ok  # nada que restringir falsamente

        def _denied(label: str) -> bool:
            """¿La etiqueta cae dentro de la ventana posterior a una negación?
            ('no lo tenemos en 15ml' → 15ml negada)."""
            nl = _norm(label).replace(" ", "")
            if not nl:
                return False
            for ne in neg_ends:
                window = norm_text[ne:ne + _NEG_WINDOW].replace(" ", "")
                if nl in window:
                    return True
            return False

        # Una variante en stock está FALSAMENTE excluida si:
        #   (a) está explícitamente negada ("no tenemos … 15ml"), o
        #   (b) hay marcador de exclusividad ("solo …") y NO se menciona.
        falsely_excluded = []
        for v in in_stock:
            label = str(v.get("label"))
            mentioned = _label_appears(label, norm_text)
            if _denied(label) or (exclusivity and not mentioned):
                falsely_excluded.append(v)

        if not falsely_excluded:
            return ok

        listing = ", ".join(
            f"{str(v.get('label')).strip()} ({_fmt_price(v.get('price'))})"
            for v in in_stock
        )
        title = str(matched.get("title") or "el producto").strip()
        replacement = (
            f"El *{title}* lo tenemos disponible en: {listing}. "
            f"¿Cuál presentación prefieres?"
        )
        return InvariantResult(
            outcome=InvariantOutcome.REWRITE,
            invariant_name=self.name,
            replacement_text=replacement,
            reason=(
                f"claim restrictivo falso sobre '{title}': "
                f"variantes en stock falsamente excluidas = "
                f"{[str(v.get('label')) for v in falsely_excluded]}"
            ),
        )
