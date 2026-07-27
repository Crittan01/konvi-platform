"""Domain filter — out-of-domain Meta Policy compliance.

Rev. 104 (F1-1) — extraído de orchestrator.py.

Cobertura:
  • Healthcare/Medical: Meta Healthcare Policy + Ley 23/1981 Colombia (ejercicio
    ilegal de medicina). Bot redirige a profesional, NO afirma curaciones.
  • Drugs/Pharmaceuticals: Meta Commerce Policy prohíbe Rx + OTC en WhatsApp.
    Bot redirige a droguería/farmacia.

Detectores son funciones puras sobre texto normalizado. Vertical-agnósticos:
ningún tenant puede dar consejo médico ni vender medicamentos por WhatsApp,
sin importar si vende cosmética, tecnología, comida, etc.

Public API:
  • `detect_medical_query(text) -> bool`
  • `detect_drug_purchase_request(text) -> bool`
  • Constantes públicas: `MEDICAL_QUERY_PHRASES`, `DRUG_PURCHASE_PHRASES`.

Tests: `tests/test_safety_domain_filter.py`.
"""
from __future__ import annotations

import unicodedata as _ud


# ─── Frases canónicas (referenciadas por orchestrator + tests) ──────────────

MEDICAL_QUERY_PHRASES: tuple[str, ...] = (
    # Enfermedades dermatológicas/sistémicas comunes
    "acne", "rosacea", "eczema", "psoriasis", "dermatitis",
    "vitiligo", "alopecia", "celulitis", "infeccion", "infección",
    "herpes", "verruga", "queratosis", "melanoma", "lupus",
    "diabetes", "hipertension", "hipertensión", "cancer", "cáncer",
    "tumor", "asma", "hepatitis", "vih", "sida",
    # Lenguaje de diagnóstico/tratamiento
    "me diagnostic", "diagnosticar", "diagnostico", "diagnóstico",
    "que enfermedad tengo", "qué enfermedad tengo",
    "tratamiento para", "que tratamiento", "qué tratamiento",
    "cura ", "curar ", "cura el", "cura la", "cura mi",
    "trata el", "trata la", "trata mi", "tratar el", "tratar la",
    "es seguro en embaraz", "puedo usar embaraz",
    "estoy embaraz", "lactanc", "amamantar",
    "soy alergic", "es alergic", "tengo alergia", "alergia a",
    "sintoma", "síntoma",
    "receta medica", "receta médica",
    "doctor recom", "medico recom", "médico recom",
    "que medicament", "qué medicament",
    # Consultas tipo "este producto sirve para X enfermedad"
    "sirve para tratar", "sirve para curar",
    "es bueno para mi", "remedio para",
)


DRUG_PURCHASE_PHRASES: tuple[str, ...] = (
    # Genéricos populares (Rx + OTC)
    "ibuprofeno", "acetaminofen", "acetaminofén", "paracetamol",
    "aspirina", "naproxeno", "diclofenaco", "loratadina", "cetirizina",
    "amoxicilina", "azitromicina", "penicilina",
    "antibiotico", "antibiótico", "antibióticos",
    "antidepresiv", "ansiolítico", "ansiolitico",
    "viagra", "cialis", "anticonceptiv",
    "morfina", "tramadol", "oxicodona", "codeina", "codeína",
    "ritalin", "metilfenidato",
    # Genéricos genéricos
    "medicamento", "medicamentos", "remedio para el dolor",
    "pastilla para", "pastillas para", "tableta para",
    "vendes medic", "venden medic",
)


# ─── Helper interno: normalizador local (evita import circular) ─────────────

def _normalize(text: str) -> str:
    """Lowercase + sin acentos + espacios colapsados.

    Replica el comportamiento de `text_utils.normalize_text` localmente
    para que `safety/` sea independiente del módulo `text_utils` (evita
    import circular cuando orchestrator importe safety y safety necesita
    text_utils que orchestrator también importa).
    """
    if not text:
        return ""
    norm = _ud.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(norm.lower().split())


# ─── Public detectors ────────────────────────────────────────────────────────

def detect_medical_query(text: str) -> bool:
    """True si el cliente hace consulta médica/diagnóstica que el bot
    NO debe responder.

    Cobertura Meta Business Policy + Ley 23 de 1981 Colombia (ejercicio
    ilegal de medicina). El bot debe redirigir a profesional médico,
    nunca afirmar que un producto cura/trata una condición clínica.

    Conservador: si hay duda, redirigir es mejor que arriesgar claim
    médico ilegal o ban de Meta.
    """
    if not text:
        return False
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in MEDICAL_QUERY_PHRASES)


def hay_algo_mas_en_el_turno(text: str) -> bool:
    """True si, además de lo que disparó la guarda, el cliente preguntó otra cosa.

    POR QUÉ EXISTE
    La guarda de consultas médicas corta ANTES del LLM y marca el mensaje como procesado.
    Eso es correcto —el bot no puede opinar de salud— pero se lleva por delante el resto
    del turno. En el recorrido E2E del 2026-07-27 la clienta escribió:

        "y sirve para el melasma? mi dermatologa me dijo que tengo eso.
         tambien buscaba shampoo solido, manejan?"

    Recibió el redirect médico y **nadie le respondió lo del shampoo**. Preguntado aparte,
    el bot lo contesta perfecto: no es que no sepa, es que no lo vio.

    La señal es deliberadamente tonta y determinística —dos preguntas, o una frase nueva
    después de un punto— porque la alternativa sería un clasificador, y meter interpretación
    en una guarda de seguridad es cómo se debilita la guarda. Un falso positivo solo agrega
    una línea invitando a repetir la pregunta; no baja el filtro ni deja pasar nada al LLM.
    """
    if not text:
        return False
    if text.count("?") >= 2:
        return True
    # Una oración más, con contenido real, después de un cierre de frase.
    cola = text.split(".")[-1].strip() if "." in text else ""
    return len(cola) >= 20


def detect_drug_purchase_request(text: str) -> bool:
    """True si el cliente intenta comprar/conseguir un medicamento.

    Meta Commerce Policy prohíbe la venta de Rx y OTC en WhatsApp.
    Bot redirige a droguería/farmacia.
    """
    if not text:
        return False
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in DRUG_PURCHASE_PHRASES)
