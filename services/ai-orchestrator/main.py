import asyncio
import logging
import signal
import sys
from worker import OrchestratorWorker

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("ai-orchestrator")


def _validate_startup_config() -> None:
    """Falla rápido (sys.exit) si la configuración crítica es inválida.

    G13 fase 2a (2026-08-14): la lógica vive en `config.validate_critical()`
    (config central, mismo patrón que services/api). Este entry point
    standalone comparte la llamada con el lifespan de server.py (lo que
    arranca Render vía `uvicorn server:app`).
    """
    from config import validate_critical

    errors = validate_critical()
    if errors:
        for err in errors:
            logger.error("[STARTUP] ❌ %s", err)
        sys.exit(1)

    logger.info("[STARTUP] Validación de configuración OK")


async def main():
    logger.info("🚀 AI Orchestrator iniciando...")

    _validate_startup_config()
    worker = OrchestratorWorker()

    # Graceful shutdown en SIGINT / SIGTERM (Render envía SIGTERM)
    loop = asyncio.get_running_loop()

    def _shutdown(sig_name: str):
        logger.info(f"📴 Señal {sig_name} recibida — apagando worker...")
        worker.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda s=sig.name: _shutdown(s))

    await worker.run()
    logger.info("Worker finalizado correctamente.")


if __name__ == "__main__":
    asyncio.run(main())
