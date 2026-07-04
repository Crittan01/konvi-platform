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
 *
 * Host: la API productiva vive en `konvi-api.onrender.com` (docs/HANDOFF.md —
 * konvi-api ✅ Live). El dominio `api.konvi.co` está pendiente de DNS
 * (ADR-0023 OQ-4, founder). Cuando el DNS entre en producción, basta setear
 * NEXT_PUBLIC_WEBHOOK_HOST=https://api.konvi.co — sin tocar componentes.
 */
export const WEBHOOK_HOST =
  process.env.NEXT_PUBLIC_WEBHOOK_HOST?.replace(/\/+$/, '') ||
  'https://konvi-api.onrender.com'

export const WEBHOOK_PATHS = {
  wompi: '/api/v1/webhooks/wompi',
  telegram: '/api/v1/integrations/telegram/webhook',
  mercadolibre: '/api/v1/meli/webhook',
} as const

export type WebhookProvider = keyof typeof WEBHOOK_PATHS

/** URL absoluta del webhook a registrar en el dashboard del proveedor. */
export function webhookUrl(provider: WebhookProvider): string {
  return `${WEBHOOK_HOST}${WEBHOOK_PATHS[provider]}`
}
