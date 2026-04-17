# Integración WhatsApp Cloud API (Meta)

Última actualización: 2026-04-16

> **NOTA ARQUITECTÓNICA:** Este documento cubre el conector WhatsApp actual (modelo legacy con `tenants.meta_waba_id`).
> La arquitectura objetivo — Meta Embedded Signup unificado para WhatsApp + Messenger + Instagram — está documentada en:
> **`docs/integrations/meta-suite.md`**
> Este documento se mantiene como referencia del estado operativo actual hasta completar la migración.

---

## Estado

✅ **Funcional en producción (Render)**

El conector está live. Pendiente: configuración del Webhook Callback URL en Meta Developers (acción humana PASO 6 de Fase 7).

---

## Principio fundamental

Esta integración usa **exclusivamente** la WhatsApp Cloud API oficial de Meta.
No se usan librerías no oficiales, scraping ni acceso no autorizado.
Todo diseño debe cumplir las políticas Anti-Spam de Meta y los lineamientos de la API oficial.

---

## Componente: `services/connector-whatsapp`

- **URL Render**: `https://commerce-ops-connector.onrender.com`
- **Responsabilidad**: Boundary gateway para Meta. Recibe webhooks, valida firma, persiste mensajes.
- **Patrón**: Fire-and-forget — responde HTTP 200 en milisegundos para cumplir política Meta de ventana corta de respuesta.

---

## Endpoints

### GET `/api/v1/whatsapp/webhook` — Verificación del challenge

Meta llama a este endpoint al configurar el webhook.
El conector verifica el `hub.verify_token` y responde con `hub.challenge`.

**Variables requeridas**:
- `META_VERIFY_TOKEN` — token que configuras en Meta Developers

### POST `/api/v1/whatsapp/webhook` — Recepción de mensajes

Meta envía aquí todos los eventos: mensajes entrantes, status updates, etc.

**Flujo**:
1. Validar firma HMAC-SHA256 del header `X-Hub-Signature-256` ✅
2. Parsear payload de Meta (mensajes de texto, media, etc.)
3. Resolver tenant por `meta_waba_id` del payload ✅
4. Persistir mensaje en tabla `messages` (direction=inbound, processed=False)
5. Responder HTTP 200 inmediatamente

---

## Validación de firma HMAC-SHA256

✅ **Implementada**

Meta firma cada request con el App Secret. El conector valida esto en cada webhook recibido:

```python
import hmac, hashlib

def validate_signature(body: bytes, signature: str, app_secret: str) -> bool:
    expected = hmac.new(
        app_secret.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)
```

**Variable requerida**: `META_APP_SECRET`

---

## Tenant resolver

✅ **Implementado correctamente**

El tenant se resuelve por `meta_waba_id` real del payload, no por hardcode.

```python
# CORRECTO — implementado en db_persistence.py
tenant_res = supabase.table("tenants").select("id").eq("meta_waba_id", meta_waba_id).execute()
```

El `meta_waba_id` actual del tenant de desarrollo: `2159052118202272`

---

## Envío de mensajes (via AI Orchestrator)

El envío de respuestas lo hace `services/ai-orchestrator` via `whatsapp_sender.py`.

**Endpoint Meta usado**: `POST /{WHATSAPP_PHONE_ID}/messages` (Graph API v21.0)

**Variables requeridas**:
- `META_ACCESS_TOKEN` — debe ser System User Token permanente en producción (ver IH-006)
- `WHATSAPP_PHONE_ID` — ID del número de teléfono de WhatsApp Business

---

## Variables de entorno del conector

| Variable | Requerida | Descripción |
|----------|-----------|-------------|
| `META_APP_SECRET` | ✅ | Firma HMAC de webhooks |
| `META_VERIFY_TOKEN` | ✅ | Verificación del challenge de Meta |
| `META_ACCESS_TOKEN` | ✅ | Token para enviar mensajes (temporal o permanente) |
| `WHATSAPP_PHONE_ID` | ✅ | ID del número WhatsApp Business |
| `SUPABASE_URL` | ✅ | URL del proyecto Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Key service_role para persistencia |

---

## Restricciones de Meta / Anti-Spam

- **No enviar mensajes masivos no solicitados** — viola políticas Anti-Spam
- Solo responder a mensajes iniciados por el cliente (dentro de la ventana de 24h)
- Para mensajes de marketing fuera de la ventana de 24h: usar Templates de Meta aprobados
- El AI Orchestrator tiene guardrails que evitan respuestas inapropiadas o masivas
- No usar el LLM para generar campañas de marketing

---

## Configuración del Webhook en Meta Developers (PASO 6 — PENDIENTE HUMANO)

Para que Meta envíe webhooks al conector en Render:

1. Ir a [Meta Developers](https://developers.facebook.com/) → Tu App → WhatsApp → Configuration
2. En **Webhook**: hacer clic en "Edit"
3. Configurar:
   - **Callback URL**: `https://commerce-ops-connector.onrender.com/api/v1/whatsapp/webhook`
   - **Verify Token**: `***META_VERIFY_TOKEN_LEGACY_REDACTED***`
4. Suscribir al campo: `messages`
5. Verificar que Meta pueda hacer el challenge GET exitosamente

Ver `docs/operations/HUMAN_INTERVENTIONS.md` → PASO 6 para guía completa.

---

## Token permanente (IH-006 — PENDIENTE HUMANO)

El token actual (`META_ACCESS_TOKEN`) es temporal (~24h).
Para producción, crear un System User Token permanente:

1. Meta Business Suite → Configuración del negocio → Usuarios → Usuarios del sistema
2. Crear usuario `commerce-ops-bot` con rol Admin
3. Generar token → permisos: `whatsapp_business_messaging`, `whatsapp_business_management`
4. Expiración: Nunca
5. Configurar en Render Environment Variables

Ver `docs/operations/HUMAN_INTERVENTIONS.md` → IH-006.

---

## Riesgos activos

| ID | Riesgo | Estado |
|----|--------|--------|
| R-04 | cold start en Render Free pierde webhooks | Aceptado (dev) — plan Starter en producción |
| R-07 | Baneo por políticas Anti-Spam Meta | Mitigado parcialmente (guardrails, canal oficial) |
| IH-006 | Token temporal expira ~24h | Pendiente upgrade a System User Token |

---

## Documentos relacionados

- `docs/architecture/modules.md` — Estado de services/connector-whatsapp
- `docs/operations/HUMAN_INTERVENTIONS.md` — Pasos manuales pendientes (PASO 6, IH-006)
- `docs/ai/guardrails.md` — Reglas de validación del Orchestrator
