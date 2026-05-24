from fastapi import FastAPI
from observability import init_sentry

# Init Sentry ANTES de routers (captura errores tempranos también).
init_sentry(service_name="connector-whatsapp")

from routers import webhook

app = FastAPI(title="WhatsApp Webhook Connector")

app.include_router(webhook.router, prefix="/api/v1/whatsapp")

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "connector-whatsapp"}
