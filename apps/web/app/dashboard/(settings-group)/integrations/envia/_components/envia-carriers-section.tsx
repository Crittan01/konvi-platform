'use client'

/**
 * Envia Carriers Section — preferencias per-tenant per-carrier.
 *
 * Movido desde `integrations-manager.tsx` (Sem 7 F2 restructura).
 * Vive en el tab "Carriers" del panel /integrations/envia.
 *
 * Backend: tabla `tenant_carriers` (provider=envia) + server actions
 * `upsertEnviaCarrier` y `resetEnviaCarrierPref` definidos en page.tsx.
 *
 * Comportamiento default-open: si tenant NO tiene NINGUNA fila, se ofrecen
 * TODOS los carriers globales (backward compat). La UI lo refleja con banner.
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import {
  Package, HelpCircle, ShieldCheck, CheckCircle2, AlertCircle, Loader2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'

export type EnviaCarrierPref = {
  carrier_code: string
  enabled: boolean
  display_label: string | null
  priority: number
  notes: string | null
}

const ENVIA_CARRIERS_CO: Array<{ code: string; label: string }> = [
  { code: 'servientrega',     label: 'Servientrega' },
  { code: 'coordinadora',     label: 'Coordinadora' },
  { code: 'interRapidisimo',  label: 'Inter Rapidísimo' },
  { code: 'envia',            label: 'Envía (carrier propio)' },
  { code: 'tcc',              label: 'TCC' },
  { code: 'deprisa',          label: 'Deprisa' },
  { code: 'mensajerosUrbanos', label: 'Mensajeros Urbanos' },
  { code: 'noventa9Minutos',  label: '99 Minutos' },
  { code: 'fedex',            label: 'FedEx' },
  { code: 'dhl',              label: 'DHL' },
]

type Props = {
  prefs: EnviaCarrierPref[]
  upsertAction: (fd: FormData) => Promise<{ ok: boolean; error?: string }>
  resetAction: (fd: FormData) => Promise<{ ok: boolean; error?: string }>
}

export default function EnviaCarriersSection({
  prefs, upsertAction, resetAction,
}: Props) {
  const router = useRouter()
  const [pending, setPending] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const prefByCode = new Map(prefs.map(p => [p.carrier_code.toLowerCase(), p]))
  const hasAnyPrefs = prefs.length > 0

  const handleToggle = async (code: string, current: EnviaCarrierPref | null) => {
    setPending(code); setErrorMsg(null); setSuccessMsg(null)
    const fd = new FormData()
    fd.set('carrier_code', code)
    const targetEnabled = current ? !current.enabled : true
    fd.set('enabled', String(targetEnabled))
    fd.set('priority', String(current?.priority ?? 100))
    if (current?.display_label) fd.set('display_label', current.display_label)
    if (current?.notes) fd.set('notes', current.notes)
    const res = await upsertAction(fd)
    setPending(null)
    if (!res.ok) { setErrorMsg(res.error ?? 'Error desconocido'); return }
    setSuccessMsg(`${code} ${targetEnabled ? 'activado' : 'desactivado'}.`)
    router.refresh()
  }

  const handleReset = async (code: string) => {
    setPending('reset:' + code); setErrorMsg(null); setSuccessMsg(null)
    const fd = new FormData()
    fd.set('carrier_code', code)
    const res = await resetAction(fd)
    setPending(null)
    if (!res.ok) { setErrorMsg(res.error ?? 'Error'); return }
    setSuccessMsg(`${code} restaurado a default.`)
    router.refresh()
  }

  return (
    <div className="rounded-xl border border-border bg-card overflow-hidden">
      <div className="px-4 py-3.5 border-b border-border bg-muted/20 flex items-center gap-2">
        <Package className="h-4 w-4 text-orange-400 shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold text-sm flex items-center gap-1.5">
            Preferencias de carriers
            <span
              className="cursor-help text-muted-foreground hover:text-foreground"
              title={
                'Cuando un cliente WhatsApp pide cotización de envío, el bot ' +
                'pregunta a Envía qué transportadoras pueden hacer el envío. ' +
                'Aquí TÚ controlas qué transportadoras se le ofrecen al ' +
                'cliente final. Sin configurar = todas las disponibles. ' +
                'Configurando = solo las que activas aquí.'
              }
            >
              <HelpCircle className="h-4 w-4" />
            </span>
          </p>
          <p className="text-[11px] text-muted-foreground">
            Selecciona qué carriers ofrecer en cotizaciones de tus clientes.
          </p>
        </div>
      </div>
      <div className="px-4 py-3.5">
        <div className="mb-3 rounded-md border border-emerald-700/30 bg-emerald-700/5 p-3 text-xs text-emerald-900 space-y-2">
          <div className="font-semibold flex items-center gap-1">
            <HelpCircle className="h-3.5 w-3.5" />
            ¿Cómo funciona?
          </div>
          <div className="space-y-1.5">
            <p className="font-medium">Selección de carriers</p>
            <p>
              El bot de WhatsApp cotiza envíos con Envía cada vez que un cliente
              confirma su pedido. Aquí decides <b>qué transportadoras ofrecer</b>:
            </p>
            <ul className="list-disc pl-4 space-y-0.5">
              <li>
                <b>Modo abierto</b> (sin configurar): el bot ofrece TODAS las
                transportadoras que Envía exponga (FedEx, DHL, Servientrega, etc.).
              </li>
              <li>
                <b>Modo configurado</b> (1+ carriers activos): el bot ofrece
                SOLO los que tengan toggle ON. Los que están en OFF nunca
                aparecen al cliente.
              </li>
            </ul>
            <p className="text-emerald-900/80">
              <b>Tip:</b> activa solo los carriers con los que tienes contrato
              real con Envía — los demás causarán errores en cotización si los
              dejas abiertos.
            </p>
          </div>
          <div className="space-y-1.5 pt-1.5 border-t border-emerald-700/20">
            <p className="font-medium flex items-center gap-1">
              <ShieldCheck className="h-3.5 w-3.5" />
              Seguro de envíos
            </p>
            <p>
              El <b>valor declarado</b> (subtotal del pedido) se envía siempre
              con cada cotización. Cada transportadora aplica su política de
              seguro automáticamente — <b>no es decisión por carrier</b>:
            </p>
            <ul className="list-disc pl-4 space-y-0.5">
              <li>
                <b>Coordinadora</b>: cobra prima automática proporcional al valor
                declarado (validado prod 2026-05-07).
              </li>
              <li>
                <b>FedEx, DHL, Servientrega, TCC</b>: aceptan el valor declarado;
                su seguro queda regulado por su contrato con Envía.
              </li>
              <li>
                <b>Envía (carrier propio)</b>: además del valor declarado, recibe
                el additional service <code className="text-[10px]">envia_insurance</code>
                {' '}(id=125 en catálogo oficial Envia).
              </li>
            </ul>
          </div>
        </div>
        {!hasAnyPrefs && (
          <div className="mb-3 rounded-md border border-amber-700/40 bg-amber-700/5 px-3 py-2 text-xs text-amber-900">
            <ShieldCheck className="inline h-3.5 w-3.5 mr-1" />
            <b>Modo abierto.</b> Aún no has configurado preferencias —
            el bot ofrece <b>todos</b> los carriers disponibles en Envia.
            Activa al menos uno abajo para empezar a filtrar.
          </div>
        )}
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
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="min-w-full text-xs">
            <thead className="bg-muted/30">
              <tr className="text-left">
                <th className="px-3 py-2 font-medium">Carrier</th>
                <th className="px-3 py-2 font-medium text-center">Activo</th>
                <th className="px-3 py-2 font-medium text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {ENVIA_CARRIERS_CO.map(c => {
                const pref = prefByCode.get(c.code.toLowerCase()) ?? null
                const enabled = pref ? pref.enabled : !hasAnyPrefs
                const isPending = pending === c.code
                return (
                  <tr key={c.code} className={enabled ? '' : 'opacity-60'}>
                    <td className="px-3 py-2">
                      <div className="font-medium">{c.label}</div>
                      <div className="font-mono text-[10px] text-muted-foreground">{c.code}</div>
                      {pref?.notes && (
                        <div className="mt-0.5 text-[10px] text-muted-foreground italic">{pref.notes}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <button
                        type="button"
                        disabled={pending !== null}
                        onClick={() => handleToggle(c.code, pref)}
                        title={enabled ? 'Desactivar' : 'Activar'}
                        className={`inline-flex items-center justify-center h-6 w-12 rounded-full transition disabled:opacity-60 disabled:cursor-not-allowed text-[11px] font-semibold ${
                          enabled
                            ? 'bg-emerald-600 text-white'
                            : 'bg-slate-300 text-slate-700'
                        }`}
                      >
                        {isPending
                          ? <Loader2 className="h-3 w-3 animate-spin" />
                          : (enabled ? 'ON' : 'OFF')}
                      </button>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {pref && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={pending !== null}
                          onClick={() => handleReset(c.code)}
                          className="h-6 text-[10px] gap-1"
                          title="Restaurar a default (eliminar preferencia explícita)"
                        >
                          {pending === 'reset:' + c.code && (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          )}
                          Reset
                        </Button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[10px] text-muted-foreground">
          Los carriers desactivados NO aparecen en cotizaciones a clientes.
          &quot;Reset&quot; elimina la preferencia explícita y vuelve a comportamiento default
          (modo abierto si no tienes ninguna fila configurada).
        </p>
      </div>
    </div>
  )
}
