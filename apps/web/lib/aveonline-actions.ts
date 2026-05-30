/**
 * Helpers compartidos para los server-actions de Aveonline.
 *
 * Rev. 107 — el hub `/dashboard/integrations` y el panel dedicado
 * `/dashboard/integrations/aveonline` necesitan la misma lógica
 * connect/test/disconnect. Para evitar drift entre las dos copias,
 * extraemos la lógica pura a este módulo (NO usa `'use server'`).
 *
 * Cada server-action en su page.tsx envuelve estas funciones, agregando
 * solo la verificación de permisos + revalidatePath específica.
 */
import type { SupabaseClient } from '@supabase/supabase-js'

// Endpoint oficial v1.0 documentado en dossier docs/research/aveonline-dossier.md §2.1.
const AVEONLINE_AUTH_URL =
  'https://app.aveonline.co/api/comunes/v1.0/autenticarusuario.php'

export type AveonlineConnectInput = {
  usuario: string
  password: string
  authVersion?: string
  tiempoToken?: number
}

export type AveonlineResult = { ok: boolean; error?: string }

type AveonlineApiResponse = {
  status?: string
  message?: string
  token?: string
  cuentas?: Array<{
    usuarios?: Array<{
      id?: number
      documento?: string
      nombre?: string
      razon?: string
      asesorlogistico?: string
      nombreasesor?: string
    }>
  }>
}

/**
 * Valida credenciales contra Aveonline + persiste en Vault + upsert
 * `tenant_integrations`. Dossier §2.1 v1.0 body canónico.
 */
export async function connectAveonline(
  sb: SupabaseClient,
  tenantId: string,
  userEmail: string | undefined,
  input: AveonlineConnectInput,
): Promise<AveonlineResult> {
  const usuario = (input.usuario || '').trim()
  const password = (input.password || '').trim()
  const authVersion = (input.authVersion || 'v1.0').trim()
  const tiempoToken = Math.max(
    3600,
    Math.min(31536000, input.tiempoToken ?? 100000),
  )

  if (!usuario || usuario.length < 3) {
    return { ok: false, error: 'Usuario requerido (mínimo 3 caracteres).' }
  }
  if (!password || password.length < 4) {
    return { ok: false, error: 'Password requerida (mínimo 4 caracteres).' }
  }
  if (!['v1.0', 'v2.0'].includes(authVersion)) {
    return { ok: false, error: 'Versión de auth inválida (use v1.0 o v2.0).' }
  }

  // POST de prueba antes de persistir nada.
  let aveResp: AveonlineApiResponse = {}
  try {
    const resp = await fetch(AVEONLINE_AUTH_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tipo: 'auth',
        usuario,
        clave: password,
        acceso: 'ecommerce',
        tiempoToken,
      }),
    })
    if (!resp.ok) {
      return {
        ok: false,
        error: `Aveonline retornó HTTP ${resp.status}. Revisa tu cuenta.`,
      }
    }
    aveResp = (await resp.json()) as AveonlineApiResponse
  } catch (e) {
    return {
      ok: false,
      error: `No pudimos conectar con Aveonline: ${
        e instanceof Error ? e.message : 'error de red'
      }`,
    }
  }

  if (aveResp.status !== 'ok' || !aveResp.token) {
    return {
      ok: false,
      error: `Aveonline rechazó las credenciales: ${
        aveResp.message || 'usuario o clave incorrectos'
      }`,
    }
  }

  const usuarioData = aveResp.cuentas?.[0]?.usuarios?.[0] ?? {}
  const empresaId = usuarioData.id ?? null
  const asesorLogistico = usuarioData.asesorlogistico ?? null
  const nombreAsesor = usuarioData.nombreasesor ?? null
  const razonSocial = usuarioData.razon ?? null

  if (!empresaId) {
    return {
      ok: false,
      error: 'Aveonline no retornó empresa_id válido. Contacta soporte.',
    }
  }

  // Vault — IDEMPOTENT: si tenant ya tenía password_secret_id, UPDATE.
  const vaultName = `${tenantId}/aveonline/password`
  let secretId: string | null = null

  const { data: existingRow } = await sb
    .from('tenant_integrations')
    .select('credentials')
    .eq('tenant_id', tenantId)
    .eq('provider', 'aveonline')
    .maybeSingle()

  const existingSecretId =
    (existingRow?.credentials as { password_secret_id?: string } | null)
      ?.password_secret_id ?? null

  if (existingSecretId) {
    const { error: updErr } = await sb.rpc('pgsec_update_secret', {
      p_id: existingSecretId,
      p_secret: password,
    })
    if (updErr) {
      return { ok: false, error: `Vault update error: ${updErr.message}` }
    }
    secretId = existingSecretId
  } else {
    const { data: newSecretId, error: createErr } = await sb.rpc(
      'pgsec_create_secret',
      {
        p_secret: password,
        p_name: vaultName,
        p_description: 'Aveonline password v1.0 auth',
      },
    )
    if (createErr || !newSecretId) {
      return {
        ok: false,
        error: `Vault create error: ${
          createErr?.message || 'no secret_id retornado'
        }`,
      }
    }
    secretId = newSecretId as string
  }

  const expiresAt = new Date(Date.now() + tiempoToken * 1000).toISOString()

  const { error: upsertErr } = await sb
    .from('tenant_integrations')
    .upsert(
      {
        tenant_id: tenantId,
        provider: 'aveonline',
        status: 'connected',
        credentials: {
          usuario,
          password_secret_id: secretId,
          empresa_id: empresaId,
          asesor_logistico: asesorLogistico,
          nombre_asesor: nombreAsesor,
          razon_social: razonSocial,
          jwt_token: aveResp.token,
          jwt_expires_at: expiresAt,
          tiempo_token: tiempoToken,
          auth_version: authVersion,
        },
        meta: {
          // Solo campos NO-sensibles para mostrar en hub UI.
          connected_at: new Date().toISOString(),
          connected_by: userEmail,
          empresa_id: String(empresaId),
          auth_version: authVersion,
          razon_social: razonSocial ?? '',
          nombre_asesor: nombreAsesor ?? '',
        },
      },
      { onConflict: 'tenant_id,provider' },
    )
  if (upsertErr) {
    return {
      ok: false,
      error: `Error guardando integración: ${upsertErr.message}`,
    }
  }

  return { ok: true }
}

