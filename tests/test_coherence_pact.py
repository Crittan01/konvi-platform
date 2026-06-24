"""
Rev. 72 — Tests de coherencia "pact" entre Pydantic models y schema DB live.

Por cada modelo Pydantic de write (Create/Patch), validamos que TODOS sus campos
existen como columnas en la tabla DB correspondiente. Si un modelo añade un
campo huérfano (no en DB) o si la DB elimina una columna sin actualizar el
modelo, este test falla con un mensaje claro.

Fuente de verdad del schema: `tests/fixtures/db_schema_canonical.json`
(generado con `python3.11 scripts/dump_schema_canonical.py` desde DB live).

Si DB live evoluciona legítimamente:
1. Re-generar el fixture con `python3.11 scripts/dump_schema_canonical.py`.
2. Commitear el JSON actualizado junto con el cambio de código.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, "/home/ansible/workspaces/konvi-platform/services/api")

from routers.orders import OrderCreate, OrderPatch, OrderItemCreate  # noqa: E402
from routers.contacts import ContactCreate, ContactPatch  # noqa: E402
from routers.products import ProductCreate, ProductPatch, VariationCreate, VariationPatch  # noqa: E402
from routers.claims import ClaimCreate, ClaimPatch, ClaimResolve  # noqa: E402
from routers.purchases import (  # noqa: E402
    SupplierCreate, POItemCreate, PurchaseOrderCreate,
)
from routers.knowledge_base import KbDocCreate, KbDocPatch  # noqa: E402
from routers.settings import TenantPatch  # noqa: E402

FIXTURE = Path("/home/ansible/workspaces/konvi-platform/tests/fixtures/db_schema_canonical.json")


def _load_schema() -> dict:
    with open(FIXTURE) as f:
        data = json.load(f)
    return {t["table_name"]: {c["col"] for c in (t.get("columns") or [])}
            for t in data.get("tables", [])}


SCHEMA = _load_schema()


def _model_fields(model) -> set[str]:
    """Pydantic v2: model.model_fields."""
    return set(getattr(model, "model_fields", {}).keys())


def _check_subset(model_cls, table_name: str, allowed_extras: set[str] = frozenset()) -> tuple[set[str], set[str]]:
    """
    Retorna (orphan_in_model, missing_in_model_only_if_required).
    `allowed_extras` declara campos del modelo que intencionalmente NO mapean a columna
    (ej. flags transitorios como `auto_confirm` en OrderCreate).
    """
    cols = SCHEMA.get(table_name, set())
    if not cols:
        return set(), set()
    fields = _model_fields(model_cls) - allowed_extras
    orphans = {f for f in fields if f not in cols}
    return orphans, set()


class OrdersCoherenceTests(unittest.TestCase):
    def test_order_create_fields_in_orders_or_items(self):
        orphans, _ = _check_subset(
            OrderCreate, "orders",
            allowed_extras={"items", "auto_confirm", "payment_link"},  # composición + flags
        )
        self.assertFalse(orphans, f"OrderCreate huérfanos vs orders: {orphans}")

    def test_order_patch_fields_in_orders(self):
        orphans, _ = _check_subset(OrderPatch, "orders")
        self.assertFalse(orphans, f"OrderPatch huérfanos: {orphans}")

    def test_order_item_create_fields_in_order_items(self):
        orphans, _ = _check_subset(OrderItemCreate, "order_items")
        self.assertFalse(orphans, f"OrderItemCreate huérfanos: {orphans}")


class ContactsCoherenceTests(unittest.TestCase):
    def test_contact_create_fields_in_contacts(self):
        orphans, _ = _check_subset(ContactCreate, "contacts")
        self.assertFalse(orphans, f"ContactCreate huérfanos: {orphans}")

    def test_contact_patch_fields_in_contacts(self):
        # A9 — campos de control del flujo de consent que NO mapean a columna:
        # los consume _compute_consent_update (máquina de estados Habeas Data) y
        # se eliminan del payload antes del UPDATE.
        orphans, _ = _check_subset(ContactPatch, "contacts", allowed_extras={
            "consent_evidence_note", "renewed_consent",
            "renewed_consent_evidence", "consent_attachment",
        })
        self.assertFalse(orphans, f"ContactPatch huérfanos: {orphans}")


class ProductsCoherenceTests(unittest.TestCase):
    def test_product_create_fields_in_products(self):
        # variation es composición — no se persiste como columna.
        orphans, _ = _check_subset(ProductCreate, "products", allowed_extras={"variation"})
        self.assertFalse(orphans, f"ProductCreate huérfanos: {orphans}")

    def test_product_patch_fields_in_products(self):
        orphans, _ = _check_subset(ProductPatch, "products")
        self.assertFalse(orphans, f"ProductPatch huérfanos: {orphans}")

    def test_variation_create_fields_in_product_variations(self):
        orphans, _ = _check_subset(VariationCreate, "product_variations")
        self.assertFalse(orphans, f"VariationCreate huérfanos: {orphans}")

    def test_variation_patch_fields_in_product_variations(self):
        orphans, _ = _check_subset(VariationPatch, "product_variations")
        self.assertFalse(orphans, f"VariationPatch huérfanos: {orphans}")


class ClaimsCoherenceTests(unittest.TestCase):
    def test_claim_create_fields_in_claims(self):
        orphans, _ = _check_subset(ClaimCreate, "claims")
        self.assertFalse(orphans, f"ClaimCreate huérfanos: {orphans}")

    def test_claim_patch_fields_in_claims(self):
        orphans, _ = _check_subset(ClaimPatch, "claims")
        self.assertFalse(orphans, f"ClaimPatch huérfanos: {orphans}")


class PurchasesCoherenceTests(unittest.TestCase):
    def test_supplier_create_fields_in_suppliers(self):
        orphans, _ = _check_subset(SupplierCreate, "suppliers")
        self.assertFalse(orphans, f"SupplierCreate huérfanos: {orphans}")

    def test_po_create_fields_in_purchase_orders(self):
        orphans, _ = _check_subset(
            PurchaseOrderCreate, "purchase_orders",
            allowed_extras={"items"},  # composición
        )
        self.assertFalse(orphans, f"PurchaseOrderCreate huérfanos: {orphans}")

    def test_po_item_create_fields_in_purchase_order_items(self):
        orphans, _ = _check_subset(POItemCreate, "purchase_order_items")
        self.assertFalse(orphans, f"POItemCreate huérfanos: {orphans}")


class KnowledgeBaseCoherenceTests(unittest.TestCase):
    def test_kb_doc_create_fields_in_kb_documents(self):
        orphans, _ = _check_subset(KbDocCreate, "kb_documents")
        self.assertFalse(orphans, f"KbDocCreate huérfanos: {orphans}")

    def test_kb_doc_patch_fields_in_kb_documents(self):
        orphans, _ = _check_subset(KbDocPatch, "kb_documents")
        self.assertFalse(orphans, f"KbDocPatch huérfanos: {orphans}")


class TenantsCoherenceTests(unittest.TestCase):
    def test_tenant_patch_fields_in_tenants(self):
        # `meta_waba_id` y `low_stock_threshold` SÍ son columnas reales.
        orphans, _ = _check_subset(TenantPatch, "tenants")
        self.assertFalse(orphans, f"TenantPatch huérfanos vs tenants: {orphans}")


class FixtureSanityTests(unittest.TestCase):
    """Asegura que el fixture incluye las tablas core. Si falta alguna, regenerar."""
    REQUIRED_TABLES = [
        "tenants", "ai_agents", "kb_documents", "contacts", "conversations",
        "messages", "products", "product_variations", "orders", "order_items",
        "claims", "suppliers", "purchase_orders", "purchase_order_items",
        "audit_log", "bot_source_log",
    ]

    def test_all_required_tables_present(self):
        missing = [t for t in self.REQUIRED_TABLES if t not in SCHEMA]
        self.assertFalse(missing,
                         f"Fixture incompleto. Faltan: {missing}. "
                         "Regenera con: python3.11 scripts/dump_schema_canonical.py")


if __name__ == "__main__":
    unittest.main()
