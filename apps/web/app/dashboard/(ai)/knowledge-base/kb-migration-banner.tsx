'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/utils/supabase/client'
import { AlertCircle, X } from 'lucide-react'

const ALERT_KEY = 'kb-rev68-categories-migrated'

/**
 * Rev. 69 — Banner one-time que avisa de la migración KB rev. 68
 * (general → faq + nuevas categorías Envíos / Pagos).
 *
 * Persiste el dismissal en `user_dismissed_alerts` (RLS por user+tenant).
 * Solo visible para owners/managers que pueden recategorizar.
 */
export function KbMigrationBanner({ canWrite }: { canWrite: boolean }) {
  const [visible, setVisible] = useState(false)
  const [dismissing, setDismissing] = useState(false)

  useEffect(() => {
    if (!canWrite) return
    let cancelled = false
    const supabase = createClient()
    ;(async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) return
        const { data } = await supabase
          .from('user_dismissed_alerts')
          .select('alert_key')
          .eq('alert_key', ALERT_KEY)
          .limit(1)
          .maybeSingle()
        if (!cancelled && !data) setVisible(true)
      } catch {
        // RLS / red — no bloquear UI
      }
    })()
    return () => { cancelled = true }
  }, [canWrite])

  async function handleDismiss() {
    if (dismissing) return
    setDismissing(true)
    try {
      const supabase = createClient()
      const { data: { user } } = await supabase.auth.getUser()
      const tenantId = (user?.app_metadata as { tenant_id?: string } | undefined)?.tenant_id
      if (user?.id && tenantId) {
        await supabase.from('user_dismissed_alerts').upsert(
          { user_id: user.id, tenant_id: tenantId, alert_key: ALERT_KEY },
          { onConflict: 'user_id,tenant_id,alert_key' },
        )
      }
    } catch {
      // best effort
    } finally {
      setVisible(false)
    }
  }

  if (!visible) return null

  return (
    <div className="rounded-xl border border-warning-border bg-warning-bg px-4 py-3 flex items-start gap-3">
      <AlertCircle className="h-4 w-4 text-warning-fg shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0 text-sm">
        <p className="font-semibold text-warning-fg mb-0.5">Categorías KB actualizadas (rev. 68)</p>
        <p className="text-xs text-foreground/80">
          Eliminamos &ldquo;General&rdquo; y agregamos <strong>Envíos</strong> y <strong>Pagos</strong>.
          Los documentos que estaban en General ahora aparecen en <strong>FAQ</strong>.
          Revisa abajo si quieres recategorizar alguno a Envíos, Pagos, Productos, etc.
        </p>
      </div>
      <button
        onClick={handleDismiss}
        disabled={dismissing}
        className="text-warning-fg hover:text-warning-fg shrink-0 p-1 rounded hover:bg-warning-bg disabled:opacity-50"
        title="Entendido"
        aria-label="Descartar aviso de categorías actualizadas"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  )
}
