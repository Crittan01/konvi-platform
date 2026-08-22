import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  // Track 6 (2026-08-22): fallback legacy `ANON_KEY` eliminado — las llaves
  // legacy (anon/service_role JWT) están DESACTIVADAS a nivel Supabase desde
  // 2026-08-19 (B2 paso 10); si falta la publishable, mejor fallar explícito
  // que caer en una key muerta con un error críptico downstream.
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!
  )
}
