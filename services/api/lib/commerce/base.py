"""CommerceChannelAdapter — interface base del eje COMERCIO del channel registry.

Hermano de `lib/channels/base.py` (que cubre el eje MENSAJERÍA). Comercio y
mensajería son capacidades ORTOGONALES: un canal implementa una, otra, o ambas.
Ver ADR-0038 (hub de comercio multicanal).

Define el contrato que CUALQUIER canal de venta (MeLi hoy; tienda virtual,
Shopify, otros marketplaces mañana) debe implementar para proyectar el catálogo
de Supabase e ingerir sus pedidos.

Diseño (igual que el adapter de mensajería):
  • Protocol (typing.Protocol), duck-typed + @runtime_checkable.
  • El adapter es PURE I/O contra la API del canal — NO escribe DB. El catálogo,
    el stock (vía RPC idempotente) y los `orders` son responsabilidad del caller
    (invariante load-bearing: Supabase es la fuente de verdad).
  • El adapter resuelve su credencial per-tenant internamente (patrón OAuth
    existente: refresh single-flight vía lease + Vault). Se admite inyección de
    `supabase` para tests; NO se pasa el access_token crudo por firma pública.
  • Negociación de capacidad: capabilities() declara qué sabe hacer el canal, así
    el dispatcher degrada con gracia (ej. MeLi HOY sin "publish" — import-only).

Todas las dataclasses de resultado llevan `error_code` + `retry_after_seconds`
para propagar rate-limit (429/Retry-After) al caller sin acoplarlo al canal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

# ─── Capacidades declarables ────────────────────────────────────────────────
# capabilities() devuelve un subconjunto de esto. El dispatcher salta las que
# el canal no declara (degradación grácil).
CAPABILITIES = frozenset({
    "publish", "update", "pause", "resume", "close",
    "sync_stock", "sync_price", "sync_images",
    "categories", "attributes",
    "order_ingest", "reconcile",
})


# ─── Data types canónicos ───────────────────────────────────────────────────


@dataclass
class CatalogItem:
    """Producto/variación proyectado desde Supabase para publicar/actualizar en
    un canal. Lo ensambla el CALLER desde products + product_variations +
    product_attribute_definitions + product_categories. `available_quantity` es
    el stock DISPONIBLE (bruto − reservas activas), NUNCA el bruto."""
    tenant_id: str
    product_id: str
    sku: str
    title: str
    available_quantity: int
    price: float
    variation_id: Optional[str] = None
    description: str = ""
    compare_at_price: Optional[float] = None
    currency: str = "COP"
    condition: str = "new"                 # new | used | refurbished
    product_category_id: Optional[str] = None  # categoría Konvi (se mapea al canal)
    attributes: dict = field(default_factory=dict)   # contrato ADR-0029 (code → value)
    image_urls: list = field(default_factory=list)
    safety_note: Optional[str] = None
    raw: Optional[dict] = None


@dataclass
class ListingRef:
    """Referencia a un listing en un canal (fila de marketplace_listings)."""
    provider: str                          # 'meli' | 'shopify' | 'web' | ...
    external_id: str                       # id del item en el canal
    channel_variation_id: Optional[str] = None  # id de variación en el canal, si aplica
    variation_id: Optional[str] = None     # variación Konvi mapeada


@dataclass
class PublishResult:
    """Resultado de publish/update/pause/resume/close/sync_images."""
    ok: bool
    external_id: Optional[str] = None
    permalink: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class StockSyncResult:
    ok: bool
    synced_quantity: Optional[int] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class PriceSyncResult:
    ok: bool
    synced_price: Optional[float] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class ChannelCategory:
    """Categoría del canal (nodo del árbol de taxonomía del canal)."""
    channel_category_id: str
    name: str
    path: Optional[str] = None
    leaf: bool = True


@dataclass
class RequiredAttribute:
    """Atributo que el canal exige/acepta para una categoría (para validar
    antes de publicar — validación BINARIA, ADR-0024)."""
    code: str
    name: str
    value_type: str = "string"             # string | number | boolean | list
    required: bool = False
    allowed_values: Optional[list] = None  # listas cerradas (SET membership)
    tags: dict = field(default_factory=dict)


@dataclass
class ListingValidation:
    """Resultado de validate_for_publish (binario: presencia + SET membership)."""
    ok: bool
    missing: list = field(default_factory=list)   # codes de atributos requeridos ausentes
    invalid: list = field(default_factory=list)   # (code, value) fuera del SET permitido
    errors: list = field(default_factory=list)


@dataclass
class IngestedOrderLine:
    external_item_id: str
    quantity: int
    unit_price: float
    variation_ref: Optional[str] = None    # id de variación en el canal
    sku: Optional[str] = None


@dataclass
class IngestedOrder:
    """Pedido normalizado del canal → Supabase (el CALLER persiste + descuenta
    stock idempotente). El adapter NO escribe DB."""
    provider: str
    external_order_id: str
    status: str
    total_amount: float
    lines: list = field(default_factory=list)      # list[IngestedOrderLine]
    currency: str = "COP"
    buyer: dict = field(default_factory=dict)       # {external_user_id, name, phone?, ...}
    created_at_iso: Optional[str] = None
    shipping: Optional[dict] = None
    raw: Optional[dict] = None


@dataclass
class OrderNotification:
    """Notificación normalizada (webhook) que apunta a un pedido a fetchear."""
    provider: str
    topic: str
    external_order_id: Optional[str] = None
    resource: Optional[str] = None          # ruta a GET (ej. MeLi '/orders/123')
    user_id: Optional[str] = None
    raw: Optional[dict] = None


@dataclass
class ChannelListingState:
    """Estado del listing leído del canal, para reconciliación de drift."""
    external_id: str
    status: Optional[str] = None
    price: Optional[float] = None
    available_quantity: Optional[int] = None
    title: Optional[str] = None
    permalink: Optional[str] = None
    raw: Optional[dict] = None


# ─── Protocol (interface) ───────────────────────────────────────────────────


@runtime_checkable
class CommerceChannelAdapter(Protocol):
    """Contrato del eje COMERCIO. Todos los args keyword-only. Los métodos de
    escritura son async (hit a la API del canal); parse/verify son sync (I/O puro).
    El adapter NUNCA escribe DB — proyecta/traduce; el caller persiste."""

    # ── identidad / negociación de capacidad ──
    def channel_name(self) -> str: ...
    def capabilities(self) -> set: ...

    # ── A. Ciclo de vida del listing (write; Supabase → canal) ──
    async def publish_listing(self, *, tenant_id: str, item: CatalogItem, supabase: Any = None) -> PublishResult: ...
    async def update_listing(self, *, tenant_id: str, ref: ListingRef, item: CatalogItem, supabase: Any = None) -> PublishResult: ...
    async def pause_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> PublishResult: ...
    async def resume_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> PublishResult: ...
    async def close_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> PublishResult: ...

    # ── B. Sync de campo (hot paths) ──
    async def sync_stock(self, *, tenant_id: str, ref: ListingRef, quantity: int,
                         siblings: Optional[list] = None, supabase: Any = None) -> StockSyncResult: ...
    async def sync_price(self, *, tenant_id: str, ref: ListingRef, price: float,
                         compare_at: Optional[float] = None, supabase: Any = None) -> PriceSyncResult: ...
    async def sync_images(self, *, tenant_id: str, ref: ListingRef, image_urls: list, supabase: Any = None) -> PublishResult: ...

    # ── C. Descubrimiento/validación de categoría + atributos ──
    async def fetch_categories(self, *, tenant_id: str, root: Optional[str] = None, supabase: Any = None) -> list: ...
    async def fetch_category_attributes(self, *, tenant_id: str, channel_category_id: str, supabase: Any = None) -> list: ...
    async def suggest_category(self, *, tenant_id: str, item: CatalogItem, supabase: Any = None) -> Optional[ChannelCategory]: ...
    def validate_for_publish(self, *, item: CatalogItem, required: list) -> ListingValidation: ...

    # ── D. Ingesta de pedidos (canal → Supabase; el caller persiste) ──
    def verify_origin(self, *, headers: dict, raw_body: bytes, tenant_id: str) -> bool: ...
    def parse_order_notification(self, payload: dict) -> OrderNotification: ...
    async def fetch_order(self, *, tenant_id: str, external_order_id: str, supabase: Any = None) -> IngestedOrder: ...
    async def list_orders(self, *, tenant_id: str, since_iso: str, supabase: Any = None) -> list: ...

    # ── E. Reconciliación (canal → Supabase; solo lectura, para drift) ──
    async def fetch_listing(self, *, tenant_id: str, ref: ListingRef, supabase: Any = None) -> ChannelListingState: ...
