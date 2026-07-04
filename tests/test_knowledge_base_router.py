"""
Tests del router /api/v1/knowledge-base — CRUD con embedding server-side.

Cierra el gap "0 tests de endpoints" (F5). Cubre, sin tocar red ni DB real:
  - Validación pura: _validate_category, _strip_embedding, _embedding_to_pgvector,
    KbDocCreate / KbDocPatch (límites de longitud).
  - TestClient con FakeSupabase (in-memory) y embed_kb_document mockeado:
      * cap 409 SOLO sobre docs activos (desactivar/eliminar libera cupo)
      * categoría inválida → 422
      * RBAC → 403
      * reindex sin embedding disponible → 502
      * soft-delete: is_active=False + embedding NULL, fila persiste
      * fallback embedding NULL al crear (Gemini caído) → 201 sin embedding
      * embedding_model_version se escribe al indexar (columna antes fantasma)
"""
import os
import sys
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "service-key")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("GEMINI_API_KEY", "test-key")

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import routers.knowledge_base as kb  # noqa: E402
from routers.knowledge_base import (  # noqa: E402
    KbDocCreate,
    KbDocPatch,
    _embedding_to_pgvector,
    _strip_embedding,
    _validate_category,
)

TENANT = "tenant-1"


# ─── Fake Supabase in-memory ────────────────────────────────────────────────

