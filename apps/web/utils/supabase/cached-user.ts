/**
 * Cached auth helpers — Sem 5 perf optimization (rev. 105).
 *
 * Disparador: founder reportó (2026-05-07) que tras compilación, navegar
 * en localhost se siente lento. Diagnóstico: latencia VM Colombia →
 * Supabase AWS US-East-1 = ~640ms por `auth.getUser()`. En layouts +
 * server components anidados se hacen 2-3 llamadas duplicadas por page
 * render.
 *
 * Solución: `React.cache()` deduplicate dentro del MISMO server render
 * tree. Múltiples invocaciones de `getCachedUser()` en layout + page
 * + sub-server-components comparten UNA sola query.
 *
 * Importante:
 *   - El cache es por-request (per render). React lo descarta entre
 *     requests. NO leak de auth entre usuarios.
 *   - Middleware vive en runtime distinto (Edge) — su `auth.getUser()`
 *     NO comparte cache con server components (Node runtime). Por eso
 *     middleware sigue su llamada propia.
 *   - Server actions corren en su propia request — NO comparten cache
 *     con la page render que los originó.
 *
 * Ahorro medido: ~640ms por page load en VM Colombia (pasa de 2 calls
 * Auth → 1 call). En producción Render (mismo region que Supabase) el
 * ahorro absoluto es marginal (~10ms) pero gratuito.
 *
 * Uso:
 *
 *   // En page server component:
 *   import { getCachedUser, getCachedTenantMeta } from '@/utils/supabase/cached-user'
 *
 *   export default async function Page() {
 *     const user = await getCachedUser()
 *     const meta = await getCachedTenantMeta()
 *     // ...
 *   }
 */
import { cache } from 'react'
import { createClient } from './server'

/**
 * Retorna el usuario autenticado actual. Cached por request via
 * React.cache — múltiples llamadas en el mismo render tree comparten
 * UNA sola query a Supabase Auth.
 *
 * Returns null si no hay sesión válida (caller decide redirect).
 */
export const getCachedUser = cache(async () => {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  return user
})

/**
 * Tipo del meta extraído de `app_metadata`.
 *
 * `tenant_id` y `role` son los stamps que el platform admin coloca
 * cuando crea/asigna usuarios. Si user existe pero meta no tiene
 * `tenant_id`, es un usuario malformado (caller debe rechazar).
 */
export type TenantMeta = {
  tenantId: string | undefined
  role: 'owner' | 'manager' | 'operator'
  email: string
  userId: string | undefined
}

/**
 * Wrapper conveniente: extrae tenant + role + email del usuario.
 * Cached por la dependencia transitiva de `getCachedUser`.
 *
 * Si user es null → retorna meta con tenantId undefined + role
 * 'operator' (caller decide redirect).
 */
export const getCachedTenantMeta = cache(async (): Promise<TenantMeta> => {
  const user = await getCachedUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  return {
    tenantId: meta.tenant_id,
    role: (meta.role as 'owner' | 'manager' | 'operator') ?? 'operator',
    email: user?.email ?? '',
    userId: user?.id,
  }
})

/**
 * Tenant-centric branding (Sem 7 F2 cierre — segregación Konvi/tenant).
 *
 * Lookup del nombre del tenant para sidebar + browser title +
 * placeholders de templates. Cached per-request — múltiples llamadas en
 * el mismo render tree (layout + page + components) comparten 1 query.
 *
 * Returns:
 *   null si tenantId undefined (caller decide fallback como 'Tu tienda').
 *   El nombre real (e.g. "KAIU") si existe en la tabla `tenants`.
 *
 * NO levanta excepción si la query falla — devuelve null defensivamente
 * (un title degradado es mejor que un crash en SSR).
 */
export const getCachedTenantName = cache(async (): Promise<string | null> => {
  const { tenantId } = await getCachedTenantMeta()
  if (!tenantId) return null
  const supabase = createClient()
  const { data } = await supabase
    .from('tenants')
    .select('name')
    .eq('id', tenantId)
    .maybeSingle()
  const name = (data?.name ?? '').trim()
  return name.length > 0 ? name : null
})
