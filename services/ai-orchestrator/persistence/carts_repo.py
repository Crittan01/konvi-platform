"""Repositorio de ``conversation_carts`` + ``conversation_cart_items``.

Fuente única de verdad del carrito conversacional. Reemplaza la reconstrucción
vía regex sobre ``messages[]`` que vivía en orchestrator.py.

Schema definido en ``supabase/migrations/20260501000000_conversation_carts.sql``.
Contrato documentado en ``.context/06-contracts.md`` (sección 13).

Reglas de uso (NO negociables):
  - Todo método recibe ``tenant_id`` explícito y lo pasa al filtro Supabase
    (service_role bypassa RLS — el aislamiento depende de la app).
  - Locking optimista: cada UPDATE incluye ``WHERE version = :v_actual``.
    Si afecta 0 filas, levantar :class:`CartConflict` para que el caller
    recargue y reintente con backoff.
  - Modificación de items SIEMPRE vía RPC ``cart_add_item`` (atómico,
    idempotente). Editar la tabla directamente desde Python rompe la
    invariante de totales.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from supabase import Client

logger = logging.getLogger("orchestrator.persistence.carts")


# ── Excepciones tipadas ──────────────────────────────────────────────────────


class CartError(Exception):
    """Base de errores del repo de carritos."""


class CartNotFound(CartError):
    """No existe carrito open para la conversación dada."""


class CartConflict(CartError):
    """Update concurrente — version mismatch (SQLSTATE 40001).

    El caller debe recargar el carrito y reintentar la operación.
    """


class CartClosed(CartError):
    """El carrito ya está en estado terminal (converted/abandoned/cancelled)."""


# ── Tipos de dominio ─────────────────────────────────────────────────────────


@dataclass
class CartItem:
    id: str
    cart_id: str
    product_id: str
    variation_id: str
    quantity: int
    unit_price_cents: int
    meta: dict = field(default_factory=dict)

    @property
    def line_total_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass
class Cart:
    id: str
    tenant_id: str
    conversation_id: str
    contact_id: Optional[str]
    status: str
    version: int
    shipping_meta: dict
    subtotal_cents: int
    shipping_cents: int
    total_cents: int
    currency: str
    converted_order_id: Optional[str]
    items: list[CartItem] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return self.status == "open"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)


# ── Repo ─────────────────────────────────────────────────────────────────────


class CartsRepo:
    """Acceso CRUD a ``conversation_carts`` + ``conversation_cart_items``.

    NO contiene lógica de negocio (eso vive en ``cart_service`` o el
    coordinator). Solo serializa I/O contra Supabase.
    """

    def __init__(self, supabase: Client):
        self._sb = supabase

    # ── Reads ────────────────────────────────────────────────────────────────

    def get_open_cart(
        self, *, tenant_id: str, conversation_id: str
    ) -> Optional[Cart]:
        """Retorna el carrito ``open`` de la conversación con sus items, o None."""
        res = (
            self._sb.table("conversation_carts")
            .select(
                "id, tenant_id, conversation_id, contact_id, status, version, "
                "shipping_meta, subtotal_cents, shipping_cents, total_cents, "
                "currency, converted_order_id"
            )
            .eq("tenant_id", tenant_id)
            .eq("conversation_id", conversation_id)
            .eq("status", "open")
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        cart = self._row_to_cart(rows[0])
        cart.items = self._fetch_items(tenant_id=tenant_id, cart_id=cart.id)
        return cart

    def get_cart_by_id(
        self, *, tenant_id: str, cart_id: str
    ) -> Optional[Cart]:
        res = (
            self._sb.table("conversation_carts")
            .select(
                "id, tenant_id, conversation_id, contact_id, status, version, "
                "shipping_meta, subtotal_cents, shipping_cents, total_cents, "
                "currency, converted_order_id"
            )
            .eq("tenant_id", tenant_id)
            .eq("id", cart_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        cart = self._row_to_cart(rows[0])
        cart.items = self._fetch_items(tenant_id=tenant_id, cart_id=cart.id)
        return cart

    # ── Writes ───────────────────────────────────────────────────────────────

    def create_open_cart(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        contact_id: Optional[str] = None,
    ) -> Cart:
        """Crea un carrito ``open``. El partial UNIQUE de la migración
        garantiza que solo puede haber uno por conversación; si ya existe
        uno open, este insert falla y devolvemos el existente.
        """
        try:
            res = (
                self._sb.table("conversation_carts")
                .insert(
                    {
                        "tenant_id": tenant_id,
                        "conversation_id": conversation_id,
                        "contact_id": contact_id,
                    }
                )
                .execute()
            )
            row = (res.data or [{}])[0]
            return self._row_to_cart(row)
        except Exception as exc:
            existing = self.get_open_cart(
                tenant_id=tenant_id, conversation_id=conversation_id
            )
            if existing is not None:
                logger.info(
                    "[carts_repo] insert race resolved; returning existing open cart=%s",
                    existing.id,
                )
                return existing
            logger.exception("[carts_repo] create_open_cart failed: %s", exc)
            raise

    def add_item(
        self,
        *,
        tenant_id: str,
        cart_id: str,
        product_id: str,
        variation_id: str,
        quantity: int,
        unit_price_cents: int,
        expected_version: Optional[int] = None,
    ) -> dict:
        """Agrega/incrementa un item de forma atómica vía RPC ``cart_add_item``.

        Retorna ``{cart_id, new_version, subtotal_cents, total_cents}``.
        Levanta :class:`CartConflict` si ``expected_version`` no coincide.
        """
        if quantity <= 0:
            raise ValueError("quantity must be >= 1")
        try:
            res = self._sb.rpc(
                "cart_add_item",
                {
                    "p_tenant_id": tenant_id,
                    "p_cart_id": cart_id,
                    "p_product_id": product_id,
                    "p_variation_id": variation_id,
                    "p_quantity": quantity,
                    "p_unit_price_cents": unit_price_cents,
                    "p_expected_version": expected_version,
                },
            ).execute()
            rows = res.data or []
            if not rows:
                raise CartNotFound(f"cart {cart_id} not found for tenant {tenant_id}")
            row = rows[0]
            # Normalizar nombres OUT del RPC (prefijo `out_` desde rev. fix
            # del 2026-05-01). Mantener compat hacia atrás por si algún test
            # mockea con los nombres viejos.
            return {
                "cart_id": row.get("out_cart_id") or row.get("cart_id"),
                "new_version": row.get("out_new_version") or row.get("new_version"),
                "subtotal_cents": row.get("out_subtotal_cents")
                    if row.get("out_subtotal_cents") is not None
                    else row.get("subtotal_cents"),
                "total_cents": row.get("out_total_cents")
                    if row.get("out_total_cents") is not None
                    else row.get("total_cents"),
            }
        except CartError:
            raise
        except Exception as exc:
            msg = str(exc)
            if "version mismatch" in msg or "40001" in msg:
                raise CartConflict(msg) from exc
            if "not open" in msg:
                raise CartClosed(msg) from exc
            if "not found" in msg:
                raise CartNotFound(msg) from exc
            logger.exception("[carts_repo] add_item rpc failed: %s", exc)
            raise

    def update_shipping_meta(
        self,
        *,
        tenant_id: str,
        cart_id: str,
        shipping_meta: dict,
        shipping_cents: int,
        expected_version: int,
    ) -> int:
        """Persiste metadatos de envío + costo y bumpea version.

        Retorna el nuevo ``version``. Levanta :class:`CartConflict` si la
        version esperada no coincide (update afectó 0 filas).
        """
        res = (
            self._sb.table("conversation_carts")
            .update(
                {
                    "shipping_meta": shipping_meta,
                    "shipping_cents": shipping_cents,
                    "version": expected_version + 1,
                    "last_activity_at": "now()",
                }
            )
            .eq("tenant_id", tenant_id)
            .eq("id", cart_id)
            .eq("version", expected_version)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise CartConflict(
                f"cart {cart_id} version mismatch (expected {expected_version})"
            )
        # Recalcular total = subtotal + shipping desde la fila ya updated
        cart_row = rows[0]
        new_total = int(cart_row.get("subtotal_cents") or 0) + int(shipping_cents)
        if new_total != int(cart_row.get("total_cents") or 0):
            self._sb.table("conversation_carts").update(
                {"total_cents": new_total}
            ).eq("id", cart_id).execute()
        return int(cart_row["version"])

    def transition_status(
        self,
        *,
        tenant_id: str,
        cart_id: str,
        new_status: str,
        expected_version: int,
        converted_order_id: Optional[str] = None,
    ) -> int:
        """Transiciona el carrito a un estado terminal.

        Estados válidos: ``checkout``, ``converted``, ``abandoned``, ``cancelled``.
        ``converted`` requiere ``converted_order_id``.
        """
        valid = {"checkout", "converted", "abandoned", "cancelled"}
        if new_status not in valid:
            raise ValueError(f"invalid status transition target: {new_status}")
        if new_status == "converted" and not converted_order_id:
            raise ValueError("transition to 'converted' requires converted_order_id")

        update: dict = {
            "status": new_status,
            "version": expected_version + 1,
            "last_activity_at": "now()",
        }
        if converted_order_id:
            update["converted_order_id"] = converted_order_id

        res = (
            self._sb.table("conversation_carts")
            .update(update)
            .eq("tenant_id", tenant_id)
            .eq("id", cart_id)
            .eq("version", expected_version)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise CartConflict(
                f"cart {cart_id} version mismatch (expected {expected_version})"
            )
        return int(rows[0]["version"])

    def remove_item(
        self,
        *,
        tenant_id: str,
        cart_id: str,
        variation_id: str,
        expected_version: int,
    ) -> int:
        """Elimina un item completo del carrito y recalcula totales.

        Idempotente: si el item no existe, retorna la version sin cambios.
        """
        # Borrar el item
        self._sb.table("conversation_cart_items").delete().eq(
            "tenant_id", tenant_id
        ).eq("cart_id", cart_id).eq("variation_id", variation_id).execute()

        # Recalcular subtotal desde las filas remanentes
        items_res = (
            self._sb.table("conversation_cart_items")
            .select("quantity, unit_price_cents")
            .eq("tenant_id", tenant_id)
            .eq("cart_id", cart_id)
            .execute()
        )
        new_subtotal = sum(
            int(r["quantity"]) * int(r["unit_price_cents"])
            for r in (items_res.data or [])
        )

        # Update con check de version (optimistic lock)
        cart_res = (
            self._sb.table("conversation_carts")
            .select("shipping_cents")
            .eq("id", cart_id)
            .single()
            .execute()
        )
        shipping = int((cart_res.data or {}).get("shipping_cents") or 0)

        res = (
            self._sb.table("conversation_carts")
            .update(
                {
                    "subtotal_cents": new_subtotal,
                    "total_cents": new_subtotal + shipping,
                    "version": expected_version + 1,
                    "last_activity_at": "now()",
                }
            )
            .eq("tenant_id", tenant_id)
            .eq("id", cart_id)
            .eq("version", expected_version)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise CartConflict(
                f"cart {cart_id} version mismatch (expected {expected_version})"
            )
        return int(rows[0]["version"])

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _fetch_items(self, *, tenant_id: str, cart_id: str) -> list[CartItem]:
        res = (
            self._sb.table("conversation_cart_items")
            .select(
                "id, cart_id, product_id, variation_id, quantity, "
                "unit_price_cents, meta"
            )
            .eq("tenant_id", tenant_id)
            .eq("cart_id", cart_id)
            .order("created_at")
            .execute()
        )
        return [
            CartItem(
                id=r["id"],
                cart_id=r["cart_id"],
                product_id=r["product_id"],
                variation_id=r["variation_id"],
                quantity=int(r["quantity"]),
                unit_price_cents=int(r["unit_price_cents"]),
                meta=r.get("meta") or {},
            )
            for r in (res.data or [])
        ]

    @staticmethod
    def _row_to_cart(row: dict) -> Cart:
        return Cart(
            id=row["id"],
            tenant_id=row["tenant_id"],
            conversation_id=row["conversation_id"],
            contact_id=row.get("contact_id"),
            status=row["status"],
            version=int(row["version"]),
            shipping_meta=row.get("shipping_meta") or {},
            subtotal_cents=int(row.get("subtotal_cents") or 0),
            shipping_cents=int(row.get("shipping_cents") or 0),
            total_cents=int(row.get("total_cents") or 0),
            currency=row.get("currency") or "COP",
            converted_order_id=row.get("converted_order_id"),
        )
