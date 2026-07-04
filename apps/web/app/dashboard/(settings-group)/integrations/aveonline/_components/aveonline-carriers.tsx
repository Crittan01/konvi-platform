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
  ShieldCheck, Coins, Save, ExternalLink,
} from 'lucide-react'
import { useConfirm } from '@/components/ui/confirm-dialog'

type CarrierPref = {
  carrier_code: string
  enabled: boolean
  display_label: string | null
  priority: number
  notes: string | null
  supports_cod: boolean
}

// Datos por carrier — solo afirma lo VERBATIM de fuentes oficiales.
// Fuentes con cita verificada:
//   [A] aveonline.co/servicios-pago-contraentrega (validado 2026-05-26)
//   [C] coordinadora.com/envios/tarifas-e-informacion-general (validado 2026-05-26)
//   [D] dossier interno docs/research/aveonline-dossier.md §3.10.2 (peso/dim)
// Lo que NO está en fuente pública verificable → cod='unknown' o weightMax omitido.
// El tenant verifica con su asesor logístico (campo `officialSite` para verificar).
type CarrierFacts = {
  cod: 'supported' | 'unknown'  // ❌ 'unsupported' removido — sin fuente pública
  codLiquidation?: string       // [A] verbatim
  codPaySchedule?: string       // [A] verbatim
  weightMax?: string            // [C][D] solo donde fuente oficial publica
  declaredValueMax?: string     // [C] solo Coordinadora documenta
  officialSite?: string         // URL para que tenant verifique con asesor
  notes?: string                // limitaciones honestas
}

// Mapeo CODE_CANONICAL_LOWER → facts. Lookup se hace case-insensitive
// + spaces→underscores en getFacts().
const CARRIER_FACTS: Record<string, CarrierFacts> = {
  // ─── COD confirmado por Aveonline COD page oficial ─────────────────────────
  tcc: {
    cod: 'supported',
    codLiquidation: '4–6 días hábiles',
    codPaySchedule: 'Martes (corte miércoles anterior) y viernes',
    weightMax: '5 kg mensajería',
    officialSite: 'https://www.tcc.com.co/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  tcc_sa: {
    cod: 'supported',
    codLiquidation: '4–6 días hábiles',
    codPaySchedule: 'Martes (corte miércoles anterior) y viernes',
    weightMax: '5 kg mensajería',
    officialSite: 'https://www.tcc.com.co/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  domina: {
    cod: 'supported',
    codLiquidation: '4–6 días hábiles',
    codPaySchedule: 'Martes y viernes',
    officialSite: 'https://www.dominapack.com/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  servientrega: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPaySchedule: 'Viernes',
    officialSite: 'https://www.servientrega.com/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  envia: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPaySchedule: 'Viernes',
    officialSite: 'https://www.envia.co/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  interrapidisimo: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPaySchedule: 'Viernes',
    officialSite: 'https://www.interrapidisimo.com/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  inter_rapidisimo: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPaySchedule: 'Viernes',
    officialSite: 'https://www.interrapidisimo.com/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  saferbo: {
    cod: 'supported',
    codLiquidation: '7–11 días hábiles',
    codPaySchedule: 'Viernes',
    officialSite: 'https://www.thesaferbo.com/',
    notes: 'Fuente: aveonline.co/servicios-pago-contraentrega.',
  },
  coordinadora: {
    cod: 'supported',
    codLiquidation: '5–11 días hábiles',
    codPaySchedule: '3 veces/mes — días 15, 25 y 5 (cortes 1–10, 11–20, 21–31)',
    weightMax: '5 kg mensajería · aristas máx 50 cm (1–2 kg)',
    declaredValueMax: '$200.000 COP en documentos',
    officialSite: 'https://www.coordinadora.com/envios/tarifas-e-informacion-general/',
    notes: 'Fuente: aveonline.co + coordinadora.com (validado oficial).',
  },
  coordinadora_mercantil: {
    cod: 'supported',
    codLiquidation: '5–11 días hábiles',
    codPaySchedule: '3 veces/mes — días 15, 25 y 5 (cortes 1–10, 11–20, 21–31)',
    weightMax: '5 kg mensajería · aristas máx 50 cm (1–2 kg)',
    declaredValueMax: '$200.000 COP en documentos',
    officialSite: 'https://www.coordinadora.com/',
    notes: 'Fuente: aveonline.co + coordinadora.com (validado oficial).',
  },
  // ─── COD NO documentado en Aveonline COD page oficial ──────────────────────
  // No afirmamos NI niegamos — el tenant debe confirmar con su contrato.
  '99minutos': {
    cod: 'unknown',
    officialSite: 'https://99minutos.com/co/',
    notes: 'No aparece en página COD oficial Aveonline. Validar con asesor logístico si tu contrato incluye recaudo en este carrier.',
  },
  noventa9minutos: {
    cod: 'unknown',
    officialSite: 'https://99minutos.com/co/',
    notes: 'No aparece en página COD oficial Aveonline. Validar con asesor logístico.',
  },
  go_envios: {
    cod: 'unknown',
    notes: 'No aparece en página COD oficial Aveonline. Validar con asesor logístico.',
  },
  moova: {
    cod: 'unknown',
    officialSite: 'https://moova.io/',
    notes: 'Mensajería same-day urbana. No aparece en página COD oficial Aveonline. Validar con asesor.',
  },
  mensajeros_urbanos: {
    cod: 'unknown',
    officialSite: 'https://mensajerosurbanos.com/',
    notes: 'Mensajería urbana same-day. No aparece en página COD oficial Aveonline. Validar con asesor.',
  },
  deprisa: {
    cod: 'unknown',
    officialSite: 'https://www.deprisa.com/',
    notes: 'No aparece en página COD oficial Aveonline. Modalidad crédito predominante. Validar con asesor logístico.',
  },
}

