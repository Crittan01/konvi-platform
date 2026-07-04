/**
 * Tipos y constantes compartidas de "Salud de mis integraciones".
 *
 * Rev. 109 J.2.11 · F6 2026-07-04: fuente única para el esquema HealthRow
 * (antes duplicado por copia en page.tsx y health-grid.tsx — un cambio de
 * esquema no lo detectaba TypeScript cross-file).
 */

export interface HealthRow {
  provider: string
  metric: string
  value: string | null
  threshold: string | null
  status: 'healthy' | 'warning' | 'critical' | 'unknown'
  detail: Record<string, unknown>
  observed_at: string
  updated_at: string
}

export type HealthStatus = HealthRow['status']

/** Etiqueta humana por provider. Nombres reales (Aveonline, no "Envia" — ADR-0019). */
export const PROVIDER_LABELS: Record<string, string> = {
  whatsapp: 'WhatsApp Business',
  wompi: 'Wompi (pagos)',
  aveonline: 'Aveonline (despachos)',
  meli: 'MercadoLibre',
  telegram: 'Telegram (notificaciones operador)',
}

export const PROVIDER_ORDER = ['whatsapp', 'wompi', 'aveonline', 'meli', 'telegram']

/**
 * Deep-link a la página de la integración correspondiente para remediar.
 * El provider emitido "meli" mapea a la ruta real /integrations/mercadolibre.
 */
export const PROVIDER_ROUTE: Record<string, string> = {
  whatsapp: '/dashboard/integrations/whatsapp',
  wompi: '/dashboard/integrations/wompi',
  aveonline: '/dashboard/integrations/aveonline',
  meli: '/dashboard/integrations/mercadolibre',
  telegram: '/dashboard/integrations/telegram',
}

/**
 * El cron del orchestrator recolecta cada 5 min (300s). Una observación más
 * antigua que 2× el intervalo + jitter (11 min) indica que el ciclo se detuvo
 * (deploy caído, worker hibernado): el badge deja de ser "tiempo real".
 */
export const STALE_AFTER_MS = 11 * 60 * 1000
