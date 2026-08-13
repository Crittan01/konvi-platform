"""Fuente única del manifest CONNECTOR_OWNED para el split de tests por dominio de pins.

Lo consumen `tests/conftest.py` (aplica el marker `connector`) y
`tests/test_connector_split_guard.py` (guard anti-drift). Ver conftest.py para el porqué.
"""
import pathlib
import re

_TESTS_DIR = pathlib.Path(__file__).resolve().parent

# Tests cuyo código bajo prueba es EXCLUSIVAMENTE del connector-whatsapp → leg del
# connector. HISTÓRICO: el split nació cuando el connector pinneaba fastapi 0.128.8 y
# divergía del core; desde 2026-08-13 (G28) los 3 servicios comparten pins (0.139.x) —
# la atribución por dominio se conserva porque la protege el guard y desambigúa a qué
# servicio pertenece cada test. Los pact/parity que cargan fuente de varios servicios vía
# importlib (test_phone_helpers_pact) o son orch-only con el connector en un comentario
# (test_multimodal_audio) NO son connector-owned → van a core.
CONNECTOR_OWNED = frozenset({
    "test_a11_wh01_verified_tenant.py",
    "test_db_persistence_reopen.py",
    "test_f53_connector_no_blocking_io.py",
    "test_meta_hmac_model_b.py",
    "test_template_events_handlers.py",
    "test_whatsapp_parser_context.py",
})


def connector_only_by_scan():
    """Archivos de tests/ cuyo ÚNICO servicio referenciado es el connector-whatsapp
    (heurística que derivó el manifest). Oráculo del guard anti-drift."""
    out = set()
    for f in _TESTS_DIR.rglob("test_*.py"):
        if "dbharness" in str(f):
            continue
        src = f.read_text(errors="ignore")
        svcs = {m.group(1) for m in re.finditer(
            r"services/(api|ai-orchestrator|connector-whatsapp)", src)}
        if svcs == {"connector-whatsapp"}:
            out.add(f.name)
    return out
