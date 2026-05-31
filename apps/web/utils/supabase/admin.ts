import { createClient as createSupabaseClient } from '@supabase/supabase-js'

/**
 * Cliente Supabase con Service Role Key.
 * SOLO para uso en Server Actions y Route Handlers (SSR).
 * NUNCA importar en componentes client ('use client').
 *
 * Capacidades: auth.admin.* — invite, delete users, update metadata.
 * Bypasea RLS — usar con extremo cuidado y solo donde sea explícitamente necesario.
 */
export function createAdminClient() {
  const url  = process.env.NEXT_PUBLIC_SUPABASE_URL
  // A0.2c: SUPABASE_SECRET_KEY canónico con fallback legacy SERVICE_ROLE_KEY.
  const key  = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY

  if (!url || !key) {
    throw new Error(
      'NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY (legacy: SUPABASE_SERVICE_ROLE_KEY) ' +
      'no están configurados. Verificar variables de entorno en Render / .env'
    )
  }

  return createSupabaseClient(url, key, {
    auth: {
      autoRefreshToken: false,
      persistSession:   false,
    },
  })
}
