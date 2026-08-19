"""M18 — cobertura de services/api/routers/marketplace.py.

Complementa a test_p15_marketplace_adapter_seam.py (seam del adapter en
sync_meli_stock) y test_marketplace_body_validation.py (modelos Pydantic):
aquí se ejercitan los ENDPOINTS y helpers con Supabase y MeLi mockeados
(cero I/O real), invocando los handlers directamente (el decorator audit_log
es fire-and-forget y tolera request=None):

  • _resolve_variations_for_put — sin variaciones / sin mapeo exacto / hermanos
    con verdad local (Supabase) vs fallback al GET de MeLi.
  • sync_meli_stock — sin listing, sin token, item closed (marca local), fallo
    del GET de verificación (sigue con variaciones vacías), fallo del update de
    pull-fields (warning, no rompe), error externo (falla silente).
  • GET /listings — clamp de paginación, no conectado, sin items, enriquecido
    de vínculos/variantes, skip de entries no-200, 502 ante error MeLi.
  • POST /link — 400 meli_id vacío, 404 variante, 400 sin token, 409 duplicado,
    500 genérico, happy path con enriquecido (y enriquecido tolerante a fallo).
  • DELETE /link/{id} — 404 / ok.
  • PATCH /{id}/status — 404 / 400 sin token / 502 MeLi / happy.
  • PATCH /{id}/sync-stock — 404 listing, 400 sin variante, 404 variante, 400
    sin token, 502 GET, 409 closed (marca local), 502 PUT, happy (item simple y
    con variaciones hermanas → array del PUT).
  • POST /import + _import_meli_item — guards, rollbacks (producto/variante),
    409 previo, happy paths (con/sin compare_at_price y cover).
  • POST /import-bulk — guards, dedup+normalización, buckets imported/skipped/errors.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEXT_PUBLIC_SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SECRET_KEY", "service-role")
os.environ.setdefault("SUPABASE_JWT_SECRET", "jwt-secret")
os.environ.setdefault("SUPABASE_SECRET_KEY", "k")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import HTTPException  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from routers import marketplace  # noqa: E402
from routers.marketplace import (  # noqa: E402
    ImportBody,
    ImportBulkBody,
    LinkListingBody,
    ListingStatusBody,
)

TENANT = "t1"


# ─── Fake Supabase (patrón _Chain/_FakeSb de test_p15, extendido) ────────────

class _Chain:
    """Cadena Supabase mínima: select/insert/update/delete + eq/in_/single."""

    def __init__(self, table, sb):
        self._t = table
        self._sb = sb
        self._op = "select"
        self._one = False
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self, *a, **k):
        self._op = "delete"
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def single(self):
        self._one = True
        return self

    def maybe_single(self):
        self._one = True
        return self

    def execute(self):
        op = f"{self._op}_one" if (self._op == "select" and self._one) else self._op
        return self._sb._exec(self._t, op, self._payload)


class _FakeSb:
    """Registra llamadas y responde por (tabla, op).

    handlers[(table, op)] = data (list/dict/None) | Exception (se lanza).
    """

    def __init__(self, handlers=None):
        self.handlers = handlers or {}
        self.calls = []  # (table, op, payload)

    def table(self, name):
        return _Chain(name, self)

    def _exec(self, table, op, payload):
        self.calls.append((table, op, payload))
        res = self.handlers.get((table, op))
        if isinstance(res, Exception):
            raise res
        return types.SimpleNamespace(data=res)

    def payloads(self, table, op):
        return [p for (t, o, p) in self.calls if t == table and o == op]

    def called(self, table, op):
        return any(t == table and o == op for (t, o, _p) in self.calls)


_LISTING = [{"id": "L1", "external_id": "MCO9", "tenant_id": TENANT, "meli_variation_id": None}]
_VAR = {"price": 1000, "compare_at_price": 1500}
_MELI_ITEM = {"status": "active", "variations": [], "title": "Prod", "thumbnail": "http://t",
              "condition": "new", "category_id": "MCO1", "attributes": []}


def _token_patch(value="TOK"):
    return patch("routers.marketplace.get_valid_token", AsyncMock(return_value=value))


# ─── _resolve_variations_for_put ──────────────────────────────────────────────

class ResolveVariationsForPutTests(unittest.TestCase):
    def test_sin_variations_retorna_none(self):
        sb = _FakeSb()
        out = marketplace._resolve_variations_for_put(sb, TENANT, "MCO9", 111, 5, [])
        self.assertIsNone(out)

    def test_sin_meli_variation_id_solo_ids(self):
        # Sin mapeo exacto: ids solos → MeLi conserva cantidades; SIN tocar DB.
        sb = _FakeSb()
        variations = [{"id": 1}, {"id": 2, "available_quantity": 3}, {"available_quantity": 9}]
        out = marketplace._resolve_variations_for_put(sb, TENANT, "MCO9", None, 5, variations)
        self.assertEqual(out, [{"id": 1}, {"id": 2}])
        self.assertEqual(sb.calls, [])

    def test_hermano_mapeado_recibe_verdad_supabase(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [{"meli_variation_id": 222, "variation_id": "v2"}],
                ("product_variations", "select"): [{"id": "v2", "stock_quantity": 6}],
            }
        )
        variations = [{"id": 111, "available_quantity": 1}, {"id": 222, "available_quantity": 9}]
        out = marketplace._resolve_variations_for_put(sb, TENANT, "MCO9", 111, 5, variations)
        self.assertEqual(out, [
            {"id": 111, "available_quantity": 5},   # target → qty forzada
            {"id": 222, "available_quantity": 6},   # hermano → stock REAL de Supabase
        ])

    def test_hermano_sin_mapeo_cae_al_get_meli(self):
        sb = _FakeSb({("marketplace_listings", "select"): []})
        variations = [{"id": 111, "available_quantity": 1}, {"id": 222, "available_quantity": 9}]
        out = marketplace._resolve_variations_for_put(sb, TENANT, "MCO9", 111, 5, variations)
        self.assertEqual(out, [
            {"id": 111, "available_quantity": 5},
            {"id": 222, "available_quantity": 9},   # sin mapeo → conserva valor del GET
        ])

    def test_hermano_mapeado_sin_fila_stock_cae_al_get(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [{"meli_variation_id": 222, "variation_id": "v2"}],
                ("product_variations", "select"): [],   # variante borrada → sin verdad local
            }
        )
        variations = [{"id": 111, "available_quantity": 1}, {"id": 222, "available_quantity": 9}]
        out = marketplace._resolve_variations_for_put(sb, TENANT, "MCO9", 111, 5, variations)
        self.assertEqual(out, [
            {"id": 111, "available_quantity": 5},
            {"id": 222, "available_quantity": 9},
        ])


# ─── sync_meli_stock — ramas no cubiertas por el seam P1.5 ───────────────────

class SyncMeliStockBranchTests(unittest.IsolatedAsyncioTestCase):
    async def test_sin_listing_activo_retorna_sin_io(self):
        sb = _FakeSb({("marketplace_listings", "select"): []})
        with patch("routers.marketplace.get_valid_token", AsyncMock()) as tok:
            await marketplace.sync_meli_stock("v1", 4, sb)
        tok.assert_not_called()

    async def test_sin_token_omite_sync(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): _LISTING,
                ("product_variations", "select_one"): _VAR,
            }
        )
        with _token_patch(None), \
             patch("routers.marketplace.get_item", AsyncMock()) as gi:
            await marketplace.sync_meli_stock("v1", 4, sb)
        gi.assert_not_called()

    async def test_item_closed_marca_listing_local_y_no_hace_put(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): _LISTING,
                ("product_variations", "select_one"): _VAR,
                ("marketplace_listings", "update"): [{}],
            }
        )
        with _token_patch(), \
             patch("routers.marketplace.get_item", AsyncMock(return_value={"status": "closed"})), \
             patch("routers.marketplace.update_item_listing", AsyncMock()) as put:
            await marketplace.sync_meli_stock("v1", 4, sb)
        put.assert_not_awaited()
        self.assertIn({"status": "closed"}, sb.payloads("marketplace_listings", "update"))

    async def test_fallo_verificacion_get_sigue_con_variaciones_vacias(self):
        # GET de verificación falla → meli_variations=[] y se intenta el PUT igual.
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): _LISTING,
                ("product_variations", "select_one"): None,   # price None → rama sync_stock
                ("marketplace_listings", "update"): [{}],
            }
        )
        with patch("routers.marketplace.get_commerce_adapter", return_value=None), \
             _token_patch(), \
             patch("routers.marketplace.get_item", AsyncMock(side_effect=Exception("timeout"))), \
             patch("routers.marketplace.update_item_quantity", AsyncMock()) as put_q:
            await marketplace.sync_meli_stock("v1", 4, sb)   # NO debe propagar
        put_q.assert_awaited_once_with("MCO9", 4, "TOK")

    async def test_fallo_update_pull_fields_no_rompe(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): _LISTING,
                ("product_variations", "select_one"): None,
                ("marketplace_listings", "update"): Exception("db write failed"),
            }
        )
        with patch("routers.marketplace.get_commerce_adapter", return_value=None), \
             _token_patch(), \
             patch("routers.marketplace.get_item", AsyncMock(return_value=_MELI_ITEM)), \
             patch("routers.marketplace.update_item_quantity", AsyncMock()):
            await marketplace.sync_meli_stock("v1", 4, sb)   # warning + continúa

    async def test_error_externo_es_falla_silente(self):
        sb = _FakeSb({("marketplace_listings", "select"): Exception("db down")})
        await marketplace.sync_meli_stock("v1", 4, sb)       # NO propaga


# ─── GET /listings ────────────────────────────────────────────────────────────

class GetListingsTests(unittest.IsolatedAsyncioTestCase):
    def _sb(self, links=None, variations=None):
        return _FakeSb(
            {
                ("marketplace_listings", "select"): links if links is not None else [],
                ("product_variations", "select"): variations if variations is not None else [],
            }
        )

    async def _run(self, sb, creds, search, details, offset=0, limit=50):
        with patch("routers.marketplace._get_service_client", return_value=sb), \
             patch("routers.marketplace.get_tenant_meli_credentials", return_value=creds), \
             _token_patch(), \
             patch("routers.marketplace.get_user_items", AsyncMock(return_value=search)) as gui, \
             patch("routers.marketplace.get_items_details", AsyncMock(return_value=details)):
            out = await marketplace.get_listings(offset=offset, limit=limit, tenant_id=TENANT)
        return out, gui

    async def test_paginacion_se_acota_a_rangos_meli(self):
        out, gui = await self._run(
            self._sb(), {"user_id": 123},
            {"results": [], "paging": {"total": 0, "limit": 1, "offset": 0}}, [],
            offset=-5, limit=0,
        )
        gui.assert_awaited_once_with("123", "TOK", limit=1, offset=0)   # clamp inferior
        self.assertTrue(out["connected"])

        out, gui = await self._run(
            self._sb(), {"user_id": 123},
            {"results": [], "paging": {"total": 0, "limit": 100, "offset": 0}}, [],
            offset=0, limit=500,
        )
        gui.assert_awaited_once_with("123", "TOK", limit=100, offset=0)  # clamp superior

    async def test_sin_credenciales_retorna_no_conectado(self):
        sb = self._sb()
        with patch("routers.marketplace._get_service_client", return_value=sb), \
             patch("routers.marketplace.get_tenant_meli_credentials", return_value=None):
            out = await marketplace.get_listings(tenant_id=TENANT)
        self.assertEqual(out, {"connected": False, "items": [], "paging": {"total": 0}})

    async def test_sin_user_id_en_creds_retorna_no_conectado(self):
        sb = self._sb()
        with patch("routers.marketplace._get_service_client", return_value=sb), \
             patch("routers.marketplace.get_tenant_meli_credentials", return_value={"user_id": None}):
            out = await marketplace.get_listings(tenant_id=TENANT)
        self.assertFalse(out["connected"])

    async def test_sin_token_retorna_no_conectado(self):
        sb = self._sb()
        with patch("routers.marketplace._get_service_client", return_value=sb), \
             patch("routers.marketplace.get_tenant_meli_credentials", return_value={"user_id": 1}), \
             _token_patch(None):
            out = await marketplace.get_listings(tenant_id=TENANT)
        self.assertEqual(out, {"connected": False, "items": [], "paging": {"total": 0}})

    async def test_sin_items_retorna_conectado_vacio(self):
        out, _ = await self._run(
            self._sb(), {"user_id": 123},
            {"results": [], "paging": {"total": 0, "limit": 50, "offset": 0}}, [],
        )
        self.assertEqual(out, {"connected": True, "items": [],
                               "paging": {"total": 0, "limit": 50, "offset": 0}})

    async def test_happy_path_enriquece_vinculos_y_salta_entries_malos(self):
        links = [
            {"id": "L1", "external_id": "MCO1", "variation_id": "v1", "status": "active",
             "meli_variation_id": 111},
            {"id": "L2", "external_id": "MCO4", "variation_id": "v2", "status": "active"},
        ]
        variations = [
            {"id": "v1", "sku": "SKU1", "stock_quantity": 7, "price": 1500,
             "products": {"title": "Prod X"}},
            {"id": "v2", "sku": "SKU2", "stock_quantity": 0, "price": None, "products": None},
        ]
        details = [
            {"code": 200, "body": {
                "id": "MCO1", "title": "Item 1", "status": "active", "price": 2000,
                "available_quantity": 3, "thumbnail": "th", "permalink": "pl",
                "variations": [
                    {"id": 111, "attribute_combinations": [{"name": "Color"}], "available_quantity": 3},
                    {"id": None},   # sin id → filtrada
                ],
            }},
            {"code": 404, "body": {}},                  # code != 200 → skip
            {"code": 200, "body": {}},                  # body vacío → skip
            {"code": 200, "body": {"id": "MCO4", "title": "Item 4", "status": "paused"}},
            {"code": 200, "body": {"id": "MCO5", "title": "Item 5", "status": "active"}},
        ]
        search = {"results": ["MCO1", "MCO2", "MCO3", "MCO4", "MCO5"],
                  "paging": {"total": 5, "limit": 50, "offset": 0}}
        out, _ = await self._run(self._sb(links, variations), {"user_id": 123}, search, details)

        self.assertTrue(out["connected"])
        self.assertEqual([i["meli_id"] for i in out["items"]], ["MCO1", "MCO4", "MCO5"])

        it1 = out["items"][0]
        self.assertTrue(it1["is_linked"])
        self.assertEqual(it1["listing_id"], "L1")
        self.assertEqual(it1["variation_id"], "v1")
        self.assertEqual(it1["meli_variation_id"], 111)
        self.assertEqual(it1["sku"], "SKU1")
        self.assertEqual(it1["product_name"], "Prod X")
        self.assertEqual(it1["supabase_stock"], 7)
        self.assertEqual(it1["supabase_price"], 1500.0)
        self.assertEqual(it1["meli_variations"], [
            {"id": 111, "attributes": [{"name": "Color"}], "available_quantity": 3},
        ])

        it4 = out["items"][1]
        self.assertTrue(it4["is_linked"])
        self.assertEqual(it4["product_name"], "")        # products None → ""
        self.assertIsNone(it4["supabase_price"])         # price None → None
        self.assertIsNone(it4["meli_variation_id"])
        self.assertEqual(it4["meli_variations"], [])

        it5 = out["items"][2]
        self.assertFalse(it5["is_linked"])               # sin vínculo
        self.assertIsNone(it5["listing_id"])
        self.assertIsNone(it5["variation_id"])

    async def test_error_meli_retorna_502(self):
        sb = self._sb()
        with patch("routers.marketplace._get_service_client", return_value=sb), \
             patch("routers.marketplace.get_tenant_meli_credentials", return_value={"user_id": 1}), \
             _token_patch(), \
             patch("routers.marketplace.get_user_items", AsyncMock(side_effect=Exception("meli down"))):
            with self.assertRaises(HTTPException) as ctx:
                await marketplace.get_listings(tenant_id=TENANT)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertNotIn("meli down", ctx.exception.detail)   # F23: sin fuga de detalle


# ─── POST /link ───────────────────────────────────────────────────────────────

class LinkListingTests(unittest.IsolatedAsyncioTestCase):
    def _body(self, **kw):
        base = {"meli_id": "  mco123 ", "variation_id": "v1"}
        base.update(kw)
        return LinkListingBody(**base)

    async def _call(self, sb, body, **patch_kw):
        with _token_patch(patch_kw.get("token", "TOK")), \
             patch("routers.marketplace.get_item",
                   AsyncMock(side_effect=patch_kw.get("get_item_exc", None),
                             return_value=patch_kw.get("item", _MELI_ITEM))):
            return await marketplace.link_listing(
                request=None, payload=body, tenant_id=TENANT, _role="owner", supabase=sb,
            )

    async def test_meli_id_solo_espacios_400(self):
        sb = _FakeSb()
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, self._body(meli_id="   "))
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_variante_no_encontrada_404(self):
        sb = _FakeSb({("product_variations", "select"): []})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, self._body())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_sin_token_400(self):
        sb = _FakeSb({("product_variations", "select"): [{"id": "v1", "stock_quantity": 3}]})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, self._body(), token=None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_happy_path_normaliza_id_e_inserta_y_enriquece(self):
        sb = _FakeSb(
            {
                ("product_variations", "select"): [{"id": "v1", "stock_quantity": 3}],
                ("marketplace_listings", "insert"): [{"id": "L1", "external_id": "MCO123"}],
                ("marketplace_listings", "update"): [{}],
            }
        )
        item = dict(_MELI_ITEM, price=999)
        out = await self._call(
            sb, self._body(meli_price=15000, meli_variation_id=42), item=item,
        )
        self.assertEqual(out, {"id": "L1", "external_id": "MCO123"})

        insert_payload = sb.payloads("marketplace_listings", "insert")[0]
        self.assertEqual(insert_payload["external_id"], "MCO123")   # strip + upper
        self.assertEqual(insert_payload["tenant_id"], TENANT)
        self.assertEqual(insert_payload["provider"], "mercadolibre")
        self.assertEqual(insert_payload["status"], "active")
        self.assertEqual(insert_payload["external_price"], 15000)
        self.assertEqual(insert_payload["meli_variation_id"], 42)
        self.assertEqual(insert_payload["external_url"],
                         "https://articulo.mercadolibre.com/MCO123")

        update_payload = sb.payloads("marketplace_listings", "update")[0]
        self.assertEqual(update_payload["meli_title"], "Prod")
        self.assertEqual(update_payload["external_price"], 999)     # precio real MeLi gana
        self.assertIn("synced_at", update_payload)

    async def test_enriquecido_fallido_no_rompe_la_vinculacion(self):
        sb = _FakeSb(
            {
                ("product_variations", "select"): [{"id": "v1", "stock_quantity": 3}],
                ("marketplace_listings", "insert"): [{"id": "L1"}],
            }
        )
        out = await self._call(sb, self._body(), get_item_exc=Exception("meli caido"))
        self.assertEqual(out, {"id": "L1"})                         # warning + sigue
        self.assertFalse(sb.called("marketplace_listings", "update"))

    async def test_insert_sin_data_retorna_ok(self):
        sb = _FakeSb(
            {
                ("product_variations", "select"): [{"id": "v1"}],
                ("marketplace_listings", "insert"): [],
            }
        )
        out = await self._call(sb, self._body())
        self.assertEqual(out, {"ok": True})

    async def test_duplicado_retorna_409(self):
        sb = _FakeSb(
            {
                ("product_variations", "select"): [{"id": "v1"}],
                ("marketplace_listings", "insert"): Exception("duplicate key value violates unique constraint"),
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, self._body())
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_error_generico_retorna_500_sin_fuga(self):
        sb = _FakeSb(
            {
                ("product_variations", "select"): [{"id": "v1"}],
                ("marketplace_listings", "insert"): Exception("connection reset by peer"),
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, self._body())
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertNotIn("connection reset", ctx.exception.detail)


# ─── DELETE /link/{listing_id} ────────────────────────────────────────────────

class UnlinkListingTests(unittest.TestCase):
    def test_no_encontrado_404(self):
        sb = _FakeSb({("marketplace_listings", "delete"): []})
        with self.assertRaises(HTTPException) as ctx:
            marketplace.unlink_listing(
                "L9", request=None, tenant_id=TENANT, _role="owner", supabase=sb,
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_ok(self):
        sb = _FakeSb({("marketplace_listings", "delete"): [{"id": "L1"}]})
        out = marketplace.unlink_listing(
            "L1", request=None, tenant_id=TENANT, _role="owner", supabase=sb,
        )
        self.assertEqual(out, {"ok": True})


# ─── PATCH /{listing_id}/status ───────────────────────────────────────────────

class UpdateListingStatusTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, sb, status="paused", token="TOK", meli_exc=None):
        with _token_patch(token), \
             patch("routers.marketplace.update_item_status",
                   AsyncMock(side_effect=meli_exc)) as uis:
            out = await marketplace.update_listing_status(
                "L1", request=None, payload=ListingStatusBody(status=status),
                tenant_id=TENANT, _role="owner", supabase=sb,
            )
        return out, uis

    async def test_listing_no_encontrado_404(self):
        sb = _FakeSb({("marketplace_listings", "select_one"): None})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_sin_token_400(self):
        sb = _FakeSb({("marketplace_listings", "select_one"): {"id": "L1", "external_id": "MCO9"}})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, token=None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_happy_path_actualiza_meli_y_local(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select_one"): {"id": "L1", "external_id": "MCO9"},
                ("marketplace_listings", "update"): [{"id": "L1", "status": "paused"}],
            }
        )
        out, uis = await self._call(sb, status="paused")
        uis.assert_awaited_once_with("MCO9", "paused", "TOK")
        self.assertEqual(out, {"id": "L1", "status": "paused"})
        self.assertIn({"status": "paused"}, sb.payloads("marketplace_listings", "update"))

    async def test_update_local_sin_data_retorna_ok(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select_one"): {"id": "L1", "external_id": "MCO9"},
                ("marketplace_listings", "update"): [],
            }
        )
        out, _ = await self._call(sb, status="active")
        self.assertEqual(out, {"ok": True})

    async def test_fallo_meli_retorna_502_sin_fuga(self):
        sb = _FakeSb({("marketplace_listings", "select_one"): {"id": "L1", "external_id": "MCO9"}})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, meli_exc=Exception("403 forbidden by meli"))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertNotIn("403 forbidden", ctx.exception.detail)


# ─── PATCH /{listing_id}/sync-stock ───────────────────────────────────────────

class SyncStockFromSupabaseTests(unittest.IsolatedAsyncioTestCase):
    _LISTING_ONE = {"id": "L1", "external_id": "MCO9", "variation_id": "v1",
                    "meli_variation_id": None}
    _VAR_ONE = {"stock_quantity": 5, "price": 1200, "compare_at_price": None}

    def _sb_ok(self, over=None):
        handlers = {
            ("marketplace_listings", "select_one"): dict(self._LISTING_ONE),
            ("product_variations", "select_one"): dict(self._VAR_ONE),
            ("marketplace_listings", "select"): [],
            ("product_variations", "select"): [],
            ("marketplace_listings", "update"): [{}],
        }
        handlers.update(over or {})
        return _FakeSb(handlers)

    async def _call(self, sb, token="TOK", item=None, get_exc=None, put_exc=None):
        with _token_patch(token), \
             patch("routers.marketplace.get_item",
                   AsyncMock(side_effect=get_exc, return_value=item or _MELI_ITEM)), \
             patch("routers.marketplace.update_item_listing",
                   AsyncMock(side_effect=put_exc)) as uil:
            out = await marketplace.sync_stock_from_supabase(
                "L1", request=None, tenant_id=TENANT, _role="owner", supabase=sb,
            )
        return out, uil

    async def test_listing_no_encontrado_404(self):
        sb = _FakeSb({("marketplace_listings", "select_one"): None})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_listing_sin_variante_400(self):
        sb = _FakeSb({("marketplace_listings", "select_one"):
                        {"id": "L1", "external_id": "MCO9", "variation_id": None}})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_variante_no_encontrada_404(self):
        sb = self._sb_ok({("product_variations", "select_one"): None})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_sin_token_400(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._sb_ok(), token=None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_fallo_get_item_502(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._sb_ok(), get_exc=Exception("read timeout"))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertNotIn("read timeout", ctx.exception.detail)

    async def test_item_closed_marca_local_y_409(self):
        sb = self._sb_ok()
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, item={"status": "closed"})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("cerrada", ctx.exception.detail)
        self.assertIn({"status": "closed"}, sb.payloads("marketplace_listings", "update"))

    async def test_fallo_put_502_sin_fuga(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(self._sb_ok(), put_exc=Exception("400 bad request body"))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertNotIn("bad request body", ctx.exception.detail)

    async def test_happy_item_simple(self):
        out, uil = await self._call(self._sb_ok())
        uil.assert_awaited_once_with("MCO9", 5, 1200.0, None, "TOK", None)
        self.assertEqual(out, {
            "ok": True, "meli_id": "MCO9", "synced_quantity": 5,
            "synced_price": 1200.0, "synced_original_price": None,
        })

    async def test_happy_con_variaciones_hermanas(self):
        sb = self._sb_ok(
            {
                ("marketplace_listings", "select_one"): {
                    "id": "L1", "external_id": "MCO9", "variation_id": "v1",
                    "meli_variation_id": 111,
                },
                ("product_variations", "select_one"): {
                    "stock_quantity": 5, "price": 1200, "compare_at_price": 1500,
                },
                ("marketplace_listings", "select"): [{"meli_variation_id": 222, "variation_id": "v2"}],
                ("product_variations", "select"): [{"id": "v2", "stock_quantity": 6}],
            }
        )
        item = dict(_MELI_ITEM, variations=[
            {"id": 111, "available_quantity": 1},
            {"id": 222, "available_quantity": 9},
        ])
        out, uil = await self._call(sb, item=item)
        uil.assert_awaited_once_with(
            "MCO9", 5, 1200.0, 1500.0, "TOK",
            [{"id": 111, "available_quantity": 5},     # target → stock Supabase
             {"id": 222, "available_quantity": 6}],    # hermano → verdad Supabase (no 0, no GET)
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["synced_original_price"], 1500.0)

    async def test_error_inesperado_en_resolucion_502(self):
        # La query de hermanos de _resolve_variations_for_put lanza → except
        # genérico del endpoint (no es fallo GET ni PUT) → 502 genérico.
        sb = self._sb_ok(
            {
                ("marketplace_listings", "select_one"): {
                    "id": "L1", "external_id": "MCO9", "variation_id": "v1",
                    "meli_variation_id": 111,
                },
                ("marketplace_listings", "select"): Exception("db caida a mitad"),
            }
        )
        item = dict(_MELI_ITEM, variations=[
            {"id": 111, "available_quantity": 1},
            {"id": 222, "available_quantity": 9},   # hermana → dispara la query que falla
        ])
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, item=item)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertNotIn("db caida", ctx.exception.detail)


# ─── _assert_category_owned ───────────────────────────────────────────────────

class AssertCategoryOwnedTests(unittest.IsolatedAsyncioTestCase):
    async def test_none_es_noop(self):
        sb = _FakeSb()
        await marketplace._assert_category_owned(None, TENANT, sb)
        self.assertEqual(sb.calls, [])

    async def test_categoria_ajena_422(self):
        sb = _FakeSb({("product_categories", "select"): []})
        with self.assertRaises(HTTPException) as ctx:
            await marketplace._assert_category_owned("cat-x", TENANT, sb)
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_categoria_propia_pasa(self):
        sb = _FakeSb({("product_categories", "select"): [{"id": "cat-1"}]})
        await marketplace._assert_category_owned("cat-1", TENANT, sb)   # no lanza


# ─── _import_meli_item ────────────────────────────────────────────────────────

class ImportMeliItemTests(unittest.IsolatedAsyncioTestCase):
    _ITEM = {
        "title": "Camiseta", "price": 1000, "available_quantity": 4,
        "permalink": "http://pl", "original_price": 1500,
        "pictures": [{"secure_url": "https://img-hd"}],
        "status": "active", "thumbnail": "http://th", "condition": "new",
        "category_id": "MCO-C1", "attributes": [{"id": "BRAND"}],
    }

    def _sb_ok(self):
        return _FakeSb(
            {
                ("marketplace_listings", "select"): [],
                ("products", "insert"): [{"id": "p1"}],
                ("product_variations", "insert"): [{"id": "v1"}],
                ("marketplace_listings", "insert"): [{"id": "L1"}],
                ("products", "delete"): [{}],
                ("product_variations", "delete"): [{}],
            }
        )

    async def _call(self, sb, item=None, get_exc=None, category_id=None):
        with patch("routers.marketplace.get_item",
                   AsyncMock(side_effect=get_exc, return_value=item or self._ITEM)):
            return await marketplace._import_meli_item("MCO9", category_id, TENANT, "TOK", sb)

    async def test_ya_vinculado_409(self):
        sb = _FakeSb({("marketplace_listings", "select"): [{"id": "L9"}]})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_fallo_get_item_502(self):
        sb = _FakeSb({("marketplace_listings", "select"): []})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, get_exc=Exception("meli 500"))
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertNotIn("meli 500", ctx.exception.detail)

    async def test_producto_sin_data_500(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [],
                ("products", "insert"): [],
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 500)

    async def test_sku_duplicado_409_con_rollback_producto(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [],
                ("products", "insert"): [{"id": "p1"}],
                ("product_variations", "insert"): Exception('duplicate key ("23505")'),
                ("products", "delete"): [{}],
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("ML-MCO9", ctx.exception.detail)
        self.assertTrue(sb.called("products", "delete"))            # rollback

    async def test_error_variante_generico_500_con_rollback(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [],
                ("products", "insert"): [{"id": "p1"}],
                ("product_variations", "insert"): Exception("db explotó"),
                ("products", "delete"): [{}],
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertTrue(sb.called("products", "delete"))

    async def test_variante_sin_data_500_con_rollback(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [],
                ("products", "insert"): [{"id": "p1"}],
                ("product_variations", "insert"): [],
                ("products", "delete"): [{}],
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertTrue(sb.called("products", "delete"))

    async def test_link_sin_data_500_con_rollback_doble(self):
        sb = _FakeSb(
            {
                ("marketplace_listings", "select"): [],
                ("products", "insert"): [{"id": "p1"}],
                ("product_variations", "insert"): [{"id": "v1"}],
                ("marketplace_listings", "insert"): [],
                ("products", "delete"): [{}],
                ("product_variations", "delete"): [{}],
            }
        )
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb)
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertTrue(sb.called("product_variations", "delete"))   # rollback variante
        self.assertTrue(sb.called("products", "delete"))             # rollback producto

    async def test_happy_path_completo(self):
        sb = self._sb_ok()
        out = await self._call(sb, category_id="cat-1")

        self.assertTrue(out["ok"])
        self.assertEqual(out["product_id"], "p1")
        self.assertEqual(out["variation_id"], "v1")
        self.assertEqual(out["listing_id"], "L1")
        self.assertEqual(out["imported"], {
            "title": "Camiseta", "sku": "ML-MCO9", "price": 1000.0,
            "compare_at_price": 1500.0, "stock_quantity": 4,
            "cover_image_url": "https://img-hd", "meli_id": "MCO9",
        })

        prod_payload = sb.payloads("products", "insert")[0]
        self.assertEqual(prod_payload["tenant_id"], TENANT)
        self.assertEqual(prod_payload["title"], "Camiseta")
        self.assertEqual(prod_payload["category_id"], "cat-1")
        self.assertEqual(prod_payload["cover_image_url"], "https://img-hd")

        var_payload = sb.payloads("product_variations", "insert")[0]
        self.assertEqual(var_payload["sku"], "ML-MCO9")
        self.assertEqual(var_payload["price"], 1000.0)
        self.assertEqual(var_payload["stock_quantity"], 4)
        self.assertEqual(var_payload["compare_at_price"], 1500.0)     # 1500 > 1000

        link_payload = sb.payloads("marketplace_listings", "insert")[0]
        self.assertEqual(link_payload["external_id"], "MCO9")
        self.assertEqual(link_payload["meli_title"], "Camiseta")
        self.assertEqual(link_payload["meli_category_id"], "MCO-C1")
        self.assertEqual(link_payload["external_url"], "http://pl")
        self.assertIn("synced_at", link_payload)

    async def test_happy_minimo_sin_compare_at_ni_pictures(self):
        sb = self._sb_ok()
        item = {
            "title": "Simple", "price": 1000, "available_quantity": 0,
            "original_price": 900,          # menor que price → NO se guarda compare_at
            "pictures": [], "thumbnail": "http://th",
        }
        out = await self._call(sb, item=item)
        # El resumen reporta lo EFECTIVAMENTE persistido: 900 < 1000 → el guard
        # no lo guarda → None (antes reportaba el crudo de MeLi, divergiendo de
        # la DB — corregido 2026-08-13, observación M18 del agente marketplace).
        self.assertIsNone(out["imported"]["compare_at_price"])
        self.assertEqual(out["imported"]["cover_image_url"], "http://th")  # fallback thumbnail
        var_payload = sb.payloads("product_variations", "insert")[0]
        self.assertNotIn("compare_at_price", var_payload)


# ─── POST /import ─────────────────────────────────────────────────────────────

class ImportFromMeliTests(unittest.IsolatedAsyncioTestCase):
    async def test_meli_id_solo_espacios_400(self):
        sb = _FakeSb()
        with self.assertRaises(HTTPException) as ctx:
            await marketplace.import_from_meli(
                request=None, payload=ImportBody(meli_id="   "),
                tenant_id=TENANT, _role="owner", supabase=sb,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_sin_token_400(self):
        sb = _FakeSb()
        with _token_patch(None):
            with self.assertRaises(HTTPException) as ctx:
                await marketplace.import_from_meli(
                    request=None, payload=ImportBody(meli_id="MCO1"),
                    tenant_id=TENANT, _role="owner", supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_categoria_ajena_422(self):
        sb = _FakeSb({("product_categories", "select"): []})
        with _token_patch():
            with self.assertRaises(HTTPException) as ctx:
                await marketplace.import_from_meli(
                    request=None, payload=ImportBody(meli_id="MCO1", category_id="cat-x"),
                    tenant_id=TENANT, _role="owner", supabase=sb,
                )
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_normaliza_id_y_delega(self):
        sb = _FakeSb()
        with _token_patch(), \
             patch("routers.marketplace._import_meli_item",
                   AsyncMock(return_value={"ok": True})) as imp:
            out = await marketplace.import_from_meli(
                request=None, payload=ImportBody(meli_id="  mco123 "),
                tenant_id=TENANT, _role="owner", supabase=sb,
            )
        imp.assert_awaited_once_with("MCO123", None, TENANT, "TOK", sb)
        self.assertEqual(out, {"ok": True})


# ─── POST /import-bulk ────────────────────────────────────────────────────────

class ImportBulkTests(unittest.IsolatedAsyncioTestCase):
    async def _call(self, sb, ids, token="TOK", side_effects=None, category_id=None):
        with _token_patch(token), \
             patch("routers.marketplace._import_meli_item",
                   AsyncMock(side_effect=side_effects or [])) as imp:
            out = await marketplace.import_bulk_from_meli(
                request=None, payload=ImportBulkBody(meli_ids=ids, category_id=category_id),
                tenant_id=TENANT, _role="owner", supabase=sb,
            )
        return out, imp

    async def test_body_rechaza_lista_vacia_y_mas_de_50(self):
        with self.assertRaises(ValidationError):
            ImportBulkBody(meli_ids=[])
        with self.assertRaises(ValidationError):
            ImportBulkBody(meli_ids=[f"MCO{i}" for i in range(51)])

    async def test_sin_token_400(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(_FakeSb(), ["MCO1"], token=None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_categoria_ajena_422(self):
        sb = _FakeSb({("product_categories", "select"): []})
        with self.assertRaises(HTTPException) as ctx:
            await self._call(sb, ["MCO1"], category_id="cat-x")
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_ids_todos_invalidos_400(self):
        with self.assertRaises(HTTPException) as ctx:
            await self._call(_FakeSb(), ["  ", ""])
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_dedup_normaliza_preservando_orden(self):
        sb = _FakeSb()
        ok = {"variation_id": "v1", "imported": {"sku": "ML-MCO1", "title": "T"}}
        out, imp = await self._call(sb, ["mco1", " MCO1 ", "  mco2"], side_effects=[ok, ok])
        self.assertEqual([c.args[0] for c in imp.await_args_list], ["MCO1", "MCO2"])
        self.assertEqual(out["summary"]["total"], 2)

    async def test_buckets_imported_skipped_errors(self):
        sb = _FakeSb()
        ok = {"variation_id": "v1", "imported": {"sku": "ML-MCO1", "title": "T1"}}
        out, _ = await self._call(
            sb, ["MCO1", "MCO2", "MCO3", "MCO4"],
            side_effects=[
                ok,
                HTTPException(status_code=409, detail="ya vinculado"),
                HTTPException(status_code=502, detail="meli caido"),
                Exception("boom inesperado"),
            ],
        )
        self.assertTrue(out["ok"])
        self.assertEqual(out["imported"], [
            {"meli_id": "MCO1", "variation_id": "v1", "sku": "ML-MCO1", "title": "T1"},
        ])
        self.assertEqual(out["skipped"], [{"meli_id": "MCO2", "reason": "ya vinculado"}])
        self.assertEqual(out["errors"], [
            {"meli_id": "MCO3", "reason": "meli caido"},
            {"meli_id": "MCO4", "reason": "Error inesperado al importar"},  # sin fuga de "boom"
        ])
        self.assertEqual(out["summary"], {"total": 4, "imported": 1, "skipped": 1, "errors": 2})


if __name__ == "__main__":
    unittest.main()
