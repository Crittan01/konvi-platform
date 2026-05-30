'use server'

/**
 * Server actions del flow Cerrar cuenta.
 *
 * Rev. 109 J.2.4.4 Fase 2.
 *
 * Cada action invoca el backend API (services/api/routers/tenant_offboarding.py)
 * con el access_token del session cookie. NO toca DB directamente — el backend
 * tiene la lógica + RPCs + audit logging.
 */
import { redirect } from 'next/navigation'
import { revalidatePath } from 'next/cache'
import { createClient } from '@/utils/supabase/server'
import { CORE_API_URL } from '@/lib/runtime-env'

async function getOwnerToken(): Promise<string> {
  const sb = createClient()
  const { data: { session } } = await sb.auth.getSession()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { role?: string }
  if (!session?.access_token || meta.role !== 'owner') {
    redirect('/dashboard')
  }
  return session.access_token
}

/**
 * Solicita el export completo del tenant data (Ley 1581 Art. 19 portabilidad).
 * Backend retorna JSON inline — UI debe convertir a download.
 */
export async function requestTenantExport(): Promise<
  | { ok: true; data: unknown }
  | { ok: false; error: string }
> {
  const token = await getOwnerToken()
  try {
    const res = await fetch(
      `${CORE_API_URL}/api/v1/tenant/offboarding/export`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        cache: 'no-store',
      },
    )
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
      return { ok: false, error: err.detail || `Error ${res.status}` }
    }
    const data = await res.json()
    return { ok: true, data }
  } catch (e) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : 'Error de red al exportar',
    }
  }
}

/**
 * Inicia el soft-delete del tenant con grace period 30d.
 *
 * Requiere confirmation_phrase EXACTA = 'ELIMINAR <tenant_name>' (anti-fat-finger
 * server-side, validado por el backend) + reason min 10 chars.
 */
export async function requestTenantDeletion(
  confirmationPhrase: string,
  reason: string,
): Promise<
  | { ok: true; scheduled_for: string; message: string }
  | { ok: false; error: string }
> {
  const token = await getOwnerToken()
  try {
    const res = await fetch(
      `${CORE_API_URL}/api/v1/tenant/offboarding/request-deletion`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          confirmation_phrase: confirmationPhrase,
          reason,
        }),
        cache: 'no-store',
      },
    )
    const data = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    if (!res.ok) {
      return { ok: false, error: data.detail || `Error ${res.status}` }
    }
    revalidatePath('/dashboard/settings/account-closure')
    return {
      ok: true,
      scheduled_for: data.scheduled_for,
      message: data.message,
    }
  } catch (e) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : 'Error de red',
    }
  }
}

/**
 * Cancela el soft-delete dentro del grace period.
 *
 * NO restaura credenciales tenant_integrations invalidadas — el owner
 * debe re-conectarlas vía Settings → Integraciones (decisión seguridad).
 */
export async function cancelTenantDeletion(): Promise<
  | { ok: true; message: string }
  | { ok: false; error: string }
> {
  const token = await getOwnerToken()
  try {
    const res = await fetch(
      `${CORE_API_URL}/api/v1/tenant/offboarding/cancel-deletion`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ confirm: true }),
        cache: 'no-store',
      },
    )
    const data = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
    if (!res.ok) {
      return { ok: false, error: data.detail || `Error ${res.status}` }
    }
    revalidatePath('/dashboard/settings/account-closure')
    return { ok: true, message: data.message }
  } catch (e) {
    return {
      ok: false,
      error: e instanceof Error ? e.message : 'Error de red',
    }
  }
}
