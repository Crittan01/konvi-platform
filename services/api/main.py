import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from config import get_settings  # G13 — config central validada

from fastapi import Depends as _Depends

from dependencies.auth import reject_if_tenant_deleting, enforce_mfa
from dependencies.internal_auth import enforce_mfa_internal_or_user  # noqa: E402
from routers import (
    aveonline_webhook,
    catalog,
    claims,
    contacts,
    conversations,
    coupons,
    expenses,
    integrations,
    internal_meli,
    knowledge_base,
    marketplace,
    meli_webhook,
    orders,
    product_attribute_definitions,
    product_categories,
    products,
    purchases,
    resend_webhook,
    settings,
    shipping,
    telegram_webhook,
    wompi_webhook,
)

# Rev. 109 J.2.4.4 Fase 2 — gate compartido para todos los routers de mutación.
# Aplica `reject_if_tenant_deleting` que rechaza writes con HTTP 423 si el
# tenant está en grace period de offboarding. Skip automático para GET/HEAD/
# OPTIONS (read-only). Excluido en webhooks externos (sin JWT) y en
# tenant_offboarding (cancel-deletion debe funcionar siempre durante grace).
_OFFBOARDING_GATE = [_Depends(reject_if_tenant_deleting)]
# BLOQUE 0 (P1): además del gate de offboarding, exige AAL2 si el usuario tiene MFA
# verificado. Se aplica a routers sensibles: config (settings), credenciales (integrations),
# dinero (expenses, purchases), export/borrado de cuenta (tenant_offboarding: export +
# request-deletion, por-endpoint), export de PII (data_subject_request) y crédito (sic_report).
# NO al router `mfa` (se necesita aal1-con-factor para completar el 2º factor), NI a
# tenant_offboarding /status y /cancel-deletion (deben correr en grace/recovery), ni a
# webhooks (sin JWT). `orders` NO se gatea a nivel router (alta frecuencia + dual-auth bot);
# sus endpoints money-movement (PATCH, payment-link) se gatean por-endpoint en orders.py.
_MFA_GATE = [_Depends(reject_if_tenant_deleting), _Depends(enforce_mfa)]

logger = logging.getLogger("api.startup")

# Logging idéntico al de Render: todos los loggers de la app al mismo stream que uvicorn
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(name)s: %(message)s",
)

def _validate_startup_config() -> None:
    """
    Valida coherencia de configuración crítica antes de aceptar tráfico.
    Falla rápido (sys.exit) si detecta incoherencias que causarían errores
    silenciosos en producción.

    G13 (2026-08-13): la lógica vive en `config.validate_critical()` (config
    central — declaración + defaults + checks en una sola fuente). Esta función
    es solo el puente boot: loguea y sale.

    Nota: las credenciales de Wompi son por-tenant (tenant_integrations + Vault).
    No se validan aquí.
    """
    from config import validate_critical

    errors = validate_critical()
    if errors:
        for err in errors:
            logger.error("[STARTUP] ❌ %s", err)
        sys.exit(1)

    logger.info("[STARTUP] Validación de configuración OK")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    # ADR-0038 (P1) — activar los commerce adapters reales, sobreescribiendo los
    # stubs default-deny del registry. Fail-safe: si el registro fallara, se loguea
    # y el arranque continúa (el registry cae al stub; ningún caller lo usa aún).
    try:
        from lib.commerce.meli import register as _register_meli_commerce
        _register_meli_commerce()
        logger.info("[STARTUP] commerce adapter MeLi registrado")
    except Exception as _exc:  # noqa: BLE001
        logger.warning("[STARTUP] no se pudo registrar el commerce adapter MeLi: %s", _exc)
    yield


# GREEN-16 (OWASP 2026-08-23): el schema OpenAPI (/docs, /redoc, /openapi.json)
# no se expone en producción — revela la superficie completa del API a atacantes.
_is_prod_env = get_settings().APP_ENV.strip().lower() in ("production", "prod")

app = FastAPI(
    title="Konvi Core API",
    description="Síncrona REST",
    lifespan=lifespan,
    docs_url=None if _is_prod_env else "/docs",
    redoc_url=None if _is_prod_env else "/redoc",
    openapi_url=None if _is_prod_env else "/openapi.json",
)

