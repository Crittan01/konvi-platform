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
import hmac
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("orchestrator-server")


# ─── Lifespan — arrancar el worker al iniciar uvicorn ─────────────────────────
# F-doc (Fase 6): migrado de @app.on_event("startup") (deprecado en FastAPI) al patrón
# lifespan idiomático (mismo que services/api/main.py). `_run_worker_thread` se resuelve
# en runtime (definido más abajo), por eso la forward-reference es válida.
def _validate_startup_config() -> None:
    """Falla rápido (sys.exit) si la configuración crítica es inválida.

    G13 fase 2a (2026-08-14): la lógica vive en `config.validate_critical()`
    (config central, mismo patrón que services/api). Este puente boot se
    comparte entre los 2 entry points: este lifespan (Render: uvicorn
    server:app) y main.py standalone — ambos llaman al mismo validate.
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
    t = threading.Thread(target=_run_worker_thread, daemon=True, name="orchestrator-worker")
    t.start()
    logger.info("Worker thread iniciado. Servidor HTTP escuchando en $PORT.")
    yield


# ─── FastAPI — solo para satisfacer el requisito de puerto de Render ───────────
# GREEN-16 (OWASP 2026-08-23): /docs, /redoc y /openapi.json off en producción.
_orch_is_prod = os.getenv("APP_ENV", "").strip().lower() in ("production", "prod")

app = FastAPI(
    title="AI Orchestrator",
    description="Worker de polling de Supabase → Gemini → WhatsApp. El endpoint /health es solo para que Render detecte el servicio activo.",
    lifespan=lifespan,
    docs_url=None if _orch_is_prod else "/docs",
    redoc_url=None if _orch_is_prod else "/redoc",
    openapi_url=None if _orch_is_prod else "/openapi.json",
)

# Estado global del worker (para /status)
_worker_status = {"running": False, "started_at": None, "error": None}
_worker_ref = {"instance": None}


# A11 audit 2026-06-25: el worker pollea cada POLL_INTERVAL_SECONDS (~3s);
# 120s sin heartbeat = decenas de ciclos perdidos = worker colgado/muerto.
HEALTH_HEARTBEAT_STALE_SECONDS = 120


def _estado_canales() -> dict:
    """Qué canales de salida al comprador están realmente configurados.

    Solo booleanos derivados de la PRESENCIA de cada credencial: exponer el valor sería
    filtrar un secreto por un endpoint público. Se leen como atributos de módulo porque el
    env se resuelve en import-time.
    """
    try:
        import notifications
        email_ok = bool(getattr(notifications, "RESEND_API_KEY", ""))
    except Exception:
        email_ok = False
    return {
        "email_configurado": email_ok,
        # WhatsApp es per-tenant (credenciales en Vault), así que no hay un booleano
        # global honesto: depende de cada tenant. Se omite a propósito en vez de
        # inventar uno que mienta.
    }


@app.get("/health")
def health():
    """Health check de Render. Devuelve 503 si el worker está caído o colgado
    (heartbeat stale) para que Render lo auto-reinicie. Antes devolvía 200
    incondicional → si el thread del worker moría, /health seguía OK = outage
    silencioso (mensajes sin procesar, sin auto-restart)."""
    instance = _worker_ref.get("instance")
    hb = getattr(instance, "last_heartbeat_ts", None) if instance is not None else None
    age = (time.time() - hb) if hb is not None else None

    reason = None
    if not _worker_status.get("running"):
        reason = "worker_not_running"
    elif _worker_status.get("error"):
        reason = "worker_error"
    elif age is not None and age > HEALTH_HEARTBEAT_STALE_SECONDS:
        reason = "heartbeat_stale"
    # hb None + running=True → ventana de arranque (worker aún no late) → healthy.

    body = {
        "status": "ok" if reason is None else "degraded",
        "worker": _worker_status,
        "heartbeat_age_s": round(age, 1) if age is not None else None,
        # Canales de salida al comprador. Son BOOLEANOS: nunca el valor del secreto.
        #
        # `email_configurado` responde una pregunta que hasta ahora no tenía respuesta sin
        # entrar al panel de Render: si está en false, el comprobante NO le llega por correo
        # a nadie. No se pierde en silencio (el envío se niega a marcarse como remitido),
        # pero el comprador solo recibe el acuse corto de WhatsApp — y el detalle completo,
        # que es el que sirve para una garantía o un retracto, no sale.
        "canales": _estado_canales(),
    }
    if reason is not None:
        body["reason"] = reason
        return JSONResponse(status_code=503, content=body)
    return body


@app.get("/status")
def status(request: Request):
    """Estado detallado del worker de IA.

    GREEN-17 (OWASP 2026-08-23): exige X-Internal-Service-Secret — antes era
    público (Render expone el servicio) y filtraba estado operativo interno
    (running, started_at, error con str(exc), métricas). El health check de
    Render es /health (render.yaml healthCheckPath), que sigue público.
    """
    _require_internal_secret(request)
    payload = dict(_worker_status)
    instance = _worker_ref.get("instance")
    if instance is not None and hasattr(instance, "metrics_snapshot"):
        try:
            payload["metrics"] = instance.metrics_snapshot()
        except Exception:
            payload["metrics"] = {}
    return JSONResponse(content=payload)


# A11 audit 2026-06-25: el endpoint exponía métricas agregadas SIN auth y con
# tenant_id opcional → cualquiera (Render lo sirve público) podía dumpear datos
# operativos cross-tenant. Se exige internal-service-secret + tenant_id.
_INTERNAL_SERVICE_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")
# Ventana de rotación sin-caída (mismo patrón que services/api internal_auth;
# runbook: docs/operations/runbooks/credential-rotation.md). Vacío = desactivado.
_INTERNAL_SERVICE_SECRET_PREVIOUS = os.getenv("INTERNAL_SERVICE_SECRET_PREVIOUS", "")


def _internal_secret_matches(sent: str) -> bool:
    """True si `sent` coincide con el secret vigente (o con PREVIOUS en ventana)."""
    if not sent or not _INTERNAL_SERVICE_SECRET:
        return False
    if hmac.compare_digest(sent, _INTERNAL_SERVICE_SECRET):
        return True
    return bool(_INTERNAL_SERVICE_SECRET_PREVIOUS) and hmac.compare_digest(
        sent, _INTERNAL_SERVICE_SECRET_PREVIOUS
    )


def _require_internal_secret(request: Request) -> None:
    sent = request.headers.get("X-Internal-Service-Secret", "")
    if not _internal_secret_matches(sent):
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/agentic/metrics")
def agentic_metrics(request: Request, tenant_id: str | None = None, since_hours: int = 24):
    """Métricas del agentic — ratio success/truncated/errored, latencias, tools.

    Lee `agentic_shadow_log` y agrega en la ventana indicada. Pensado para
    monitoreo operativo + diagnóstico de regresiones del LLM.

    A11 audit: requiere header `X-Internal-Service-Secret` (ops interno) y
    `tenant_id` obligatorio (no dump cross-tenant).

    Query params:
      • tenant_id (OBLIGATORIO): filtra por tenant.
      • since_hours (default 24): ventana hacia atrás.
    """
    _require_internal_secret(request)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id requerido")
    from agentic.observability import compute_agentic_metrics
    from supabase import create_client

    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    if not url or not key:
        return JSONResponse(
            status_code=503,
            content={"error": "supabase creds not configured"},
        )
    try:
        sb = create_client(url, key)
        data = compute_agentic_metrics(
            sb, tenant_id=tenant_id, since_hours=since_hours,
        )
        return JSONResponse(content=data)
    except Exception as exc:
        # GREEN-18 (OWASP 2026-08-23): no devolver str(exc) crudo al cliente.
        logger.warning("[AGENTIC_METRICS] err: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"error": "Error interno consultando métricas"},
        )


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
