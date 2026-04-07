import { createServerClient, type CookieOptions } from '@supabase/ssr'

export function createSSRClient(cookies: any) {
  // Patrón SSR Seguro Oficial Supabase
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
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