# ─── CORS — restringido a dominios permitidos ──────────────────────────────────
# En desarrollo: ALLOWED_ORIGINS=http://localhost:3000
# En producción (Render): configurar como secret con el dominio real del frontend
# G13: la fuente de la var es config.get_settings() (declarada + validada en boot).
_raw_origins = get_settings().ALLOWED_ORIGINS
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    # F7 — sin expose_headers el browser (fetch) NO puede leer estos headers de
    # respuesta cross-origin: el SPA necesita X-RateLimit-* / Retry-After para
    # respetar el throttling y X-Request-ID para correlacionar errores.
    expose_headers=[
        "X-RateLimit-Limit",
        "X-RateLimit-Remaining",
        "X-RateLimit-Reset",
        "Retry-After",
        "X-Request-ID",
    ],
)


# ─── G2 — Body-cap pre-lectura (anti-DoS por payload gigante) ────────────────
# Registrado DESPUÉS de CORS y ANTES de security_headers/request_id en el código
# → en ejecución queda por DENTRO de ambos: el 413 hereda X-Request-ID y los
# security headers en el camino de vuelta.
# El cap usa SOLO el header Content-Length (rechaza ANTES de leer el body). Sin
# backstop post-lectura: los endpoints del gateway son JSON (los frameworks
# respetan Content-Length) y los uploads grandes van directo a Supabase Storage
# desde el browser — verificado: ningún router de services/api usa UploadFile.
_MAX_REQUEST_BODY_BYTES_DEFAULT = 2 * 1024 * 1024  # 2MB


def _max_request_body_bytes() -> int:
    """Límite de body en bytes (env MAX_REQUEST_BODY_BYTES, default 2MB).

    Se lee por request (un os.getenv es negligible) para que ops/tests puedan
    ajustarlo sin reimportar la app.
    """
    try:
        return int(
            os.getenv("MAX_REQUEST_BODY_BYTES", str(_MAX_REQUEST_BODY_BYTES_DEFAULT))
        )
    except ValueError:
        return _MAX_REQUEST_BODY_BYTES_DEFAULT


@app.middleware("http")
async def body_size_limit_middleware(request: Request, call_next):
    """413 si Content-Length supera el cap — ANTES de consumir el body."""
    raw = request.headers.get("Content-Length", "")
    try:
        declared = int(raw) if raw else 0
    except ValueError:
        # Header malformado: no decidimos aquí — el server HTTP lo rechaza (400).
        declared = 0
    max_bytes = _max_request_body_bytes()
    if declared > max_bytes:
        return JSONResponse(
            status_code=413,
            content={
                "detail": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "msg": (
                        "El cuerpo de la petición supera el máximo permitido "
                        f"({max_bytes} bytes)."
                    ),
                }
            },
        )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # Rev. 100 — CSP defensivo + HSTS para clientes HTTPS.
    # CSP `default-src 'none'` porque la API solo sirve JSON, no HTML.
    # `connect-src 'self'` permite que un browser en el mismo origin la consuma.
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; connect-src 'self'; frame-ancestors 'none'",
    )
    # HSTS: idempotente. El browser solo lo respeta sobre HTTPS (Render lo es).
    response.headers.setdefault(
        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
    )
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """F7 — correlation-id en el pipeline HTTP síncrono.

    El webhook_framework ya tenía correlation_id; el gateway HTTP no. Sin un ID
    por request es imposible correlacionar los logs de un fallo end-to-end.

    Respeta un `X-Request-ID` entrante (proxy/tracing upstream) o genera uno.
    Lo expone en `request.state.request_id` (accesible por handlers) y lo
    devuelve en el header de respuesta.
    """
    incoming = request.headers.get("X-Request-ID", "").strip()
    request_id = incoming[:64] if incoming else uuid.uuid4().hex
    request.state.request_id = request_id
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ─── F7 — Contrato de error uniforme es-CO ─────────────────────────────────────
# Sin handler, FastAPI devuelve 422 con detail=[{type,loc,msg(EN),input}] — un
# array con mensajes en inglés que el frontend es-CO no puede mostrar. Este
# handler normaliza a `{detail: "<texto es-CO>", errors: [...], request_id}`.

_VALIDATION_ES: dict[str, str] = {
    "missing": "es obligatorio",
    "string_type": "debe ser texto",
    "string_too_short": "es demasiado corto",
    "string_too_long": "es demasiado largo",
    "int_parsing": "debe ser un número entero",
    "int_type": "debe ser un número entero",
    "float_parsing": "debe ser un número",
    "float_type": "debe ser un número",
    "bool_parsing": "debe ser verdadero o falso",
    "bool_type": "debe ser verdadero o falso",
    "value_error": "tiene un valor inválido",
    "json_invalid": "no es un JSON válido",
    "enum": "no es una opción permitida",
    "greater_than": "es demasiado pequeño",
    "greater_than_equal": "es demasiado pequeño",
    "less_than": "es demasiado grande",
    "less_than_equal": "es demasiado grande",
    "list_type": "debe ser una lista",
    "dict_type": "debe ser un objeto",
    "uuid_parsing": "no es un identificador válido",
    "datetime_parsing": "no es una fecha/hora válida",
}


