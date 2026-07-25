"""Inbox durable del webhook de WhatsApp.

Por qué existe: `receive_message` debe responder 200 a Meta de inmediato (política obligatoria),
y el procesamiento real ocurre después, en una tarea in-process. Meta NO reintenta ante un 200 y
no ofrece pull → si el proceso muere en ese hueco (deploy, OOM, crash), el mensaje del cliente se
perdía PARA SIEMPRE, con un `logger.error` como único rastro.

Este módulo persiste el payload (ya HMAC-verificado) ANTES del ACK y reconcilia lo que quedó
pendiente. Convierte un fallo irreversible e invisible en uno recuperable y observable.

Espeja el patrón ya probado de `wompi_webhook_inbox` (migración 20260714000000) en vez de inventar
un mecanismo nuevo.
"""
import logging
import os
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Lease de visibilidad: una fila reclamada no se vuelve a tomar dentro de esta ventana. Evita que
# un mensaje LENTO pero válido (persistencia + dispatch pueden tardar) infle `attempts` o termine
# en dead-letter mientras aún se está procesando bien.
CLAIM_LEASE_SECONDS = int(os.getenv("WA_INBOX_LEASE_SECONDS", "120"))
# Backstop: tras N intentos se deja de reintentar. Un payload que falla siempre (p. ej. malformado
# o un bug) no debe reintentarse en bucle para siempre; queda con `last_error` para revisión.
MAX_ATTEMPTS = int(os.getenv("WA_INBOX_MAX_ATTEMPTS", "5"))
# Cada cuánto barre el re-drive.
REDRIVE_INTERVAL_SECONDS = int(os.getenv("WA_INBOX_REDRIVE_SECONDS", "60"))
# Cuántas filas por barrido (acota el trabajo por ciclo).
REDRIVE_BATCH = int(os.getenv("WA_INBOX_REDRIVE_BATCH", "20"))
# Purga de filas procesadas (crecimiento acotado).
RETENTION_DAYS = int(os.getenv("WA_INBOX_RETENTION_DAYS", "7"))

_metrics = {
    "inbox_persisted": 0,
    "inbox_processed": 0,
    "inbox_failed": 0,
    "inbox_redriven": 0,
    "inbox_dead_lettered": 0,
    "inbox_depth": 0,          # gauge: pendientes (alertable)
}


def get_inbox_metrics() -> dict:
    return dict(_metrics)


def _client():
    from services.db_persistence import get_supabase  # import perezoso: evita ciclo
    return get_supabase()


def persist_inbox(body_sha: str, tenant_id: str, payload: dict) -> None:
    """Persiste el payload crudo. Idempotente por PK (un reintento de Meta con el mismo body
    reusa la fila en vez de duplicarla)."""
    sb = _client()
    try:
        sb.table("whatsapp_webhook_inbox").insert({
            "body_sha256": body_sha,
            "tenant_id": tenant_id,
            "raw_payload": payload,
        }).execute()
        _metrics["inbox_persisted"] += 1
    except Exception as exc:  # noqa: BLE001
        # 23505 = ya existía (reintento de Meta del MISMO body) → no es error.
        if "23505" in str(exc) or "duplicate key" in str(exc).lower():
            logger.debug("[WH_INBOX] payload ya en inbox (reintento de Meta): %s", body_sha[:12])
            return
        raise


def mark_processed(body_sha: str) -> None:
    """Marca la fila como procesada para que el re-drive no la repita."""
    try:
        _client().table("whatsapp_webhook_inbox").update({
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "last_error": None,
        }).eq("body_sha256", body_sha).execute()
        _metrics["inbox_processed"] += 1
    except Exception as exc:  # noqa: BLE001
        # No se propaga: el mensaje YA se procesó bien. Peor caso, el re-drive lo reintenta
        # (el procesamiento es idempotente por wamid en `messages`).
        logger.warning("[WH_INBOX] no se pudo marcar procesado %s: %s", body_sha[:12], exc)


def mark_failed(body_sha: str, error: str) -> None:
    """Deja la fila pendiente con el error, para que el re-drive la reintente."""
    try:
        _client().table("whatsapp_webhook_inbox").update({
            "last_error": error,
        }).eq("body_sha256", body_sha).execute()
        _metrics["inbox_failed"] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WH_INBOX] no se pudo marcar fallo %s: %s", body_sha[:12], exc)


