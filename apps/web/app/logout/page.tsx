import { createClient } from '@/utils/supabase/server'
import { AuthBrand, AuthCardReveal, AuthScene } from '@/components/auth/auth-scene'
import LogoutFarewell from './logout-farewell'

export const metadata = {
  title: 'Cerrar sesión — Konvi',
}

/**
 * T7.10 — Logout con despedida de marca (directiva founder 2026-08-25: el valor
 * de diseño del lenguaje de auth en TODO el front, incluido el logout).
 * La despedida usa la MISMA escena de auth (grano + aurora + brand tile) y el
 * signOut preserva la limpieza G7 de la cookie de bypass AAL2.
 */
export default function LogoutPage() {
  const farewellAction = async () => {
    'use server'
    const supabase = await createClient()
    await supabase.auth.signOut()
    // Rev. 109 J.2.4.3 — limpiar cookie de recovery bypass al cerrar sesión:
    // si el user entró con recovery code, la cookie HttpOnly debe borrarse para
    // que el próximo login REQUIERA TOTP o nuevo recovery (mismo patrón que
    // tenía el logout del dashboard y el switch-user del login).
    const { cookies } = await import('next/headers')
    const cookieStore = await cookies()   // Next 16: cookies() es async
    cookieStore.delete('mfa_recovery_session')
  }

  return (
    <AuthScene>
      <AuthBrand subtitle="Hasta pronto — tu negocio sigue en buenas manos" />
      <AuthCardReveal>
        <LogoutFarewell action={farewellAction} />
      </AuthCardReveal>
    </AuthScene>
  )
}
