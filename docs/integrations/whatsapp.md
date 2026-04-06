# Integración WhatsApp Cloud API

El núcleo de interacción con los clientes finales se aloja en `services/connector-whatsapp`.

## 1. Patrón Webhook Asíncrono
La integración no procesa la IA síncronamente. Meta exige que los webhooks (mensajes de status, updates y textos de clientes del WABA) sean contestados en milisegundos de forma HTTP 200, si no, penalizarán el Webdoor.

Por lo tanto, la arquitectura configurada en el **Connector** es la de un proxy ciego muy rápido:
1. Recibe por el endpoint `routers/webhook.py`.
2. Si es configuración inicial de Meta, responde al _challenge_.
3. Si es un JSON Inbound, dispara un `BackgroundTask` dentro de FastAPI que insertará la payload virgen en `pgmq` / Supabase.
4. Responde `{"status": "received"}` (o vacío) con código 200 directo.

## 2. Dependencias y Despliegue
Este módulo usará estrictamente `fastapi` y `uvicorn`.  
Sin embargo, **restricción operativa local**: La máquina de desarrollo principal virtual no se inflará con un pipenv gigantesco de modo presencial si no es necesario correr pruebas masivas de IA síncronas. Todo correrá delegándose en los entornos CI/CD (ej: despliegue Docker directo en Render Web Services).

## 3. Próximo Milestone Criptográfico
Falta desarrollar para iteraciones posteriores:
* **Verificación de Firma SHA-256 (X-Hub-Signature-256)**: La Task de encolado debe validar el body crudo con el `APP_SECRET` de la Meta App. Si no machea, la inyección base se aborta (mitigación DDoS / Spoofing).