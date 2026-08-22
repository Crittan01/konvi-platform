/**
 * URLs canónicas de webhooks entrantes que el operador registra en el
 * dashboard de cada proveedor. Fuente ÚNICA de verdad para la UI de
 * Integraciones — elimina el drift de rutas (F93): Wompi/Telegram mostraban
 * paths 404 que impedían confirmar pagos / recibir alertas.
 *
 * Los paths DEBEN coincidir con los routers montados en services/api/main.py:
 *   - Wompi:    prefix "/api/v1/webhooks"      + POST "/wompi"          → /api/v1/webhooks/wompi
 *   - Telegram: prefix "/api/v1/integrations"  + POST "/telegram/webhook" → /api/v1/integrations/telegram/webhook
 *   - MeLi:     prefix "/api/v1/meli"          + POST "/webhook"        → /api/v1/meli/webhook
 *   - Resend:   prefix "/api/v1/webhooks"      + POST "/resend"         → /api/v1/webhooks/resend
 *     (Track 6 — plataforma, no per-tenant: se registra una vez por ambiente)
 *
 * Host: la API productiva vive en `konvi-api.onrender.com` (docs/HANDOFF.md —
 * konvi-api ✅ Live). El dominio `api.konvi.co` está pendiente de DNS
 * (ADR-0023 OQ-4, founder). Cuando el DNS entre en producción, basta setear
 * NEXT_PUBLIC_WEBHOOK_HOST=https://api.konvi.co — sin tocar componentes.
 */
export const WEBHOOK_HOST =
  process.env.NEXT_PUBLIC_WEBHOOK_HOST?.replace(/\/+$/, '') ||
  'https://konvi-api.onrender.com'

// El webhook de WhatsApp NO vive en el host de la API: lo sirve el servicio CONNECTOR
// (services/connector-whatsapp → konvi-connector.onrender.com, render.yaml). Antes la UI y el
// backend hardcodeaban `api.konvi.co` (NXDOMAIN, sin DNS) → el handshake Meta día-1 fallaba y el
// onboarding self-service Model B (ADR-0023) estaba roto E2E. Default al host LIVE del connector;
// cuando el DNS entre (connector.konvi.co, ADR-0023 OQ-4) basta setear
// NEXT_PUBLIC_CONNECTOR_WEBHOOK_HOST — sin tocar componentes. DEBE coincidir con el backend
// (WHATSAPP_CONNECTOR_URL en integrations.py).
export const CONNECTOR_WEBHOOK_HOST =
  process.env.NEXT_PUBLIC_CONNECTOR_WEBHOOK_HOST?.replace(/\/+$/, '') ||
  'https://konvi-connector.onrender.com'

/** URL del webhook WhatsApp per-tenant a registrar en Meta (incluye el tenantId; sin él Meta 404). */
export function whatsappWebhookUrl(tenantId: string): string {
  return `${CONNECTOR_WEBHOOK_HOST}/api/v1/whatsapp/webhook/${tenantId}`
}

export const WEBHOOK_PATHS = {
  wompi: '/api/v1/webhooks/wompi',
  telegram: '/api/v1/integrations/telegram/webhook',
  mercadolibre: '/api/v1/meli/webhook',
  resend: '/api/v1/webhooks/resend',
} as const

export type WebhookProvider = keyof typeof WEBHOOK_PATHS

/** URL absoluta del webhook a registrar en el dashboard del proveedor. */
export function webhookUrl(provider: WebhookProvider): string {
  return `${WEBHOOK_HOST}${WEBHOOK_PATHS[provider]}`
}
