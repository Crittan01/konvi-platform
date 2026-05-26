'use client'

/**
 * Aveonline Carriers Matrix — Rev. 108.
 *
 * Permite al tenant elegir qué carriers de su cuenta Aveonline ofrecer
 * en cotización + activar COD per-carrier (matriz independiente: un
 * carrier puede estar enabled SIN cod, o enabled CON cod).
 *
 * Backend: `services/api/routers/integrations.py` Rev. 108
 *   GET    /api/v1/integrations/aveonline/carriers       → lista prefs
 *   PUT    /api/v1/integrations/aveonline/carriers       → bulk upsert
 *   POST   /api/v1/integrations/aveonline/carriers/seed  → discover desde API
 *   DELETE /api/v1/integrations/aveonline/carriers/{code} → reset uno
 *
 * Datos comerciales reales por carrier (tooltips):
 *   - Dossier §7.2 (Aveonline COD plazos + cobro devolución)
 *   - Dossier §3.10.2 (limites peso/dimensiones por carrier)
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Truck, Loader2, AlertCircle, CheckCircle2, RefreshCw, Info,
  ShieldCheck, Coins, Save,
} from 'lucide-react'

type CarrierPref = {
  carrier_code: string
  enabled: boolean
  display_label: string | null
  priority: number
  notes: string | null
  supports_cod: boolean
}

// Datos reales por carrier (verbatim dossier §7.2 + §3.10.2). Lookup
// case-insensitive — carrier_code llega lowercase con underscores.
type CarrierFacts = {
  cod: 'supported' | 'unsupported' | 'unknown'
  codLiquidation?: string
  codPayDay?: string
  codChargesReturn?: boolean
  weightMax?: string
  notes?: string
}

const CARRIER_FACTS: Record<string, CarrierFacts> = {
  tcc: {
    cod: 'supported',
    codLiquidation: '4–6 días hábiles',
    codPayDay: 'Martes y viernes',
    codChargesReturn: false,
    weightMax: '5 kg mensajería / 150 kg carga',
    notes: 'Asegurable hasta $3.511.000 COP en mensajería.',
  },
  tcc_sa: {
    cod: 'supported',
    codLiquidation: '4–6 días hábiles',
    codPayDay: 'Martes y viernes',
    codChargesReturn: false,
    weightMax: '5 kg mensajería / 150 kg carga',
    notes: 'Asegurable hasta $3.511.000 COP en mensajería.',
  },
  domina: {
    cod: 'supported',
    codLiquidation: '4–6 días hábiles',
    codPayDay: 'Martes y viernes',
    codChargesReturn: false,
  },
  servientrega: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPayDay: 'Viernes',
    codChargesReturn: false,
    weightMax: '2 kg documentos / ≥3 kg mercancías',
  },
  envia: {
    cod: 'supported',
    codLiquidation: '7–11 días (contrato 9–15)',
    codPayDay: 'Viernes',
    codChargesReturn: true,
    weightMax: '1–8 kg paqueteo / 9–200 kg carga',
    notes: '⚠️ Cobra flete devolución si paquete regresa.',
  },
  interrapidisimo: {
    cod: 'supported',
    codLiquidation: '7–11 días (contrato 13–19)',
    codPayDay: 'Viernes',
    codChargesReturn: false,
    weightMax: '5 kg expresa / 6–60 kg carga',
  },
  inter_rapidisimo: {
    cod: 'supported',
    codLiquidation: '7–11 días (contrato 13–19)',
    codPayDay: 'Viernes',
    codChargesReturn: false,
  },
  saferbo: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPayDay: 'Viernes',
    codChargesReturn: false,
    weightMax: '1 kg mensajería / 5–30 kg carga',
  },
  coordinadora: {
    cod: 'supported',
    codLiquidation: '5–11 días (contrato 5–14)',
    codPayDay: 'Variable',
    codChargesReturn: true,
    weightMax: '5 kg paquetes pequeños',
    notes: '⚠️ Cobra flete devolución. Asegurable hasta $200.000 base.',
  },
  coordinadora_mercantil: {
    cod: 'supported',
    codLiquidation: '5–11 días (contrato 5–14)',
    codPayDay: 'Variable',
    codChargesReturn: true,
    weightMax: '5 kg paquetes pequeños',
    notes: '⚠️ Cobra flete devolución. Asegurable hasta $200.000 base.',
  },
  moova: {
    cod: 'unsupported',
    notes: 'Mensajería urbana inmediata — no recauda.',
  },
  mensajeros_urbanos: {
    cod: 'unsupported',
    notes: 'Mensajería urbana — no recauda.',
  },
  deprisa: {
    cod: 'unknown',
    weightMax: '50 kg estándar / 0.5 kg mensajería',
    notes: 'Modalidad crédito predominante. Validar COD con contrato.',
  },
  '99minutos': {
    cod: 'unknown',
    notes: 'Mensajería same-day. Validar COD con contrato.',
  },
  noventa9minutos: {
    cod: 'unknown',
    notes: 'Mensajería same-day. Validar COD con contrato.',
  },
  go_envios: {
    cod: 'unknown',
    notes: 'Validar COD con contrato Aveonline.',
  },
}

function getFacts(code: string): CarrierFacts {
  const key = (code || '').toLowerCase().replace(/[\s-]/g, '_')
  return CARRIER_FACTS[key] || { cod: 'unknown' }
}

export default function AveonlineCarriersSection() {
  const [prefs, setPrefs] = useState<CarrierPref[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/carriers', {
        method: 'GET',
        credentials: 'include',
      })
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const data = (await resp.json()) as CarrierPref[]
      setPrefs(Array.isArray(data) ? data : [])
      setDirty(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error consultando carriers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const seedFromAveonline = async () => {
    if (!confirm(
      'Consultar tus carriers habilitados en Aveonline y agregarlos a esta lista? '
      + 'NO sobreescribe configuración existente (solo agrega nuevos).',
    )) return
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/carriers/seed', {
        method: 'POST',
        credentials: 'include',
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Error sincronizando')
      setSuccess(
        `${data.inserted ?? 0} carrier${(data.inserted ?? 0) === 1 ? '' : 's'} `
        + `nuevos · ${data.preserved ?? 0} existentes preservados.`,
      )
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error sincronizando con Aveonline')
    } finally {
      setBusy(false)
    }
  }

  const toggleField = (code: string, field: 'enabled' | 'supports_cod') => {
    setPrefs(prev => prev.map(p =>
      p.carrier_code === code ? { ...p, [field]: !p[field] } : p,
    ))
    setDirty(true)
  }

  const saveBulk = async () => {
    setBusy(true)
    setError(null)
    setSuccess(null)
    try {
      const resp = await fetch('/api/integrations/aveonline/carriers', {
        method: 'PUT',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: prefs.map(p => ({
            carrier_code: p.carrier_code,
            enabled: p.enabled,
            display_label: p.display_label,
            priority: p.priority,
            notes: p.notes,
            supports_cod: p.supports_cod,
          })),
        }),
      })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail || 'Error guardando')
      const errs = (data.errors as Array<unknown>) || []
      if (errs.length) {
        setError(`${errs.length} carrier${errs.length === 1 ? '' : 's'} con error al guardar`)
      } else {
        setSuccess('Preferencias guardadas.')
        setDirty(false)
      }
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Error guardando')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      {/* Header + actions */}
      <div className="rounded-lg border border-border bg-card p-5 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-foreground">
            <Truck className="h-5 w-5 text-muted-foreground" />
            <h3 className="font-semibold">Carriers habilitados</h3>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void seedFromAveonline()}
              disabled={busy || loading}
              className="text-xs flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 hover:bg-muted disabled:opacity-50"
              title="Consulta Aveonline para descubrir carriers de tu contrato"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${busy ? 'animate-spin' : ''}`} />
              Sincronizar
            </button>
            <button
              type="button"
              onClick={() => void saveBulk()}
              disabled={busy || loading || !dirty}
              className="text-xs flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <Save className="h-3.5 w-3.5" />
              Guardar cambios
            </button>
          </div>
        </div>

        <p className="text-sm text-muted-foreground">
          Elige qué transportadoras se ofrecen al cliente y cuáles aceptan
          pago contra entrega (COD). El cliente solo verá las que activas.
        </p>

        {/* Default-open banner */}
        {!loading && prefs.length === 0 && (
          <div className="flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <Info className="h-4 w-4 mt-0.5 shrink-0" />
            <span>
              Aún no has configurado preferencias. Por defecto se ofrecen
              <strong> todos </strong>los carriers que Aveonline devuelva en cotización.
              Haz click <strong>Sincronizar</strong> para descubrirlos y personalizar.
            </span>
          </div>
        )}

        {error && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {success && (
          <div className="flex items-start gap-2 rounded-md border border-green-700/50 bg-green-50 px-3 py-2 text-sm text-green-800">
            <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" />
            <span>{success}</span>
          </div>
        )}
      </div>

      {/* Matrix */}
      {loading ? (
        <div className="rounded-lg border border-border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
          <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" />
          Cargando carriers…
        </div>
      ) : prefs.length === 0 ? null : (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/40">
              <tr className="text-left text-xs text-muted-foreground">
                <th className="px-4 py-3 font-medium">Carrier</th>
                <th className="px-4 py-3 font-medium text-center">Ofrecer</th>
                <th className="px-4 py-3 font-medium text-center">Pago contraentrega</th>
                <th className="px-4 py-3 font-medium">Detalles</th>
              </tr>
            </thead>
            <tbody>
              {prefs.map(p => {
                const facts = getFacts(p.carrier_code)
                const label = p.display_label || p.carrier_code
                const codNotSupported = facts.cod === 'unsupported'
                return (
                  <tr key={p.carrier_code} className="border-t border-border">
                    <td className="px-4 py-3 align-top">
                      <div className="font-medium text-foreground">{label}</div>
                      <code className="text-[10px] font-mono text-muted-foreground">
                        {p.carrier_code}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-center align-top">
                      <label className="inline-flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          checked={p.enabled}
                          onChange={() => toggleField(p.carrier_code, 'enabled')}
                          className="h-4 w-4 rounded border-input"
                        />
                      </label>
                    </td>
                    <td className="px-4 py-3 text-center align-top">
                      <label
                        className={
                          'inline-flex items-center cursor-pointer'
                          + (codNotSupported ? ' opacity-40 cursor-not-allowed' : '')
                        }
                        title={
                          codNotSupported
                            ? 'Este carrier no soporta COD (mensajería urbana sin recaudo)'
                            : ''
                        }
                      >
                        <input
                          type="checkbox"
                          checked={p.supports_cod}
                          disabled={codNotSupported}
                          onChange={() => toggleField(p.carrier_code, 'supports_cod')}
                          className="h-4 w-4 rounded border-input"
                        />
                      </label>
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-muted-foreground space-y-1">
                      {facts.cod === 'supported' && (
                        <div className="flex flex-wrap gap-x-3 gap-y-1">
                          <span>
                            <Coins className="inline h-3 w-3 mr-0.5" />
                            COD: {facts.codLiquidation} · {facts.codPayDay}
                          </span>
                          {facts.codChargesReturn !== undefined && (
                            <span
                              className={
                                facts.codChargesReturn
                                  ? 'text-amber-700'
                                  : 'text-green-700'
                              }
                            >
                              Devolución: {facts.codChargesReturn ? 'cobra flete' : 'sin cargo extra'}
                            </span>
                          )}
                        </div>
                      )}
                      {facts.cod === 'unsupported' && (
                        <div className="flex items-center gap-1">
                          <AlertCircle className="h-3 w-3 text-amber-700" />
                          <span>COD: no aplica</span>
                        </div>
                      )}
                      {facts.cod === 'unknown' && (
                        <div className="text-muted-foreground/70 italic">
                          COD: validar con tu contrato Aveonline
                        </div>
                      )}
                      {facts.weightMax && (
                        <div>
                          <ShieldCheck className="inline h-3 w-3 mr-0.5" />
                          Peso máx: {facts.weightMax}
                        </div>
                      )}
                      {facts.notes && (
                        <div className="text-[11px]">{facts.notes}</div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Disclaimer fuente datos */}
      {prefs.length > 0 && (
        <p className="text-[11px] text-muted-foreground border-t border-border pt-3">
          Datos comerciales (COD, plazos, devoluciones) tomados del contrato
          oficial Aveonline + página comercial pública. Verifica con tu asesor
          logístico si tu cuenta tiene condiciones distintas.
        </p>
      )}
    </div>
  )
}
