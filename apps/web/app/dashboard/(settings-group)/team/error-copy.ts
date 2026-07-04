/**
 * mapTeamError — traduce el slug/mensaje crudo de una action de equipo a copy
 * en es-CO orientado al operador tenant.
 *
 * Vive fuera de page.tsx para ser testeable (regresión sobre el camino vivo:
 * los banners son la única superficie de feedback de las 6 server actions).
 *
 * IMPORTANTE: no exponer slugs internos ni mensajes Supabase en inglés al
 * operador, y no instruir acciones de plataforma (SMTP, dashboard Supabase)
 * que un tenant no puede ejecutar.
 */
export function mapTeamError(rawError: string): string {
  const raw = rawError.toLowerCase()

  if (raw.includes('rate') || raw.includes('limit') || raw.includes('too many') || raw.includes('demasiad')) {
    return 'Demasiados envíos de invitación en poco tiempo. Espera unos minutos e inténtalo de nuevo.'
  }
  if (raw.includes('sin-permiso') || raw.includes('permission') || raw.includes('not allowed') || raw.includes('unauthorized')) {
    return 'No tienes permiso para realizar esta acción. Es posible que tu sesión haya expirado; recarga la página e inténtalo de nuevo.'
  }
  if (raw.includes('datos-invalidos')) {
    return 'Email o rol inválido. Verifica los datos e inténtalo de nuevo.'
  }
  if (raw.includes('ya-es-miembro')) {
    return 'Este email ya es miembro del equipo.'
  }
  if (raw.includes('miembro-no-encontrado')) {
    return 'No se encontró a ese miembro en tu equipo, o su rol no permite esta acción. Recarga la página para ver el estado actualizado.'
  }
  if (raw.includes('usuario-no-encontrado')) {
    return 'No se pudo localizar la cuenta de ese usuario. Recarga la página e inténtalo de nuevo; si persiste, contacta a soporte.'
  }
  if (raw.includes('respuesta-inesperada')) {
    return 'El servicio de invitaciones respondió de forma inesperada. Inténtalo de nuevo en unos minutos; si persiste, contacta a soporte.'
  }
  if (raw.includes('rol-invalido')) {
    return 'El rol seleccionado no es válido. Solo puedes asignar Supervisor o Gestor.'
  }
  // Fallback genérico — NUNCA renderizar el mensaje crudo (suele venir en inglés).
  return 'No se pudo completar la acción. Inténtalo de nuevo en unos minutos; si el problema persiste, contacta a soporte.'
}