def _field_label(loc: tuple) -> str:
    """Nombre de campo legible: descarta el prefijo body/query/path."""
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header")]
    return ".".join(parts) if parts else "petición"


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        field = _field_label(tuple(err.get("loc", ())))
        es_msg = _VALIDATION_ES.get(err.get("type", ""), "es inválido")
        errors.append({"field": field, "message": f"El campo '{field}' {es_msg}."})

    if len(errors) == 1:
        detail = errors[0]["message"]
    else:
        detail = "Hay campos inválidos en la petición: " + " ".join(
            e["message"] for e in errors
        )

    return JSONResponse(
        status_code=422,
        content={
            "detail": detail,
            "errors": errors,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


app.include_router(products.router, prefix="/api/v1/products", dependencies=_OFFBOARDING_GATE)
app.include_router(product_categories.router, prefix="/api/v1/product-categories", dependencies=_OFFBOARDING_GATE)
app.include_router(product_attribute_definitions.router, prefix="/api/v1/product-attribute-definitions", dependencies=_OFFBOARDING_GATE)
app.include_router(catalog.router, prefix="/api/v1/catalog", dependencies=_OFFBOARDING_GATE)
app.include_router(coupons.router, prefix="/api/v1/coupons", dependencies=_OFFBOARDING_GATE)
app.include_router(expenses.router, prefix="/api/v1/expenses", dependencies=_MFA_GATE)
app.include_router(conversations.router, prefix="/api/v1/conversations", dependencies=_OFFBOARDING_GATE)
app.include_router(orders.router, prefix="/api/v1/orders", dependencies=_OFFBOARDING_GATE)
app.include_router(contacts.router, prefix="/api/v1/contacts", dependencies=_OFFBOARDING_GATE)
# Rev. 93 — Habeas Data: Subject Access Request (SAR / ARCO).
from routers import data_subject_request as _dsr  # noqa: E402

# BLOQUE 0 (P1) — _MFA_GATE: el SAR exporta/imprime PII de un titular (export/portability
# + printable HTML). Exige AAL2 si el usuario tiene MFA (bulk-PII = crown jewel).
app.include_router(_dsr.router, prefix="/api/v1/contacts", dependencies=_MFA_GATE)
# Rev. 109 J.2.4.4 — Tenant offboarding (export + soft-delete + cancel).
# NO aplicar _OFFBOARDING_GATE — el owner debe poder cancelar dentro del grace.
from routers import tenant_offboarding as _toff  # noqa: E402

app.include_router(_toff.router, prefix="/api/v1/tenant/offboarding")
# Rev. 109 J.2.4.3 — MFA TOTP recovery codes.
from routers import mfa as _mfa  # noqa: E402

app.include_router(_mfa.router, prefix="/api/v1/mfa")
# Rev. 101 (F5) — SIC pre-cocinado.
from routers import sic_report as _sic  # noqa: E402

# BLOQUE 0 (P1) — _MFA_GATE: el reporte SIC expone datos de crédito (PII sensible).
app.include_router(_sic.router, prefix="/api/v1", dependencies=_MFA_GATE)
app.include_router(settings.router, prefix="/api/v1/settings", dependencies=_MFA_GATE)
# Integrations: gate MFA internal-aware — el endpoint UAT
# /aveonline/guide-dry-run es dual-auth (A0.2c) y se invoca service-to-service
# (X-Internal-Service-Secret); para usuarios JWT el gate exige AAL2 igual que
# _MFA_GATE (enforce_mfa_internal_or_user delega a la misma lógica).
app.include_router(
    integrations.router,
    prefix="/api/v1/integrations",
    dependencies=[
        _Depends(reject_if_tenant_deleting),
        _Depends(enforce_mfa_internal_or_user),
    ],
)
app.include_router(shipping.router, prefix="/api/v1/shipping", dependencies=_OFFBOARDING_GATE)
app.include_router(marketplace.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
# Webhooks externos NO usan _OFFBOARDING_GATE — no tienen JWT del tenant,
# vienen autenticados por signature del provider. Si el tenant está siendo
# eliminado, los webhooks fallarán en otros guards (RLS, FK, etc.).
app.include_router(meli_webhook.router, prefix="/api/v1/meli")
app.include_router(wompi_webhook.router, prefix="/api/v1/webhooks")
# Track 6 (2026-08-22) — Resend webhook de eventos de email (bounced/complained/
# failed/suppressed + suppression.*). Auth: firma svix sobre el raw body
# (RESEND_WEBHOOK_SECRET), NO JWT → SIN _OFFBOARDING_GATE, igual que wompi/meli.
app.include_router(resend_webhook.router, prefix="/api/v1/webhooks")
# Rev. 108 — Aveonline webhook estados de guía (dossier §6.2). Provider único
# de shipping post-pivote rev. 107 (ver ADR-0019). Envia eliminado en rev. 109.
app.include_router(aveonline_webhook.router, prefix="/api/v1/webhooks/aveonline")
# Webhook externo Telegram (comandos /resolver /estado de la escalación humana):
# autenticado por X-Telegram-Bot-Api-Secret-Token (hmac.compare_digest en el handler),
# NO por JWT → SIN _OFFBOARDING_GATE, igual que meli/wompi/aveonline. Con el gate, todo
# POST de Telegram recibía 401 (no manda Authorization) y la feature estaba muerta (F17).
app.include_router(telegram_webhook.router, prefix="/api/v1/integrations")
# M17 — Endpoints internos service-to-service (barridos de mantenimiento).
# Auth propia por-endpoint (require_internal_service: X-Internal-Service-Secret,
# SIN JWT ni X-Tenant-Id) → SIN _OFFBOARDING_GATE ni _MFA_GATE, igual que los
# webhooks externos: ningún usuario del Tenant Console debe alcanzarlos.
app.include_router(internal_meli.router, prefix="/api/v1/internal/meli")
# Rev. 109 ADR-0017 — Multi-agente per tenant (templates + AI suggest).
from routers import ai_agents as _ai_agents  # noqa: E402
from routers import catalog_ai as _catalog_ai  # noqa: E402
# F-transversales (drift D3): espejos server-side de /api/ai/* (web). Aditivos —
# el web sigue operando hasta el cutover del founder (retiro de GEMINI_API_KEY).
# G20: insights se suma como espejo (POST/GET) y cierra el cutover del web —
# los 3 handlers (/api/insights, /api/ai/preview, /api/ai/index-pending) ya son
# proxies a este servicio.
from routers import ai_preview as _ai_preview  # noqa: E402
from routers import ai_index as _ai_index  # noqa: E402
from routers import insights as _insights  # noqa: E402

app.include_router(_ai_agents.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
app.include_router(_catalog_ai.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
app.include_router(_ai_preview.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
app.include_router(_ai_index.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
app.include_router(_insights.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
# Rev. 72 — routers nuevos (cierran drifts D1/D2/D3)
app.include_router(claims.router, prefix="/api/v1/claims", dependencies=_OFFBOARDING_GATE)
app.include_router(purchases.router, prefix="/api/v1/purchases", dependencies=_MFA_GATE)
app.include_router(knowledge_base.router, prefix="/api/v1/knowledge-base", dependencies=_OFFBOARDING_GATE)

# Versión/build para trazabilidad (Render expone RENDER_GIT_COMMIT).
_BUILD_VERSION = (
    os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or os.getenv("APP_VERSION")
    or "unknown"
)


@app.get("/health")
def health_check():
    """Liveness — trivial y sin dependencias externas.

    Render usa este endpoint como healthcheck; NO debe tocar la DB (un blip de
    Supabase reiniciaría el servicio sano). Para readiness usar /health/ready.
    """
    return {"status": "ok", "version": _BUILD_VERSION}


@app.get("/health/ready")
def readiness_check(response: Response):
    """Readiness — verifica dependencias (DB) antes de declararse listo.

    Devuelve 503 si Supabase no responde. Separado de /health para no acoplar
    el liveness de Render a un blip transitorio de la DB.
    """
    db_ok = False
    detail = None
    try:
        from dependencies.auth import _get_service_client

        _get_service_client().table("tenants").select("id").limit(1).execute()
        db_ok = True
    except Exception as exc:  # pragma: no cover — depende de infra
        # M14 (auditoría 2026-08-02): el endpoint es PÚBLICO (sin auth) — el
        # mensaje interno de PostgREST/DB (host, schema, hint) NO se expone al
        # cliente. Detalle genérico hacia afuera; error completo a logs.
        detail = "dependencia no disponible"
        logger.warning("[READINESS] DB no disponible: %s", str(exc)[:500])

    if not db_ok:
        response.status_code = 503
    return {
        "status": "ready" if db_ok else "not_ready",
        "version": _BUILD_VERSION,
        "checks": {"database": "ok" if db_ok else "fail"},
        "detail": detail,
    }
