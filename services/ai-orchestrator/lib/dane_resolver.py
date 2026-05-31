"""DANE resolver — resuelve código DIVIPOLA 5 dígitos desde nombre de ciudad.

Reusa el catálogo canónico `apps/web/lib/dane-colombia.ts` (33 deptos + ~1103
municipios DIVIPOLA DANE). El parsing es defensivo: si el archivo no existe o no
parsea, retorna "" — el caller decide si bloquea o continúa.

Caso de uso primario rev. 109: `wompi_webhook` requiere DANE numérico para
`aveonline_client.generate_guide()` cuando `contact.address.dane_code` está NULL.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_DANE_TS_CATALOG = (
    Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "dane-colombia.ts"
)


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower()


@lru_cache(maxsize=1)
def _load_index() -> dict[str, list[dict[str, str]]]:
    if not _DANE_TS_CATALOG.exists():
        return {}
    try:
        source = _DANE_TS_CATALOG.read_text(encoding="utf-8")
    except Exception:
        return {}

    dept_pat = re.compile(
        r"\{\s*codigo:\s*'(?P<dep_code>\d+)'\s*,\s*nombre:\s*'(?P<dep_name>[^']+)'\s*,\s*municipios:\s*\[(?P<munis>.*?)\]\s*,?\s*\}",
        re.DOTALL,
    )
    muni_pat = re.compile(
        r"\{\s*codigo:\s*'(?P<code>\d{5})'\s*,\s*nombre:\s*'(?P<name>[^']+)'\s*\}"
    )

    idx: dict[str, list[dict[str, str]]] = {}
    for dep in dept_pat.finditer(source):
        dept_name = dep.group("dep_name").strip()
        for muni in muni_pat.finditer(dep.group("munis")):
            city_name = muni.group("name").strip()
            code = muni.group("code")
            norm = _normalize(city_name)
            aliases = {norm}
            if " d.c." in norm:
                aliases.add(norm.replace(" d.c.", ""))
            if "bogota" in norm:
                aliases.add("bogota")
            for alias in aliases:
                idx.setdefault(alias, []).append(
                    {"city": city_name, "state": dept_name, "dane_code": code}
                )
    return idx


def resolve_dane_from_city(city: str | None, state: str | None = None) -> str:
    """Retorna DANE 5 dígitos o "" si no encuentra. Si `state` se provee,
    desambigua entre ciudades homónimas (e.g. "San José" en múltiples deptos).
    Acepta None/"" gracefully (retorna "")."""
    norm = _normalize(city)
    if not norm:
        return ""
    matches = _load_index().get(norm, [])
    if not matches:
        return ""
    if state:
        state_norm = _normalize(state)
        for m in matches:
            if _normalize(m["state"]) == state_norm:
                return m["dane_code"]
    return matches[0]["dane_code"]
