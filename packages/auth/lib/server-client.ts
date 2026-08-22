import { createServerClient, type CookieOptions } from '@supabase/ssr'

export function createSSRClient(cookies: any) {
  // Patrón SSR Seguro Oficial Supabase
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    // Track 6 (2026-08-22): sin fallback a la legacy ANON_KEY (desactivadas
    // a nivel Supabase desde 2026-08-19 — el fallback era código muerto).
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        get(name: string) {
          return cookies.get(name)?.value
        },
        set(name: string, value: string, options: CookieOptions) {
          cookies.set({ name, value, ...options })
        },
        remove(name: string, options: CookieOptions) {
          cookies.set({ name, value: '', ...options })
        },
      },
    }
  )
}
