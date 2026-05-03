"""
server.py — Wrapper HTTP para el AI Orchestrator en Render Free Plan.

El plan Free de Render NO soporta Background Workers (type: worker).
Este módulo expone un servidor FastAPI mínimo con /health y /status,
y lanza el OrchestratorWorker en un thread de fondo al arrancar.

Render exige que el servidor escuche en $PORT — esto satisface ese requisito.
El worker sigue siendo un proceso de polling puro (sin cambios en su lógica).

Referencia: https://render.com/docs/free#free-web-services
"""
import asyncio
import logging
import os
import sys
import threading

from fastapi import FastAPI
from fastapi.responses import JSONResponse

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("orchestrator-server")

# ─── FastAPI — solo para satisfacer el requisito de puerto de Render ───────────
app = FastAPI(
    title="AI Orchestrator",
    description="Worker de polling de Supabase → Gemini → WhatsApp. El endpoint /health es solo para que Render detecte el servicio activo.",
)

# Estado global del worker (para /status)
_worker_status = {"running": False, "started_at": None, "error": None}
_worker_ref = {"instance": None}


@app.get("/health")
def health():
    """Health check requerido por Render para detectar que el servicio está vivo."""
    return {"status": "ok", "worker": _worker_status}


@app.get("/status")
def status():
    """Estado detallado del worker de IA."""
    payload = dict(_worker_status)
    instance = _worker_ref.get("instance")
    if instance is not None and hasattr(instance, "metrics_snapshot"):
        try:
            payload["metrics"] = instance.metrics_snapshot()
        except Exception:
            payload["metrics"] = {}
    return JSONResponse(content=payload)


# ─── Worker thread ─────────────────────────────────────────────────────────────
def _run_worker_thread():
    """
    Ejecuta el OrchestratorWorker en un event loop propio en un thread separado.
    Esto permite que uvicorn maneje el servidor HTTP mientras el worker hace polling.
    """
    from datetime import datetime, timezone
    from worker import OrchestratorWorker

    _worker_status["started_at"] = datetime.now(timezone.utc).isoformat()
    _worker_status["running"] = True
    logger.info("🚀 OrchestratorWorker iniciando en thread de fondo...")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        worker = OrchestratorWorker()
        _worker_ref["instance"] = worker
        loop.run_until_complete(worker.run())
    except Exception as exc:
        logger.error("❌ Worker terminó con error: %s", exc, exc_info=True)
        _worker_status["error"] = str(exc)
    finally:
        _worker_status["running"] = False
        logger.warning("⚠️  Worker detenido. El servidor HTTP sigue activo.")


# ─── Lifespan — lanzar worker al arrancar uvicorn ─────────────────────────────
@app.on_event("startup")
def startup_event():
    """Arrancar el worker en un daemon thread al iniciar el servidor."""
    t = threading.Thread(target=_run_worker_thread, daemon=True, name="orchestrator-worker")
    t.start()
    logger.info("Worker thread iniciado. Servidor HTTP escuchando en $PORT.")
