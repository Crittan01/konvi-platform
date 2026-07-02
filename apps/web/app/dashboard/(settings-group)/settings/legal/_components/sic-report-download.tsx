'use client'

import { useState } from 'react'
import { FileDown, Loader2, ShieldCheck } from 'lucide-react'
import { createClient } from '@/utils/supabase/client'

// F6 — descarga del reporte de cumplimiento para la SIC (Superintendencia de
// Industria y Comercio). El endpoint GET /api/v1/sic-report (owner/manager) ya
// existía y registra el acceso en consent_audit_log; faltaba el disparador en UI.
// Periodo default: últimos 90 días (from/to opcionales). Formato: CSV o JSON.

export function SicReportDownload({ apiUrl }: { apiUrl: string }) {
  const [fromDate, setFromDate] = useState('')
  const [toDate, setToDate] = useState('')
  const [busy, setBusy] = useState<'csv' | 'json' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const download = async (fmt: 'csv' | 'json') => {
    setBusy(fmt)
    setError(null)
    try {
      const supabase = createClient()
      const { data: { session } } = await supabase.auth.getSession()
      if (!session?.access_token) { setError('Sesión expirada. Vuelve a entrar.'); return }
      const params = new URLSearchParams({ format: fmt })
      if (fromDate) params.set('from_date', fromDate)
      if (toDate) params.set('to_date', toDate)
      const res = await fetch(`${apiUrl}/api/v1/sic-report?${params.toString()}`, {
        headers: { 'Authorization': `Bearer ${session.access_token}` },
      })
      if (!res.ok) { setError((await res.text()) || `Error ${res.status}`); return }
      const blob = await res.blob()
      const stamp = new Date().toISOString().slice(0, 10)
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = `reporte-sic-${stamp}.${fmt}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(a.href)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al descargar')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <div className="flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-primary" />
        <p className="text-sm font-semibold text-foreground">Reporte de cumplimiento (SIC)</p>
      </div>
      <p className="text-xs text-muted-foreground">
        Genera el reporte agregado de eventos de consentimiento y accesos a datos personales,
        listo para presentar a la Superintendencia de Industria y Comercio ante un requerimiento.
        Periodo por defecto: últimos 90 días. La descarga queda registrada de forma auditable.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase">Desde</label>
          <input
            type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
            className="h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground"
          />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] font-semibold text-muted-foreground uppercase">Hasta</label>
          <input
            type="date" value={toDate} onChange={e => setToDate(e.target.value)}
            className="h-8 rounded-md border border-input bg-background text-sm px-2 text-foreground"
          />
        </div>
        <button
          onClick={() => download('csv')} disabled={busy !== null}
          className="inline-flex items-center gap-1.5 h-8 px-4 text-xs font-medium rounded-lg bg-foreground text-background hover:bg-foreground/80 disabled:opacity-50"
        >
          {busy === 'csv' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
          Descargar CSV
        </button>
        <button
          onClick={() => download('json')} disabled={busy !== null}
          className="inline-flex items-center gap-1.5 h-8 px-4 text-xs font-medium rounded-lg border border-border text-foreground hover:bg-muted/40 disabled:opacity-50"
        >
          {busy === 'json' ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileDown className="h-4 w-4" />}
          JSON
        </button>
      </div>
      {error && <p className="text-xs text-red-700 bg-red-700/10 border border-red-700/30 rounded px-2 py-1">{error}</p>}
    </div>
  )
}
