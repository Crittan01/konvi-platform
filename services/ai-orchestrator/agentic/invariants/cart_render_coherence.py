"""Invariant CONSOLIDADO: coherencia render cart + catálogo (rev. 108 cleanup).

Founder feedback 2026-05-27 — "arquitectura sobrecargada". Consolidación
de 3 invariants relacionados con cart/catalog rendering:
  • CartStateInvariant — LLM afirma cart pero tool NO ejecutó / mismatch counts
  • CartAddPricingInvariant — add_to_cart success sin precio/subtotal en outbound
  • CategoryCompletenessInvariant — bot omite productos al listar categoría

Una sola pipeline 4-case con priorización determinística. Comparte
state loading (cart DB, catalog DB) entre cases — más eficiente que 3
invariants independientes.

Pattern: validate() ejecuta cases en orden. Primer match → REWRITE.
Si ningún case match → OK.

NO machetazo — refactor arquitectónico que preserva 100% del coverage
original. Reduce 753 → ~450 LOC y elimina 3 archivos.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from agentic.invariants.base import (
    InvariantOutcome,
    InvariantResult,
)


# ─── Patterns: detección de afirmaciones cart ─────────────────────────────

# Verbos de afirmación cart-write (agregar, añadir, sumar — todas conjugaciones).
_CART_AFFIRM_PATTERNS = (
    re.compile(r"\bagreg(?:o|as|a|amos|an|u[eé]|[oó]|ando|ar[eé]|aste)\b", re.IGNORECASE),
    re.compile(r"\ba[nñ]ad(?:o|es|e|imos|en|[ií]|i[oó]|iendo|ir[eé])\b", re.IGNORECASE),
    re.compile(r"\bsum(?:o|as|a|amos|an|[eé]|[oó]|ando|ar[eé])\b", re.IGNORECASE),
    re.compile(r"\blisto[,.\s]\s*(?:\d+\s*x?\s*)", re.IGNORECASE),
    re.compile(r"\bagregado\s+a\s+tu\s+(?:carrito|pedido|orden)\b", re.IGNORECASE),
    re.compile(r"\bte\s+vend[oa]\b", re.IGNORECASE),
    re.compile(r"\bqued(?:o|a|an|[oó]|aron)\s+(?:agregad|sumad|a[nñ]adid)[oa]s?\b", re.IGNORECASE),
)

# Anchors de inicio de bloque "Agregué X" (para reemplazar SOLO ese bloque).
_ADD_BLOCK_PATTERN = re.compile(
    r"^\s*(?:[¡!]?\s*Listo[\!\.\,]?\s*)?"
    r"(?:Agregu[eé]|He agregado|A[ñn]ad[ií])"
    r"[^\n]*(?:\n\s*[\*\-•][^\n]+)*",
    re.IGNORECASE | re.MULTILINE,
)

# Anchors de afirmación cart (para Case B: contar items afirmados).
_CART_ANCHORS = (
    re.compile(r"\b(?:ya\s+)?(?:agregu[eé]|sum[eé]|a[nñ]ad[ií])\b", re.IGNORECASE),
    re.compile(r"\bhe\s+agregado\b", re.IGNORECASE),
    re.compile(r"\btu\s+(?:carrito|pedido|orden)\s+(?:incluye|contiene|tiene|actual)\b", re.IGNORECASE),
    re.compile(r"\b(?:pedido|carrito)\s+actual[:\s]", re.IGNORECASE),
    re.compile(r"\blisto[,.]?\s*\d", re.IGNORECASE),
    re.compile(r"\bqued(?:ó|aron)\s+(?:agregad|sumad)", re.IGNORECASE),
)

# Anchors de presentación variantes/carriers (NO son items del cart).
_VARIANT_PRESENTATION_ANCHORS = (
    re.compile(r"\bpresentacion(?:es)?\b", re.IGNORECASE),
    re.compile(r"\bcu[aá]l\s+(?:te|presentaci[oó]n|prefieres|escoges|eliges)", re.IGNORECASE),
    re.compile(r"\btenemos\s+est[ao]s?\b", re.IGNORECASE),
    re.compile(r"\bopciones?\s+disponibles?", re.IGNORECASE),
    re.compile(r"\bopciones?\s+de\s+env[ií]o", re.IGNORECASE),
    re.compile(r"\bpara\s+(?:el\s+)?env[ií]o\s+a\b", re.IGNORECASE),
    re.compile(r"\btransportador(?:a|as)\s+disponibles?", re.IGNORECASE),
    re.compile(r"\bcarriers?\s+disponibles?", re.IGNORECASE),
    re.compile(
        r"\b(?:COORDINADORA|SERVIENTREGA|ENVIA|INTERRAPIDISIMO|TCC|"
        r"DOMINA|SAFERBO|99\s?MINUTOS|GO\s?ENVIOS)\b.*\$",
        re.IGNORECASE | re.DOTALL,
    ),
)


# ─── Patterns: categorías ──────────────────────────────────────────────────

# Categorías canónicas + función matcher producto.
_CATEGORIES = [
    ("sérum", [re.compile(r"\bs[eé]rum(?:es|s)?\b", re.IGNORECASE)],
     lambda title: "serum" in title.lower() or "sérum" in title.lower()),
    ("jabón", [re.compile(r"\bjab[oó]n(?:es)?\b", re.IGNORECASE)],
     lambda title: "jabon" in title.lower() or "jabón" in title.lower()),
    ("aceite", [re.compile(r"\baceites?\b", re.IGNORECASE)],
     lambda title: "aceite" in title.lower()),
    ("kit", [re.compile(r"\bkits?\b", re.IGNORECASE)],
     lambda title: "kit" in title.lower()),
]

# Anchors de presentación de categoría (lista).
_CATEGORY_LIST_ANCHORS = (
    re.compile(r"\b(?:tenemos|aqu[ií]\s+est[aá]n|estos?\s+son|estas?\s+son)\b", re.IGNORECASE),
    re.compile(r"\bopciones?\s+disponibles?\b", re.IGNORECASE),
    re.compile(r"\b(?:te\s+(?:cuento|presento|muestro)\s+(?:lo|las|los|todas))\b", re.IGNORECASE),
    re.compile(r"\bdisponibles?\b", re.IGNORECASE),
    re.compile(r"\n\s*[\*\-•]\s+[\*_]?[A-Z]", re.MULTILINE),
)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _format_cop(cop: int) -> str:
    return f"${int(cop):,}".replace(",", ".")


def _llm_affirms_cart_change(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _CART_AFFIRM_PATTERNS)


def _cart_write_succeeded(tool_call_log: list[dict]) -> Optional[dict]:
    """Returns el último add_to_cart success, o None."""
    write_tools = {"add_to_cart", "update_cart_item_quantity", "remove_cart_item"}
    for call in reversed(tool_call_log or []):
        if call.get("name") in write_tools or call.get("tool") in write_tools:
            result = call.get("result") or {}
            if "error" not in result and result.get("added"):
                return result
    return None


def _count_successful_cart_writes(tool_call_log: list[dict]) -> int:
    write_tools = {"add_to_cart", "update_cart_item_quantity", "remove_cart_item"}
    count = 0
    for call in tool_call_log or []:
        if call.get("name") in write_tools or call.get("tool") in write_tools:
            if "error" not in (call.get("result") or {}):
                count += 1
    return count


def _any_cart_write_executed(tool_call_log: list[dict]) -> bool:
    return _count_successful_cart_writes(tool_call_log) > 0


def _count_items_affirmed_in_text(text: str) -> int:
    """Cuenta bullets ENTRE ancla cart-write y ancla variant-presentation."""
    if not text:
        return 0
    lines = text.split("\n")
    cart_anchor_idx = None
    variant_anchor_idx = None
    for i, line in enumerate(lines):
        if cart_anchor_idx is None and any(p.search(line) for p in _CART_ANCHORS):
            cart_anchor_idx = i
        elif cart_anchor_idx is not None and variant_anchor_idx is None \
                and any(p.search(line) for p in _VARIANT_PRESENTATION_ANCHORS):
            variant_anchor_idx = i
    if cart_anchor_idx is None:
        return 0
    end_idx = variant_anchor_idx if variant_anchor_idx is not None else len(lines)
    count = 0
    for line in lines[cart_anchor_idx:end_idx]:
        stripped = line.strip()
        if not stripped or not (stripped.startswith(("*", "•", "-"))):
            continue
        if "$" in stripped or re.search(r"\b\d+\s*x?\b", stripped):
            count += 1
    return count


async def _get_cart_state(
    supabase: Any, conversation_id: str, tenant_id: str,
) -> tuple[int, dict]:
    """Returns (items_count, cart_row) o (0, {})."""
    try:
        cart_q = (
            supabase.table("conversation_carts")
            .select("id, subtotal_cents, total_cents")
            .eq("conversation_id", conversation_id)
            .eq("tenant_id", tenant_id)
            .eq("status", "open")
            .limit(1).execute()
        )
        if not cart_q.data:
            return (0, {})
        cart_row = cart_q.data[0]
        items_res = (
            supabase.table("conversation_cart_items")
            .select("id")
            .eq("cart_id", cart_row["id"]).execute()
        )
        return (len(items_res.data or []), cart_row)
    except Exception:
        return (0, {})


def _outbound_has_price(text: str) -> bool:
    return bool(re.search(r"\$\s?\d", text or ""))


def _outbound_has_subtotal(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(
        r"\b(?:subtotal|total\s+(?:del\s+)?(?:carrito|cart|pedido))\b",
        text, re.IGNORECASE,
    ))


def _detect_category_intent(text: str) -> Optional[tuple]:
    if not text:
        return None
    for label, patterns, match_fn in _CATEGORIES:
        for p in patterns:
            if p.search(text):
                return (label, match_fn)
    return None


def _outbound_presents_category_list(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _CATEGORY_LIST_ANCHORS)


def _products_in_text(
    catalog: list[dict], text: str, match_fn,
) -> tuple[list[dict], list[dict]]:
    text_lower = (text or "").lower()
    matched_in_cat = [p for p in catalog if match_fn(str(p.get("title") or ""))]
    present, missing = [], []
    for p in matched_in_cat:
        title = str(p.get("title") or "").lower()
        title_words = [w for w in title.split() if len(w) > 4 and w not in ("artesanal", "natural", "esencial")]
        if title in text_lower:
            present.append(p)
        elif title_words and any(w in text_lower for w in title_words):
            present.append(p)
        else:
            missing.append(p)
    return present, missing


# ─── Replacement builders ──────────────────────────────────────────────────


def _build_case_a_replacement() -> str:
    """LLM afirmó cart-write SIN tool ejecutado — replacement neutral."""
    return (
        "Cuéntame de nuevo qué producto y presentación quieres y te "
        "lo agrego al carrito enseguida."
    )


def _build_case_b_replacement(items_added_this_turn: int) -> str:
    """LLM afirmó MÁS items que el cart real."""
    return (
        f"Logré agregar {items_added_this_turn} item(s) al "
        "carrito. Hubo un inconveniente con el otro item. "
        "¿Podrías repetir cuál te interesa y en qué presentación?"
    )


def _build_pricing_replacement(
    add_result: dict, cart_row: dict, original_text: str,
) -> str:
    """add_to_cart success sin precio/subtotal → enriquecer outbound."""
    added = add_result.get("added") or {}
    title = str(added.get("title") or "Producto")
    variant = str(added.get("variant_label") or "").strip()
    qty = int(added.get("quantity") or 1)
    unit_price = int(added.get("unit_price_cop") or 0)
    line_total = unit_price * qty
    subtotal = int(cart_row.get("subtotal_cents") or 0) // 100

    variant_part = f" de {variant}" if variant else ""
    if qty > 1:
        enriched = (
            f"Agregué {qty} *{title}*{variant_part} a tu carrito por "
            f"{_format_cop(line_total)} ({_format_cop(unit_price)} c/u)."
        )
    else:
        enriched = (
            f"Agregué 1 *{title}*{variant_part} a tu carrito por "
            f"{_format_cop(line_total)}."
        )
    subtotal_line = f"Subtotal: *{_format_cop(subtotal)}*."

    if not original_text:
        return f"{enriched}\n{subtotal_line}"

    match = _ADD_BLOCK_PATTERN.search(original_text)
    if match:
        before = original_text[:match.start()].rstrip()
        after = original_text[match.end():].lstrip()
        result = enriched + "\n" + subtotal_line
        if before:
            result = before + "\n\n" + result
        if after:
            result = result + "\n\n" + after
        return result
    return f"{enriched}\n{subtotal_line}\n\n{original_text}"


def _build_category_completeness_replacement(
    category_label: str, missing: list[dict], present: list[dict],
) -> str:
    """LLM omitió productos al listar categoría → lista compacta completa."""
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


# ─── Invariant principal ───────────────────────────────────────────────────


class CartRenderCoherenceInvariant:
    """Invariant CONSOLIDADO: coherencia render cart + catálogo.

    4 cases verificados en orden:
      A. LLM afirma cart-write SIN tool ejecutado → REWRITE neutral.
      B. Items afirmados > items reales del cart → REWRITE específico.
      C. add_to_cart success pero outbound sin precio/subtotal → ENRICH.
      D. Bot lista categoría pero omite productos del catálogo → REWRITE
         con lista compacta completa.
    """

    name = "cart_render_coherence"

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

        # ── CASE A: LLM afirma cart sin tool ejecutado ─────────────────
        if _llm_affirms_cart_change(candidate_text):
            if not _any_cart_write_executed(tool_call_log):
                return InvariantResult(
                    outcome=InvariantOutcome.REWRITE,
                    invariant_name=self.name,
                    replacement_text=_build_case_a_replacement(),
                    reason="CASE A: LLM afirmó cart sin tool exitoso",
                )

            # ── CASE B: items afirmados > items en cart real ──────────
            items_affirmed = _count_items_affirmed_in_text(candidate_text)
            if items_affirmed >= 2:
                cart_items_count, _ = await _get_cart_state(
                    supabase, conversation_id, tenant_id,
                )
                if cart_items_count is not None and items_affirmed > cart_items_count:
                    return InvariantResult(
                        outcome=InvariantOutcome.REWRITE,
                        invariant_name=self.name,
                        replacement_text=_build_case_b_replacement(
                            _count_successful_cart_writes(tool_call_log),
                        ),
                        reason=(
                            f"CASE B: affirmed={items_affirmed} > "
                            f"cart_real={cart_items_count}"
                        ),
                    )

        # ── CASE C: add_to_cart success sin precio + subtotal ─────────
        # Skip si en el MISMO turno el bot llamó list_catalog (mostrando
        # variantes de OTRO producto) — el outbound mezcla contextos:
        # "agregué X" + "para Y presentaciones $52K/$85K". CASE C no debe
        # forzar subtotal aquí porque los precios pertenecen a variantes,
        # no al item agregado. Coherencia: Case B ya valida items count.
        add_result = _cart_write_succeeded(tool_call_log)
        if add_result and add_result.get("added"):
            also_listed_variants = any(
                (call.get("tool") or "") in {"list_catalog", "send_product_image"}
                for call in (tool_call_log or [])
            )
            if not also_listed_variants:
                has_price = _outbound_has_price(candidate_text)
                # CASE C fire condition: outbound afirma add_to_cart pero
                # NO incluye precio alguno ($). Si ya muestra precios por
                # línea o subtotal explícito, lo dejamos pasar (suficiente
                # transparencia comercial).
                if not has_price:
                    _, cart_row = await _get_cart_state(
                        supabase, conversation_id, tenant_id,
                    )
                    if cart_row:
                        return InvariantResult(
                            outcome=InvariantOutcome.REWRITE,
                            invariant_name=self.name,
                            replacement_text=_build_pricing_replacement(
                                add_result, cart_row, candidate_text,
                            ),
                            reason="CASE C: add_to_cart success sin precio en outbound",
                        )

        # ── CASE D: categoría con productos omitidos ──────────────────
        if _outbound_presents_category_list(candidate_text):
            intent = _detect_category_intent(candidate_text)
            client_asked = False
            if inbound_text and intent:
                for _, patterns, _ in _CATEGORIES:
                    for p in patterns:
                        if p.search(inbound_text):
                            client_asked = True
                            break
                    if client_asked:
                        break
            if intent and client_asked:
                category_label, match_fn = intent
                try:
                    from tools.catalog_tool import get_tenant_catalog
                    catalog = await get_tenant_catalog(supabase, tenant_id)
                except Exception:
                    catalog = []
                if catalog:
                    present, missing = _products_in_text(catalog, candidate_text, match_fn)
                    if missing:
                        return InvariantResult(
                            outcome=InvariantOutcome.REWRITE,
                            invariant_name=self.name,
                            replacement_text=_build_category_completeness_replacement(
                                category_label, missing, present,
                            ),
                            reason=(
                                f"CASE D: categoría '{category_label}' "
                                f"omitió {len(missing)} productos"
                            ),
                        )

        return InvariantResult(
            outcome=InvariantOutcome.OK, invariant_name=self.name,
            reason="cart + catálogo render coherente",
        )
