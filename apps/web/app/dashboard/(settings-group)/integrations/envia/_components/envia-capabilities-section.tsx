'use client'

/**
 * Envia Capabilities Section — toggles granulares Fase 2 per-tenant.
 *
 * Movido desde `integrations-manager.tsx` (Sem 7 F2 restructura).
 * Vive en el tab "Capacidades" del panel /integrations/envia.
 *
 * Backend: F.3 capabilities_matrix + tabla `tenant_provider_capabilities`.
 * Cada capability gate un endpoint específico — el tenant activa solo lo que usa.
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  ShieldCheck, HelpCircle, CheckCircle2, AlertCircle, Loader2,
} from 'lucide-react'

const ENVIA_CAPABILITIES: Array<{
  key: string
  label: string
  help: string
}> = [
  {
    key: 'label_generation',
    label: 'Generación de etiquetas',
    help:
      'Permite generar etiquetas (PDF/ZPL) tras seleccionar tarifa. ' +
      'Necesario para imprimir y entregar al carrier.',
  },
  {
    key: 'tracking_polling',
    label: 'Tracking & polling',
    help:
      'Habilita consultar estado del envío y polling backup periódico. ' +
      'Usado por el cron que detecta entregas + actualiza el cliente.',
  },
  {
    key: 'pickup',
    label: 'Recolección (pickup)',
    help:
      'Permite agendar recolección domiciliaria del paquete con el carrier. ' +
      'No todos los carriers soportan pickup en todas las ciudades.',
  },
  {
    key: 'cancel',
    label: 'Cancelación',
    help:
      'Permite cancelar envíos antes de despacharse (refund según política ' +
      'del carrier). Útil cuando el cliente cancela la orden tras generar etiqueta.',
  },
]

type Props = {
  capabilities: Record<string, boolean>
  toggleAction: (fd: FormData) => Promise<{ ok: boolean; error?: string }>
}

export default function EnviaCapabilitiesSection({
  capabilities, toggleAction,
}: Props) {
  const router = useRouter()
  const [pending, setPending] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const handleToggle = async (key: string, current: boolean) => {
    setPending(key); setErrorMsg(null); setSuccessMsg(null)
    const fd = new FormData()
    fd.set('capability', key)
    fd.set('enabled', String(!current))
    const res = await toggleAction(fd)
    setPending(null)
    if (!res.ok) { setErrorMsg(res.error ?? 'Error'); return }
    const cap = ENVIA_CAPABILITIES.find(c => c.key === key)
    setSuccessMsg(`${cap?.label ?? key} ${!current ? 'activada' : 'desactivada'}.`)
    router.refresh()
  }

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-4 py-3.5 border-b border-border bg-muted/20 flex items-center gap-2">
        <ShieldCheck className="h-4 w-4 text-orange-400 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-sm flex items-center gap-1.5">
            Capabilities Fase 2
            <span
              className="cursor-help text-muted-foreground hover:text-foreground"
              title={
                'Cada capability es un "interruptor" que habilita o deshabilita ' +
                'una operación específica de Envía para tu tenant. Si la apagas, ' +
                'el endpoint correspondiente devolverá HTTP 503 cuando el bot u ' +
                'otro código intente usarlo. Útil si quieres limitar qué hace ' +
                'Envía (ej. cotizar pero no generar etiquetas todavía).'
              }
            >
              <HelpCircle className="h-4 w-4" />
            </span>
          </p>
          <p className="text-[11px] text-muted-foreground">
            Activa solo las operaciones que usas. Cada capability protege un endpoint específico.
          </p>
        </div>
      </div>
      <div className="px-4 py-3.5">
        <div className="mb-3 rounded-md border border-emerald-700/30 bg-emerald-700/5 p-3 text-xs text-emerald-900 space-y-1.5">
          <div className="font-semibold flex items-center gap-1">
            <HelpCircle className="h-3.5 w-3.5" />
            ¿Cómo funciona?
          </div>
          <p>
            <b>Hoy todas están activadas</b> (estado por defecto post-onboarding).
            Cada toggle representa un endpoint Envía. Si lo apagas, ese endpoint
            queda <b>bloqueado</b> a nivel API (HTTP 503) — útil si quieres,
            por ejemplo, permitir cotización pero NO permitir cancelar etiquetas
            ya generadas.
          </p>
          <p className="text-emerald-900/80">
            <b>Recomendación:</b> mantenlas todas en <b>ON</b> a menos que tengas
            una razón comercial específica para limitar (ej. tu account Envía no
            tiene saldo suficiente para imprimir etiquetas — desactivas
            <i> Generación de etiquetas</i> hasta recargar).
          </p>
        </div>
        {successMsg && (
          <div className="mb-3 rounded-md border border-emerald-700/40 bg-emerald-700/5 px-3 py-2 text-xs text-emerald-700">
            <CheckCircle2 className="inline h-3.5 w-3.5 mr-1" />
            {successMsg}
          </div>
        )}
        {errorMsg && (
          <div className="mb-3 rounded-md border border-rose-700/40 bg-rose-700/5 px-3 py-2 text-xs text-rose-700">
            <AlertCircle className="inline h-3.5 w-3.5 mr-1" />
            {errorMsg}
          </div>
        )}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {ENVIA_CAPABILITIES.map(cap => {
            const enabled = !!capabilities[cap.key]
            const isPending = pending === cap.key
            return (
              <div
                key={cap.key}
                className={`flex items-center gap-3 rounded-md border px-3 py-2 ${
                  enabled ? 'border-emerald-700/30 bg-emerald-700/5' : 'border-border bg-muted/10'
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium">{cap.label}</span>
                    <span
                      className="cursor-help text-emerald-700/70 hover:text-emerald-900"
                      title={cap.help}
                    >
                      <HelpCircle className="h-4 w-4" />
                    </span>
                  </div>
                  <span className="font-mono text-[10px] text-muted-foreground">{cap.key}</span>
                </div>
                <button
                  type="button"
                  disabled={pending !== null}
                  onClick={() => handleToggle(cap.key, enabled)}
                  title={enabled ? 'Desactivar' : 'Activar'}
                  className={`shrink-0 inline-flex items-center justify-center h-6 w-12 rounded-full transition text-[10px] font-semibold disabled:opacity-60 disabled:cursor-not-allowed ${
                    enabled
                      ? 'bg-emerald-600 text-white'
                      : 'bg-slate-300 text-slate-700'
                  }`}
                >
                  {isPending
                    ? <Loader2 className="h-3 w-3 animate-spin" />
                    : (enabled ? 'ON' : 'OFF')}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
