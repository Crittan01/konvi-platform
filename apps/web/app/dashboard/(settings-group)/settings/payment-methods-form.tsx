'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Check, Loader2, CreditCard, Wallet, AlertTriangle } from 'lucide-react'

type Method = 'cod' | 'online_wompi'

type MethodConfig = {
  method: Method
  enabled: boolean
  display_label?: string | null
  notes?: string | null
}

interface Props {
  initialMethods: MethodConfig[]
  action: (formData: FormData) => Promise<{ ok: boolean; error?: string }>
}

const METHOD_META: Record<Method, {
  Icon: typeof CreditCard
  title: string
  description: string
  consequence: string
}> = {
  online_wompi: {
    Icon: CreditCard,
    title: 'Pago online (Wompi)',
    description: 'Link de pago tarjeta crédito/débito, PSE, Nequi, transferencia Bancolombia.',
    consequence: 'Si deshabilitas, el bot NO ofrecerá link de pago online. Solo manejarás contraentrega.',
  },
  cod: {
    Icon: Wallet,
    title: 'Contraentrega (COD vía Aveonline)',
    description: 'El courier recauda el dinero al entregar. Liquidación según carrier (4–11 días hábiles).',
    consequence: 'Si deshabilitas, el bot rechazará pedidos contraentrega y ofrecerá solo pago online.',
  },
}

export default function PaymentMethodsForm({ initialMethods, action }: Props) {
  // Estado local controlado por método.
  const initialState: Record<Method, boolean> = {
    cod: initialMethods.find(m => m.method === 'cod')?.enabled ?? true,
    online_wompi: initialMethods.find(m => m.method === 'online_wompi')?.enabled ?? true,
  }

  const seedText = (m: Method, field: 'display_label' | 'notes') =>
    initialMethods.find(x => x.method === m)?.[field] ?? ''

  const [methods, setMethods] = useState<Record<Method, boolean>>(initialState)
  const [labels, setLabels] = useState<Record<Method, string>>({
    cod: seedText('cod', 'display_label'),
    online_wompi: seedText('online_wompi', 'display_label'),
  })
  const [notes, setNotes] = useState<Record<Method, string>>({
    cod: seedText('cod', 'notes'),
    online_wompi: seedText('online_wompi', 'notes'),
  })
  const [loading, setLoading] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const enabledCount = Object.values(methods).filter(Boolean).length
  const noneEnabled = enabledCount === 0

  const toggle = (m: Method) => {
    setMethods(prev => ({ ...prev, [m]: !prev[m] }))
    setSaved(false)
    setError(null)
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    const fd = new FormData()
    fd.set('cod_enabled', methods.cod ? '1' : '0')
    fd.set('online_wompi_enabled', methods.online_wompi ? '1' : '0')
    fd.set('cod_display_label', labels.cod)
    fd.set('cod_notes', notes.cod)
    fd.set('online_wompi_display_label', labels.online_wompi)
    fd.set('online_wompi_notes', notes.online_wompi)
    const result = await action(fd)
    setLoading(false)
    if (result.ok) {
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } else {
      setError(result.error ?? 'Error al guardar')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {(['online_wompi', 'cod'] as Method[]).map(m => {
        const meta = METHOD_META[m]
        const Icon = meta.Icon
        const enabled = methods[m]
        return (
          <div
            key={m}
            className={[
              'rounded-lg border p-4 transition-colors',
              enabled
                ? 'border-emerald-700/40 bg-emerald-700/5'
                : 'border-border bg-card opacity-80',
            ].join(' ')}
          >
            <div className="flex items-start gap-3">
              <Icon className={[
                'h-5 w-5 mt-0.5 shrink-0',
                enabled ? 'text-emerald-700' : 'text-muted-foreground',
              ].join(' ')} />

              <div className="flex-1 space-y-1.5">
                <div className="flex items-center justify-between gap-3">
                  <Label className="text-sm font-medium">{meta.title}</Label>
                  <label className="inline-flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={() => toggle(m)}
                      className="h-4 w-4 cursor-pointer"
                    />
                    <span className="text-xs text-muted-foreground">
                      {enabled ? 'Habilitado' : 'Deshabilitado'}
                    </span>
                  </label>
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {meta.description}
                </p>
                {!enabled && (
                  <p className="text-[11px] text-amber-700/90 leading-relaxed mt-2 flex items-start gap-1.5">
                    <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                    <span>{meta.consequence}</span>
                  </p>
                )}

                {/* display_label / notes — el bot los usa al presentar este método al cliente */}
                {enabled && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                    <div className="space-y-1">
                      <Label className="text-[11px] text-muted-foreground" htmlFor={`${m}_label`}>
                        Nombre para el cliente <span className="text-muted-foreground/60">(opcional)</span>
                      </Label>
                      <input
                        id={`${m}_label`}
                        type="text"
                        value={labels[m]}
                        onChange={e => { setLabels(prev => ({ ...prev, [m]: e.target.value })); setSaved(false) }}
                        maxLength={60}
                        placeholder={meta.title}
                        className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
                      />
                      <p className="text-[10px] text-muted-foreground/70">Cómo nombra el bot este método al cliente.</p>
                    </div>
                    <div className="space-y-1">
                      <Label className="text-[11px] text-muted-foreground" htmlFor={`${m}_notes`}>
                        Nota / aclaración <span className="text-muted-foreground/60">(opcional)</span>
                      </Label>
                      <input
                        id={`${m}_notes`}
                        type="text"
                        value={notes[m]}
                        onChange={e => { setNotes(prev => ({ ...prev, [m]: e.target.value })); setSaved(false) }}
                        maxLength={240}
                        placeholder="Ej: recargo del 3% · liquidación a 5 días"
                        className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-ring"
                      />
                      <p className="text-[10px] text-muted-foreground/70">El bot puede mencionarla al ofrecer el método.</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })}

      {noneEnabled && (
        <div className="rounded-lg border border-red-700/40 bg-red-700/5 p-3 flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 text-red-700 mt-0.5 shrink-0" />
          <div className="text-xs text-red-700/90 leading-relaxed">
            <strong>Configuración inválida:</strong> NINGÚN método de pago habilitado.
            El bot escalará a humano todas las compras. Habilita al menos uno.
          </div>
        </div>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}

      <div className="flex items-center gap-3 pt-1">
        <Button type="submit" size="sm" disabled={loading || noneEnabled}>
          {loading
            ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Guardando...</>
            : 'Guardar configuración'}
        </Button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-emerald-700">
            <Check className="h-3.5 w-3.5" /> Métodos actualizados
          </span>
        )}
      </div>
    </form>
  )
}
