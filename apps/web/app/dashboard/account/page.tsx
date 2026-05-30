/**
 * Rev. 109 J.2.4.3 — consolidación post-feedback founder 2026-05-29.
 *
 * Esta página fue reemplazada por /dashboard/settings/security que ahora
 * agrupa: cambiar contraseña + MFA TOTP + recovery codes en un solo lugar.
 *
 * Redirect permanente para backward-compat con bookmarks viejos y link
 * legacy del dropdown del avatar (ya actualizado al link nuevo).
 */
import { redirect } from 'next/navigation'

export default function AccountPage() {
  redirect('/dashboard/settings/security')
}
