"""Resolución de ciudad/destino DANE para el cotizador (extraído de
tools/shipping_quote_tool.py — G12). Lee el dataset canónico dane-colombia.ts
(apps/web) y resuelve ciudad mencionada en texto libre → destino estructurado.
Extraído verbatim 2026-08-13 — comportamiento idéntico.
"""
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from text_utils import normalize_text as _normalize_text  # noqa: F401

logger = logging.getLogger("orchestrator.tools.shipping_geo")


_DANE_SOURCE_FILE = Path(__file__).resolve().parents[3] / "apps" / "web" / "lib" / "dane-colombia.ts"


@lru_cache(maxsize=1)
def _load_city_index() -> dict[str, list[dict[str, str]]]:
    """
    Carga índice de municipios CO desde apps/web/lib/dane-colombia.ts.
    Estructura: { city_normalized: [{city, state, dane_code}, ...] }.
    """
    if not _DANE_SOURCE_FILE.exists():
        logger.warning("No se encontró catálogo DANE en %s", _DANE_SOURCE_FILE)
        return {}

    try:
        source = _DANE_SOURCE_FILE.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("No se pudo leer catálogo DANE: %s", exc)
        return {}

    city_index: dict[str, list[dict[str, str]]] = {}
    dept_pattern = re.compile(
        r"\{\s*codigo:\s*'(?P<dep_code>\d+)'\s*,\s*nombre:\s*'(?P<dep_name>[^']+)'\s*,\s*municipios:\s*\[(?P<munis>.*?)\]\s*,?\s*\}",
        re.DOTALL,
    )
    muni_pattern = re.compile(
        r"\{\s*codigo:\s*'(?P<code>\d{5})'\s*,\s*nombre:\s*'(?P<name>[^']+)'\s*\}"
    )

    for dep in dept_pattern.finditer(source):
        dept_name = dep.group("dep_name").strip()
        munis_blob = dep.group("munis")
        for muni in muni_pattern.finditer(munis_blob):
            city_name = muni.group("name").strip()
            dane_code = muni.group("code")
            city_norm = _normalize_text(city_name)
            
            aliases = [city_norm]
            if " d.c." in city_norm:
                aliases.append(city_norm.replace(" d.c.", ""))
            if " (distrito capital)" in city_norm:
                aliases.append(city_norm.replace(" (distrito capital)", ""))
            if "bogota" in city_norm:
                aliases.append("bogota") # Catch-all por si las dudas
                
            for alias in set(aliases):
                city_index.setdefault(alias, []).append(
                    {
                        "city": city_name,
                        "state": dept_name,
                        "dane_code": dane_code,
                    }
                )

    return city_index


@lru_cache(maxsize=1)
def _city_names_by_length_desc() -> list[str]:
    return sorted(_load_city_index().keys(), key=len, reverse=True)


def _find_city_entries_in_text(normalized_query: str) -> list[dict[str, str]]:
    city_index = _load_city_index()
    if not city_index or not normalized_query:
        return []

    matches: list[dict[str, str]] = []
    for city_norm in _city_names_by_length_desc():
        if len(city_norm) < 3:
            continue
        pattern = rf"(^|\b){re.escape(city_norm)}(\b|$)"
        if not re.search(pattern, normalized_query):
            continue
        entries = city_index.get(city_norm, [])
        if not entries:
            continue
        matches.extend(entries)
        # El match más largo suele ser suficiente para destino conversacional.
        break
    return matches


def _destination_from_city_entry(entry: dict[str, str]) -> dict[str, str]:
    return {
        "city": entry["city"],
        "state": entry["state"],
        "country": "CO",
        "postalCode": entry["dane_code"],
        "dane_code": entry["dane_code"],
    }


def _resolve_destination_from_query(query_text: str) -> tuple[Optional[dict], Optional[str]]:
    """
    Intenta resolver destino desde texto libre.
    Retorna:
    - (destination, None) si resolvió
    - (None, city_name) si ciudad detectada pero ambigua (requiere depto)
    - (None, None) si no pudo resolver ciudad
    """
    normalized_query = _normalize_text(query_text)
    entries = _find_city_entries_in_text(normalized_query)
    if not entries:
        return None, None

    # Deduplicar por dane_code (en caso de alias redundantes)
    unique_dane = {}
    for e in entries:
        unique_dane[e["dane_code"]] = e
    entries = list(unique_dane.values())

    if len(entries) == 1:
        return _destination_from_city_entry(entries[0]), None

    # Si la ciudad aparece en múltiples departamentos, intentar desambiguar
    # por departamento mencionado explícitamente en el mensaje.
    narrowed = []
    for entry in entries:
        state_norm = _normalize_text(entry["state"])
        if state_norm and state_norm in normalized_query:
            narrowed.append(entry)

    if len(narrowed) == 1:
        return _destination_from_city_entry(narrowed[0]), None

    return None, entries[0]["city"]
