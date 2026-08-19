import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

// Next 15: `cookies()` es async → `createClient()` debe ser async y todos sus callers
// deben `await createClient()`. Adapter migrado a getAll/setAll (API no-deprecada de
// @supabase/ssr 0.10).
export async function createClient() {
  const cookieStore = await cookies()

  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll()
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options),
            )
          } catch {
            // setAll llamado desde un Server Component — se ignora si hay
            // middleware refrescando la sesión del usuario (el caso normal).
          }
        },
      },
    },
  )
}
