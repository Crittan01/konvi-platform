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


async def main():
    logger.info("🚀 AI Orchestrator iniciando...")

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
