import { describe, it, expect } from 'vitest'
import { buildCategoryPicker, leafCategoryIds, type FlatCategory } from './category-tree'

describe('buildCategoryPicker', () => {
  it('lista plana (sin padres) → un grupo sin etiqueta con todas las hojas', () => {
    const cats: FlatCategory[] = [
      { id: 'a', display_label: 'Aceites Esenciales', parent_id: null },
      { id: 'b', display_label: 'Jabones', parent_id: null },
    ]
    const groups = buildCategoryPicker(cats)
    expect(groups).toEqual([{ label: null, options: [
      { id: 'a', display_label: 'Aceites Esenciales' },
      { id: 'b', display_label: 'Jabones' },
    ] }])
  })

  it('jerarquía: padre con hijos → optgroup etiquetado; el padre NO es opción', () => {
    const cats: FlatCategory[] = [
      { id: 'p', display_label: 'Salud y Belleza', parent_id: null },
      { id: 'a', display_label: 'Aceites Esenciales', parent_id: 'p' },
      { id: 'b', display_label: 'Jabones', parent_id: 'p' },
    ]
    const groups = buildCategoryPicker(cats)
    expect(groups).toEqual([{ label: 'Salud y Belleza', options: [
      { id: 'a', display_label: 'Aceites Esenciales' },
      { id: 'b', display_label: 'Jabones' },
    ] }])
    // el padre 'p' no aparece como opción seleccionable en ningún grupo
    const allIds = groups.flatMap(g => g.options.map(o => o.id))
    expect(allIds).not.toContain('p')
  })

  it('mixto: grupos etiquetados primero, hojas sueltas al final sin etiqueta', () => {
    const cats: FlatCategory[] = [
      { id: 'p', display_label: 'Salud y Belleza', parent_id: null },
      { id: 'a', display_label: 'Aceites', parent_id: 'p' },
      { id: 'z', display_label: 'Sin Vertical', parent_id: null }, // raíz sin hijos → hoja suelta
    ]
    const groups = buildCategoryPicker(cats)
    expect(groups).toEqual([
      { label: 'Salud y Belleza', options: [{ id: 'a', display_label: 'Aceites' }] },
      { label: null, options: [{ id: 'z', display_label: 'Sin Vertical' }] },
    ])
  })

  it('defensivo 3 niveles: un hijo con nietos se trata como encabezado, no como opción', () => {
    const cats: FlatCategory[] = [
      { id: 'p', display_label: 'Tecnología', parent_id: null },
      { id: 'c', display_label: 'Accesorios', parent_id: 'p' },   // tiene hijo → encabezado, no opción
      { id: 'g', display_label: 'Forros', parent_id: 'c' },
    ]
    const groups = buildCategoryPicker(cats)
    // 'p' no emite grupo (su único hijo 'c' es a su vez encabezado → sin hojas directas).
    expect(groups.find(gr => gr.label === 'Tecnología')).toBeUndefined()
    // 'c' sí emite grupo con su hoja 'g'.
    expect(groups.find(gr => gr.label === 'Accesorios')?.options)
      .toEqual([{ id: 'g', display_label: 'Forros' }])
    // 'c' nunca aparece como opción seleccionable.
    expect(groups.flatMap(gr => gr.options.map(o => o.id))).not.toContain('c')
  })

  it('lista vacía → sin grupos', () => {
    expect(buildCategoryPicker([])).toEqual([])
  })
})

describe('leafCategoryIds', () => {
  it('devuelve solo hojas (categorías sin hijos)', () => {
    const cats: FlatCategory[] = [
      { id: 'p', display_label: 'Salud', parent_id: null },
      { id: 'a', display_label: 'Aceites', parent_id: 'p' },
      { id: 'b', display_label: 'Jabones', parent_id: 'p' },
      { id: 'z', display_label: 'Suelta', parent_id: null },
    ]
    expect(leafCategoryIds(cats)).toEqual(new Set(['a', 'b', 'z']))
  })
})
