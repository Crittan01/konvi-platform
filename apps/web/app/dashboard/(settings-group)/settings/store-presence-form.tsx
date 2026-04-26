'use client'

import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Check, Loader2, Plus, Trash2 } from 'lucide-react'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

type StoreType = 'fisica' | 'virtual' | 'fisica_virtual'
type Location = { name: string; city: string; state: string; street: string; phone?: string; email?: string }
type SocialLinks = { instagram?: string; facebook?: string; tiktok?: string; youtube?: string; website?: string }

interface Props {
  initialStoreType:   StoreType
  initialLocations:   Location[]
  initialSocialLinks: SocialLinks
  action:             (formData: FormData) => Promise<void>
}

const STORE_TYPE_OPTIONS = [
  { value: 'fisica'         as const, label: 'Solo física',      desc: 'Punto(s) de venta físico(s)' },
  { value: 'virtual'        as const, label: 'Solo virtual',     desc: 'Operan 100% en línea' },
  { value: 'fisica_virtual' as const, label: 'Física y virtual', desc: 'Ambas modalidades' },
]

const SOCIAL_KEYS: Array<{ key: keyof SocialLinks; placeholder: string }> = [
  { key: 'instagram', placeholder: '@minegocio o URL completa' },
  { key: 'facebook',  placeholder: 'URL de la página' },
  { key: 'tiktok',    placeholder: '@minegocio o URL completa' },
  { key: 'youtube',   placeholder: 'URL del canal' },
  { key: 'website',   placeholder: 'https://minegocio.com' },
]

const EMPTY_LOC: Location = { name: '', city: '', state: '', street: '', phone: undefined, email: undefined }

function resolveDptoCode(stateName?: string): string {
  return DEPARTAMENTOS.find(d => d.nombre === stateName)?.codigo ?? ''
}

// ── Fila de sede: selectores DANE en cascada ──────────────────────────────────

