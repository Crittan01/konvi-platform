import { describe, it, expect } from 'vitest'
import {
  isValidName,
  isValidLanguage,
  validateComponents,
  parseComponentsJSON,
  buildTemplatePreview,
  VALID_CATEGORIES,
  VALID_PARAMETER_FORMATS,
  EDITABLE_STATUSES,
  type TemplateComponent,
} from './template-validation'

describe('name / language patterns', () => {
  it('acepta nombres canónicos Meta', () => {
    expect(isValidName('payment_reminder_v1')).toBe(true)
    expect(isValidName('abc')).toBe(true)
  })
  it('rechaza nombres inválidos', () => {
    expect(isValidName('Payment')).toBe(false)      // mayúscula
    expect(isValidName('1abc')).toBe(false)          // empieza con dígito
    expect(isValidName('ab')).toBe(false)            // <3 chars
    expect(isValidName('a b')).toBe(false)           // espacio
    expect(isValidName('a'.repeat(60))).toBe(false)  // >50 chars
  })
  it('valida languages BCP 47 simples', () => {
    expect(isValidLanguage('es')).toBe(true)
    expect(isValidLanguage('es_CO')).toBe(true)
    expect(isValidLanguage('es_co')).toBe(false)
    expect(isValidLanguage('spanish')).toBe(false)
  })
})

describe('constantes canónicas', () => {
  it('categorías y formatos', () => {
    expect(VALID_CATEGORIES.has('UTILITY')).toBe(true)
    expect(VALID_CATEGORIES.has('MARKETING')).toBe(true)
    expect(VALID_CATEGORIES.has('AUTHENTICATION')).toBe(true)
    expect(VALID_PARAMETER_FORMATS.has('POSITIONAL')).toBe(true)
    expect(VALID_PARAMETER_FORMATS.has('NAMED')).toBe(true)
  })
  it('solo LOCAL_DRAFT y REJECTED son editables', () => {
    expect(EDITABLE_STATUSES.has('LOCAL_DRAFT')).toBe(true)
    expect(EDITABLE_STATUSES.has('REJECTED')).toBe(true)
    expect(EDITABLE_STATUSES.has('APPROVED')).toBe(false)
    expect(EDITABLE_STATUSES.has('PENDING')).toBe(false)
  })
})

describe('validateComponents', () => {
  it('exige lista no vacía', () => {
    expect(validateComponents([])).toMatch(/no vacía/)
    // @ts-expect-error probamos entrada no-array en runtime
    expect(validateComponents(null)).toMatch(/no vacía/)
  })
  it('exige exactamente 1 BODY (0 BODY falla)', () => {
    expect(validateComponents([{ type: 'FOOTER', text: 'x' }])).toMatch(/1 BODY/)
  })
  it('dos BODY se detectan como duplicado antes del conteo', () => {
    const two: TemplateComponent[] = [
      { type: 'BODY', text: 'a' },
      { type: 'BODY', text: 'b' },
    ]
    expect(validateComponents(two)).toMatch(/duplicado/)
  })
  it('BODY requiere texto no vacío', () => {
    expect(validateComponents([{ type: 'BODY', text: '   ' }])).toMatch(/BODY requiere/)
  })
  it('rechaza type inválido', () => {
    // @ts-expect-error type inválido a propósito
    expect(validateComponents([{ type: 'SUBTITLE', text: 'x' }])).toMatch(/inválido/)
  })
  it('rechaza HEADER/BODY/FOOTER duplicados pero permite BUTTONS repetido', () => {
    const dupHeader: TemplateComponent[] = [
      { type: 'HEADER', text: 'a' },
      { type: 'HEADER', text: 'b' },
      { type: 'BODY', text: 'c' },
    ]
    expect(validateComponents(dupHeader)).toMatch(/duplicado/)
    const twoButtons: TemplateComponent[] = [
      { type: 'BODY', text: 'c' },
      { type: 'BUTTONS', buttons: [{ text: 'A' }] },
      { type: 'BUTTONS', buttons: [{ text: 'B' }] },
    ]
    expect(validateComponents(twoButtons)).toBeNull()
  })
  it('acepta un template válido', () => {
    const ok: TemplateComponent[] = [
      { type: 'HEADER', text: 'Hola' },
      { type: 'BODY', text: 'Tu pedido {{1}}' },
      { type: 'FOOTER', text: 'Gracias' },
    ]
    expect(validateComponents(ok)).toBeNull()
  })
})

describe('parseComponentsJSON', () => {
  it('rechaza JSON malformado', () => {
    const r = parseComponentsJSON('{not json')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(/JSON inválido/)
  })
  it('rechaza no-array', () => {
    const r = parseComponentsJSON('{"type":"BODY"}')
    expect(r.ok).toBe(false)
    if (!r.ok) expect(r.error).toMatch(/array JSON/)
  })
  it('parsea y valida un array correcto', () => {
    const r = parseComponentsJSON('[{"type":"BODY","text":"hola"}]')
    expect(r.ok).toBe(true)
    if (r.ok) expect(r.value).toHaveLength(1)
  })
})

describe('buildTemplatePreview', () => {
  it('devuelve null sin components', () => {
    expect(buildTemplatePreview([])).toBeNull()
    expect(buildTemplatePreview(null)).toBeNull()
  })
  it('sustituye variables con el example', () => {
    const p = buildTemplatePreview([
      {
        type: 'BODY',
        text: 'Hola {{1}}, pedido #{{2}}',
        example: { body_text: [['Carlos', 'A1B2']] },
      },
    ])
    expect(p?.bodyText).toBe('Hola Carlos, pedido #A1B2')
    expect(p?.usedExample).toBe(true)
  })
  it('deja placeholders visibles sin example', () => {
    const p = buildTemplatePreview([{ type: 'BODY', text: 'Hola {{1}}' }])
    expect(p?.bodyText).toBe('Hola «1»')
    expect(p?.usedExample).toBe(false)
  })
  it('extrae header, footer y botones', () => {
    const p = buildTemplatePreview([
      { type: 'HEADER', text: 'Título', format: 'TEXT' },
      { type: 'BODY', text: 'Cuerpo' },
      { type: 'FOOTER', text: 'Pie' },
      { type: 'BUTTONS', buttons: [{ text: 'Pagar' }, { text: 'Ayuda' }] },
    ])
    expect(p?.headerText).toBe('Título')
    expect(p?.footerText).toBe('Pie')
    expect(p?.buttonLabels).toEqual(['Pagar', 'Ayuda'])
  })
})