def redrive_once() -> int:
    """Un barrido: reprocesa lo pendiente. Devuelve cuántas filas se re-drivearon.

    Reclama por lease para no pisar un procesamiento en curso, e incrementa `attempts` para
    poder dead-letterar lo que falla sistemáticamente.
    """
    sb = _client()
    now = datetime.now(timezone.utc)
    lease_cutoff = (now - timedelta(seconds=CLAIM_LEASE_SECONDS)).isoformat()

    try:
        pend = (
            sb.table("whatsapp_webhook_inbox")
            .select("body_sha256, tenant_id, raw_payload, attempts, claimed_at")
            .is_("processed_at", "null")
            .lt("attempts", MAX_ATTEMPTS)
            .order("received_at")
            .limit(REDRIVE_BATCH)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WH_INBOX] redrive: no se pudo consultar pendientes: %s", exc)
        return 0

    rows = pend.data or []
    _metrics["inbox_depth"] = len(rows)
    done = 0

    for row in rows:
        claimed = row.get("claimed_at")
        # Respetar el lease: si otra corrida la tomó hace poco, saltarla.
        if claimed and claimed > lease_cutoff:
            continue

        sha = row["body_sha256"]
        attempts = int(row.get("attempts") or 0) + 1
        try:
            sb.table("whatsapp_webhook_inbox").update({
                "claimed_at": now.isoformat(), "attempts": attempts,
            }).eq("body_sha256", sha).execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[WH_INBOX] redrive: no se pudo reclamar %s: %s", sha[:12], exc)
            continue

        try:
            # Import perezoso y DENTRO del loop, no al tope de la función: si no hay nada que
            # re-drivear (el caso normal), no se importa nada. Evita además acoplar el barrido
            # a que `routers.webhook` sea importable en ese momento.
            from routers.webhook import decouple_and_enqueue  # evita ciclo de imports

            # Se reprocesa con el tenant_id GUARDADO (el HMAC-verificado del request original),
            # NO re-resolviendo por el body → mantiene el cierre de cross-talk de A11/WH-01.
            decouple_and_enqueue(row["raw_payload"], row["tenant_id"], sha)
            done += 1
            _metrics["inbox_redriven"] += 1
            logger.info("[WH_INBOX] re-drive OK %s (intento %s)", sha[:12], attempts)
        except Exception as exc:  # noqa: BLE001
            logger.error("[WH_INBOX] re-drive falló %s (intento %s): %s", sha[:12], attempts, exc)
            if attempts >= MAX_ATTEMPTS:
                _metrics["inbox_dead_lettered"] += 1
                logger.error(
                    "[WH_INBOX] DEAD-LETTER %s tras %s intentos — requiere revisión manual",
                    sha[:12], attempts,
                )

    return done


def cleanup_processed() -> int:
    """Purga filas procesadas viejas para acotar el crecimiento."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    try:
        res = (
            _client().table("whatsapp_webhook_inbox")
            .delete()
            .lt("processed_at", cutoff)
            .execute()
        )
        return len(res.data or [])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WH_INBOX] cleanup falló: %s", exc)
        return 0


async def redrive_loop() -> None:
    """Loop de fondo del connector. Corre mientras viva el proceso.

    El connector está en plan Starter (always-on, sin cold starts), así que un loop es viable.
    Cada error se aísla: un ciclo que falla no mata el loop.
    """
    import asyncio
    from starlette.concurrency import run_in_threadpool

    logger.info(
        "[WH_INBOX] re-drive activo (cada %ss, lote %s, max_intentos %s)",
        REDRIVE_INTERVAL_SECONDS, REDRIVE_BATCH, MAX_ATTEMPTS,
    )
    last_cleanup = 0.0
    while True:
        try:
            await asyncio.sleep(REDRIVE_INTERVAL_SECONDS)
            # redrive_once hace I/O síncrona (Supabase) → al threadpool para no bloquear el loop
            # del webhook, que debe ACKear a Meta de inmediato.
            await run_in_threadpool(redrive_once)
            if time.time() - last_cleanup > 86400:
                await run_in_threadpool(cleanup_processed)
                last_cleanup = time.time()
        except asyncio.CancelledError:
            logger.info("[WH_INBOX] re-drive detenido (shutdown)")
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("[WH_INBOX] ciclo de re-drive falló (aislado, sigue): %s", exc)
