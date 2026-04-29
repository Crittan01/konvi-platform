'use client'

import { useState } from 'react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'
import { BUILDING_TYPES, BUILDING_TYPE_LABELS, type BuildingType } from '@/lib/validators/address'

export interface AddressValue {
  street:        string
  number?:       string
  city:          string
  state:         string
  country:       string
  dane_code:     string
  // Rev. 69 — campos estructurados
  neighborhood?: string
  building_type?: BuildingType
  tower?:        string
  apartment?:    string
  complex_name?: string
  reference?:    string
}

interface Props {
  defaultValue?: Partial<AddressValue>
  fieldPrefix?: string
  /** Rev. 69 — muestra building_type + neighborhood + tower/apartment/etc.
   * Default false para mantener retrocompat (shipping_origin del tenant no usa esto).
   * En Contactos del cliente: usar true. */
  showBuildingDetails?: boolean
}

export default function AddressSelector({
  defaultValue = {},
  fieldPrefix = 'addr',
  showBuildingDetails = false,
}: Props) {
  const initDpto = DEPARTAMENTOS.find(d => d.nombre === defaultValue.state)?.codigo ?? ''
  const initDane = String(defaultValue.dane_code ?? '').replace(/\D/g, '').slice(0, 5)
  const initMunis = initDpto ? getMunicipiosByDpto(initDpto) : []
  const initMuniCode = initMunis.find(m => m.codigo === initDane || m.nombre === defaultValue.city)?.codigo ?? ''
  const [dptoCode, setDptoCode]          = useState(initDpto)
  const [city, setCity]                  = useState(defaultValue.city ?? '')
  const [municipioCodigo, setMuniCodigo] = useState(initMuniCode)
  const [buildingType, setBuildingType]  = useState<BuildingType | ''>(defaultValue.building_type ?? '')

  const municipios  = dptoCode ? getMunicipiosByDpto(dptoCode) : []
  const dptoNombre  = DEPARTAMENTOS.find(d => d.codigo === dptoCode)?.nombre ?? ''
  const daneCode    = municipioCodigo || (city ? initDane : '')

  return (
    <div className="space-y-2">
      <div className="space-y-1">
        <Label className="text-xs">
          Dirección {showBuildingDetails && <span className="text-destructive">*</span>}
        </Label>
        <Input
          name={`${fieldPrefix}_street`}
          defaultValue={defaultValue.street ?? ''}
          placeholder="Ej: Calle 100 #15-20 / Carrera 7 #32-18"
          required={showBuildingDetails}
          className="h-8 text-xs"
        />
      </div>
      {/* Campo legacy `number` preservado oculto por compatibilidad con
          contactos antiguos que lo tenían separado. No se expone al operador. */}
      <input
        type="hidden"
        name={`${fieldPrefix}_number`}
        defaultValue={defaultValue.number ?? ''}
      />

      <div className="grid grid-cols-2 gap-2">
        <div className="space-y-1">
          <Label className="text-xs">
            Departamento {showBuildingDetails && <span className="text-destructive">*</span>}
          </Label>
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
          <Label className="text-xs">
            Ciudad / Municipio {showBuildingDetails && <span className="text-destructive">*</span>}
          </Label>
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

      {/* Rev. 69 — campos estructurados (Contactos del cliente final). */}
      {showBuildingDetails && (
        <>
          <div className="space-y-1">
            <Label className="text-xs">
              Barrio <span className="text-destructive">*</span>
            </Label>
            <Input
              name={`${fieldPrefix}_neighborhood`}
              defaultValue={defaultValue.neighborhood ?? ''}
              placeholder="Chapinero / El Poblado / Granada"
              required
              className="h-8 text-xs"
            />
            <p className="text-[10px] text-muted-foreground">Carriers (Coordinadora, Servientrega) lo usan para optimizar zona.</p>
          </div>

          <div className="space-y-1">
            <Label className="text-xs">
              Tipo de vivienda <span className="text-destructive">*</span>
            </Label>
            <input type="hidden" name={`${fieldPrefix}_building_type`} value={buildingType} />
            <div className="flex gap-2">
              {BUILDING_TYPES.map(bt => (
                <button
                  key={bt}
                  type="button"
                  onClick={() => setBuildingType(bt)}
                  className={`flex-1 h-8 text-xs rounded-lg border transition-colors ${
                    buildingType === bt
                      ? 'border-primary bg-primary/10 text-primary font-medium'
                      : 'border-border text-muted-foreground hover:bg-secondary/30'
                  }`}
                >
                  {BUILDING_TYPE_LABELS[bt]}
                </button>
              ))}
            </div>
          </div>

          {/* Campos condicionales por tipo de vivienda */}
          {buildingType === 'edificio' && (
            <div className="grid grid-cols-2 gap-2">
              <div className="space-y-1">
                <Label className="text-xs">Apartamento <span className="text-destructive">*</span></Label>
                <Input
                  name={`${fieldPrefix}_apartment`}
                  defaultValue={defaultValue.apartment ?? ''}
                  placeholder="401"
                  required
                  className="h-8 text-xs"
                />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Nombre del edificio</Label>
                <Input
                  name={`${fieldPrefix}_complex_name`}
                  defaultValue={defaultValue.complex_name ?? ''}
                  placeholder="(opcional)"
                  className="h-8 text-xs"
                />
              </div>
            </div>
          )}

          {buildingType === 'conjunto' && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Torre / Bloque <span className="text-destructive">*</span></Label>
                  <Input
                    name={`${fieldPrefix}_tower`}
                    defaultValue={defaultValue.tower ?? ''}
                    placeholder="Torre 3"
                    required
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Apartamento <span className="text-destructive">*</span></Label>
                  <Input
                    name={`${fieldPrefix}_apartment`}
                    defaultValue={defaultValue.apartment ?? ''}
                    placeholder="401"
                    required
                    className="h-8 text-xs"
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Nombre del conjunto</Label>
                <Input
                  name={`${fieldPrefix}_complex_name`}
                  defaultValue={defaultValue.complex_name ?? ''}
                  placeholder="(opcional) ej. Torres del Parque"
                  className="h-8 text-xs"
                />
              </div>
            </>
          )}

          <div className="space-y-1">
            <Label className="text-xs">Punto de referencia (opcional)</Label>
            <Input
              name={`${fieldPrefix}_reference`}
              defaultValue={defaultValue.reference ?? ''}
              placeholder="Frente al parque / Al lado del Éxito"
              className="h-8 text-xs"
            />
          </div>
        </>
      )}
    </div>
  )
}
