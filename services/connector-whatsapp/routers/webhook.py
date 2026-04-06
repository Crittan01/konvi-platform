import os
from fastapi import APIRouter, Request, Response, BackgroundTasks, HTTPException

router = APIRouter()

META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "fallback-dev-token")

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

    if mode and token:
        if mode == "subscribe" and token == META_VERIFY_TOKEN:
            return Response(content=challenge, media_type="text/plain")
        else:
            raise HTTPException(status_code=403, detail="Forbidden")
    raise HTTPException(status_code=400, detail="Bad Request")

async def decouple_and_enqueue(payload: dict):
    """
    Función que corre asíncronamente (Background Task).
    1. Valida la firma del webhook.
    2. Identifica el tenant WABA_ID.
    3. Serializa y empuja a Supabase Queues o PGMQ para que el Orchestrator lo lea.
    """
    # Lógica pseudo-código (No ejecutar local, requiere DB viva):
    # - db.push(queue_name='inbound_messages', payload=payload)
    pass

@router.post("/webhook")
async def receive_message(
    request: Request,
    background_tasks: BackgroundTasks
):
    """
    Recibe los payloads de WhatsApp.
    RESPONDE EXACTAMENTE CON HTTP 200 EN MILISEGUNDOS.
    Despega el procesamiento real a una Background Task o Cola.
    """
    try:
        body = await request.json()
        
        # Encolamos la carga para validación criptográfica y pasaje a Postgres
        background_tasks.add_task(decouple_and_enqueue, body)
        
        # OBLIGATORIO POLÍTICA DE META: Responder 200 de inmediato
        return {"status": "received"}

    except Exception as e:
        # Aún si falla el parseo, se debe arrojar 200 o Meta bloqueará el Webhook
        return {"status": "error_squashed"}\n