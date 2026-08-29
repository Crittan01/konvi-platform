/// <reference types="react/experimental" />
import * as React from "react"
import { ViewTransition } from 'react'
import type { Metadata } from 'next'
import { redirect } from 'next/navigation'
import { createClient } from '@/utils/supabase/server'
import {
  getCachedUser, getCachedTenantMeta, getCachedTenantName,
} from '@/utils/supabase/cached-user'
import { getMarketplaceBadgeCount } from '@/lib/marketplace-badges'
import { verifyRecoveryCookie } from '@/lib/mfa-recovery-cookie'
import SidebarClient from './sidebar-client'
import { ThemeToggle } from '@/components/theme/theme-toggle'
import { BottomNav } from './bottom-nav'
import TopbarTitle from './topbar-title'
import CommandPalette from '@/components/command-palette'

/**
 * Browser title tenant-centric (Sem 7 F2 cierre — segregación Konvi/tenant).
 *
 * Cada página dashboard provee solo el segmento (`title: 'Pedidos'`) y
 * Next.js completa con el template `'%s — {tenantName}'`. Páginas sin
 * metadata propia caen en el `default` (solo el nombre del tenant).
 *
 * Pre-auth (login, forgot-password, etc.) mantiene "Konvi" porque vive
 * fuera del layout dashboard.
 */
