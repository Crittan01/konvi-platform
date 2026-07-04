// Rev. 101 (F7) — UI click-wrap aceptación legal (DPA + Privacy + Subprocessors).
//
// Tabla `tenant_legal_acceptance` (rev. 99): append-only via DB triggers.
// Cada documento + versión se acepta una vez; si cambia la versión,
// requiere nueva aceptación. La aceptación captura:
//   - tenant_id, document_id, document_version, accepted_by_user_id,
//     accepted_by_email, ip_address, user_agent, accepted_at.
//
// Versiones vigentes (sincronizar con docs/legal/*.md):
//   dpa: v2026-05-01
//   privacy_policy: v2026-05-01
//   subprocessors: v2026-05-01
//
// Cuando se actualice un documento, bump la versión aquí.

import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { headers } from 'next/headers'
import { ScrollText } from 'lucide-react'
import { CORE_API_URL } from '@/lib/runtime-env'
import LegalAcceptanceClient from './_components/legal-acceptance-client'
import { SicReportDownload } from './_components/sic-report-download'

const CURRENT_VERSIONS = {
  dpa: 'v2026-05-01',
  privacy_policy: 'v2026-05-01',
  subprocessors: 'v2026-05-01',
} as const

const DOCUMENT_LABELS: Record<keyof typeof CURRENT_VERSIONS, { label: string; description: string; href: string }> = {
  dpa: {
    label: 'Data Processing Agreement (DPA)',
    description: 'Acuerdo de tratamiento de datos. Define que el tenant es Responsable y la plataforma es Encargado.',
    href: '/docs/legal/dpa.md',
  },
  privacy_policy: {
    label: 'Política de Privacidad (template)',
    description: 'Template para que el tenant publique al titular. El tenant adapta a su operación.',
    href: '/docs/legal/privacy-policy.md',
  },
  subprocessors: {
    label: 'Lista de Subprocesadores',
    description: 'Terceros con quienes la plataforma comparte datos para operar.',
    href: '/docs/legal/subprocessors.md',
  },
}

type Acceptance = {
  id: string
  document_id: string
  document_version: string
  accepted_by_email: string | null
  accepted_at: string
}

export default async function LegalAcceptancePage() {
  const sb = await createClient()
  const { data: { user } } = await sb.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const canAccept = ['owner', 'manager'].includes(meta.role ?? '')

  let history: Acceptance[] = []
  if (tenantId) {
    const { data } = await sb
      .from('tenant_legal_acceptance')
      .select('id, document_id, document_version, accepted_by_email, accepted_at')
      .eq('tenant_id', tenantId)
      .order('accepted_at', { ascending: false })
      .limit(50)
    history = (data ?? []) as Acceptance[]
  }

  // Versión vigente -> aceptación más reciente que coincida (si hay).
  const acceptedByDoc: Record<string, Acceptance | undefined> = {}
  for (const doc of Object.keys(CURRENT_VERSIONS) as (keyof typeof CURRENT_VERSIONS)[]) {
    const version = CURRENT_VERSIONS[doc]
    acceptedByDoc[doc] = history.find(h => h.document_id === doc && h.document_version === version)
  }

  // Server action: append acceptance row.
  async function acceptDocument(formData: FormData) {
    'use server'
    const sb2 = await createClient()
    const { data: { user: u } } = await sb2.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const docId = String(formData.get('document_id') || '')
    const docVersion = String(formData.get('document_version') || '')
    if (!(docId in CURRENT_VERSIONS) || !docVersion) return
    const hdrs = await headers()
    const ip =
      hdrs.get('x-forwarded-for')?.split(',')[0]?.trim() ||
      hdrs.get('x-real-ip') ||
      null
    const ua = hdrs.get('user-agent')?.slice(0, 500) || null
    // Triggers en DB son append-only — INSERT directo. Unique idx
    // (tenant_id, document_id, document_version) protege duplicados.
    await sb2.from('tenant_legal_acceptance').insert({
      tenant_id: m.tenant_id,
      document_id: docId,
      document_version: docVersion,
      accepted_by_user_id: u?.id ?? null,
      accepted_by_email: u?.email ?? null,
      ip_address: ip,
      user_agent: ua,
    })
    revalidatePath('/dashboard/settings/legal')
  }

  return (
    <div className="space-y-5 max-w-4xl">
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <ScrollText className="h-5 w-5 text-primary" /> Aceptación legal
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Habeas Data Ley 1581/2012 — relación Responsable (tenant) ↔ Encargado (plataforma).
          La aceptación queda registrada de forma inmutable (append-only) con timestamp + IP.
        </p>
      </div>

      <LegalAcceptanceClient
        currentVersions={CURRENT_VERSIONS}
        documentLabels={DOCUMENT_LABELS}
        acceptedByDoc={acceptedByDoc as Record<string, Acceptance | undefined>}
        history={history}
        canAccept={canAccept}
        acceptAction={acceptDocument}
      />

      {canAccept && <SicReportDownload apiUrl={CORE_API_URL} />}
    </div>
  )
}
