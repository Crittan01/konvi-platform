import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from observability import init_sentry

# Init Sentry ANTES de cargar routers (capturar errores de import también).
init_sentry(service_name="api")

from fastapi import Depends as _Depends

from dependencies.auth import reject_if_tenant_deleting
from routers import (
    aveonline_webhook,
    claims,
    contacts,
    conversations,
    integrations,
    knowledge_base,
    marketplace,
    meli_webhook,
    orders,
    products,
    purchases,
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

    Nota: las credenciales de Wompi son por-tenant (tenant_integrations + Vault).
    No se validan aquí.
    """
    errors: list[str] = []

    # ── Variables críticas de Supabase ────────────────────────────────────────
    if not os.getenv("NEXT_PUBLIC_SUPABASE_URL", "").startswith("https://"):
        errors.append("NEXT_PUBLIC_SUPABASE_URL no configurada o inválida")
    # Aceptar el nombre nuevo (SECRET_KEY) o el legacy (SERVICE_ROLE_KEY) durante
    # transición A0.2c. Cleanup del legacy en commit final post-migración código.
    if not (
        os.getenv("SUPABASE_SECRET_KEY", "")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    ):
        errors.append(
            "SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY legacy) no configurada"
        )
    # A0.2b/c: SUPABASE_JWT_SECRET dejó de ser bloqueante. auth.py usa JWKS
    # asymmetric (ES256) sin shared secret. payment_link_tool + shipping_quote_tool
    # usan INTERNAL_SERVICE_SECRET header-based.
    if not os.getenv("INTERNAL_SERVICE_SECRET", ""):
        errors.append(
            "INTERNAL_SERVICE_SECRET no configurada — el Orchestrator no podrá llamar al "
            "Core API (payment_link + shipping_quote requieren header X-Internal-Service-Secret)"
        )

    if errors:
        for err in errors:
            logger.error("[STARTUP] ❌ %s", err)
        sys.exit(1)

    logger.info("[STARTUP] Validación de configuración OK")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    yield


app = FastAPI(title="Konvi Core API", description="Síncrona REST", lifespan=lifespan)

# ─── CORS — restringido a dominios permitidos ──────────────────────────────────
# En desarrollo: ALLOWED_ORIGINS=http://localhost:3000
# En producción (Render): configurar como secret con el dominio real del frontend
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)


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

app.include_router(products.router, prefix="/api/v1/products", dependencies=_OFFBOARDING_GATE)
app.include_router(conversations.router, prefix="/api/v1/conversations", dependencies=_OFFBOARDING_GATE)
app.include_router(orders.router, prefix="/api/v1/orders", dependencies=_OFFBOARDING_GATE)
app.include_router(contacts.router, prefix="/api/v1/contacts", dependencies=_OFFBOARDING_GATE)
# Rev. 93 — Habeas Data: Subject Access Request (SAR / ARCO).
from routers import data_subject_request as _dsr  # noqa: E402

app.include_router(_dsr.router, prefix="/api/v1/contacts", dependencies=_OFFBOARDING_GATE)
# Rev. 109 J.2.4.4 — Tenant offboarding (export + soft-delete + cancel).
# NO aplicar _OFFBOARDING_GATE — el owner debe poder cancelar dentro del grace.
from routers import tenant_offboarding as _toff  # noqa: E402

app.include_router(_toff.router, prefix="/api/v1/tenant/offboarding")
# Rev. 109 J.2.4.3 — MFA TOTP recovery codes.
from routers import mfa as _mfa  # noqa: E402

app.include_router(_mfa.router, prefix="/api/v1/mfa")
# Rev. 101 (F5) — SIC pre-cocinado.
from routers import sic_report as _sic  # noqa: E402

app.include_router(_sic.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
app.include_router(settings.router, prefix="/api/v1/settings", dependencies=_OFFBOARDING_GATE)
app.include_router(integrations.router, prefix="/api/v1/integrations", dependencies=_OFFBOARDING_GATE)
app.include_router(shipping.router, prefix="/api/v1/shipping", dependencies=_OFFBOARDING_GATE)
app.include_router(marketplace.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
# Webhooks externos NO usan _OFFBOARDING_GATE — no tienen JWT del tenant,
# vienen autenticados por signature del provider. Si el tenant está siendo
# eliminado, los webhooks fallarán en otros guards (RLS, FK, etc.).
app.include_router(meli_webhook.router, prefix="/api/v1/meli")
app.include_router(wompi_webhook.router, prefix="/api/v1/webhooks")
# Rev. 108 — Aveonline webhook estados de guía (dossier §6.2). Provider único
# de shipping post-pivote rev. 107 (ver ADR-0019). Envia eliminado en rev. 109.
app.include_router(aveonline_webhook.router, prefix="/api/v1/webhooks/aveonline")
app.include_router(telegram_webhook.router, prefix="/api/v1/integrations", dependencies=_OFFBOARDING_GATE)
# Rev. 109 ADR-0017 — Multi-agente per tenant (templates + AI suggest).
from routers import ai_agents as _ai_agents  # noqa: E402

app.include_router(_ai_agents.router, prefix="/api/v1", dependencies=_OFFBOARDING_GATE)
# Rev. 72 — routers nuevos (cierran drifts D1/D2/D3)
app.include_router(claims.router, prefix="/api/v1/claims", dependencies=_OFFBOARDING_GATE)
app.include_router(purchases.router, prefix="/api/v1/purchases", dependencies=_OFFBOARDING_GATE)
app.include_router(knowledge_base.router, prefix="/api/v1/knowledge-base", dependencies=_OFFBOARDING_GATE)

@app.get("/health")
def health_check():
    return {"status": "ok"}
