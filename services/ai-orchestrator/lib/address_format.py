"""Fuente única de render de dirección (contacts.address JSONB) a una línea.

Consolida los renderizadores divergentes previos (F32 fullstack-review 2026-07-03):
known_customer._format_address (FUENTE — la más rica/robusta, con back-compat para
contactos sin building_type), orchestrator._format_address_for_summary y el bloque
CONTEXTO_CLIENTE, agentic/system_prompt, agentic/tools/contact.GetContactInfoTool,
agentic/invariants/summary_coherence._format_address_compact. Mismo patrón
single-source que lib/phone_format. SOLO presenta (no valida ni canonicaliza).

Cuerpo extraído verbatim de tools/known_customer_tool._format_address.
"""
from __future__ import annotations


def format_address_line(address: dict) -> str:
    """Renderiza contacts.address humanamente a una sola línea.

    Diferencia semántica de `apartment` según building_type:
      • conjunto+casas → "Casa #X".
      • oficina → "Oficina X" (+ "Piso Y" si floor).
      • edificio → "Apto X" (+ "Piso Y" si floor).
      • conjunto torres → "Torre X" + "Apto Y".
      • casa → solo street + ciudad.

    Anexa "Empresa: X" cuando building_type='oficina' + company_name.
    """
    if not isinstance(address, dict):
        return ""
    parts: list[str] = []
    street = (address.get("street") or "").strip()
    if street:
        parts.append(street)
    if address.get("complex_name"):
        parts.append(str(address["complex_name"]).strip())

    building_type = (address.get("building_type") or "").strip().lower()
    conjunto_type = (address.get("conjunto_type") or "").strip().lower()
    floor = str(address.get("floor") or "").strip()
    company_name = (address.get("company_name") or "").strip()

    # Torre / Manzana cuando aplica.
    # Sem 7 F2 cierre 2026-05-20 (D4) — `tower` reusado como Manzana/Bloque
    # cuando conjunto_type='casas'.
    if address.get("tower"):
        _tower_raw = str(address['tower']).strip()
        if not building_type:
            # Back-compat: contacto antiguo con tower pero sin building_type.
            parts.append(f"Torre {_tower_raw}")
        elif building_type == "conjunto" and conjunto_type == "casas":
            _tlow = _tower_raw.lower()
            if _tlow.startswith("manzana") or _tlow.startswith("bloque"):
                parts.append(_tower_raw)
            else:
                parts.append(f"Manzana {_tower_raw}")
        elif building_type == "conjunto" and conjunto_type != "casas":
            parts.append(f"Torre {_tower_raw}")

    # Piso visible solo para edificio y oficina.
    if floor and building_type in {"edificio", "oficina"}:
        parts.append(f"Piso {floor}")

    # Unit label: Casa # / Oficina / Apto según building_type.
    # Default = "Apto" (back-compat para contactos legacy sin building_type).
    if address.get("apartment"):
        unit_value = str(address["apartment"]).strip()
        if building_type == "conjunto" and conjunto_type == "casas":
            unit_label = f"Casa #{unit_value}"
        elif building_type == "oficina":
            unit_label = f"Oficina {unit_value}"
        else:
            unit_label = f"Apto {unit_value}"
        parts.append(unit_label)

    if address.get("neighborhood"):
        parts.append(str(address["neighborhood"]).strip())
    if address.get("city"):
        parts.append(str(address["city"]).strip())

    # Anexar empresa si building_type='oficina'.
    if building_type == "oficina" and company_name:
        parts.append(f"Empresa: {company_name}")

    return " — ".join(p for p in parts if p)
