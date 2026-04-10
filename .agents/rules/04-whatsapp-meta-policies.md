# Regla: WhatsApp / Meta Cloud API

## Restricciones absolutas

- Solo **WhatsApp Cloud API oficial** (Meta v21.0) — sin librerías no oficiales
- Respuestas al cliente: solo con datos reales del backend — nunca inventados por LLM
- Cumplir políticas Anti-Spam de Meta (no envíos masivos sin opt-in)
- Ventana de 24h para mensajes iniciados por el negocio — usar Templates para fuera de ventana

## Arquitectura de mensajería

- `connector-whatsapp` → **solo recibe** webhooks entrantes (HMAC-SHA256 validado)
- `ai-orchestrator` → **envía directamente** a Meta Graph API v21.0 via `whatsapp_sender.py`
- No acoplar Shipping, cotizaciones ni datos operacionales directamente al LLM

## Webhooks

- Meta reintenta si no recibe HTTP 200 en < 20s → `connector-whatsapp` responde inmediatamente (fire-and-forget)
- Validación HMAC-SHA256 obligatoria en cada webhook
