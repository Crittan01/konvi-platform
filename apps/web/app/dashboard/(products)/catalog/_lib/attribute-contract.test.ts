import { describe, it, expect } from 'vitest'
import type { AttributeDef } from '../types'
import {
  normKey, optionOf, optionsFor, getAttrValue, orphanValue,
  canonicalizeAttrs, finalizeAttrs, attrsToObj, type Attr,
} from './attribute-contract'

// Helper: AttributeDef con defaults; se sobreescribe lo relevante por test.
const def = (o: Partial<AttributeDef>): AttributeDef => ({
  product_category_id: 'cat', code: 'c', label: 'X', type: 'text', unit: null,
  allowed_values: [], is_variant_axis: false, sort_order: 0, ...o,
})

// Contrato real KAIU (verificado en DB): Volumen metric ml [10,30]; Ingrediente activo select [enum].
const VOLUMEN = def({ code: 'volume', label: 'Volumen', type: 'metric', unit: 'ml', allowed_values: ['10', '30'], is_variant_axis: true })
const INGREDIENTE = def({ code: 'active', label: 'Ingrediente activo', type: 'select', unit: null, allowed_values: ['Ácido Hialurónico', 'Bakuchiol', 'Vitamina C'] })

describe('helpers puros', () => {
  it('normKey normaliza trim+lower', () => {
    expect(normKey('  Volumen ')).toBe('volumen')
  })
  it('optionOf pega la unidad (o no)', () => {
    expect(optionOf(VOLUMEN, '10')).toBe('10ml')
    expect(optionOf(INGREDIENTE, 'Bakuchiol')).toBe('Bakuchiol')
  })
  it('optionsFor lista las opciones canónicas', () => {
    expect(optionsFor(VOLUMEN)).toEqual(['10ml', '30ml'])
  })
  it('getAttrValue lee por label con match normalizado', () => {
    const attrs: Attr[] = [{ key: 'volumen ', value: '30ml' }]
    expect(getAttrValue(attrs, 'Volumen')).toBe('30ml')
    expect(getAttrValue(attrs, 'Peso')).toBe('')
  })
  it('orphanValue detecta valor fuera del set', () => {
    expect(orphanValue('50ml', ['10ml', '30ml'])).toBe('50ml')
    expect(orphanValue('10ml', ['10ml', '30ml'])).toBeNull()
    expect(orphanValue('', ['10ml'])).toBeNull()
  })
})

describe('canonicalizeAttrs — bug HIGH (round-trip del matrix / valores no canónicos)', () => {
  it('valor exacto se mantiene y canonicaliza la key', () => {
    expect(canonicalizeAttrs([{ key: 'Volumen', value: '10ml' }], [VOLUMEN])).toEqual([{ key: 'Volumen', value: '10ml' }])
  })
  it('valor con espacio "10 ml" → "10ml"', () => {
    expect(canonicalizeAttrs([{ key: 'Volumen', value: '10 ml' }], [VOLUMEN])).toEqual([{ key: 'Volumen', value: '10ml' }])
  })
  it('valor sin unidad "10" → "10ml"', () => {
    expect(canonicalizeAttrs([{ key: 'Volumen', value: '10' }], [VOLUMEN])).toEqual([{ key: 'Volumen', value: '10ml' }])
  })
  it('valor con caso "10ML" → "10ml"', () => {
    expect(canonicalizeAttrs([{ key: 'Volumen', value: '10ML' }], [VOLUMEN])).toEqual([{ key: 'Volumen', value: '10ml' }])
  })
  it('key en minúscula "volumen" → label canónico "Volumen"', () => {
    expect(canonicalizeAttrs([{ key: 'volumen', value: '30' }], [VOLUMEN])).toEqual([{ key: 'Volumen', value: '30ml' }])
  })
  it('valor FUERA de contrato "50ml" se preserva (key canónica) — no se pierde ni inventa', () => {
    expect(canonicalizeAttrs([{ key: 'Volumen', value: '50ml' }], [VOLUMEN])).toEqual([{ key: 'Volumen', value: '50ml' }])
  })
  it('atributo NO del contrato pasa intacto', () => {
    expect(canonicalizeAttrs([{ key: 'Aroma', value: 'Lavanda' }], [VOLUMEN])).toEqual([{ key: 'Aroma', value: 'Lavanda' }])
  })
  it('select por caso: "bakuchiol" → "Bakuchiol"', () => {
    expect(canonicalizeAttrs([{ key: 'ingrediente activo', value: 'bakuchiol' }], [INGREDIENTE]))
      .toEqual([{ key: 'Ingrediente activo', value: 'Bakuchiol' }])
  })
})

describe('finalizeAttrs — bug MEDIUM (colisión de key → payload == UI)', () => {
  it('dedup conserva la PRIMERA (la que muestra el dropdown)', () => {
    const attrs: Attr[] = [{ key: 'Volumen', value: '10ml' }, { key: 'Volumen', value: '50ml' }]
    expect(finalizeAttrs(attrs, [VOLUMEN])).toEqual([{ key: 'Volumen', value: '10ml' }])
  })
  it('dedup case-insensitive: "Volumen" + "volumen"', () => {
    const attrs: Attr[] = [{ key: 'Volumen', value: '10ml' }, { key: 'volumen', value: '30' }]
    expect(finalizeAttrs(attrs, [VOLUMEN])).toEqual([{ key: 'Volumen', value: '10ml' }])
  })
  it('preserva filas de key vacía (attrsToObj las filtra) y atributos libres', () => {
    const attrs: Attr[] = [{ key: '', value: '' }, { key: 'Volumen', value: '10' }, { key: 'Aroma', value: 'Menta' }]
    expect(finalizeAttrs(attrs, [VOLUMEN])).toEqual([
      { key: '', value: '' }, { key: 'Volumen', value: '10ml' }, { key: 'Aroma', value: 'Menta' },
    ])
  })
})

describe('attrsToObj', () => {
  it('filtra vacíos y hace trim', () => {
    expect(attrsToObj([{ key: ' Volumen ', value: ' 10ml ' }, { key: '', value: 'x' }, { key: 'k', value: '' }]))
      .toEqual({ Volumen: '10ml' })
  })
})

describe('integración — escenarios exactos que la revisión adversarial reportó', () => {
  it('HIGH: matrix genera "10 ml" → payload final = {Volumen:"10ml"} (no un valor no canónico)', () => {
    const generated: Attr[] = [{ key: 'Volumen', value: '10 ml' }]
    expect(attrsToObj(finalizeAttrs(generated, [VOLUMEN]))).toEqual({ Volumen: '10ml' })
  })
  it('MEDIUM: estado con fila fantasma colisionante → payload = lo que ve el dropdown (10ml, no 50ml)', () => {
    const state: Attr[] = [{ key: '', value: '' }, { key: 'Volumen', value: '10ml' }, { key: 'Volumen', value: '50ml' }]
    // El dropdown muestra getAttrValue (primer match) = 10ml; el payload debe coincidir.
    expect(getAttrValue(state, 'Volumen')).toBe('10ml')
    expect(attrsToObj(finalizeAttrs(state, [VOLUMEN]))).toEqual({ Volumen: '10ml' })
  })
})
