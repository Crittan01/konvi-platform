import { describe, it, expect } from 'vitest'
import {
  KB_CATEGORY_VALUES,
  CATEGORY_COLORS,
  CATEGORY_LABELS,
  categoryBadgeClass,
  categoryLabel,
} from './categories'
import { STARTER_TEMPLATES } from './starter-templates'

// Contrato canónico rev. 68 — DEBE empatar VALID_CATEGORIES del router
// (services/api/routers/knowledge_base.py) y el CHECK constraint de DB.
const CANONICAL = ['faq', 'negocio', 'politicas', 'productos', 'envios', 'pagos']

describe('KB categorías canónicas', () => {
  it('expone exactamente las 6 categorías rev. 68 sin slugs legacy', () => {
    expect(KB_CATEGORY_VALUES).toEqual(CANONICAL)
    // Regresión: los slugs pre-rev.68 no deben reaparecer.
    for (const legacy of ['politica', 'producto', 'general']) {
      expect(KB_CATEGORY_VALUES).not.toContain(legacy)
    }
  })

  it('color y label definidos para las 6 categorías (sin className undefined)', () => {
    for (const v of CANONICAL) {
      expect(CATEGORY_COLORS[v]).toBeTruthy()
      expect(CATEGORY_COLORS[v]).not.toContain('undefined')
      expect(CATEGORY_LABELS[v]).toBeTruthy()
    }
  })

  it('paleta founder: texto/border solo en shade 700 (nunca 300-500)', () => {
    for (const v of CANONICAL) {
      expect(CATEGORY_COLORS[v]).not.toMatch(/(text|border)-\w+-(300|400|500)\b/)
    }
  })

  it('helpers hacen fallback seguro ante slug desconocido', () => {
    expect(categoryBadgeClass('inexistente')).toContain('bg-muted')
    expect(categoryLabel('inexistente')).toBe('inexistente')
  })

  it('cada plantilla starter usa una categoría canónica', () => {
    for (const t of STARTER_TEMPLATES) {
      expect(CANONICAL).toContain(t.category)
    }
  })

  it('las plantillas cubren las 6 categorías (envios y pagos incluidas)', () => {
    const covered = new Set(STARTER_TEMPLATES.map((t) => t.category))
    for (const v of CANONICAL) {
      expect(covered.has(v)).toBe(true)
    }
  })
})
