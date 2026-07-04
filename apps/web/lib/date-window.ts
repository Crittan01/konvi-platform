/**
 * date-window — ventanas temporales en hora Colombia (F1 2026-07-04).
 *
 * Patrón canónico para la analítica (métricas, finanzas, dashboard). Konvi es
 * es-CO only y Colombia NO tiene horario de verano → offset fijo UTC-5. El bug
 * recurrente que esto cierra: agrupar/filtrar por día usando UTC hace que los
 * mensajes/pedidos de las 19:00-24:00 hora Colombia caigan en el día siguiente.
 *
 * Funciones puras (el `now` es inyectable para tests): úsalas para
 *   .gte('created_at', bogotaWindowUTC(7).fromUTC)
 * y para agrupar por día con bogotaDayKey(row.created_at).
 */
export const COLOMBIA_UTC_OFFSET_MIN = -5 * 60 // Bogota = UTC - 5h (sin DST)

const MIN = 60_000

/** 'YYYY-MM-DD' del día en hora Colombia para un timestamp UTC. */
export function bogotaDayKey(utc: string | Date): string {
  const d = typeof utc === 'string' ? new Date(utc) : utc
  return new Date(d.getTime() + COLOMBIA_UTC_OFFSET_MIN * MIN).toISOString().slice(0, 10)
}

/**
 * Ventana [fromUTC, toUTC] en ISO-UTC que cubre los últimos `days` días de
 * CALENDARIO en Colombia (incluye el día de hoy), desde el inicio del día
 * Colombia más antiguo hasta `now`. `days=7` → los 7 días Colombia visibles hoy.
 */
export function bogotaWindowUTC(days: number, now: Date = new Date()): { fromUTC: string; toUTC: string } {
  const bogotaNow = new Date(now.getTime() + COLOMBIA_UTC_OFFSET_MIN * MIN)
  // inicio (00:00 Colombia) del día de hace (days-1) jornadas
  const startBogotaMidnight = Date.UTC(
    bogotaNow.getUTCFullYear(),
    bogotaNow.getUTCMonth(),
    bogotaNow.getUTCDate() - (days - 1),
  )
  // de vuelta a UTC real: restar el offset (Bogota → UTC = +5h)
  const fromUTC = new Date(startBogotaMidnight - COLOMBIA_UTC_OFFSET_MIN * MIN)
  return { fromUTC: fromUTC.toISOString(), toUTC: now.toISOString() }
}

/**
 * datetime-local (wall-clock Colombia, ej '2026-07-04T22:00') → ISO UTC.
 * '' o null → null. El <input type="datetime-local"> no lleva zona; el operador
 * escribe hora Colombia, así que se ancla a UTC-5 antes de persistir (timestamptz).
 */
export function bogotaLocalToUTC(local: string | null | undefined): string | null {
  if (!local) return null
  const d = new Date(`${local}:00-05:00`)
  return isNaN(d.getTime()) ? null : d.toISOString()
}

/** ISO UTC → 'YYYY-MM-DDTHH:mm' en hora Colombia, para prellenar un datetime-local. */
export function utcToBogotaLocal(utc: string | null | undefined): string {
  if (!utc) return ''
  const d = new Date(utc)
  if (isNaN(d.getTime())) return ''
  return new Date(d.getTime() + COLOMBIA_UTC_OFFSET_MIN * MIN).toISOString().slice(0, 16)
}

/** Lista ordenada de las claves 'YYYY-MM-DD' Colombia de los últimos `days` días. */
export function bogotaDayKeys(days: number, now: Date = new Date()): string[] {
  const bogotaNow = new Date(now.getTime() + COLOMBIA_UTC_OFFSET_MIN * MIN)
  const keys: string[] = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(Date.UTC(bogotaNow.getUTCFullYear(), bogotaNow.getUTCMonth(), bogotaNow.getUTCDate() - i))
    keys.push(d.toISOString().slice(0, 10))
  }
  return keys
}