export async function generateMetadata(): Promise<Metadata> {
  const tenantName = (await getCachedTenantName()) ?? 'Tu tienda'
  return {
    title: {
      template: `%s — ${tenantName}`,
      default: tenantName,
    },
  }
}

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  // Sem 5 perf: getCachedUser comparte resultado con page server
  // components anidados via React.cache. Ahorra 1 round-trip por
  // navegación (~640ms en VM Colombia → Supabase US-East).
  const user = await getCachedUser()

  if (!user) redirect('/login')

  const { role, tenantId } = await getCachedTenantMeta()
  const supabase = await createClient()

  // T7.10 — el logout vive en `/logout` (despedida de marca con la escena de
  // auth + signOut con limpieza G7 de la cookie AAL2). El sidebar enlaza allí.

  // Rev. 109 J.2.4.3 — detectar si el user entró vía recovery code
  // para mostrar banner urgente: regenerar TOTP idealmente esta sesión.
  const { cookies: cookiesFn } = await import('next/headers')
  const recoveryCookieStore = await cookiesFn()   // Next 16: cookies() es async
  // F83: verificar firma HMAC (ligada al user + expiry), no `=== '1'`.
  const usedRecoveryCode = await verifyRecoveryCookie(
    recoveryCookieStore.get('mfa_recovery_session')?.value,
    user.id,
    Math.floor(Date.now() / 1000),
  )

  // ── Ronda 2: todas las queries del tenant en paralelo ─────────────────────
  let tenantName: string | null = null
  let tenantLogoUrl: string | null = null
  let inboxBadge = 0
  let meliBadge = 0
  let planCode = 'enterprise'
  const planCapabilities: Record<string, boolean> = {}
  // Rev. 107 — `shipping` es la integración de logistics del tenant: true si
  // Aveonline (provider shipping soportado) está connected. Habilita el
  // módulo Cotizador del sidebar.
  const integrations = { whatsapp: false, shipping: false, mercadolibre: false }

  if (tenantId) {
    const [tenantRes, inboxRes, meliRes, integRes, subRes] = await Promise.all([
      supabase.from('tenants').select('name, logo_url').eq('id', tenantId).single(),
      // BLOQUE G-1: excluir archivadas (paridad inbox + home) — la retención archiva
      // conversaciones de cualquier status → el badge sobre-contaba las ya archivadas.
      supabase.from('conversations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('status', 'human_takeover').is('archived_at', null),
      supabase.from('marketplace_listings').select('status').eq('tenant_id', tenantId).eq('provider', 'mercadolibre'),
      supabase.from('tenant_integrations').select('provider, status').eq('tenant_id', tenantId).in('provider', ['whatsapp', 'aveonline', 'mercadolibre']),
      supabase.from('tenant_subscriptions').select('plan_code').eq('tenant_id', tenantId).maybeSingle(),
    ])

    tenantName    = tenantRes.data?.name ?? null
    tenantLogoUrl = tenantRes.data?.logo_url ?? null
    inboxBadge    = inboxRes.count ?? 0
    meliBadge     = getMarketplaceBadgeCount(meliRes.data ?? [])
    planCode      = subRes.data?.plan_code ?? 'enterprise'

    for (const row of integRes.data ?? []) {
      const provider  = (row as { provider?: string }).provider
      const connected = (row as { status?: string }).status === 'connected'
      if (provider === 'whatsapp')     integrations.whatsapp     = connected
      if (provider === 'aveonline')    integrations.shipping     = connected
      if (provider === 'mercadolibre') integrations.mercadolibre = connected
    }

    // ── Ronda 3: capabilities depende del planCode anterior ─────────────────
    try {
      const { data: caps } = await supabase
        .from('plan_capabilities')
        .select('capability_key, enabled')
        .eq('plan_code', planCode)

      for (const row of caps ?? []) {
        const key = (row as { capability_key?: string }).capability_key
        if (!key) continue
        planCapabilities[key] = (row as { enabled?: boolean }).enabled !== false
      }
    } catch {
      // Fail-open: si plan_capabilities no está disponible, no bloquear navegación.
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background">

      {/* ── Sidebar (responsive: desktop sticky, mobile drawer) ─────────── */}
      <SidebarClient
        role={role}
        userEmail={user?.email ?? ''}
        tenantName={tenantName}
        tenantLogoUrl={tenantLogoUrl}
        inboxBadge={inboxBadge}
        meliBadge={meliBadge}
        integrations={integrations}
        planCode={planCode}
        planCapabilities={planCapabilities}
      />

      {/* ── Main content ─────────────────────────────────────────────────── */}
      <main className="flex-1 overflow-y-auto min-w-0">
        {/* Top bar */}
        <div className="sticky top-0 z-10 h-12 border-b topbar-bg flex items-center px-4 sm:px-8">
          {/* Espacio para el hamburger en mobile */}
          <div className="w-10 lg:hidden" />
          {/* T7.5 — identidad de página (móvil y desktop; fuente única nav-items) */}
          <TopbarTitle />
          <div className="flex-1" />
          <div className="flex items-center gap-3">
            {/* Spec WOW §4.3 — entrada a la command palette (⌘K). Móvil: icono;
                desktop: input fake. Los gates son los mismos del sidebar. */}
            <CommandPalette
              role={role}
              integrations={integrations}
              planCapabilities={planCapabilities}
            />
            <ThemeToggle />
            {/* El indicador estático "Live" se eliminó (2026-08-21): afirmaba tiempo
                real sin medirlo y contradecía el badge real del dashboard
                ("Sin tiempo real"/"Reconectando…" en dashboard-client, que SÍ
                refleja el estado del canal). Sin señal falsa: sano = sin aviso. */}
          </div>
        </div>

        {/* Rev. 109 J.2.4.3 — Banner urgente si sesión vía recovery code */}
        {usedRecoveryCode && (
          <div className="mx-4 sm:mx-6 lg:mx-8 mt-4 rounded-lg border border-amber-700/40 bg-amber-50 px-4 py-3 text-sm text-amber-900 flex items-start gap-3">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>
            <div className="flex-1">
              <p className="font-medium">Sesión iniciada con código de respaldo</p>
              <p className="text-xs mt-1 text-amber-800">
                Esto significa que perdiste tu authenticator. Te recomendamos
                regenerar tu MFA + nuevos códigos de respaldo en{' '}
                <a href="/dashboard/settings/security" className="underline font-medium">Configuración → Seguridad</a>
                {' '}antes de que esta sesión expire (24h).
              </p>
            </div>
          </div>
        )}

        {/* Page content — pb extra en móvil para no quedar bajo el bottom-nav.
            ViewTransition (CABO 1, flag experimental.viewTransition): las
            navegaciones entre rutas del dashboard cruzan con un crossfade
            sutil del contenido (CSS ::view-transition-* en globals.css,
            180ms, easing DS; reduced-motion → sin animación). */}
        <div className="px-4 pt-4 pb-24 sm:px-6 sm:pt-6 lg:px-8 lg:pt-8 lg:pb-8">
          <ViewTransition name="dashboard-page">{children}</ViewTransition>
        </div>
      </main>

      {/* Navegación inferior móvil (fixed, < lg) — badge human_takeover,
          mismo dato que el sidebar desktop */}
      <BottomNav inboxBadge={inboxBadge} />
    </div>
  )
}
