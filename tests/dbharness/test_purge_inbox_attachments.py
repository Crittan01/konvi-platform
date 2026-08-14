"""G8a — erasure de adjuntos inbox en fn_purge_tenant_storage_objects.

Antes la RPC solo borraba storage.objects con name '{tenant_id}/%' → los
adjuntos de conversación ('inbox-attachments/{tenant_id}/%') SOBREVIVÍAN al
hard-delete del tenant (fuga PII post-erasure). Ahora borra ambos prefijos.

Ejecutable contra Postgres real (harness). Si el schema storage no existe en
el entorno (Postgres vanilla en CI), el test crea uno SINTÉTICO mínimo — la
RPC usa solo storage.buckets(id) + storage.objects(bucket_id, name), así que
la LÓGICA (los 2 prefijos + aislamiento por tenant) queda ejercida igual.
"""
import psycopg
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness

# UUIDs hex-válidos (un UUID no acepta caracteres fuera de 0-9a-f).
_TENANT = "8a000000-0000-0000-0000-000000000001"
_OTHER = "8a000000-0000-0000-0000-000000000002"
_BUCKET = "g8a-bucket"


def _storage_disponible(cur) -> bool:
    cur.execute("SELECT to_regclass('storage.objects') IS NOT NULL")
    return cur.fetchone()[0]


def _storage_sintetico(cur) -> None:
    """Schema storage mínimo si el harness no trae Supabase Storage."""
    cur.execute("CREATE SCHEMA IF NOT EXISTS storage")
    cur.execute(
        "CREATE TABLE IF NOT EXISTS storage.buckets ("
        "  id text PRIMARY KEY, name text NOT NULL, public boolean DEFAULT false)"
    )
    cur.execute(
        "CREATE TABLE IF NOT EXISTS storage.objects ("
        "  id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bucket_id text, name text, owner uuid)"
    )


def _seed(cur):
    """Filas fake: ambos prefijos del tenant objetivo + ambos del otro tenant."""
    cur.execute(
        "INSERT INTO storage.buckets (id, name, public) VALUES (%s, %s, true) "
        "ON CONFLICT (id) DO NOTHING",
        (_BUCKET, _BUCKET),
    )
    for name in (
        f"{_TENANT}/logo/x.png",
        f"inbox-attachments/{_TENANT}/conv-1/adj.png",
        f"{_OTHER}/logo/y.png",
        f"inbox-attachments/{_OTHER}/conv-9/z.png",
    ):
        cur.execute(
            "INSERT INTO storage.objects (id, bucket_id, name, owner) "
            "VALUES (gen_random_uuid(), %s, %s, NULL) ON CONFLICT DO NOTHING",
            (_BUCKET, name),
        )


def _count(cur) -> dict[str, int]:
    cur.execute(
        "SELECT name FROM storage.objects WHERE bucket_id = %s", (_BUCKET,)
    )
    rows = [r[0] for r in cur.fetchall()]
    return {
        "tenant": sum(1 for n in rows if n.startswith(f"{_TENANT}/") or n.startswith(f"inbox-attachments/{_TENANT}/")),
        "other": sum(1 for n in rows if n.startswith(f"{_OTHER}/") or n.startswith(f"inbox-attachments/{_OTHER}/")),
    }


def _purge(cur, tenant: str) -> int:
    cur.execute(
        "SELECT public.fn_purge_tenant_storage_objects(%s::uuid, %s::text[])",
        (tenant, [_BUCKET]),
    )
    return cur.fetchone()[0]


@pytest.fixture
def storage(db):
    with db.cursor() as cur:
        if not _storage_disponible(cur):
            _storage_sintetico(cur)
        _purge(cur, _TENANT)  # limpieza vía la RPC (SECURITY DEFINER puede
        _purge(cur, _OTHER)   # borrar; el DELETE directo está prohibido)
        _seed(cur)
    yield
    with db.cursor() as cur:
        _purge(cur, _TENANT)
        _purge(cur, _OTHER)


def test_purge_borra_ambos_prefijos_solo_del_tenant(storage, db):
    with db.cursor() as cur:
        assert _count(cur) == {"tenant": 2, "other": 2}
        # Con el bucket DEFAULT (tenant-media) no toca el bucket de prueba:
        cur.execute("SELECT public.fn_purge_tenant_storage_objects(%s::uuid)", (_TENANT,))
        assert _count(cur) == {"tenant": 2, "other": 2}
        deleted = _purge(cur, _TENANT)
        after = _count(cur)
    assert deleted == 2, f"la RPC reportó {deleted} borradas (esperaba 2)"
    assert after == {"tenant": 0, "other": 2}


def test_purge_solo_afecta_al_tenant_objetivo(storage, db):
    with db.cursor() as cur:
        deleted = _purge(cur, _TENANT)
        after = _count(cur)
    assert deleted == 2
    assert after["tenant"] == 0
    assert after["other"] == 2  # el otro tenant intacto (aislamiento)


def test_idempotente_segunda_corrida_cero(storage, db):
    with db.cursor() as cur:
        _purge(cur, _TENANT)
        deleted = _purge(cur, _TENANT)
    assert deleted == 0