class FakeResult:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class FakeQuery:
    def __init__(self, tables, name):
        self.tables = tables
        self.name = name
        self._filters = []
        self._op = None
        self._payload = None
        self._count = False
        self._single = False
        self._limit = None

    def select(self, *args, count=None):
        self._op = "select"
        self._count = count == "exact"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def maybe_single(self):
        self._single = True
        return self

    def _match(self, row):
        return all(row.get(c) == v for c, v in self._filters)

    def execute(self):
        rows = self.tables[self.name]
        if self._op == "insert":
            row = dict(self._payload)
            row.setdefault("id", f"doc-{len(rows) + 1}")
            # Postgres devuelve TODAS las columnas en la representación (incl. NULLs).
            row.setdefault("embedding", None)
            rows.append(row)
            return FakeResult(data=[dict(row)])
        matched = [r for r in rows if self._match(r)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
            return FakeResult(data=[dict(r) for r in matched])
        # select
        if self._count:
            return FakeResult(data=None, count=len(matched))
        if self._single:
            return FakeResult(data=(dict(matched[0]) if matched else None))
        data = [dict(r) for r in matched]
        if self._limit:
            data = data[: self._limit]
        return FakeResult(data=data)


class FakeSupabase:
    def __init__(self, tables=None):
        self.tables = defaultdict(list)
        if tables:
            for k, v in tables.items():
                self.tables[k] = v

    def table(self, name):
        return FakeQuery(self.tables, name)


def make_client(kb_rows=None, role="owner", vec=(0.1, 0.2, 0.3)):
    """App con router aislado + deps mockeadas. Retorna (client, fake_supabase)."""
    fake = FakeSupabase({"kb_documents": list(kb_rows or [])})
    app = FastAPI()
    app.include_router(kb.router, prefix="/api/v1/knowledge-base")

    app.dependency_overrides[kb.get_current_tenant] = lambda: TENANT
    app.dependency_overrides[kb.get_service_client] = lambda: fake
    app.dependency_overrides[kb.RL_WRITE_DEFAULT] = lambda: None

    if role in ("owner", "manager"):
        app.dependency_overrides[kb.require_write_role] = lambda: role
    else:
        def _deny():
            raise HTTPException(status_code=403, detail="No autorizado")
        app.dependency_overrides[kb.require_write_role] = _deny

    client = TestClient(app)
    client._fake = fake  # type: ignore[attr-defined]
    client._vec = list(vec) if vec else None
    return client, fake


def _doc(idx, active=True, embedding="[0.1]"):
    return {
        "id": f"seed-{idx}",
        "tenant_id": TENANT,
        "title": f"Doc {idx}",
        "content": f"Contenido {idx}",
        "category": "faq",
        "is_active": active,
        "embedding": embedding,
    }


# ─── Validación pura ────────────────────────────────────────────────────────

class PureValidationTests(unittest.TestCase):
    def test_valid_category_passes(self):
        for c in ["faq", "negocio", "politicas", "productos", "envios", "pagos"]:
            self.assertIsNone(_validate_category(c))

    def test_legacy_category_rejected(self):
        for c in ["general", "politica", "producto"]:
            with self.assertRaises(HTTPException) as ctx:
                _validate_category(c)
            self.assertEqual(ctx.exception.status_code, 422)

    def test_strip_embedding_sets_has_embedding(self):
        clean = _strip_embedding({"id": "x", "embedding": "[0.1]"})
        self.assertNotIn("embedding", clean)
        self.assertTrue(clean["has_embedding"])
        clean_null = _strip_embedding({"id": "x", "embedding": None})
        self.assertFalse(clean_null["has_embedding"])

    def test_pgvector_format(self):
        self.assertEqual(_embedding_to_pgvector([0.1, 0.2]), "[0.1,0.2]")

    def test_create_rejects_overlong_title(self):
        with self.assertRaises(ValidationError):
            KbDocCreate(title="x" * 121, content="ok")

    def test_create_rejects_empty_content(self):
        with self.assertRaises(ValidationError):
            KbDocCreate(title="ok", content="")

    def test_patch_all_optional(self):
        p = KbDocPatch(is_active=False)
        self.assertFalse(p.is_active)
        self.assertIsNone(p.title)


# ─── Endpoints (TestClient) ─────────────────────────────────────────────────

class EndpointTests(unittest.TestCase):
    def _post(self, client, body):
        with patch.object(kb, "embed_kb_document", return_value=client._vec):
            return client.post("/api/v1/knowledge-base/", json=body)

    def test_cap_409_counts_only_active(self):
        # 30 activos → bloqueado.
        rows = [_doc(i) for i in range(30)]
        client, _ = make_client(rows)
        r = self._post(client, {"title": "Nuevo", "content": "algo", "category": "faq"})
        self.assertEqual(r.status_code, 409)
        self.assertIn("activos", r.json()["detail"])

    def test_cap_frees_when_inactive(self):
        # 29 activos + 10 inactivos → aún hay cupo (el cap cuenta solo activos).
        rows = [_doc(i) for i in range(29)] + [_doc(100 + i, active=False) for i in range(10)]
        client, fake = make_client(rows)
        r = self._post(client, {"title": "Nuevo", "content": "algo", "category": "pagos"})
        self.assertEqual(r.status_code, 201, r.text)

    def test_invalid_category_422(self):
        client, _ = make_client([])
        r = self._post(client, {"title": "X", "content": "Y", "category": "general"})
        self.assertEqual(r.status_code, 422)

    def test_rbac_403(self):
        client, _ = make_client([], role="operator")
        r = self._post(client, {"title": "X", "content": "Y", "category": "faq"})
        self.assertEqual(r.status_code, 403)

    def test_create_writes_model_version(self):
        client, fake = make_client([])
        r = self._post(client, {"title": "X", "content": "Y", "category": "faq"})
        self.assertEqual(r.status_code, 201, r.text)
        row = fake.tables["kb_documents"][-1]
        self.assertIn("embedding_model_version", row)
        self.assertTrue(row["embedding_model_version"])

    def test_create_fallback_null_embedding(self):
        # Gemini caído → embed_kb_document None → doc se persiste sin embedding.
        client, fake = make_client([], vec=None)
        r = self._post(client, {"title": "X", "content": "Y", "category": "faq"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertFalse(r.json()["has_embedding"])
        row = fake.tables["kb_documents"][-1]
        self.assertIsNone(row.get("embedding"))
        self.assertIsNone(row.get("embedding_model_version"))

    def test_soft_delete_semantics(self):
        rows = [_doc(1)]
        client, fake = make_client(rows)
        r = client.delete("/api/v1/knowledge-base/seed-1")
        self.assertEqual(r.status_code, 200, r.text)
        row = fake.tables["kb_documents"][0]
        self.assertFalse(row["is_active"])
        self.assertIsNone(row["embedding"])

    def test_reindex_502_when_embed_unavailable(self):
        rows = [_doc(1, embedding=None)]
        client, _ = make_client(rows)
        with patch.object(kb, "embed_kb_document", return_value=None):
            r = client.post("/api/v1/knowledge-base/seed-1/reindex")
        self.assertEqual(r.status_code, 502)

    def test_reindex_writes_model_version_and_strips_embedding(self):
        rows = [_doc(1, embedding=None)]
        client, fake = make_client(rows)
        with patch.object(kb, "embed_kb_document", return_value=[0.1, 0.2, 0.3]):
            r = client.post("/api/v1/knowledge-base/seed-1/reindex")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("embedding", r.json())  # no fuga de 3072 floats
        self.assertTrue(r.json()["indexed"])
        self.assertTrue(fake.tables["kb_documents"][0]["embedding_model_version"])

    def test_reindex_404_missing_doc(self):
        client, _ = make_client([])
        with patch.object(kb, "embed_kb_document", return_value=[0.1]):
            r = client.post("/api/v1/knowledge-base/nope/reindex")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
