import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from observability import init_sentry

# Init Sentry ANTES de routers (captura errores tempranos también).
init_sentry(service_name="connector-whatsapp")

from routers import webhook

logger = logging.getLogger(__name__)

# Kill switch operativo del re-drive: se puede apagar por env sin redeploy de código.
INBOX_REDRIVE_ENABLED = os.getenv("WA_INBOX_REDRIVE_ENABLED", "true").lower() != "false"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Arranca el re-drive del inbox durable del webhook.

    Por qué vive acá y no en el worker del orchestrator: el re-drive reprocesa payloads de Meta,
    y quien sabe hacerlo es el connector (`decouple_and_enqueue`). Ponerlo en otro servicio
    obligaría a duplicar esa lógica. El connector corre en plan Starter (always-on, sin cold
    starts, verificado vía Render API), así que un loop de fondo es viable.
    """
    task = None
    if INBOX_REDRIVE_ENABLED:
        from services.inbox import redrive_loop
        task = asyncio.create_task(redrive_loop())
    else:
        logger.warning("[WH_INBOX] re-drive DESACTIVADO por WA_INBOX_REDRIVE_ENABLED=false")
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="WhatsApp Webhook Connector", lifespan=lifespan)

app.include_router(webhook.router, prefix="/api/v1/whatsapp")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "connector-whatsapp"}
