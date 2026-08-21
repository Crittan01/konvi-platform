import { createBrowserClient } from '@supabase/ssr'

// STG local: si la URL configurada es loopback (127.0.0.1/localhost) pero la
// página se está viendo desde OTRO host (ej. la IP de LAN de la VM desde otro
// equipo), el browser debe llamar al MISMO host que sirvió la página — con
// 127.0.0.1 el websocket/REST apuntaría a la máquina del visitante y el
// realtime moriría con CHANNEL_ERROR (el resto de la app sigue porque el dato
// viaja por SSR en la VM). En PRD la URL es pública (https) y el swap no aplica.
export function resolveSupabaseUrl(
  configuredUrl: string,
  pageHostname?: string,
): string {
  const host = pageHostname ?? (typeof window !== 'undefined' ? window.location.hostname : '')
  if (!host || host === '127.0.0.1' || host === 'localhost') return configuredUrl
  return configuredUrl.replace(
    /^(https?:\/\/)(127\.0\.0\.1|localhost)(?=[:/]|$)/,
    `$1${host}`,
  )
}

export function createClient() {
  return createBrowserClient(
    resolveSupabaseUrl(process.env.NEXT_PUBLIC_SUPABASE_URL!),
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!
  )
}
