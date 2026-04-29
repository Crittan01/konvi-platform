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
        expected_version: Optional[int] = None,
    ) -> int:
        """Persiste metadatos de envío + costo y bumpea version.

        Si ``expected_version`` es None, se hace UPDATE sin check optimista
        (read-current + apply). Útil cuando un mismo turn ejecuta múltiples
        tools que tocan el cart y la versión cached del context queda stale
        rápidamente.

        Retorna el nuevo ``version``. Levanta :class:`CartConflict` si la
        version esperada no coincide (update afectó 0 filas).
        """
        if expected_version is None:
            # Leer el version actual y reintentar; si la fila desaparece
            # (CASCADE, etc.), levantar CartNotFound.
            cur = (
                self._sb.table("conversation_carts")
                .select("version")
                .eq("id", cart_id)
                .eq("tenant_id", tenant_id)
                .single()
                .execute()
            )
            if not cur.data:
                raise CartNotFound(f"cart {cart_id} not found for tenant {tenant_id}")
            expected_version = int(cur.data["version"])
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

    # ── Soft-reserve helpers (RPCs de stock_reservations) ───────────────────
    #
    # Diseño Stripe Checkout pattern: reservar al confirmar intención fuerte
    # (quote_shipping_ok), consumir al pagar, liberar al cancelar. TTL 35 min
    # alineado con PENDING_PAYMENT_TTL_MINUTES.
    # Schema: supabase/migrations/20260502000000_stock_reservations.sql

    def reserve_stock_for_cart(
        self,
        *,
        tenant_id: str,
        cart_id: str,
        conversation_id: str,
        items: list[dict],  # [{variation_id, qty}]
        ttl_minutes: int = 35,
    ) -> tuple[list[dict], list[str]]:
        """Reserva stock para todos los items del cart de forma atómica por item.

        Retorna ``(reservations, insufficient)``:
          - ``reservations``: lista de dicts ``{variation_id, reservation_id, expires_at}``
          - ``insufficient``: lista de variation_id donde no había stock suficiente

        Si algún item falla, los anteriores quedan reservados (caller decide
        si los libera o sigue con los disponibles). Cada llamada a la RPC
        es atómica con FOR NO KEY UPDATE.
        """
        reservations: list[dict] = []
        insufficient: list[str] = []
        for it in items:
            variation_id = str(it.get("variation_id") or "").strip()
            qty = int(it.get("qty") or 0)
            if not variation_id or qty <= 0:
                continue
            try:
                res = self._sb.rpc(
                    "rpc_stock_reserve",
                    {
                        "p_tenant_id": tenant_id,
                        "p_variation_id": variation_id,
                        "p_qty": qty,
                        "p_cart_id": cart_id,
                        "p_conversation_id": conversation_id,
                        "p_ttl_minutes": ttl_minutes,
                    },
                ).execute()
                rows = res.data or []
                if rows:
                    row = rows[0]
                    reservations.append({
                        "variation_id": variation_id,
                        "reservation_id": row.get("out_reservation_id"),
                        "expires_at": row.get("out_expires_at"),
                        "available_after": row.get("out_available_after"),
                    })
            except Exception as exc:
                msg = str(exc)
                if "insufficient_stock" in msg or "P0001" in msg:
                    logger.info(
                        "[carts_repo] insufficient stock var=%s qty=%d: %s",
                        variation_id, qty, msg,
                    )
                    insufficient.append(variation_id)
                else:
                    logger.exception(
                        "[carts_repo] reserve_stock failed var=%s: %s",
                        variation_id, exc,
                    )
                    insufficient.append(variation_id)
        return reservations, insufficient

    def consume_reservations_for_order(
        self,
        *,
        cart_id: str,
        order_id: str,
    ) -> int:
        """Convierte todas las reservas activas del cart en stock_movements.

        Llamar cuando Wompi confirma APPROVED. Decrementa stock_quantity
        real y marca la reserva como ``consumed``. Retorna el conteo
        de reservas consumidas exitosamente.
        """
        # Listar reservas activas del cart
        res = (
            self._sb.table("stock_reservations")
            .select("id")
            .eq("cart_id", cart_id)
            .eq("status", "active")
            .execute()
        )
        reservation_ids = [r["id"] for r in (res.data or [])]
        consumed = 0
        for rid in reservation_ids:
            try:
                self._sb.rpc(
                    "rpc_stock_reservation_consume",
                    {"p_reservation_id": rid, "p_order_id": order_id},
                ).execute()
                consumed += 1
            except Exception as exc:
                logger.warning(
                    "[carts_repo] consume reservation=%s failed: %s",
                    rid, exc,
                )
        return consumed

    def release_reservations_for_cart(self, *, cart_id: str) -> int:
        """Libera todas las reservas activas del cart (cancelación/abandono).

        Retorna el conteo de reservas liberadas.
        """
        res = (
            self._sb.table("stock_reservations")
            .select("id")
            .eq("cart_id", cart_id)
            .eq("status", "active")
            .execute()
        )
        reservation_ids = [r["id"] for r in (res.data or [])]
        released = 0
        for rid in reservation_ids:
            try:
                self._sb.rpc(
                    "rpc_stock_reservation_release",
                    {"p_reservation_id": rid},
                ).execute()
                released += 1
            except Exception as exc:
                logger.warning(
                    "[carts_repo] release reservation=%s failed: %s",
                    rid, exc,
                )
        return released

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
