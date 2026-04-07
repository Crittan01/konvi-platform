import asyncio
import logging
import os
from supabase import create_client, Client
from orchestrator import build_and_run_orchestration

logger = logging.getLogger("orchestrator.worker")

POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "3"))
SUPABASE_URL = os.getenv("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


class OrchestratorWorker:
    """
    Worker de polling que detecta mensajes entrantes no procesados
    y dispara el ciclo de orquestación IA → WhatsApp por cada uno.

    Patrón: Background Worker de Render (sin HTTP).
    Intervalo: configurable via env POLL_INTERVAL_SECONDS (default 3s).
    """

    def __init__(self):
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise RuntimeError("Faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY")
        self.supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        self._running = False

    def stop(self):
        self._running = False

    async def run(self):
        self._running = True
        logger.info(f"Worker activo — polling cada {POLL_INTERVAL_SECONDS}s")

        while self._running:
            try:
                await self._poll_cycle()
            except Exception as e:
                logger.error(f"Error en ciclo de polling: {e}", exc_info=True)
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _poll_cycle(self):
        """Busca mensajes inbound no procesados y los orquesta."""
        # Selección de mensajes pendientes — hasta 10 por ciclo para no saturar
        result = (
            self.supabase.table("messages")
            .select("id, tenant_id, conversation_id, content, content_type")
            .eq("direction", "inbound")
            .eq("processed", False)
            .order("created_at", desc=False)
            .limit(10)
            .execute()
        )

        pending = result.data or []
        if not pending:
            return

        logger.info(f"📬 {len(pending)} mensaje(s) pendiente(s) encontrado(s)")

        # Procesar en secuencia para no sobrecargar la API de Gemini
        for msg in pending:
            try:
                await build_and_run_orchestration(
                    supabase=self.supabase,
                    message_id=msg["id"],
                    tenant_id=msg["tenant_id"],
                    conversation_id=msg["conversation_id"],
                    content=msg["content"],
                    content_type=msg["content_type"],
                )
            except Exception as e:
                logger.error(
                    f"Error procesando mensaje {msg['id']}: {e}", exc_info=True
                )
                # No re-lanzar — continuar con el siguiente mensaje
