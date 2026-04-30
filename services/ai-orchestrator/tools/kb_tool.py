"""
Knowledge Base Tool — recupera documentos activos del tenant para el contexto del Orchestrator.

Rev. 71 — Las 6 categorías canónicas (CHECK constraint en kb_documents) son:
faq, negocio, politicas, productos, envios, pagos.

El sistema combina RAG semántico (pgvector) con un boost determinístico por
categoría: si el query del cliente toca temas críticos (pagos / envíos /
políticas / productos / garantía), se garantiza que al menos un doc de la
categoría correspondiente entra al contexto, aunque el embedding semántico no
lo haya rankeado top-3. Si el tenant NO tiene docs en esa categoría, se
inyecta un marker explícito para que el LLM responda "no tengo info para
darte una respuesta confiable" en vez de alucinar.
"""
import logging
import re
from supabase import Client

logger = logging.getLogger("orchestrator.tools.kb")

# Categorías canónicas rev. 68 (CHECK constraint en kb_documents).
CATEGORY_LABELS = {
    "faq":       "Preguntas frecuentes",
    "negocio":   "Información del negocio",
    "politicas": "Políticas",
    "productos": "Información de productos",
    "envios":    "Envíos y tarifas",
    "pagos":     "Métodos de pago",
}

# Triggers léxicos por categoría — si el query del cliente coincide, se fuerza
# inyección de un doc de esa categoría aunque el RAG semántico no la priorice.
_CATEGORY_TRIGGERS: dict[str, re.Pattern] = {
    "pagos": re.compile(
        r"\b(pago|pagos|pagar|paga|paguen|pse|tarjeta|nequi|bancolombia|daviplata|"
        r"transferencia|efectivo|cuotas|financiar|financiamiento|debito|credito)\b",
        re.IGNORECASE,
    ),
    "envios": re.compile(
        r"\b(env[ií]o|env[ií]os|env[ií]a|env[ií]an|env[ií]ar|"
        r"despacho|despachos|entrega|entregan|entregar|domicilio|domicilios|"
        r"mensajer[ií]a|cobertura|coordinadora|servientrega|deprisa|"
        r"recogida|recoger|tarifa de env[ií]o|costo de env[ií]o|"
        r"d[ií]as h[aá]biles|tiempo de entrega)\b",
        re.IGNORECASE,
    ),
    "politicas": re.compile(
        r"\b(politica|pol[ií]ticas|devoluci[oó]n|devoluciones|cambio|cambios|"
        r"garantia|garant[ií]a|garantias|garant[ií]as|reclamo|reclamos|rma|"
        r"privacidad|habeas|t[eé]rminos|condiciones)\b",
        re.IGNORECASE,
    ),
    "productos": re.compile(
        r"\b(uso|usar|c[oó]mo se usa|cuidado|cuidados|lavado|lavar|talla|tallas|"
        r"medida|medidas|composici[oó]n|material|materiales|durabilidad)\b",
        re.IGNORECASE,
    ),
    "negocio": re.compile(
        r"\b(qui[eé]nes son|qu[ií]enes somos|historia|fundador|equipo|"
        r"ubicaci[oó]n|aliados|alianzas|trayectoria|experiencia)\b",
        re.IGNORECASE,
    ),
}


def _detect_categories_from_query(query: str) -> list[str]:
    """Devuelve las categorías canónicas detectadas en el query (orden estable)."""
    if not query:
        return []
    detected: list[str] = []
    for cat, pattern in _CATEGORY_TRIGGERS.items():
        if pattern.search(query):
            detected.append(cat)
    return detected


def _fetch_top_doc_by_category(supabase: Client, tenant_id: str, category: str) -> dict | None:
    """Trae el doc más reciente activo de una categoría dada. None si no hay."""
    try:
        res = (
            supabase.table("kb_documents")
            .select("title, content, category")
            .eq("tenant_id", tenant_id)
            .eq("category", category)
            .eq("is_active", True)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return (res.data or [None])[0]
    except Exception as e:
        logger.warning("Error consultando KB por categoría %s: %s", category, e)
        return None


def _missing_category_marker(category: str) -> dict:
    """Documento sintético que avisa al LLM que el tenant no tiene info en esa categoría.
    Evita alucinación: el bot debe escalar/preguntar en vez de inventar."""
    label = CATEGORY_LABELS.get(category, category.capitalize())
    return {
        "title": f"{label} — sin información configurada",
        "content": (
            f"El tenant aún no ha cargado información en la categoría '{label}'. "
            "NO INVENTES respuestas; si el cliente pregunta sobre este tema, indícale "
            "que vas a confirmar con un especialista y registra la consulta para escalar."
        ),
        "category": category,
        "_synthetic_missing": True,
    }

import os
from google import genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
GEMINI_EMBEDDING_FALLBACK_MODEL = os.getenv(
    "GEMINI_EMBEDDING_FALLBACK_MODEL",
    "text-embedding-004",
)


def _embedding_models() -> list[str]:
    models = [GEMINI_EMBEDDING_MODEL]
    fallback = GEMINI_EMBEDDING_FALLBACK_MODEL.strip()
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _is_model_unavailable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "not found" in text
        or "404" in text
        or "not supported" in text
        or "unsupported" in text
    )


