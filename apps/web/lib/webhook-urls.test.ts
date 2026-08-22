import { describe, it, expect } from 'vitest'
import { WEBHOOK_PATHS, WEBHOOK_HOST, webhookUrl } from './webhook-urls'

/**
 * Test de contrato UI ↔ rutas backend. Ancla el fix F93 (URLs de webhook
 * erróneas para Wompi/Telegram). Si alguien cambia un path aquí sin cambiar
 * el router de services/api, este test falla y evita el drift que provocó
 * pagos no confirmados (404 en el webhook Wompi).
 *
 * Paths verificados contra services/api/main.py:
 *   - wompi_webhook:    prefix "/api/v1/webhooks"     + "/wompi"
 *   - telegram_webhook: prefix "/api/v1/integrations" + "/telegram/webhook"
 *   - meli_webhook:     prefix "/api/v1/meli"         + "/webhook"
 *   - resend_webhook:   prefix "/api/v1/webhooks"     + "/resend" (Track 6)
 */
describe('webhook-urls', () => {
  it('mantiene los paths exactos que expone el API', () => {
    expect(WEBHOOK_PATHS.wompi).toBe('/api/v1/webhooks/wompi')
    expect(WEBHOOK_PATHS.telegram).toBe('/api/v1/integrations/telegram/webhook')
    expect(WEBHOOK_PATHS.mercadolibre).toBe('/api/v1/meli/webhook')
    expect(WEBHOOK_PATHS.resend).toBe('/api/v1/webhooks/resend')
  })

  it('NO usa las rutas 404 antiguas (regresión F93)', () => {
    expect(WEBHOOK_PATHS.wompi).not.toBe('/api/v1/wompi/webhook')
    expect(WEBHOOK_PATHS.telegram).not.toBe('/api/v1/telegram/webhook')
  })

  it('compone la URL absoluta sobre el host productivo por defecto', () => {
    expect(WEBHOOK_HOST).toMatch(/^https:\/\//)
    expect(webhookUrl('wompi')).toBe(`${WEBHOOK_HOST}/api/v1/webhooks/wompi`)
    expect(webhookUrl('telegram')).toBe(
      `${WEBHOOK_HOST}/api/v1/integrations/telegram/webhook`,
    )
  })
})
