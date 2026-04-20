'use client'

import { useState } from 'react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

export interface AddressValue {
  street:    string
  number?:   string
  city:      string
  state:     string
  country:   string
  dane_code: string
}

interface Props {
  defaultValue?: Partial<AddressValue>
  fieldPrefix?: string
}

export default function AddressSelector({ defaultValue = {}, fieldPrefix = 'addr' }: Props) {
  const initDpto = DEPARTAMENTOS.find(d => d.nombre === defaultValue.state)?.codigo ?? ''
  const initDane = String(defaultValue.dane_code ?? '').replace(/\D/g, '').slice(0, 5)
  const initMunis = initDpto ? getMunicipiosByDpto(initDpto) : []
  const initMuniCode = initMunis.find(m => m.codigo === initDane || m.nombre === defaultValue.city)?.codigo ?? ''
  const [dptoCode, setDptoCode]          = useState(initDpto)
  const [city, setCity]                  = useState(defaultValue.city ?? '')
  const [municipioCodigo, setMuniCodigo] = useState(initMuniCode)

  const municipios  = dptoCode ? getMunicipiosByDpto(dptoCode) : []
  const dptoNombre  = DEPARTAMENTOS.find(d => d.codigo === dptoCode)?.nombre ?? ''
  const daneCode    = municipioCodigo || (city ? initDane : '')

  return (
    <div className="space-y-2">
      <div className="space-y-1">
        <Label className="text-xs">Dirección</Label>
        <Input
          name={`${fieldPrefix}_street`}
          defaultValue={defaultValue.street ?? ''}
          placeholder="Calle 15 # 100-20 / Cra 7 # 32-18"
          className="h-8 text-xs"
        />
      </div>

      <div className="space-y-1">
        <Label className="text-xs">Número / Apto (opcional)</Label>
        <Input
          name={`${fieldPrefix}_number`}
          defaultValue={defaultValue.number ?? ''}
          placeholder="Apto 301"
          className="h-8 text-xs"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">Departamento</Label>
          <input type="hidden" name={`${fieldPrefix}_state`} value={dptoNombre} />
          <Select
            value={dptoCode || undefined}
            onValueChange={v => { setDptoCode(v); setCity(''); setMuniCodigo('') }}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder="Seleccionar..." />
            </SelectTrigger>
            <SelectContent>
              {DEPARTAMENTOS.map(d => (
                <SelectItem key={d.codigo} value={d.codigo}>{d.nombre}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1">
          <Label className="text-xs">Ciudad / Municipio</Label>
          <input type="hidden" name={`${fieldPrefix}_city`} value={city} />
          <input type="hidden" name={`${fieldPrefix}_dane_code`} value={daneCode} />
          <Select
            value={city || undefined}
            onValueChange={v => {
              const muni = municipios.find(m => m.nombre === v)
              setCity(v)
              setMuniCodigo(muni?.codigo ?? '')
            }}
            disabled={!dptoCode}
          >
            <SelectTrigger className="h-8 text-xs">
              <SelectValue placeholder={dptoCode ? 'Seleccionar...' : 'Elige dpto.'} />
            </SelectTrigger>
            <SelectContent>
              {municipios.map(m => (
                <SelectItem key={m.codigo} value={m.nombre}>{m.nombre}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  )
}
