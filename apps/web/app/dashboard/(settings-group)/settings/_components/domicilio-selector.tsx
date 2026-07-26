'use client'

import { useMemo, useState } from 'react'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { DEPARTAMENTOS, getMunicipiosByDpto } from '@/lib/dane-colombia'

/**
 * Departamento y ciudad del domicilio, elegidos de la lista oficial (DIVIPOLA DANE:
 * 33 departamentos, 1.103 municipios) en vez de escritos a mano.
 *
 * POR QUÉ NO ES SOLO COMODIDAD: esta dirección va impresa en cada comprobante como el
 * lugar donde se puede notificar al vendedor (Ley 1480 art. 50 lit. a). Escrita a mano
 * produce "Bogota", "bogotá D.C.", "Btá" — variantes que además rompen la cotización de
 * envíos, que resuelve el código DANE por nombre normalizado.
 *
 * Reusa el MISMO catálogo que el cotizador de envíos (`@/lib/dane-colombia`); no se
 * duplica la fuente.
 *
 * Se envían los NOMBRES, no los códigos, porque `tenants.domicilio_ciudad` y
 * `domicilio_departamento` son texto — y así el comprobante puede imprimirlos tal cual.
 * Los `<input type="hidden">` son los que viajan en el FormData: el resto del formulario
 * es server action, así que no hay estado compartido que sincronizar.
 */
export default function DomicilioSelector({
  departamentoInicial,
  ciudadInicial,
}: {
  departamentoInicial?: string | null
  ciudadInicial?: string | null
}) {
  // Se busca por NOMBRE porque es lo que hay guardado. Si el valor guardado no está en el
  // catálogo (dato viejo escrito a mano), no se pierde: se conserva en el hidden y se
  // muestra el aviso de abajo, en vez de borrarlo en silencio.
  const dptoGuardado = useMemo(
    () => DEPARTAMENTOS.find((d) => d.nombre === departamentoInicial),
    [departamentoInicial],
  )
  const [dptoCodigo, setDptoCodigo] = useState(dptoGuardado?.codigo ?? '')
  const [ciudad, setCiudad] = useState(ciudadInicial ?? '')

  const municipios = dptoCodigo ? getMunicipiosByDpto(dptoCodigo) : []
  const dptoNombre = DEPARTAMENTOS.find((d) => d.codigo === dptoCodigo)?.nombre ?? ''

  // Dato previo que no matchea el catálogo: se avisa en vez de descartarlo.
  const guardadoFueraDelCatalogo =
    Boolean(departamentoInicial) && !dptoGuardado

  return (
    <>
      <div className="space-y-1">
        <Label htmlFor="dom-depto" className="text-xs">Departamento</Label>
        <Select
          value={dptoCodigo || undefined}
          onValueChange={(v) => {
            setDptoCodigo(v)
            setCiudad('')   // la ciudad anterior ya no pertenece a este departamento
          }}
        >
          <SelectTrigger id="dom-depto" className="h-9">
            <SelectValue placeholder="Seleccionar..." />
          </SelectTrigger>
          <SelectContent>
            {DEPARTAMENTOS.map((d) => (
              <SelectItem key={d.codigo} value={d.codigo}>{d.nombre}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input type="hidden" name="domicilio_departamento" value={dptoNombre} />
      </div>

      <div className="space-y-1">
        <Label htmlFor="dom-ciudad" className="text-xs">Ciudad / Municipio</Label>
        <Select
          value={ciudad || undefined}
          onValueChange={setCiudad}
          disabled={!dptoCodigo}
        >
          <SelectTrigger id="dom-ciudad" className="h-9">
            <SelectValue
              placeholder={dptoCodigo ? 'Seleccionar...' : 'Elige el departamento primero'}
            />
          </SelectTrigger>
          <SelectContent>
            {municipios.map((m) => (
              <SelectItem key={m.codigo} value={m.nombre}>{m.nombre}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <input type="hidden" name="domicilio_ciudad" value={ciudad} />
        {guardadoFueraDelCatalogo && (
          <p className="text-[10px] text-amber-700">
            Lo guardado antes («{departamentoInicial}») no está en la lista oficial.
            Vuelve a elegirlo para que las guías de envío lo reconozcan.
          </p>
        )}
      </div>
    </>
  )
}
