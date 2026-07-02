"""
Router de Productos — CRUD con aislamiento multi-tenant via RLS.

Schema real (migration 20260406181236_catalog_schema.sql):
  products:           id, tenant_id, title, description, status, external_reference_id
  product_variations: id, product_id, tenant_id, price, stock_quantity, attributes, external_variation_id

Endpoints:
  GET    /api/v1/products/                              — listar productos activos del tenant
  POST   /api/v1/products/                              — crear producto + variante inicial  [owner, manager]
  GET    /api/v1/products/{id}                          — obtener producto con variantes
  PATCH  /api/v1/products/{id}                          — editar título / descripción        [owner, manager]
  DELETE /api/v1/products/{id}                          — soft delete (status='inactive')    [owner, manager]
  PATCH  /api/v1/products/{id}/variations/{var_id}      — editar variante por ID             [owner, manager]
  POST   /api/v1/products/{id}/variations               — añadir variante a producto         [owner, manager]
  DELETE /api/v1/products/{id}/variations/{var_id}      — eliminar variante (no si es única) [owner, manager]

RBAC:
  owner / manager → lectura + escritura
  operator        → solo lectura (403 en escritura)

Nota: patch_variation dispara sync_meli_stock si stock_quantity cambia y hay listing activo.
"""
import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from supabase import Client

from dependencies.audit import audit_log
from dependencies.auth import get_current_tenant, get_service_client, require_write_role
from routers.marketplace import sync_meli_stock

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Products"])


# ─── Modelos Pydantic ──────────────────────────────────────────────────────────

