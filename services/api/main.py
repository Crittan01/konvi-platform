import logging
import os
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from routers import products, conversations, orders, contacts, settings, integrations, shipping, meli_webhook, marketplace, wompi_webhook, telegram_webhook, claims, purchases, knowledge_base
from dependencies.auth import get_current_tenant

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
    if not os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""):
        errors.append("SUPABASE_SERVICE_ROLE_KEY no configurada")
    if not os.getenv("SUPABASE_JWT_SECRET", ""):
        errors.append("SUPABASE_JWT_SECRET no configurada — el Orchestrator no podrá generar links de pago")

    if errors:
        for err in errors:
            logger.error("[STARTUP] ❌ %s", err)
        sys.exit(1)

    logger.info("[STARTUP] ✅ Validación de configuración OK")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    yield


app = FastAPI(title="Commerce Ops Core API", description="Síncrona REST", lifespan=lifespan)

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
    return response

app.include_router(products.router, prefix="/api/v1/products")
app.include_router(conversations.router, prefix="/api/v1/conversations")
app.include_router(orders.router, prefix="/api/v1/orders")
app.include_router(contacts.router, prefix="/api/v1/contacts")
# Rev. 93 — Habeas Data: Subject Access Request (SAR / ARCO).
from routers import data_subject_request as _dsr  # noqa: E402
app.include_router(_dsr.router, prefix="/api/v1/contacts")
app.include_router(settings.router, prefix="/api/v1/settings")
app.include_router(integrations.router, prefix="/api/v1/integrations")
app.include_router(shipping.router, prefix="/api/v1/shipping")
app.include_router(marketplace.router, prefix="/api/v1")
app.include_router(meli_webhook.router, prefix="/api/v1/meli")
app.include_router(wompi_webhook.router, prefix="/api/v1/webhooks")
app.include_router(telegram_webhook.router, prefix="/api/v1/integrations")
# Rev. 72 — routers nuevos (cierran drifts D1/D2/D3)
app.include_router(claims.router, prefix="/api/v1/claims")
app.include_router(purchases.router, prefix="/api/v1/purchases")
app.include_router(knowledge_base.router, prefix="/api/v1/knowledge-base")

@app.get("/health")
def health_check():
    return {"status": "ok"}
