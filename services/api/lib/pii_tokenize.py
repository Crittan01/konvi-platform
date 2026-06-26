"""Rev. 96 — Helpers para tokenización de PII (document_number).

Espejo del SQL de la migración 20260506010000_pii_tokenization.sql:
mismas reglas de normalización + hash → coherencia entre código Python
y triggers en DB. Cualquier cambio en una de las dos partes debe
sincronizarse.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

_DOC_NORMALIZE_RE = re.compile(r"[\s\-\.]")


def normalize_document(doc: Optional[str]) -> Optional[str]:
    """Strip whitespace/dashes/dots, uppercase. Return None for empty."""
    if doc is None:
        return None
    s = _DOC_NORMALIZE_RE.sub("", str(doc)).upper()
    return s or None


def document_hash(doc: Optional[str]) -> Optional[str]:
    """Sha256 hex del documento normalizado."""
    norm = normalize_document(doc)
    if norm is None:
        return None
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def document_last4(doc: Optional[str]) -> Optional[str]:
    """Últimos 4 caracteres del documento normalizado."""
    if doc is None:
        return None
    s = _DOC_NORMALIZE_RE.sub("", str(doc))
    if not s:
        return None
    return s[-4:]


def mask_document(doc: Optional[str]) -> Optional[str]:
    """Display-friendly: '****1234' para UI."""
    last4 = document_last4(doc)
    if last4 is None:
        return None
    return "*" * 4 + last4