def _embed_query_vector(client: genai.Client, query: str) -> list[float]:
    last_error: Exception | None = None
    for model_name in _embedding_models():
        try:
            embed_resp = client.models.embed_content(
                model=model_name,
                contents=query,
            )
            embeddings = getattr(embed_resp, "embeddings", None) or []
            if not embeddings:
                raise ValueError("Embedding sin datos.")
            values = getattr(embeddings[0], "values", None)
            if not values:
                raise ValueError("Embedding vector vacío.")
            if model_name != GEMINI_EMBEDDING_MODEL:
                logger.info(
                    "Embedding KB usando modelo fallback: %s (primario=%s)",
                    model_name,
                    GEMINI_EMBEDDING_MODEL,
                )
            return values
        except Exception as exc:  # pragma: no cover - variación de errores SDK/API
            last_error = exc
            if _is_model_unavailable_error(exc):
                logger.warning(
                    "Modelo de embeddings no disponible (%s). Reintentando con fallback.",
                    model_name,
                )
                continue
            raise

    raise RuntimeError(
        f"No fue posible generar embeddings con modelos {_embedding_models()}"
    ) from last_error

async def get_tenant_kb_rag(supabase: Client, tenant_id: str, query: str) -> list[dict]:
    """Retorna los documentos KB para inyectar al system prompt.

    Estrategia híbrida (rev. 71):
      1. RAG semántico (pgvector top-3 por embeddings).
      2. Boost por categoría: si el query toca tema crítico (pagos/envíos/etc.),
         garantiza al menos un doc de esa categoría en el resultado.
      3. Si el tenant no tiene docs en una categoría triggered, inyecta marker
         "sin información configurada" para forzar escalación cordial vs. alucinación.

    Esto resuelve el caso real observado: un tenant con KB solo en `faq` y
    `negocio` (0 docs en pagos/envíos/políticas/productos) recibía consultas
    transaccionales y el bot inventaba o escalaba sin contexto.
    """
    forced_categories = _detect_categories_from_query(query)
    semantic_docs: list[dict] = []
    if query.strip() and GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            query_vector = _embed_query_vector(client, query)
            result = supabase.rpc(
                "match_kb_documents",
                {
                    "query_embedding": query_vector,
                    "match_threshold": 0.5,
                    "match_count": 3,
                    "t_id": tenant_id,
                },
            ).execute()
            semantic_docs = result.data or []
        except Exception as e:
            logger.warning(f"Error realizando KB RAG para tenant {tenant_id}: {e}")
            semantic_docs = []

    # Boost determinístico por categoría detectada en el query.
    # Si el RAG ya trajo un doc de esa categoría, no se duplica.
    boosted: list[dict] = list(semantic_docs)
    seen_titles = {d.get("title") for d in boosted}
    for cat in forced_categories:
        already_in_semantic = any(d.get("category") == cat for d in boosted)
        if already_in_semantic:
            continue
        top = _fetch_top_doc_by_category(supabase, tenant_id, cat)
        if top and top.get("title") not in seen_titles:
            boosted.append(top)
            seen_titles.add(top.get("title"))
        elif not top:
            # No hay doc en esta categoría — inyectar marker anti-alucinación.
            boosted.append(_missing_category_marker(cat))

    if boosted:
        return boosted
    return _fallback_kb(supabase, tenant_id)

def _fallback_kb(supabase: Client, tenant_id: str) -> list[dict]:
    """Recupera apenas las 3 principales políticas generales en caso de error RAG."""
    result = (
        supabase.table("kb_documents")
        .select("title, content, category")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .order("category")
        .limit(3)
        .execute()
    )
    return result.data or []


def format_kb_for_prompt(documents: list[dict]) -> str:
    """Formatea los documentos KB como texto para inyectar en el system prompt.

    Rev. 78 — Cita de fuentes: cuando se inyecten docs reales (no markers
    sintéticos), se prefija una instrucción al LLM para que cierre la
    respuesta con `_Fuente: <título>_` cuando use la información. Permite
    auditar trazabilidad KB → respuesta y reduce alucinación percibida.
    """
    if not documents:
        return ""

    # Agrupar por categoría manteniendo orden estable canónico.
    by_category: dict[str, list[dict]] = {}
    for doc in documents:
        cat = doc.get("category", "faq")
        by_category.setdefault(cat, []).append(doc)

    canonical_order = ["faq", "negocio", "politicas", "productos", "envios", "pagos"]
    ordered_cats = [c for c in canonical_order if c in by_category] + \
                   [c for c in by_category if c not in canonical_order]

    has_real_docs = any(
        not d.get("_synthetic_missing") for docs in by_category.values() for d in docs
    )
    lines: list[str] = []
    if has_real_docs:
        lines.append(
            "⚙️ INSTRUCCIÓN DE CITA: cuando uses información de algún documento "
            "de esta base, cierra la respuesta con una línea en cursiva del "
            "formato `_Fuente: <título exacto del documento>_`. Si combinas "
            "varios docs, cita los títulos separados por coma. Si la respuesta "
            "no proviene de la KB, NO agregues la línea de fuente."
        )
    for cat in ordered_cats:
        label = CATEGORY_LABELS.get(cat, cat.capitalize())
        lines.append(f"\n### {label}")
        for doc in by_category[cat]:
            if doc.get("_synthetic_missing"):
                # Marker anti-alucinación — formato distinto para que el LLM lo identifique.
                lines.append(f"⚠️ {doc['title']}\n{doc['content']}")
            else:
                lines.append(f"**{doc['title']}**\n{doc['content']}")

    return "\n".join(lines)
