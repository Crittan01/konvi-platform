import os
import json
from fastapi import APIRouter, Request, Response, BackgroundTasks, HTTPException, Depends
import logging

from dependencies.meta import verify_meta_signature

logger = logging.getLogger(__name__)

router = APIRouter()

META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")

@router.get("/webhook")
async def verify_webhook(
    request: Request,
    response: Response
):
    """
    Endpoint de desafío para el dashboard de Meta.
    Verifica que el hub.verify_token coincida con el nuestro.
    """
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if not META_VERIFY_TOKEN:
        logger.error("META_VERIFY_TOKEN no configurado en runtime")
        raise HTTPException(status_code=503, detail="META_VERIFY_TOKEN no configurado")

    if mode and token:
        if mode == "subscribe" and token == META_VERIFY_TOKEN:
            return Response(content=challenge, media_type="text/plain")
        else:
            raise HTTPException(status_code=403, detail="Forbidden")
    raise HTTPException(status_code=400, detail="Bad Request")

from services.parser import parse_webhook_payloads, parse_webhook_events
from services.db_persistence import persist_whatsapp_message
from services.template_events import handle_event as handle_template_event

async def decouple_and_enqueue(body_dict: dict):
    """
    Función que corre asíncronamente (Background Task).

    Sem 6 pre-HSM (rev. 106 / 2026-05-08): además del flow inbound original,
    invoca `parse_webhook_events()` para clasificar fields no-`messages`.

    Sem 7 F2 HSM (rev. 106 / 2026-05-17 item 4): cada evento dispatch a
    `template_events.handle_event()` que persiste:
      - template_status_update → whatsapp_templates.status + approved_at
      - template_quality_update → whatsapp_templates.quality_rating
      - phone_quality_update → tenant_integrations.credentials.tier
    Eventos sin handler asociado (outbound_status, account_alert, etc.)
    se loggean por ahora — persistence futura Sem 11.
    """
    try:
        parsed_messages = parse_webhook_payloads(body_dict)
        if parsed_messages:
            for parsed_data in parsed_messages:
                persist_whatsapp_message(parsed_data)
        else:
            logger.debug("Webhook recibido crudio asincrono no contenía un mensaje puro o malformado.")

        # Sem 6 → Sem 7 F2: dispatcher multi-field con persistence per tipo.
        try:
            events = parse_webhook_events(body_dict)
            for event in events:
                event_type = event.get("event_type")
                # Persistence handler para events HSM (Sem 7 item 4)
                result = handle_template_event(event)
                if result is None:
                    # Sin handler asociado — solo log informativo
                    logger.info(
                        "[WH_EVENT] type=%s waba=%s (no persistence) payload=%s",
                        event_type,
                        event.get("meta_waba_id"),
                        {k: v for k, v in event.items()
                         if k not in {"event_type", "meta_waba_id", "raw_value"}},
                    )
                elif result is True:
                    logger.debug(
                        "[WH_EVENT] type=%s persisted OK", event_type,
                    )
                else:
                    logger.warning(
                        "[WH_EVENT] type=%s persistence retornó False (template no encontrado o error)",
                        event_type,
                    )
        except Exception as e_disp:
            logger.error(f"Dispatcher multi-field fallo (no crítico, inbound ya procesado): {e_disp}")
    except Exception as e:
        logger.error(f"Falla silenciosa engullida en el Background DB Task: {e}")

@router.post("/webhook")
async def receive_message(
    request: Request,
    background_tasks: BackgroundTasks,
    raw_body: bytes = Depends(verify_meta_signature)
):
    """
    Recibe los payloads de WhatsApp. Transita por la barrera `verify_meta_signature` obligatoriamente.
    RESPONDE EXACTAMENTE CON HTTP 200 EN MILISEGUNDOS.
    """
    try:
        # El body fue recuperado en bytes crudos por el verificador (necesario para el Hash)
        # Recién aquí lo parseamos a JSON para nuestra tubería.
        body_dict = json.loads(raw_body)
        
        # Encolamos la carga para pasaje transaccional a Postgres o PG-MQ en background
        background_tasks.add_task(decouple_and_enqueue, body_dict)
        
    except Exception as e:
        logger.error(f"Fallo grave al intentar parsear o encolar la orden post-firma: {e}")
        # Aún si falla el parseo, se debe arrojar 200 o Meta bloqueará la API indefinidamente.
        pass
    
    # OBLIGATORIO POLÍTICA DE META: Responder 200 de inmediato
    return {"status": "received"}
