import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routers import products, conversations, orders, contacts, settings, integrations, shipping, meli_webhook, marketplace
from dependencies.auth import get_current_tenant

app = FastAPI(title="Commerce Ops Core API", description="Síncrona REST")

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
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(products.router, prefix="/api/v1/products")
app.include_router(conversations.router, prefix="/api/v1/conversations")
app.include_router(orders.router, prefix="/api/v1/orders")
app.include_router(contacts.router, prefix="/api/v1/contacts")
app.include_router(settings.router, prefix="/api/v1/settings")
app.include_router(integrations.router, prefix="/api/v1/integrations")
app.include_router(shipping.router, prefix="/api/v1/shipping")
app.include_router(marketplace.router, prefix="/api/v1")
app.include_router(meli_webhook.router, prefix="/api/v1/meli")

@app.get("/health")
def health_check():
    return {"status": "ok"}
