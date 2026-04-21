/**
 * Genera una llave de idempotencia estable por intento de acción en UI.
 * Formato: <scope>:<timestamp_base36>:<uuid_sin_guiones>
 */
export function createIdempotencyKey(scope: string): string {
  const safeScope = scope.replace(/[^a-zA-Z0-9:_-]/g, '').slice(0, 40) || 'op'
  const ts = Date.now().toString(36)
  const uuid = crypto.randomUUID().replace(/-/g, '')
  return `${safeScope}:${ts}:${uuid}`
}
