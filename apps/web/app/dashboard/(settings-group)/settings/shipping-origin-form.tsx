'use client'

import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Check, Loader2, MapPin } from 'lucide-react'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string; dane_code?: string
}
type StoreLocation = { name?: string; city?: string; state?: string; street?: string; phone?: string }

interface Props {
  initialData?:    ShippingOrigin | null
  action:          (formData: FormData) => Promise<{ ok: boolean; error?: string }>
  tenantName?:     string
  tenantPhone?:    string
  storeLocations?: StoreLocation[]
}

export default function ShippingOriginForm({ initialData, action, tenantName, tenantPhone, storeLocations }: Props) {
  const normalizeDaneCode = (raw?: string) => {
    const digits = String(raw ?? '').replace(/\D/g, '')
    return digits.slice(0, 5)
  }

  const initialDpto = DEPARTAMENTOS.find(d => d.nombre === initialData?.state)?.codigo ?? ''
  const initialDane = normalizeDaneCode(initialData?.dane_code ?? initialData?.postal_code)

  // Campos auto-rellenables desde una sede
  const [remitente, setRemitente] = useState(initialData?.name ?? '')
  const [street,    setStreet]    = useState(initialData?.street ?? '')
  // Celular: sede.phone → tenantPhone → initialData.phone (en ese orden de prioridad)
  const [phone,     setPhone]     = useState(initialData?.phone ?? tenantPhone ?? '')
  // Empresa siempre vinculada al nombre del negocio (read-only en el form)
  const empresa = tenantName ?? initialData?.company ?? ''

  // Selectores DANE
  const [codigoDpto,    setCodigoDpto]    = useState(initialDpto)
  const [city,          setCity]          = useState(initialData?.city ?? '')
  const [municipioCodigo, setMunicipioCodigo] = useState<string>(() => {
    const munis = initialDpto ? getMunicipiosByDpto(initialDpto) : []
    return munis.find(m => m.codigo === initialDane || m.nombre === initialData?.city)?.codigo ?? ''
  })

  const [saved,    setSaved]    = useState(false)
  const [loading,  setLoading]  = useState(false)
  const [selectedSede, setSelectedSede] = useState('')

  const municipios  = useMemo(() => getMunicipiosByDpto(codigoDpto), [codigoDpto])
  const nombreDpto  = DEPARTAMENTOS.find(d => d.codigo === codigoDpto)?.nombre ?? ''
  const daneCode    = municipioCodigo || (city ? initialDane : '')
  const sedesValidas = (storeLocations ?? []).filter(s => s.city || s.street || s.name)

  const handleSedeSelect = (idxStr: string) => {
    setSelectedSede(idxStr)
    const idx = parseInt(idxStr)
    if (isNaN(idx) || !sedesValidas[idx]) return
    const sede = sedesValidas[idx]

    if (sede.name)   setRemitente(sede.name)
    if (sede.street) setStreet(sede.street)
    // Celular: usa el de la sede si existe, cae al teléfono principal del tenant
    setPhone(sede.phone || tenantPhone || '')

    if (sede.state) {
      const dpto = DEPARTAMENTOS.find(d => d.nombre === sede.state)
      if (dpto) {
        setCodigoDpto(dpto.codigo)
        const munis = getMunicipiosByDpto(dpto.codigo)
        const muni  = munis.find(m => m.nombre === sede.city)
        setCity(muni?.nombre ?? sede.city ?? '')
        setMunicipioCodigo(muni?.codigo ?? '')
      }
    }
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setLoading(true)
    const result = await action(new FormData(e.currentTarget))
    setLoading(false)
    // F-doc: no mostrar "Guardado ✓" si la action falló (antes era incondicional).
    if (!result.ok) {
      window.alert(result.error || 'No se pudo guardar la dirección de despacho.')
      return
    }
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">

      {/* ── Selector de sede (solo si hay sedes configuradas) ── */}
      {sedesValidas.length > 0 && (
        <div className="space-y-1.5">
          <Label className="text-xs font-medium flex items-center gap-1.5">
            <MapPin className="h-3.5 w-3.5 text-primary" />
            Sede de despacho
          </Label>
          <select
            value={selectedSede}
            onChange={e => handleSedeSelect(e.target.value)}
            className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Seleccionar sede para auto-completar…</option>
            {sedesValidas.map((s, i) => (
              <option key={i} value={i}>{s.name || `Sede ${i + 1}`} — {s.city}</option>
            ))}
          </select>
          {selectedSede !== '' && (
            <p className="text-[10px] text-muted-foreground">
              Datos cargados desde la sede. Puedes editarlos si la dirección de despacho difiere.
            </p>
          )}
        </div>
      )}

      {/* ── Nombre del remitente + Empresa ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-name">Nombre del remitente</Label>
          <Input id="origin-name" name="origin_name"
            value={remitente}
            onChange={e => setRemitente(e.target.value)}
            placeholder="Juan Pérez" className="h-8 text-sm" />
          <p className="text-[10px] text-muted-foreground">Quién entrega el paquete al transportador</p>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium">
            Empresa <span className="text-muted-foreground font-normal text-[10px]">(aparece en la guía)</span>
          </Label>
          {/* Vinculado a "Nombre del negocio" — campo read-only */}
          <input type="hidden" name="origin_company" value={empresa} />
          <div className="h-8 rounded-md border border-input bg-muted/50 px-3 flex items-center text-sm text-muted-foreground">
            {empresa || <span className="italic text-muted-foreground/60">Sin nombre de negocio configurado</span>}
          </div>
          <p className="text-[10px] text-muted-foreground">
            Viene de <span className="font-medium text-foreground/70">Identidad del negocio</span> → Nombre del negocio
          </p>
        </div>
      </div>

      {/* ── Dirección ── */}
      <div className="space-y-1.5">
        <Label className="text-xs font-medium" htmlFor="origin-street">Dirección de la sede</Label>
        <Input id="origin-street" name="origin_street"
          value={street}
          onChange={e => setStreet(e.target.value)}
          placeholder="Calle 3 Sur # 70-84" className="h-8 text-sm" />
      </div>

      {/* ── Departamento + Municipio ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-state">Departamento</Label>
          <input type="hidden" name="origin_state" value={nombreDpto} />
          <select id="origin-state" value={codigoDpto}
            onChange={e => { setCodigoDpto(e.target.value); setCity(''); setMunicipioCodigo('') }}
            className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring">
            <option value="">Seleccionar…</option>
            {DEPARTAMENTOS.map(d => <option key={d.codigo} value={d.codigo}>{d.nombre}</option>)}
          </select>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-city">Municipio / Ciudad</Label>
          <input type="hidden" name="origin_city"        value={city} />
          <input type="hidden" name="origin_postal_code" value={daneCode} />
          <input type="hidden" name="origin_dane_code"   value={daneCode} />
          <select id="origin-city" value={city}
            onChange={e => {
              setCity(e.target.value)
              setMunicipioCodigo(municipios.find(m => m.nombre === e.target.value)?.codigo ?? '')
            }}
            disabled={!codigoDpto}
            className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed">
            <option value="">{codigoDpto ? 'Seleccionar…' : 'Primero selecciona departamento'}</option>
            {municipios.map(m => <option key={m.codigo} value={m.nombre}>{m.nombre}</option>)}
          </select>
        </div>
      </div>

      {/* ── DANE + País + Celular ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium">Código DANE</Label>
          <div className="h-8 rounded-md border border-input bg-muted/50 px-3 flex items-center text-sm text-muted-foreground">
            {daneCode || 'Se completa al elegir municipio'}
          </div>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium">País</Label>
          <input type="hidden" name="origin_country" value="Colombia" />
          <div className="h-8 rounded-md border border-input bg-muted/50 px-3 flex items-center text-sm text-muted-foreground">
            Colombia
          </div>
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-phone">Celular</Label>
          <div className="flex items-center gap-1">
            <span className="h-8 px-2.5 rounded-md border border-input bg-muted/50 text-xs text-muted-foreground flex items-center shrink-0">+57</span>
            <Input id="origin-phone" name="origin_phone" type="tel"
              value={phone}
              onChange={e => setPhone(e.target.value)}
              placeholder="3121234567" pattern="3[0-9]{9}" maxLength={10}
              className="h-8 text-sm" />
          </div>
          <p className="text-[10px] text-muted-foreground">10 dígitos, ej: 3121234567</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" disabled={loading}>
          {loading
            ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Guardando...</>
            : 'Guardar opciones de despacho'}
        </Button>
        {saved && (
          <span className="flex items-center gap-1 text-xs text-emerald-400">
            <Check className="h-3.5 w-3.5" /> Información guardada
          </span>
        )}
      </div>
    </form>
  )
}
