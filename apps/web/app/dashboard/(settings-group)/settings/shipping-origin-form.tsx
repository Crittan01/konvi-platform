'use client'

import { useState, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ShieldCheck } from 'lucide-react'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

type ShippingOrigin = {
  name?: string; company?: string; street?: string; city?: string
  state?: string; postal_code?: string; country?: string; phone?: string
}

interface Props {
  initialData?: ShippingOrigin | null
  action: (formData: FormData) => Promise<void>
}

export default function ShippingOriginForm({ initialData, action }: Props) {
  // Encuentra el código DANE del departamento guardado por nombre
  const initialDpto = DEPARTAMENTOS.find(
    (d) => d.nombre === initialData?.state
  )?.codigo ?? ''

  const [codigoDpto, setCodigoDpto] = useState<string>(initialDpto)
  const [busquedaMunicipio, setBusquedaMunicipio] = useState('')

  const municipios = useMemo(
    () => getMunicipiosByDpto(codigoDpto),
    [codigoDpto]
  )

  const municipiosFiltrados = useMemo(() => {
    const q = busquedaMunicipio.toLowerCase()
    return q ? municipios.filter((m) => m.nombre.toLowerCase().includes(q)) : municipios
  }, [municipios, busquedaMunicipio])

  const nombreDpto = DEPARTAMENTOS.find((d) => d.codigo === codigoDpto)?.nombre ?? ''

  return (
    <form action={action} className="space-y-4">
      {/* Nombre del remitente + empresa */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-name">Nombre del remitente</Label>
          <Input id="origin-name" name="origin_name"
            defaultValue={initialData?.name ?? ''}
            placeholder="Juan Pérez" className="h-8 text-sm" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-company">Empresa</Label>
          <Input id="origin-company" name="origin_company"
            defaultValue={initialData?.company ?? ''}
            placeholder="Mi Tienda S.A." className="h-8 text-sm" />
        </div>
      </div>

      {/* Calle */}
      <div className="space-y-1.5">
        <Label className="text-xs font-medium" htmlFor="origin-street">Calle y número</Label>
        <Input id="origin-street" name="origin_street"
          defaultValue={initialData?.street ?? ''}
          placeholder="Av. Principal 123" className="h-8 text-sm" />
      </div>

      {/* Departamento + Municipio */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-state">Departamento</Label>
          {/* Campo oculto que guarda el nombre del dpto para compatibilidad con Envia */}
          <input type="hidden" name="origin_state" value={nombreDpto} />
          <select
            id="origin-state"
            value={codigoDpto}
            onChange={(e) => {
              setCodigoDpto(e.target.value)
              setBusquedaMunicipio('')
            }}
            className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
          >
            <option value="">Seleccionar departamento…</option>
            {DEPARTAMENTOS.map((d) => (
              <option key={d.codigo} value={d.codigo}>{d.nombre}</option>
            ))}
          </select>
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="municipio-search">Municipio / Ciudad</Label>
          {codigoDpto ? (
            <>
              <Input
                placeholder="Buscar municipio…"
                value={busquedaMunicipio}
                onChange={(e) => setBusquedaMunicipio(e.target.value)}
                className="h-8 text-sm mb-1"
              />
              <select
                id="origin-city"
                name="origin_city"
                defaultValue={initialData?.city ?? ''}
                className="h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Seleccionar municipio…</option>
                {municipiosFiltrados.map((m) => (
                  <option key={m.codigo} value={m.nombre}>{m.nombre}</option>
                ))}
              </select>
            </>
          ) : (
            <Input
              disabled
              placeholder="Selecciona un departamento primero"
              className="h-8 text-sm opacity-50"
            />
          )}
        </div>
      </div>

      {/* Código postal + País + Teléfono */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-cp">Código postal</Label>
          <Input id="origin-cp" name="origin_postal_code"
            defaultValue={initialData?.postal_code ?? ''}
            placeholder="110111" className="h-8 text-sm" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-country">País</Label>
          <Input id="origin-country" name="origin_country"
            defaultValue={initialData?.country ?? 'CO'}
            placeholder="CO" maxLength={2} className="h-8 text-sm" />
        </div>
        <div className="space-y-1.5">
          <Label className="text-xs font-medium" htmlFor="origin-phone">Teléfono</Label>
          <Input id="origin-phone" name="origin_phone"
            defaultValue={initialData?.phone ?? ''}
            placeholder="+573001234567" className="h-8 text-sm" />
        </div>
      </div>

      {initialData?.city && (
        <div className="flex items-center gap-1.5 text-xs text-emerald-400">
          <ShieldCheck className="h-3 w-3" /> Dirección guardada
        </div>
      )}
      <Button type="submit" size="sm">Guardar dirección</Button>
    </form>
  )
}
