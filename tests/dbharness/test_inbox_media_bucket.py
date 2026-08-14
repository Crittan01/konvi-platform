"""G8b fase 1 — bucket privado tenant-inbox-media (adjuntos de conversación).

Verifica contra Postgres real (harness): el bucket existe con public=FALSE +
límite 5MB + MIMEs de imagen, y sus 3 policies RLS (write member / read member
/ delete owner|manager). El schema storage sintético de otros tests no aplica
aquí — este test requiere el Supabase real del harness (skip si no está).
"""
import psycopg
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness


@pytest.fixture
def cur_db(db):
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('storage.buckets') IS NOT NULL")
        if not cur.fetchone()[0]:
            pytest.skip("schema storage no existe en este entorno")
        yield cur


def test_bucket_privado_con_limites(cur_db):
    cur_db.execute(
        "SELECT public, file_size_limit, allowed_mime_types "
        "FROM storage.buckets WHERE id = 'tenant-inbox-media'"
    )
    row = cur_db.fetchone()
    assert row is not None, "bucket tenant-inbox-media no existe (migración G8b no aplicada)"
    public, size_limit, mimes = row
    assert public is False, "el bucket de adjuntos inbox debe ser PRIVADO"
    assert size_limit == 5242880
    assert set(mimes) == {"image/jpeg", "image/png", "image/webp"}


def test_policies_rls_del_bucket(cur_db):
    cur_db.execute(
        "SELECT policyname, cmd FROM pg_policies "
        "WHERE schemaname = 'storage' AND tablename = 'objects' "
        "  AND policyname LIKE 'inbox_media_%'"
    )
    policies = {name: cmd for name, cmd in cur_db.fetchall()}
    assert set(policies) == {
        "inbox_media_tenant_write",
        "inbox_media_tenant_read",
        "inbox_media_tenant_delete",
    }, f"policies presentes: {set(policies)}"
    assert policies["inbox_media_tenant_write"] == "INSERT"
    assert policies["inbox_media_tenant_read"] == "SELECT"
    assert policies["inbox_media_tenant_delete"] == "DELETE"


def test_bucket_tenant_media_sigue_publico_para_catalogo(cur_db):
    """Regresión: el catálogo/logo SIGUEN públicos (el bot los reenvía por
    WhatsApp todo el tiempo — privatizarlos rompería el envío de producto)."""
    cur_db.execute(
        "SELECT public FROM storage.buckets WHERE id = 'tenant-media'"
    )
    row = cur_db.fetchone()
    assert row is not None
    assert row[0] is True, "tenant-media debe seguir público (catálogo/logo)"
