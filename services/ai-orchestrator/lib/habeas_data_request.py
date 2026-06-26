"""Detector determinístico de solicitudes de DERECHOS DE DATOS (Habeas Data Ley 1581).

Cierre estructural #3 del mapa de cobertura: el opt-out por keyword (whatsapp_optout)
solo capta STOP/BAJA. Las solicitudes NO-keyword de derechos de datos ("borren mis
datos", "retiro mi consentimiento", "derecho al olvido") caían al LLM sin resolver
pre-LLM ni side-effect garantizado → exposición legal real en todos los estados.

Diseño SEGURO (per Ley 1581): este detector NO auto-ejecuta borrados (un DSR exige
verificación de identidad + respuesta en plazo legal). Garantiza el side-effect
correcto: ESCALAR a humano + ACUSAR recibo. El backend DSR vive en
services/api/routers/data_subject_request.py; un asesor lo tramita.

Determinístico (ADR-0024): regex de frases ESPECÍFICAS ("mis datos" + verbo de
supresión/revocación, o términos legales inequívocos). Substring (no fullmatch) porque
son frases dentro de oraciones. Falso-positivo erra hacia ESCALAR (dirección segura).
"""
from __future__ import annotations

import re
from typing import Optional

_DATA_RIGHTS_PATTERNS = [
    # Revocación de consentimiento / objeción al tratamiento
    r"retir[oa]\w*\b.{0,15}\bconsentimiento",
    r"revoc[oa]\w*\b.{0,15}\b(consentimiento|autorizaci[oó]n)",
    r"no\s+autoriz[oa]\w*\b.{0,20}\btratamiento",
    r"no\s+quiero\s+que\s+\w*\s*(guarden|usen|traten|tengan|almacenen)\b.{0,15}\bmis\s+datos",
    r"dej[ea]n?\s+de\s+(usar|tratar|guardar)\b.{0,15}\bmis\s+datos",
    # Supresión / derecho al olvido
    r"(borr[ea]\w*|elimin[ea]\w*)\b.{0,20}\bmis\s+datos",
    r"(borr[ea]\w*|elimin[ea]\w*)\b.{0,20}\bmi\s+(informaci[oó]n|cuenta)",
    r"derecho\s+al\s+olvido",
    r"quiero\s+que\s+(borren|eliminen)\b.{0,20}\b(mis\s+datos|mi\s+informaci[oó]n)",
    # Acceso a datos
    r"qu[eé]\s+datos\s+(tienen|guardan|almacenan)\b.{0,12}\b(de\s+m[ií]|m[ií]os)",
    r"(ver|acceder\s+a|copia\s+de)\b.{0,8}\bmis\s+datos\s+personales",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _DATA_RIGHTS_PATTERNS]

# Acuse de recibo (Ley 1581): registra + escala a humano + recuerda STOP para
# el caso simple de dejar de recibir mensajes.
DATA_RIGHTS_ACK_TEXT = (
    "Recibimos tu solicitud sobre tus datos personales. La registramos y un "
    "asesor la atenderá conforme a la Ley 1581 de Habeas Data. Si solo querías "
    "dejar de recibir mensajes, también puedes responder *STOP* cuando quieras."
)

DATA_RIGHTS_AUDIT_REASON = "Solicitud Habeas Data detectada en conversación (no-keyword)"


def detect_data_rights_request(text: Optional[str]) -> Optional[str]:
    """Retorna la frase que disparó (para audit) si el texto contiene una
    solicitud de derechos de datos; None en caso contrario."""
    if not text or not isinstance(text, str):
        return None
    for p in _COMPILED:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def is_data_rights_request(text: Optional[str]) -> bool:
    return detect_data_rights_request(text) is not None
