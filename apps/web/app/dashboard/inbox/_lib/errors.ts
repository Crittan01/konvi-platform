/**
 * Normaliza el `detail` de una respuesta de error de FastAPI a un string seguro para
 * renderizar en React.
 *
 * BLOQUE E: FastAPI puede devolver `detail` como string O como objeto ({code, message, ...}).
 * La verificación de ventana 24h de WhatsApp (conversations.py `_check_24h_window_or_raise`)
 * lanza `detail={code: 'WINDOW_EXPIRED'|'WINDOW_NO_INBOUND', message, ...}` → antes el objeto
 * se seteaba directo como estado de error y al renderizarlo React crasheaba el Inbox
 * ("Objects are not valid as a React child"). Este helper extrae el `message` o cae al fallback.
 */
export function errorDetailToString(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object' && 'message' in detail) {
    const m = (detail as { message?: unknown }).message
    if (typeof m === 'string' && m.trim()) return m
  }
  return fallback
}

/** Código de error estructurado de FastAPI (si `detail` es objeto), para UI accionable. */
export function errorDetailCode(detail: unknown): string | null {
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const c = (detail as { code?: unknown }).code
    if (typeof c === 'string') return c
  }
  return null
}
