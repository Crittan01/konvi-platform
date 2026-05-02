'use client'

// Rev. 102 — Pareja `document_type` + `document_number` con validación
// dinámica según el tipo seleccionado. Espejo de las reglas del backend
// (apps/web/lib/validators/document.ts + services/api/dependencies/
// contact_validators.py).
//
// Reglas por tipo:
//   CC    6-12 dígitos · solo números
//   CE    4-8  dígitos · solo números
//   NIT   9-13 chars   · números + guion (DV)
//   PP    6-15 chars   · alfanumérico
//   TI    8-11 dígitos · solo números
//   OTHER 3-30 chars   · alfanumérico
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

export type DocType = 'CC' | 'CE' | 'NIT' | 'PP' | 'TI' | 'OTHER' | ''

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
    min: 6, max: 12, digitsOnly: true, allowDash: false,
    inputMode: 'numeric',
    pattern: '\\d{6,12}',
    placeholder: '1234567890',
    title: 'Cédula: solo dígitos, entre 6 y 12 caracteres',
    example: '6 a 12 dígitos',
  },
  CE: {
    min: 4, max: 8, digitsOnly: true, allowDash: false,
    inputMode: 'numeric',
    pattern: '\\d{4,8}',
    placeholder: '12345678',
    title: 'Cédula de extranjería: solo dígitos, entre 4 y 8 caracteres',
    example: '4 a 8 dígitos',
  },
  NIT: {
    min: 9, max: 13, digitsOnly: false, allowDash: true,
    inputMode: 'text',
    pattern: '\\d{8,12}-?\\d?',
    placeholder: '900123456-7',
    title: 'NIT: 8-12 dígitos, opcionalmente guion + dígito de verificación',
    example: '8-12 dígitos + DV opcional',
  },
  PP: {
    min: 6, max: 15, digitsOnly: false, allowDash: false,
    inputMode: 'text',
    pattern: '[A-Za-z0-9]{6,15}',
    placeholder: 'AB123456',
    title: 'Pasaporte: alfanumérico, entre 6 y 15 caracteres',
    example: '6 a 15 alfanuméricos',
  },
  TI: {
    min: 8, max: 11, digitsOnly: true, allowDash: false,
    inputMode: 'numeric',
    pattern: '\\d{8,11}',
    placeholder: '12345678901',
    title: 'Tarjeta de identidad: solo dígitos, entre 8 y 11 caracteres',
    example: '8 a 11 dígitos',
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
          <option value="TI">TI{layout === 'compact' ? '' : ' (T. Identidad)'}</option>
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
