import os
import hmac
import hashlib
from fastapi import Request, HTTPException, Header
import logging

logger = logging.getLogger(__name__)

# Se extraerá en ejecución del vault
META_APP_SECRET = os.getenv("META_APP_SECRET", "")

async def verify_meta_signature(
    request: Request,
    x_hub_signature_256: str = Header(None)
) -> bytes:
    """
    Dependencia crítica: Bloquea requests que no provengan de Meta.
    Verifica matemáticamente que el HMAC SHA-256 de toda la carga coincida
    con la firma X-Hub-Signature-256 inyectada por Meta, usando nuestra APP_SECRET compartida.
    """
    if not META_APP_SECRET:
        logger.warning("META_APP_SECRET no configurada. Rechazando forzosamente el webhook en PRD.")
        raise HTTPException(status_code=403, detail="Server misconfigured: App Secret missing")

    if not x_hub_signature_256:
        logger.warning("Firma X-Hub-Signature-256 ausente en la petición.")
        raise HTTPException(status_code=403, detail="Missing signature")

    # Extraemos el payload bruto en bytes
    raw_body = await request.body()
    
    # Meta envía el header con prefijo "sha256="
    algo, signature = x_hub_signature_256.split("=", 1) if "=" in x_hub_signature_256 else ("", x_hub_signature_256)
    
    if algo != "sha256":
        raise HTTPException(status_code=403, detail="Unsupported signature algorithm")

    # Re-calculamos dictamen hash localmente
    expected_hmac = hmac.new(
        key=META_APP_SECRET.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256
    ).hexdigest()

    # Si los hashes no son 100% idénticos, la orden está fraguada o envenenada
    if not hmac.compare_digest(expected_hmac, signature):
        logger.warning("Alarma de Seguridad: Las firmas HMAC no coinciden (Payload adulterado o App Secret incorrecto).")
        raise HTTPException(status_code=403, detail="Invalid signature")
    
    return raw_body