/**
 * Desconecta Aveonline: marca `status=disconnected`. NO borra row ni
 * password Vault (Habeas Data SAR endpoint cubre eliminación).
 */
export async function disconnectAveonline(
  sb: SupabaseClient,
  tenantId: string,
): Promise<AveonlineResult> {
  const { error } = await sb
    .from('tenant_integrations')
    .update({ status: 'disconnected' })
    .eq('tenant_id', tenantId)
    .eq('provider', 'aveonline')

  if (error) return { ok: false, error: `Error: ${error.message}` }
  return { ok: true }
}

/**
 * Prueba la conexión: re-autentica contra Aveonline usando el usuario
 * + password en Vault. Confirma que las credenciales siguen vigentes y
 * que la cuenta retorna `status=ok` + token.
 *
 * NO refresca el JWT cacheado — eso ocurre lazy desde el cotizador del
 * orchestrator cuando el JWT expira. Aquí solo validamos credenciales.
 */
export async function testAveonline(
  sb: SupabaseClient,
  tenantId: string,
): Promise<AveonlineResult> {
  const { data: row, error: readErr } = await sb
    .from('tenant_integrations')
    .select('credentials')
    .eq('tenant_id', tenantId)
    .eq('provider', 'aveonline')
    .maybeSingle()

  if (readErr) return { ok: false, error: `Error DB: ${readErr.message}` }
  if (!row) {
    return { ok: false, error: 'Aveonline no está conectado para este tenant.' }
  }

  const creds = (row.credentials as Record<string, unknown>) ?? {}
  const usuario = (creds.usuario as string) ?? ''
  const passwordSecretId = (creds.password_secret_id as string) ?? ''
  const authVersion = (creds.auth_version as string) ?? 'v1.0'
  const tiempoToken =
    typeof creds.tiempo_token === 'number'
      ? (creds.tiempo_token as number)
      : 100000

  if (!usuario || !passwordSecretId) {
    return {
      ok: false,
      error: 'Credenciales incompletas. Reconecta Aveonline.',
    }
  }

  const { data: password, error: vaultErr } = await sb.rpc(
    'pgsec_read_secret',
    { p_id: passwordSecretId },
  )
  if (vaultErr || !password) {
    return {
      ok: false,
      error: `Vault error: ${
        vaultErr?.message ?? 'no se pudo leer password'
      }`,
    }
  }

  // POST de validación contra Aveonline (igual que connect, pero sin upsert).
  try {
    const controller = new AbortController()
    const timeout = setTimeout(() => controller.abort(), 15000)
    try {
      const resp = await fetch(AVEONLINE_AUTH_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          tipo: 'auth',
          usuario,
          clave: password,
          acceso: 'ecommerce',
          tiempoToken,
        }),
        signal: controller.signal,
      })
      clearTimeout(timeout)
      if (!resp.ok) {
        return {
          ok: false,
          error: `Aveonline retornó HTTP ${resp.status}.`,
        }
      }
      const body = (await resp.json()) as AveonlineApiResponse
      if (body.status !== 'ok' || !body.token) {
        return {
          ok: false,
          error:
            body.message ||
            `Aveonline rechazó las credenciales (auth ${authVersion}).`,
        }
      }
    } finally {
      clearTimeout(timeout)
    }
  } catch (e) {
    const detail = e instanceof Error ? e.message : 'error desconocido'
    if (detail.includes('abort') || detail.includes('timeout')) {
      return {
        ok: false,
        error: 'Tiempo de espera agotado. Aveonline tardó más de 15s.',
      }
    }
    return { ok: false, error: `Error de red: ${detail}` }
  }

  return { ok: true }
}