class VariationCreate(BaseModel):
    # sku/attributes nullable: reflejan la realidad DB/web (un producto de variante única se crea sin
    # SKU y sin atributos). El contrato estricto previo (sku requerido, attributes con default)
    # divergía del web → impedía migrar addVariation. F2.2 los alinea.
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    price: float = Field(..., gt=0)
    cost_price: Optional[float] = Field(default=None, ge=0)  # costo interno (margen)
    compare_at_price: Optional[float] = Field(default=None, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    attributes: Optional[dict] = Field(default=None)
    weight_kg: Optional[float] = Field(default=None, ge=0)
    length_cm: Optional[float] = Field(default=None, ge=0)
    width_cm: Optional[float] = Field(default=None, ge=0)
    height_cm: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = None


class ProductCreate(BaseModel):
    # platform_category_id (marketplace) NO se captura por producto (ADR-0029 D2: se deriva por categoría).
    category_id: Optional[str] = None        # ADR-0027 categoría operativa per-tenant (única taxonomía de alta)
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    safety_note: Optional[str] = None        # nota de seguridad (Ley 1480, customer-facing)
    cover_image_url: Optional[str] = None
    attributes: Optional[dict] = None        # ADR-0029 F2: atributos PRODUCT-LEVEL (no-variante) {label: valor}
    variation: Optional[VariationCreate] = None        # una variante (retrocompat)
    variations: Optional[List[VariationCreate]] = None  # o varias (bulk atómico — alta de catálogo)


class ProductPatch(BaseModel):
    category_id: Optional[str] = None        # ADR-0027 categoría operativa per-tenant (marketplace se deriva, no per-producto)
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    description: Optional[str] = None
    safety_note: Optional[str] = None
    retracto_excluded: Optional[bool] = None  # exclusión derecho de retracto (Ley 1480)
    retracto_excluded_reason: Optional[str] = None
    cover_image_url: Optional[str] = None
    attributes: Optional[dict] = None         # ADR-0029 F2: atributos product-level {label: valor}
    status: Optional[str] = None              # 'active' | 'inactive' (restaurar/desactivar)


class VariationPatch(BaseModel):
    sku: Optional[str] = Field(default=None, min_length=1, max_length=100)
    price: Optional[float] = Field(default=None, gt=0)
    cost_price: Optional[float] = Field(default=None, ge=0)
    compare_at_price: Optional[float] = Field(default=None, ge=0)
    stock_quantity: Optional[int] = Field(default=None, ge=0)
    attributes: Optional[dict] = None
    weight_kg: Optional[float] = Field(default=None, ge=0)
    length_cm: Optional[float] = Field(default=None, ge=0)
    width_cm: Optional[float] = Field(default=None, ge=0)
    height_cm: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = None


# ─── Importación masiva (bulk) — enruta el mass-importer por la API (RBAC + audit) ──
class BulkVariation(BaseModel):
    sku: str = Field(..., min_length=1, max_length=100)
    price: float = Field(..., gt=0)
    compare_at_price: Optional[float] = Field(default=None, ge=0)
    cost_price: float = Field(default=0, ge=0)
    stock_quantity: int = Field(default=0, ge=0)
    attributes: Optional[dict] = None
    weight_kg: Optional[float] = Field(default=None, ge=0)
    length_cm: Optional[float] = Field(default=None, ge=0)
    width_cm: Optional[float] = Field(default=None, ge=0)
    height_cm: Optional[float] = Field(default=None, ge=0)
    image_url: Optional[str] = None


class BulkProduct(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    cover_image_url: Optional[str] = None
    category_id: Optional[str] = None
    variations: List[BulkVariation] = Field(default_factory=list)


class BulkImport(BaseModel):
    products: List[BulkProduct] = Field(default_factory=list, max_length=500)


# Campos que NUNCA deben quedar en null vía PATCH (requeridos por el dominio).
_PRODUCT_NEVER_CLEAR = {"title", "status"}
_VARIATION_NEVER_CLEAR = {"sku", "price", "stock_quantity"}
_PRODUCT_STATUSES = {"active", "inactive"}


def build_patch_update(patch: BaseModel, never_clear: set) -> dict:
    """PATCH semántico (F2.2): aplica SOLO los campos que el cliente envió explícitamente
    (`exclude_unset`), permitiendo limpiar a null los opcionales (safety_note, category_id, etc.).
    Protege `never_clear` de quedar en null aunque lleguen como null. Distingue 'campo ausente'
    (no se toca) de 'campo=null' (se limpia) — requisito para migrar editProduct a la API sin
    perder la capacidad de borrar una nota de seguridad / categoría (Ley 1480/ADR-0027)."""
    return {
        k: v
        for k, v in patch.model_dump(exclude_unset=True).items()
        if not (v is None and k in never_clear)
    }


def _assert_category_owned(supabase: Client, tenant_id: str, category_id: Optional[str]) -> None:
    """Valida que la categoría operativa (product_categories) pertenece al tenant.
    ADR-0025: el FK products.category_id es id-only (no compuesto con tenant_id), así que sin
    este chequeo un tenant podría referenciar la categoría de OTRO (integridad multi-tenant rota).
    No-op si category_id es None (la categoría operativa es opcional)."""
    if category_id is None:
        return
    owned = (
        supabase.table("product_categories")
        .select("id")
        .eq("id", category_id)
        .eq("tenant_id", tenant_id)
        .execute()
    )
    if not owned.data:
        raise HTTPException(status_code=422, detail="Categoría de catálogo inválida para este tenant")


def _norm_attr(s: str) -> str:
    """Normalización case/espacio-insensible (espeja normKey + canonicalizeAttrs del frontend)."""
    return str(s).strip().lower().replace(" ", "")


def _validate_attr_value(d: dict, key: str, value) -> None:
    """Valida UN valor contra su definición de contrato (criterio binario ADR-0024). Lanza 422 si viola.

    Regla (verify-before-build: 'Volumen' es type=metric con allowed_values → el gate real es allowed_values,
    no el type): si hay allowed_values → SET membership (con/sin unidad); si no → chequeo por tipo."""
    allowed = d.get("allowed_values") or []
    unit = str(d.get("unit") or "")
    sval = str(value).strip()
    if not sval:
        return  # vacío = atributo no provisto para este producto (opcional)
    if allowed:
        norm = _norm_attr(sval)
        ok = any(
            norm == _norm_attr(a) or norm == _norm_attr(f"{a}{unit}")
            for a in allowed
        )
        if not ok:
            raise HTTPException(
                status_code=422,
                detail=f"Valor '{sval}' fuera del contrato de '{key}'. Válidos: {', '.join(map(str, allowed))}",
            )
        return
    t = str(d.get("type") or "").lower()
    if t in ("metric", "number"):
        cleaned = sval
        if unit and cleaned.lower().endswith(unit.lower()):
            cleaned = cleaned[: -len(unit)].strip()
        try:
            float(cleaned.replace(",", "."))
        except ValueError:
            raise HTTPException(status_code=422, detail=f"'{key}' debe ser numérico (recibido '{sval}').")
    elif t == "boolean":
        if _norm_attr(sval) not in ("true", "false", "sí", "si", "no", "1", "0", "yes"):
            raise HTTPException(status_code=422, detail=f"'{key}' debe ser Sí/No (recibido '{sval}').")


def _validate_attributes_against_contract(
    supabase: Client, tenant_id: str, category_id: Optional[str], attributes: Optional[dict]
) -> None:
    """ADR-0029 D4 — valida products.attributes (product-level) contra el contrato de la categoría.

    Anti-alucinación: el bot cita estos atributos como HECHOS, así que deben estar gobernados. Si la
    categoría tiene contrato (product_attribute_definitions no-variante): cada atributo debe (a) tener un
    NOMBRE definido en el contrato, y (b) un VALOR válido (SET membership / numérico / booleano).
    NO-OP si no hay category_id, attributes vacío, o la categoría no tiene contrato (backward-compat:
    tenants sin contrato sembrado — p.ej. KAIU hasta el seed — no se ven afectados)."""
    if not category_id or not attributes:
        return
    defs = (
        supabase.table("product_attribute_definitions")
        .select("label, type, unit, allowed_values")
        .eq("tenant_id", tenant_id)
        .eq("product_category_id", category_id)
        .eq("is_variant_axis", False)
        .execute()
    )
    contract = defs.data or []
    if not contract:
        return
    by_label = {_norm_attr(d["label"]): d for d in contract}
    for raw_key, raw_val in attributes.items():
        d = by_label.get(_norm_attr(raw_key))
        if d is None:
            raise HTTPException(
                status_code=422,
                detail=f"Atributo '{raw_key}' no está en el contrato de esta categoría",
            )
        _validate_attr_value(d, raw_key, raw_val)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[dict])
async def list_products(
    status: Optional[str] = Query(default="active"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Lista productos del tenant con sus variantes. Por defecto solo activos."""
    try:
        query = (
            supabase.table("products")
            .select("id, title, description, status, platform_category_id, category_id, safety_note, attributes, retracto_excluded, cover_image_url, created_at, product_variations(id, sku, price, cost_price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)")
            .eq("tenant_id", tenant_id)
            .order("title")
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            query = query.eq("status", status)

        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error("Error listando productos tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener productos")


@router.post("/", response_model=dict, status_code=201)
@audit_log(entity_type="product", action="created")
async def create_product(
    product: ProductCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Crea producto + sus variantes (1 o N). Solo owner/manager."""
    # variations (lista) tiene prioridad; variation (single) es retrocompat.
    variations = product.variations or ([product.variation] if product.variation else [])
    if not variations:
        raise HTTPException(status_code=422, detail="Se requiere al menos una variante")
    try:
        # Integridad multi-tenant (ADR-0025): la categoría operativa DEBE pertenecer al tenant.
        # El FK products.category_id es id-only (no compuesto con tenant_id), así que sin este
        # chequeo un tenant podría referenciar la categoría de OTRO. platform_category_id es
        # taxonomía GLOBAL compartida (su FK basta, no hay riesgo cross-tenant).
        _assert_category_owned(supabase, tenant_id, product.category_id)
        # ADR-0029 D4: los atributos product-level deben respetar el contrato de la categoría (anti-alucinación).
        _validate_attributes_against_contract(supabase, tenant_id, product.category_id, product.attributes)

        prod_result = supabase.table("products").insert({
            "tenant_id": tenant_id,
            # platform_category_id nace null: la taxonomía marketplace se deriva por categoría (ADR-0029 D2).
            "platform_category_id": None,
            "category_id": product.category_id,
            "title": product.title,
            "description": product.description,
            "safety_note": product.safety_note,
            "cover_image_url": product.cover_image_url,
            "attributes": product.attributes or {},   # ADR-0029 F2: valores product-level (no-variante)
            "status": "active",
        }).execute()

        if not prod_result.data:
            raise HTTPException(status_code=500, detail="Error al crear producto")

        prod = prod_result.data[0]

        # Bulk insert atómico de todas las variantes (misma atomicidad que el alta directa previa).
        var_rows = [{
            "product_id": prod["id"],
            "tenant_id": tenant_id,
            "sku": v.sku,
            "price": v.price,
            "cost_price": v.cost_price,
            "compare_at_price": v.compare_at_price,
            "stock_quantity": v.stock_quantity,
            "attributes": v.attributes,
            "weight_kg": v.weight_kg,
            "length_cm": v.length_cm,
            "width_cm": v.width_cm,
            "height_cm": v.height_cm,
            "image_url": v.image_url,
        } for v in variations]
        try:
            # tenant_filter:exempt: cada row de var_rows lleva tenant_id del JWT (arriba); el AST no traza el payload de una comprehension.
            var_result = supabase.table("product_variations").insert(var_rows).execute()
        except Exception as var_err:
            # El producto ya se persistió; sin variantes quedaría HUÉRFANO (el bot lo listaría con
            # cero variantes y el usuario acumularía basura al reintentar). Lo borramos y devolvemos
            # un 4xx accionable en vez del 500 opaco que enmascaraba el conflicto de SKU.
            supabase.table("products").delete().eq("id", prod["id"]).eq("tenant_id", tenant_id).execute()
            emsg = str(var_err).lower()
            if "uc_tenant_sku" in emsg or "duplicate key" in emsg or "23505" in emsg:
                raise HTTPException(status_code=409, detail="SKU duplicado: ya existe una variante con ese SKU.") from var_err
            if "23502" in emsg or "not null" in emsg or "not-null" in emsg:
                raise HTTPException(status_code=422, detail="Cada variante requiere un SKU.") from var_err
            raise HTTPException(status_code=500, detail="Error al crear las variantes del producto") from var_err

        prod["product_variations"] = var_result.data or []
        return prod
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creando producto tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al crear producto")


@router.post("/bulk", response_model=dict, status_code=201)
@audit_log(entity_type="product", action="created")
async def bulk_import_products(
    payload: BulkImport,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Importación masiva vía API (antes: el importador escribía DIRECTO a Supabase desde el browser,
    saltándose RBAC + @audit_log + validación de ownership). Por producto: reusa por título o crea; las
    variantes se upsertan por (tenant_id, sku) — misma semántica que el importador. Tolerante: un producto
    que falla NO detiene los demás (se acumula en errors). Solo owner/manager."""
    created = reused = variants_upserted = 0
    errors: list[dict] = []
    owned_cats: set = set()
    for prod in payload.products or []:
        try:
            # Ownership de la categoría (una vez por categoría; integridad multi-tenant ADR-0025).
            if prod.category_id and prod.category_id not in owned_cats:
                _assert_category_owned(supabase, tenant_id, prod.category_id)
                owned_cats.add(prod.category_id)

            # Producto: reusar por título (dentro del tenant) o crear.
            existing = (
                supabase.table("products").select("id")
                .eq("tenant_id", tenant_id).eq("title", prod.title).limit(1).execute()
            )
            if existing.data:
                product_id = existing.data[0]["id"]
                upd = {"status": "active"}
                if prod.category_id:
                    upd["category_id"] = prod.category_id
                supabase.table("products").update(upd).eq("id", product_id).eq("tenant_id", tenant_id).execute()
                reused += 1
            else:
                ins = supabase.table("products").insert({
                    "tenant_id": tenant_id,
                    "title": prod.title,
                    "description": prod.description,
                    "cover_image_url": prod.cover_image_url,
                    "category_id": prod.category_id,
                    # marketplace se deriva por categoría, no per-producto (ADR-0029 D2).
                    "platform_category_id": None,
                    "status": "active",
                }).execute()
                if not ins.data:
                    raise RuntimeError("insert de producto sin data")
                product_id = ins.data[0]["id"]
                created += 1

            # Variantes: upsert por (tenant_id, sku) — misma clave que el importador (uc_tenant_sku).
            vrows = [{
                "product_id": product_id,
                "tenant_id": tenant_id,
                "sku": v.sku,
                "price": v.price,
                "compare_at_price": v.compare_at_price,
                "cost_price": v.cost_price,
                "stock_quantity": v.stock_quantity,
                "attributes": v.attributes,
                "weight_kg": v.weight_kg,
                "length_cm": v.length_cm,
                "width_cm": v.width_cm,
                "height_cm": v.height_cm,
                "image_url": v.image_url,
            } for v in (prod.variations or [])]
            if vrows:
                # tenant_filter:exempt:payload_includes_tenant_id — cada row lleva "tenant_id": tenant_id (arriba)
                supabase.table("product_variations").upsert(vrows, on_conflict="tenant_id,sku").execute()
                variants_upserted += len(vrows)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("[BULK] producto '%s' falló: %s", prod.title, exc)
            errors.append({"product": prod.title, "error": str(exc)})

    return {
        "products_created": created,
        "products_reused": reused,
        "variants_upserted": variants_upserted,
        "errors": errors,
    }


@router.get("/{product_id}", response_model=dict)
async def get_product(
    product_id: str,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
):
    """Retorna producto con variantes. Valida que pertenece al tenant."""
    try:
        result = (
            supabase.table("products")
            .select("id, title, description, status, platform_category_id, category_id, safety_note, attributes, retracto_excluded, cover_image_url, created_at, product_variations(id, sku, price, cost_price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)")
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return result.data
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error obteniendo producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener producto")


@router.patch("/{product_id}", response_model=dict)
@audit_log(entity_type="product", action="updated")
async def patch_product(
    product_id: str,
    product: ProductPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """Edita campos del producto (título, descripción, categorías, safety_note, retracto).
    PATCH semántico: los campos opcionales enviados como null se limpian. Solo owner/manager."""
    try:
        data = build_patch_update(product, _PRODUCT_NEVER_CLEAR)
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")
        if "status" in data and data["status"] not in _PRODUCT_STATUSES:
            raise HTTPException(status_code=422, detail="Estado inválido (active | inactive).")
        # Integridad multi-tenant (ADR-0025): si el patch reasigna category_id, debe ser del tenant.
        if "category_id" in data:
            _assert_category_owned(supabase, tenant_id, data["category_id"])
        # ADR-0029 D4: si el patch toca attributes (o reasigna categoría), valida contra el contrato de la
        # categoría EFECTIVA (la del patch si se reasigna; si no, la actual del producto).
        if "attributes" in data:
            eff_cat = data["category_id"] if "category_id" in data else None
            if eff_cat is None:
                cur = (
                    supabase.table("products")
                    .select("category_id")
                    .eq("id", product_id)
                    .eq("tenant_id", tenant_id)
                    .single()
                    .execute()
                )
                eff_cat = (cur.data or {}).get("category_id")
            _validate_attributes_against_contract(supabase, tenant_id, eff_cat, data["attributes"])

        result = (
            supabase.table("products")
            .update(data)
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al editar producto")


@router.patch("/{product_id}/variations/{variation_id}", response_model=dict)
@audit_log(entity_type="variation", action="updated")
async def patch_variation(
    product_id: str,
    variation_id: str,
    variation: VariationPatch,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Edita precio, stock y/o atributos de una variante específica del producto.
    Requiere variation_id explícito — soporta productos multi-variante.
    Solo owner/manager.
    """
    try:
        data = build_patch_update(variation, _VARIATION_NEVER_CLEAR)
        if not data:
            raise HTTPException(status_code=422, detail="No hay campos para actualizar")

        # Verificar que la variante pertenece al producto y al tenant
        check = (
            supabase.table("product_variations")
            .select("id")
            .eq("id", variation_id)
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Variante no encontrada")

        result = (
            supabase.table("product_variations")
            .update(data)
            .eq("id", variation_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Error al actualizar variante")

        # Si el stock cambió, sincronizar con MeLi en background (best-effort)
        if "stock_quantity" in data:
            asyncio.ensure_future(
                sync_meli_stock(variation_id, data["stock_quantity"], supabase)
            )

        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error editando variante %s producto %s: %s", variation_id, product_id, e)
        raise HTTPException(status_code=500, detail="Error al editar variante")


@router.post("/{product_id}/variations", response_model=dict, status_code=201)
@audit_log(entity_type="variation", action="created")
async def add_variation(
    product_id: str,
    variation: VariationCreate,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Añade una nueva variante a un producto existente.
    Permite agregar tallas, colores u otras dimensiones a productos ya creados.
    Solo owner/manager.
    """
    try:
        # Verificar que el producto pertenece al tenant
        prod_check = (
            supabase.table("products")
            .select("id")
            .eq("id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not prod_check.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")

        result = supabase.table("product_variations").insert({
            "product_id": product_id,
            "tenant_id": tenant_id,
            "sku": variation.sku,
            "price": variation.price,
            "cost_price": variation.cost_price,
            "compare_at_price": variation.compare_at_price,
            "stock_quantity": variation.stock_quantity,
            "attributes": variation.attributes,
            "weight_kg": variation.weight_kg,
            "length_cm": variation.length_cm,
            "width_cm": variation.width_cm,
            "height_cm": variation.height_cm,
            "image_url": variation.image_url,
        }).execute()

        if not result.data:
            raise HTTPException(status_code=500, detail="Error al crear variante")
        return result.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error añadiendo variante a producto %s: %s", product_id, e)
        raise HTTPException(status_code=500, detail="Error al añadir variante")


@router.delete("/{product_id}/variations/{variation_id}", status_code=204)
@audit_log(entity_type="variation", action="deleted")
async def delete_variation(
    product_id: str,
    variation_id: str,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    Elimina una variante específica de un producto.
    No se puede eliminar si es la única variante del producto.
    Solo owner/manager.
    """
    try:
        # Verificar que no es la única variante
        count_result = (
            supabase.table("product_variations")
            .select("id")
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if len(count_result.data or []) <= 1:
            raise HTTPException(
                status_code=422,
                detail="No se puede eliminar la única variante del producto. Desactiva el producto si deseas retirarlo."
            )

        result = (
            supabase.table("product_variations")
            .delete()
            .eq("id", variation_id)
            .eq("product_id", product_id)
            .eq("tenant_id", tenant_id)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Variante no encontrada")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando variante %s producto %s: %s", variation_id, product_id, e)
        raise HTTPException(status_code=500, detail="Error al eliminar variante")


@router.delete("/{product_id}", status_code=204)
@audit_log(entity_type="product", action="deleted")
async def delete_product(
    product_id: str,
    request: Request,
    hard: bool = Query(default=False),
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    _role: str = Depends(require_write_role),
):
    """
    DELETE /products/{id}: por defecto soft-delete (status='inactive', preserva trazabilidad).
    Con ?hard=true: hard-delete REAL — la cascada de FK borra variantes, marketplace_listings y
    stock_reservations; los order_items quedan con product_id/variation_id en NULL, así que el
    historial de pedidos se preserva POR DISEÑO (ON DELETE SET NULL). Solo owner/manager.
    """
    try:
        # tenant_filter:exempt: .eq("tenant_id") aplicado en `query` (línea siguiente); el branch delete/update impide el chain directo trazable por AST.
        table = supabase.table("products")
        query = table.delete() if hard else table.update({"status": "inactive"})
        result = query.eq("id", product_id).eq("tenant_id", tenant_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error eliminando producto %s (hard=%s): %s", product_id, hard, e)
        raise HTTPException(status_code=500, detail="Error al eliminar producto")
