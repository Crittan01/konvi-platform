"""Todo campo que la consola manda a guardar tiene que existir en el contrato de la API.

ESTE TEST NACE DE UN BUG REAL. La migración #163 creó las columnas de identidad legal y el
formulario las enviaba, pero `TenantPatch` no las tenía. Pydantic **descarta los campos
desconocidos en silencio**, así que la API respondía 200 y no guardaba nada: el comerciante
veía "guardado" y al recargar seguía vacío. No había forma de notarlo salvo probándolo a
mano.

El test lee los payloads REALES de `settings/actions.ts` (las llamadas a `updateTenant`) y
verifica que cada clave exista en el modelo. Cualquier campo que se agregue a la consola sin
agregarlo al contrato cae acá.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
API = REPO / "services" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

ACTIONS = REPO / "apps" / "web" / "app" / "dashboard" / "(settings-group)" / "settings" / "actions.ts"


def _claves_que_manda_la_consola() -> set[str]:
    """Claves de cada objeto pasado a `updateTenant(tenantId, { ... })`."""
    texto = ACTIONS.read_text()
    claves: set[str] = set()
    for m in re.finditer(r"updateTenant\(tenantId,\s*\{", texto):
        # Recorre balanceando llaves desde la apertura del objeto.
        i = texto.index("{", m.start())
        nivel, j = 0, i
        while j < len(texto):
            if texto[j] == "{":
                nivel += 1
            elif texto[j] == "}":
                nivel -= 1
                if nivel == 0:
                    break
            j += 1
        cuerpo = texto[i + 1:j]
        # Solo el primer nivel: `shipping_origin: { ... }` cuenta como shipping_origin.
        prof = 0
        for linea in cuerpo.split("\n"):
            if prof == 0:
                k = re.match(r"\s*([a-z_][a-z0-9_]*)\s*[,:]", linea)
                if k:
                    claves.add(k.group(1))
            prof += linea.count("{") + linea.count("[") - linea.count("}") - linea.count("]")
    return claves


def test_el_extractor_encuentra_algo():
    """Si el extractor dejara de matchear, el test de abajo pasaría verificando nada."""
    claves = _claves_que_manda_la_consola()
    assert len(claves) >= 15, f"solo {len(claves)} claves — el extractor se rompió"
    assert "name" in claves and "shipping_origin" in claves


def test_todo_lo_que_manda_la_consola_existe_en_el_contrato():
    """El bug de #163: campos que la web enviaba y la API descartaba en silencio."""
    from routers.settings import TenantPatch

    en_contrato = set(TenantPatch.model_fields.keys())
    enviadas = _claves_que_manda_la_consola()
    faltantes = sorted(enviadas - en_contrato)
    assert faltantes == [], (
        "la consola manda campos que la API DESCARTA EN SILENCIO (200 OK sin guardar): "
        + ", ".join(faltantes)
    )


def test_la_identidad_legal_completa_esta_en_el_contrato():
    """Los 11 campos que hacen identificable al vendedor en el comprobante
    (Ley 1480 art. 50 lit. a)."""
    from routers.settings import TenantPatch

    en_contrato = set(TenantPatch.model_fields.keys())
    for campo in ("tipo_persona", "razon_social", "doc_tipo", "doc_numero", "doc_dv",
                  "regimen_iva", "domicilio_direccion", "domicilio_ciudad",
                  "domicilio_departamento", "email_habeas_data"):
        assert campo in en_contrato, f"falta {campo} en TenantPatch"


def test_los_valores_invalidos_fallan_con_422_no_con_error_de_postgres():
    """Los Literal replican los CHECK de la tabla: el comerciante debe ver un mensaje
    explicable, no un constraint violation."""
    from pydantic import ValidationError
    from routers.settings import TenantPatch

    for campo, malo in [("tipo_persona", "empresa"), ("doc_tipo", "RUT"),
                        ("regimen_iva", "simplificado")]:
        with pytest.raises(ValidationError):
            TenantPatch(**{campo: malo})


def test_los_valores_validos_pasan():
    from routers.settings import TenantPatch

    p = TenantPatch(tipo_persona="natural", doc_tipo="CC", doc_numero="1020304050",
                    regimen_iva="no_responsable", email_habeas_data="datos@kaiu.co")
    d = p.model_dump(exclude_unset=True)
    assert d["tipo_persona"] == "natural" and d["doc_numero"] == "1020304050"


def test_el_documento_rechaza_letras():
    """El formulario limpia puntos y guiones, pero el frontend no es seguridad."""
    from pydantic import ValidationError
    from routers.settings import TenantPatch

    with pytest.raises(ValidationError):
        TenantPatch(doc_numero="900123ABC")


def test_el_dv_es_un_solo_digito():
    from pydantic import ValidationError
    from routers.settings import TenantPatch

    TenantPatch(doc_dv="7")
    with pytest.raises(ValidationError):
        TenantPatch(doc_dv="77")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