function getFacts(code: string): CarrierFacts {
  const key = (code || '').toLowerCase().replace(/[\s-]/g, '_')
  return CARRIER_FACTS[key] || {
    cod: 'unknown',
    notes: 'Carrier no documentado en fuentes públicas Aveonline. Validar con asesor logístico antes de activar COD.',
  }
}

export default function AveonlineCarriersSection() {
  const confirmar = useConfirm()
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
    if (!(await confirmar({
      title: '¿Sincronizar carriers desde Aveonline?',
      description: 'Se consultarán los carriers habilitados en tu cuenta Aveonline y se agregarán a esta lista. No se sobreescribe la configuración existente: solo se agregan los nuevos.',
      confirmLabel: 'Sincronizar',
    }))) return
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
          <div className="flex items-start gap-2 rounded-md border border-amber-700 bg-amber-50 px-3 py-2 text-sm text-amber-900">
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
                const codUnknown = facts.cod === 'unknown'
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
                        className="inline-flex items-center cursor-pointer"
                        title={
                          codUnknown
                            ? 'No documentado en Aveonline COD page oficial. Verifica con tu asesor antes de activar.'
                            : ''
                        }
                      >
                        <input
                          type="checkbox"
                          checked={p.supports_cod}
                          onChange={() => toggleField(p.carrier_code, 'supports_cod')}
                          className={`h-4 w-4 rounded border-input ${codUnknown ? 'opacity-70' : ''}`}
                        />
                      </label>
                    </td>
                    <td className="px-4 py-3 align-top text-xs text-muted-foreground space-y-1">
                      {facts.cod === 'supported' && (
                        <div className="space-y-0.5">
                          <div>
                            <Coins className="inline h-3 w-3 mr-0.5" />
                            <strong>COD:</strong> liquidación {facts.codLiquidation}
                          </div>
                          {facts.codPaySchedule && (
                            <div className="ml-4">
                              <span className="text-muted-foreground/70">Pago: </span>
                              {facts.codPaySchedule}
                            </div>
                          )}
                        </div>
                      )}
                      {facts.cod === 'unknown' && (
                        <div className="text-amber-700 italic">
                          <AlertCircle className="inline h-3 w-3 mr-0.5" />
                          COD: <strong>no documentado oficialmente</strong> — verificar con asesor logístico
                        </div>
                      )}
                      {facts.weightMax && (
                        <div>
                          <ShieldCheck className="inline h-3 w-3 mr-0.5" />
                          Peso máx: {facts.weightMax}
                        </div>
                      )}
                      {facts.declaredValueMax && (
                        <div className="text-muted-foreground/80">
                          Valor declarado máx: {facts.declaredValueMax}
                        </div>
                      )}
                      {facts.officialSite && (
                        <div>
                          <a
                            href={facts.officialSite}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-0.5 underline text-muted-foreground hover:text-foreground"
                          >
                            Sitio oficial <ExternalLink className="h-3 w-3" />
                          </a>
                        </div>
                      )}
                      {facts.notes && (
                        <div className="text-[11px] text-muted-foreground/70">{facts.notes}</div>
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
