"""conftest raíz — split de tests por DOMINIO DE PINS (venv por servicio en CI).

Contexto: los 3 servicios Python NO comparten versión. `api` y `ai-orchestrator` pinnean
fastapi 0.139.0 / pydantic 2.13.4 / supabase 2.31.0 (idénticos, "core"); el `connector`
diverge (0.128.8 / 2.12.5 / 2.28.3). El CI histórico instalaba los 3 en UN venv (el
connector se instalaba último y GANABA) → testeaba api/orch bajo la versión del connector,
NO bajo la de prod (#77, #134). Ver docs/reports/ci_sec_hardening_2026_07_24.md §4 y
reference_ci_shared_venv_dep_coupling.

Este hook aplica el marker `connector` a los tests connector-only (fuente de verdad:
connector_manifest.CONNECTOR_OWNED) para que el leg del CI que corre bajo el venv del
connector (0.139) seleccione `-m connector`, y el leg core `-m 'not connector'`. La
atribución vive en UN solo lugar y el guard (tests/test_connector_split_guard.py) la
protege del drift.
"""
import pathlib

import pytest

from connector_manifest import CONNECTOR_OWNED


def pytest_collection_modifyitems(config, items):
    """Marca con `connector` los items de los archivos de CONNECTOR_OWNED (sin tocar cada
    archivo — la fuente de verdad es el manifest)."""
    for item in items:
        if pathlib.Path(str(item.fspath)).name in CONNECTOR_OWNED:
            item.add_marker(pytest.mark.connector)
