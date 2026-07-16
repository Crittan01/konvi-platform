"""Fixtures del harness DB ejecutable (W4 / T1).

Todas las pruebas de este paquete llevan el marker `dbharness` (registrado en
pyproject) y se EXCLUYEN del run por defecto (`-m 'not dbharness'` en validate.sh),
para no romper la suite de ~3490 tests en máquinas sin Postgres local. Se corren
explícitamente con `-m dbharness` (validate.sh --db-harness / job CI dedicado).
"""
import pytest

from _harness import connect, seed_tenants, cleanup_tenants, harness_available, HARNESS_REQUIRED

# Si psycopg no está instalado (p.ej. el job de unidad en CI, o una VM sin el extra),
# NO colectar estos archivos — sus imports de psycopg romperían la colección del run
# principal `pytest tests/ -m 'not dbharness'`. El job dedicado del harness sí instala
# psycopg + levanta el Postgres.
try:
    import psycopg  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_*.py"]


def pytest_collection_modifyitems(config, items):
    """Marca el paquete como `dbharness`. Si el DB no está:
      • HARNESS_REQUIRED=1 (CI) → HARD FAIL: skip==pass sería un gate que verifica NADA.
      • local sin DB → skip elegante (no rompe la suite de unidad).
    """
    dbh_items = [it for it in items if "dbharness" in str(it.fspath)]
    if not dbh_items:
        return
    for it in dbh_items:
        it.add_marker(pytest.mark.dbharness)
    if harness_available():
        return
    if HARNESS_REQUIRED:
        pytest.exit(
            "HARNESS_REQUIRED=1 pero el harness DB no está disponible — el gate NO puede "
            "reportar verde sin ejecutar las pruebas RLS/escalada/inbox. Levantá el DB "
            "(scripts/dbharness_up.sh) o revisá HARNESS_DB_URL.",
            returncode=1,
        )
    skip = pytest.mark.skip(reason="harness DB no disponible (scripts/dbharness_up.sh)")
    for it in dbh_items:
        it.add_marker(skip)


@pytest.fixture(scope="session")
def db():
    conn = connect(autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def seed(db):
    ids = seed_tenants(db)
    yield ids
    cleanup_tenants(db)
