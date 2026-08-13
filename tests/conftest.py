"""conftest raíz — atribución de tests por DOMINIO de servicio.

Contexto histórico: los 3 servicios Python NO compartían versión (`api`/`ai-orchestrator`
en fastapi 0.139.x; el `connector` una minor atrás) y el CI instalaba todo en UN venv
(el connector se instalaba último y GANABA) → testeaba api/orch bajo la versión del
connector, NO bajo la de prod (#77, #134). G28 (2026-08-13) ALINEÓ los 3 servicios al
mismo set de pins → el venv compartido ya no diverge; el marker `connector` se conserva
como atribución de dominio (qué test ejercita qué servicio), protegida del drift por
tests/test_connector_split_guard.py. Ver docs/reports/ci_sec_hardening_2026_07_24.md §4.

Este hook aplica el marker `connector` a los tests connector-only (fuente de verdad:
connector_manifest.CONNECTOR_OWNED); el leg core del CI selecciona `-m 'not connector'`.
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
