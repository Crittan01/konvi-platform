'use client'

import { useState } from 'react'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'
import {
  BUILDING_TYPES,
  BUILDING_TYPE_LABELS,
  CONJUNTO_TYPES,
  CONJUNTO_TYPE_LABELS,
  type BuildingType,
  type ConjuntoType,
} from '@/lib/validators/address'

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
  // Sem 7 F2 cierre 2026-05-19 — sub-modalidades address (SIMPLIFY)
  conjunto_type?: ConjuntoType
  floor?:         string
  company_name?:  string
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
  const [conjuntoType, setConjuntoType]  = useState<ConjuntoType | ''>(defaultValue.conjunto_type ?? '')

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
              Tipo de destino <span className="text-destructive">*</span>
            </Label>
            <input type="hidden" name={`${fieldPrefix}_building_type`} value={buildingType} />
            {/* 4 opciones: 2 cols x 2 rows. Sem 7 F2 cierre 2026-05-19 (SIMPLIFY). */}
            <div className="grid grid-cols-2 gap-2">
              {BUILDING_TYPES.map(bt => (
                <button
                  key={bt}
                  type="button"
                  onClick={() => setBuildingType(bt)}
                  className={`h-8 text-xs rounded-lg border transition-colors ${
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

          {/* Campos condicionales por tipo de destino */}
          {buildingType === 'edificio' && (
            <>
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
                  <Label className="text-xs">Piso</Label>
                  <Input
                    name={`${fieldPrefix}_floor`}
                    defaultValue={defaultValue.floor ?? ''}
                    placeholder="(opcional) ej. 4"
                    className="h-8 text-xs"
                  />
                </div>
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
            </>
          )}

          {buildingType === 'oficina' && (
            <>
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <Label className="text-xs">Número de oficina <span className="text-destructive">*</span></Label>
                  <Input
                    name={`${fieldPrefix}_apartment`}
                    defaultValue={defaultValue.apartment ?? ''}
                    placeholder="502"
                    required
                    className="h-8 text-xs"
                  />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Piso</Label>
                  <Input
                    name={`${fieldPrefix}_floor`}
                    defaultValue={defaultValue.floor ?? ''}
                    placeholder="(opcional) ej. 5"
                    className="h-8 text-xs"
                  />
                </div>
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Nombre de la empresa</Label>
                <Input
                  name={`${fieldPrefix}_company_name`}
                  defaultValue={defaultValue.company_name ?? ''}
                  placeholder="(opcional) Acme S.A.S."
                  className="h-8 text-xs"
                />
                <p className="text-[10px] text-muted-foreground">
                  El repartidor entregará a la recepción/portería de la empresa.
                </p>
              </div>
            </>
          )}

          {buildingType === 'conjunto' && (
            <>
              <div className="space-y-1">
                <Label className="text-xs">
                  Modalidad del conjunto <span className="text-destructive">*</span>
                </Label>
                <input type="hidden" name={`${fieldPrefix}_conjunto_type`} value={conjuntoType} />
                <div className="flex gap-2">
                  {CONJUNTO_TYPES.map(ct => (
                    <button
                      key={ct}
                      type="button"
                      onClick={() => setConjuntoType(ct)}
                      className={`flex-1 h-8 text-xs rounded-lg border transition-colors ${
                        conjuntoType === ct
                          ? 'border-primary bg-primary/10 text-primary font-medium'
                          : 'border-border text-muted-foreground hover:bg-secondary/30'
                      }`}
                    >
                      {CONJUNTO_TYPE_LABELS[ct]}
                    </button>
                  ))}
                </div>
              </div>

              {conjuntoType === 'torres' && (
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
              )}

              {conjuntoType === 'casas' && (
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">
                      Número de casa <span className="text-destructive">*</span>
                    </Label>
                    <Input
                      name={`${fieldPrefix}_apartment`}
                      defaultValue={defaultValue.apartment ?? ''}
                      placeholder="Casa 12"
                      required
                      className="h-8 text-xs"
                    />
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Manzana / Bloque</Label>
                    <Input
                      name={`${fieldPrefix}_tower`}
                      defaultValue={defaultValue.tower ?? ''}
                      placeholder="(opcional) ej. Manzana A"
                      className="h-8 text-xs"
                    />
                  </div>
                </div>
              )}

              <div className="space-y-1">
                <Label className="text-xs">Nombre del conjunto</Label>
                <Input
                  name={`${fieldPrefix}_complex_name`}
                  defaultValue={defaultValue.complex_name ?? ''}
                  placeholder="(opcional) ej. Torres del Parque / Conjunto Los Almendros"
                  className="h-8 text-xs"
                />
              </div>
            </>
          )}

          <div className="space-y-1">
            <Label className="text-xs">Punto de referencia</Label>
            <Input
              name={`${fieldPrefix}_reference`}
              defaultValue={defaultValue.reference ?? ''}
              placeholder="(opcional) Frente al parque / Al lado del Éxito"
              className="h-8 text-xs"
            />
            <p className="text-[10px] text-muted-foreground">
              Detalle libre para el repartidor (portería, esquina, etc.). NO uses este campo para piso ni nombre de empresa — tienen su propio campo arriba.
            </p>
          </div>

          {/* Sem 7 F2 cierre 2026-05-19 — leyenda visual del contrato.
              Espejo de las reglas del bot conversacional (mismo schema). */}
          <p className="text-[10px] text-muted-foreground pt-1 border-t border-border/40 mt-2">
            <span className="text-destructive">*</span> Campos obligatorios — los demás son opcionales pero mejoran la entrega.
          </p>
        </>
      )}
    </div>
  )
}