function SedeRow({
  loc, index, isOnly, onChange, onRemove,
}: {
  loc: Location
  index: number
  isOnly: boolean
  onChange: (field: keyof Location, val: string) => void
  onRemove: () => void
}) {
  const [dptoCodigo, setDptoCodigo] = useState<string>(() => resolveDptoCode(loc.state))
  const municipios = useMemo(() => getMunicipiosByDpto(dptoCodigo), [dptoCodigo])

  const handleDpto = (codigo: string) => {
    setDptoCodigo(codigo)
    onChange('state', DEPARTAMENTOS.find(d => d.codigo === codigo)?.nombre ?? '')
    onChange('city', '')
  }

  return (
    <div className="rounded-lg border border-border p-3 space-y-2.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wide">
          {index === 0 ? 'Sede principal' : `Sede ${index + 1}`}
        </span>
        {!isOnly && (
          <button type="button" onClick={onRemove}
            className="text-muted-foreground hover:text-destructive transition-colors">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">

        {/* Nombre */}
        <div className="space-y-1 sm:col-span-2">
          <Label className="text-[10px] text-muted-foreground">Nombre de la sede</Label>
          <Input value={loc.name} onChange={e => onChange('name', e.target.value)}
            placeholder={index === 0 ? 'Sede Principal' : 'Sede Norte'} className="h-8 text-xs" />
        </div>

        {/* Departamento */}
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">Departamento</Label>
          <select value={dptoCodigo} onChange={e => handleDpto(e.target.value)}
            className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-ring">
            <option value="">Seleccionar…</option>
            {DEPARTAMENTOS.map(d => <option key={d.codigo} value={d.codigo}>{d.nombre}</option>)}
          </select>
        </div>

        {/* Municipio — dependiente del departamento */}
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">Municipio / Ciudad</Label>
          <select value={loc.city} onChange={e => onChange('city', e.target.value)}
            disabled={!dptoCodigo}
            className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-xs focus:outline-none focus:ring-2 focus:ring-ring disabled:opacity-50 disabled:cursor-not-allowed">
            <option value="">{dptoCodigo ? 'Seleccionar…' : 'Primero elige departamento'}</option>
            {municipios.map(m => <option key={m.codigo} value={m.nombre}>{m.nombre}</option>)}
          </select>
        </div>

        {/* Dirección */}
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">Dirección</Label>
          <Input value={loc.street} onChange={e => onChange('street', e.target.value)}
            placeholder="Calle 10 # 5-20, Local 3" className="h-8 text-xs" />
        </div>

        {/* Celular de la sede (opcional) */}
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">
            Celular <span className="text-muted-foreground/60">(opcional)</span>
          </Label>
          <Input
            value={loc.phone ?? ''}
            onChange={e => onChange('phone', e.target.value)}
            placeholder="3001234567"
            pattern="[0-9]{10}"
            maxLength={10}
            inputMode="numeric"
            className="h-8 text-xs"
          />
        </div>

        {/* Email de la sede (opcional) */}
        <div className="space-y-1">
          <Label className="text-[10px] text-muted-foreground">
            Email <span className="text-muted-foreground/60">(opcional)</span>
          </Label>
          <Input
            type="email"
            value={loc.email ?? ''}
            onChange={e => onChange('email', e.target.value)}
            placeholder="sede@minegocio.com"
            className="h-8 text-xs"
          />
        </div>

      </div>
    </div>
  )
}

// ── Componente principal ──────────────────────────────────────────────────────

export default function StorePresenceForm({ initialStoreType, initialLocations, initialSocialLinks, action }: Props) {
  const [storeType, setStoreType] = useState<StoreType>(initialStoreType ?? 'fisica')
  const [locs, setLocs] = useState<Location[]>(
    initialLocations && initialLocations.length > 0 ? initialLocations : [{ ...EMPTY_LOC }]
  )
  const [saved,        setSaved]        = useState(false)
  const [loading,      setLoading]      = useState(false)
  const [validationErr, setValidationErr] = useState<string | null>(null)

  const showFisica  = storeType === 'fisica' || storeType === 'fisica_virtual'
  const showVirtual = storeType === 'virtual' || storeType === 'fisica_virtual'

  const updateLoc = (i: number, field: keyof Location, val: string) =>
    setLocs(prev => prev.map((l, idx) => idx === i ? { ...l, [field]: val } : l))

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault()
    setValidationErr(null)

    // Validación: física requiere ≥1 sede con city + street
    if (showFisica) {
      const validSedes = locs.filter(l => l.city?.trim() && l.street?.trim())
      if (validSedes.length === 0) {
        setValidationErr('Debes configurar al menos una sede con municipio y dirección.')
        return
      }
    }
    // Validación: virtual requiere ≥1 canal digital
    if (showVirtual && !showFisica) {
      const socialInputs = SOCIAL_KEYS.map(({ key }) =>
        (e.currentTarget.elements.namedItem(`social_${key}`) as HTMLInputElement | null)?.value?.trim() ?? ''
      )
      if (!socialInputs.some(v => v)) {
        setValidationErr('Debes configurar al menos un canal digital (red social o sitio web).')
        return
      }
    }

    const fd = new FormData()
    fd.set('store_type', storeType)
    fd.set('store_locations', JSON.stringify(
      showFisica ? locs.filter(l => l.city || l.street || l.name) : []
    ))
    if (showVirtual) {
      for (const { key } of SOCIAL_KEYS) {
        const el = e.currentTarget.elements.namedItem(`social_${key}`) as HTMLInputElement | null
        if (el?.value?.trim()) fd.set(`social_${key}`, el.value.trim())
      }
    }
    setLoading(true)
    await action(fd)
    setLoading(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">

      {/* Tipo de tienda */}
      <div className="space-y-2">
        <Label className="text-xs font-medium">¿Cómo opera tu tienda?</Label>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {STORE_TYPE_OPTIONS.map(({ value, label, desc }) => (
            <button key={value} type="button" onClick={() => setStoreType(value)}
              className={[
                'flex flex-col items-start gap-0.5 rounded-lg border p-3 text-left transition-colors',
                storeType === value ? 'border-primary bg-primary/5' : 'border-border hover:border-primary/40',
              ].join(' ')}>
              <span className="text-xs font-semibold">{label}</span>
              <span className="text-[10px] text-muted-foreground">{desc}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Sedes físicas con selectores DANE */}
      {showFisica && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <Label className="text-xs font-medium">
              {locs.length > 1 ? 'Sedes físicas' : 'Sede física'}
            </Label>
            <Button type="button" size="sm" variant="outline"
              onClick={() => setLocs(prev => [...prev, { ...EMPTY_LOC }])}
              className="h-7 text-xs gap-1">
              <Plus className="h-3 w-3" /> Agregar sede
            </Button>
          </div>
          <div className="space-y-3">
            {locs.map((loc, i) => (
              <SedeRow key={i} loc={loc} index={i} isOnly={locs.length === 1}
                onChange={(field, val) => updateLoc(i, field, val)}
                onRemove={() => setLocs(prev => prev.filter((_, idx) => idx !== i))} />
            ))}
          </div>
        </div>
      )}

      {/* Canales digitales */}
      {showVirtual && (
        <div className="space-y-2">
          <Label className="text-xs font-medium">
            Canales digitales
            {showFisica && <span className="text-muted-foreground font-normal text-[10px] ml-1">(opcional si tienes sede física)</span>}
            {!showFisica && <span className="text-destructive text-[10px] ml-1">*</span>}
          </Label>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {SOCIAL_KEYS.map(({ key, placeholder }) => (
              <div key={key} className="space-y-1">
                <Label className="text-[10px] text-muted-foreground capitalize">{key}</Label>
                <Input name={`social_${key}`}
                  defaultValue={(initialSocialLinks as Record<string, string>)?.[key] ?? ''}
                  placeholder={placeholder} className="h-8 text-xs" />
              </div>
            ))}
          </div>
        </div>
      )}

      {validationErr && (
        <p className="text-xs text-destructive">{validationErr}</p>
      )}
      <div className="flex items-center gap-3">
        <Button type="submit" size="sm" disabled={loading}>
          {loading
            ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Guardando...</>
            : 'Guardar presencia'}
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
