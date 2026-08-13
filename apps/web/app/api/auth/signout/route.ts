/**
 * POST /api/auth/signout
 *
 * G7 (auditoría frontend seguridad) — logout centralizado que borra TAMBIÉN la
 * cookie HttpOnly `mfa_recovery_session` (bypass AAL2 de 24h seteada por
 * /api/mfa/recovery-codes/verify). Antes el único logout que la borraba era el
 * del dashboard (app/dashboard/layout.tsx); las vías "cambiar de cuenta" y
 * "salir del challenge MFA" la dejaban viva → una sesión AAL1 posterior (solo
 * password, p.ej. con la contraseña robada) heredaba el bypass sin pasar TOTP.
 *
 * La cookie es HttpOnly → el JS del browser no puede borrarla; por eso el
 * logout client-side del challenge MFA llama a este endpoint ANTES de su
 * signOut local.
 *
 * Nota gate AAL2 del proxy: si el caller trae la cookie de recovery VÁLIDA, el
 * proxy deja pasar la request (bypass legítimo) y aquí se borra. Si no la trae
 * válida, el proxy responde 401 — pero en ese caso no hay bypass vigente que
 * limpiar (una cookie expirada ya no verifica la firma HMAC), así que el
 * logout client-side procede igual y no se pierde seguridad.
 */
import { NextResponse } from 'next/server'
import { createClient } from '@/utils/supabase/server'
import { RECOVERY_SESSION_COOKIE } from '@/lib/mfa-recovery-cookie'

export async function POST() {
  // 1. Cierra la sesión Supabase server-side (el adapter de cookies emite los
  //    Set-Cookie que limpian la sesión SSR en el browser).
  const sb = await createClient()
  const { error } = await sb.auth.signOut()
  if (error) {
    // El logout no debe fallar por esto: la cookie de bypass se borra igual y
    // el caller hace su propio signOut client-side como respaldo.
    console.error('[auth/signout] signOut server-side falló:', error.message)
  }

  // 2. Expira la cookie de bypass AAL2 — mismos flags con que se seteó en
  //    /api/mfa/recovery-codes/verify (el path '/' es el que cuenta para que
  //    el browser la reemplace).
  const response = NextResponse.json({ ok: true })
  response.cookies.set({
    name: RECOVERY_SESSION_COOKIE,
    value: '',
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'strict',
    maxAge: 0,
    path: '/',
  })
  return response
}
