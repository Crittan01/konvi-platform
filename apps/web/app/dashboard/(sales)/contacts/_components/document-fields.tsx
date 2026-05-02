'use client'

// Rev. 102 — Pareja `document_type` + `document_number` con validación
// dinámica según el tipo seleccionado. Espejo de las reglas del backend
// (apps/web/lib/validators/document.ts + services/api/dependencies/
// contact_validators.py).
//
// Reglas estrictas por tipo (ajustadas a realidad colombiana):
//   CC    6-10 dígitos · solo números
//   CE    6-7  dígitos · solo números (Migración Colombia)
//   NIT   9-11 chars   · 9 dígitos + opcionalmente -DV
//   PP    6-15 chars   · alfanumérico (cubre pasaportes extranjeros)
//   OTHER 3-30 chars   · alfanumérico
//
// **TI removido (rev. 102)**: la Tarjeta de Identidad corresponde a
// menores de edad (7-17 años). Decreto 1377/2013 Art. 7 prohíbe el
// tratamiento de datos de menores sin autorización del representante
// legal — flujo no soportado por este sistema. Si llega solicitud
// formal de un tenant que vende a menores, se implementa flujo
// completo de representante legal (Sprint dedicado, F8 backlog).
//
// Cuando el operador cambia el select, el input ajusta:
//   - inputMode (numeric|text)
//   - maxLength
//   - pattern (regex HTML5)
//   - placeholder con ejemplo del tipo
//   - title (mensaje de validación nativo)
// Y limpia el valor previo si ya no encaja en el nuevo formato.

import { useState, useEffect } from 'react'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export type DocType = 'CC' | 'CE' | 'NIT' | 'PP' | 'OTHER' | ''

type RuleSpec = {
  min: number
  max: number
  digitsOnly: boolean
  allowDash: boolean
  inputMode: 'numeric' | 'text'
  pattern: string
  placeholder: string
  title: string
  example: string
}

const RULES: Record<Exclude<DocType, ''>, RuleSpec> = {
  CC: {
    min: 6, max: 10, digitsOnly: true, allowDash: false,
    inputMode: 'numeric',
    pattern: '\\d{6,10}',
    placeholder: '1234567890',
    title: 'Cédula: solo dígitos, entre 6 y 10 caracteres',
    example: '6 a 10 dígitos',
  },
  CE: {
    min: 6, max: 7, digitsOnly: true, allowDash: false,
    inputMode: 'numeric',
    pattern: '\\d{6,7}',
    placeholder: '1234567',
    title: 'Cédula de extranjería: solo dígitos, 6 o 7 caracteres',
    example: '6 o 7 dígitos',
  },
  NIT: {
    min: 9, max: 11, digitsOnly: false, allowDash: true,
    inputMode: 'text',
    pattern: '\\d{9}(-\\d)?',
    placeholder: '900123456-7',
    title: 'NIT: 9 dígitos, opcionalmente guion + dígito de verificación (1 dígito)',
    example: '9 dígitos + DV opcional',
  },
  PP: {
    min: 6, max: 15, digitsOnly: false, allowDash: false,
    inputMode: 'text',
    pattern: '[A-Za-z0-9]{6,15}',
    placeholder: 'AB123456',
    title: 'Pasaporte: alfanumérico, entre 6 y 15 caracteres (varía por país)',
    example: '6 a 15 alfanuméricos',
  },
  OTHER: {
    min: 3, max: 30, digitsOnly: false, allowDash: true,
    inputMode: 'text',
    pattern: '[A-Za-z0-9\\-]{3,30}',
    placeholder: 'XYZ-123',
    title: 'Otro: alfanumérico (puede incluir guion), entre 3 y 30 caracteres',
    example: '3 a 30 caracteres',
  },
}

type Props = {
  /** Layout del select+input (default: 3-col grid con select=1, input=2) */
  layout?: 'default' | 'compact'
  /** Valor inicial del select (en form Edit) */
  defaultDocType?: DocType
  /** Valor inicial del input (en form Edit) */
  defaultDocNumber?: string
  /** Es campo requerido (form Add lo es; Edit no necesariamente) */
  required?: boolean
  /** Mostrar asterisco rojo en label cuando required */
  showRequiredAsterisk?: boolean
}

const stripIfNotMatching = (value: string, rule: RuleSpec): string => {
  if (rule.digitsOnly) return value.replace(/\D/g, '').slice(0, rule.max)
  if (rule.allowDash) return value.replace(/[^A-Za-z0-9-]/g, '').slice(0, rule.max)
  return value.replace(/[^A-Za-z0-9]/g, '').slice(0, rule.max)
}

export default function DocumentFields({
  layout = 'default',
  defaultDocType = '',
  defaultDocNumber = '',
  required = false,
  showRequiredAsterisk = false,
}: Props) {
  const [docType, setDocType] = useState<DocType>(defaultDocType)
  const [docNumber, setDocNumber] = useState<string>(defaultDocNumber)

  // Si cambia el tipo, recortar/limpiar el número para que cumpla las
  // nuevas reglas (e.g., pasar de PP a CC borra letras).
  useEffect(() => {
    if (!docType) return
    const rule = RULES[docType]
    const clean = stripIfNotMatching(docNumber, rule)
    if (clean !== docNumber) setDocNumber(clean)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docType])

  const rule = docType ? RULES[docType] : null

  const labelSize = layout === 'compact' ? 'text-xs' : 'text-xs'
  const inputSize = layout === 'compact' ? 'h-8 text-xs' : ''
  const selectSize = layout === 'compact'
    ? 'h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs'
    : 'h-9 w-full rounded-md border border-input bg-transparent px-2 text-xs'

  return (
    <div className="grid grid-cols-3 gap-2">
      <div className="space-y-1">
        <Label className={labelSize}>
          Tipo doc.
          {required && showRequiredAsterisk && <span className="text-destructive"> *</span>}
        </Label>
        <select
          name="document_type"
          required={required}
          value={docType}
          onChange={e => setDocType(e.target.value as DocType)}
          className={selectSize}
        >
          <option value="">{layout === 'compact' ? '—' : '— Selecciona —'}</option>
          <option value="CC">CC{layout === 'compact' ? '' : ' (Cédula)'}</option>
          <option value="CE">CE{layout === 'compact' ? '' : ' (Extranjería)'}</option>
          <option value="NIT">NIT{layout === 'compact' ? '' : ' (Empresa)'}</option>
          <option value="PP">PP{layout === 'compact' ? '' : ' (Pasaporte)'}</option>
          <option value="OTHER">Otro</option>
        </select>
      </div>
      <div className="col-span-2 space-y-1">
        <Label className={labelSize}>
          Número doc.
          {required && showRequiredAsterisk && <span className="text-destructive"> *</span>}
          {rule && (
            <span className="ml-1 text-[10px] text-muted-foreground font-normal">
              ({rule.example})
            </span>
          )}
        </Label>
        <Input
          name="document_number"
          required={required}
          value={docNumber}
          onChange={e => setDocNumber(rule ? stripIfNotMatching(e.target.value, rule) : e.target.value)}
          inputMode={rule?.inputMode}
          maxLength={rule?.max}
          minLength={rule?.min}
          pattern={rule?.pattern}
          placeholder={rule?.placeholder ?? 'Selecciona tipo primero'}
          title={rule?.title ?? 'Selecciona tipo de documento primero'}
          disabled={!docType}
          className={inputSize}
        />
      </div>
    </div>
  )
}
