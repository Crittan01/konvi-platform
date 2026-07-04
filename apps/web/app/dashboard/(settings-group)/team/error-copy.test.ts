import { describe, it, expect } from 'vitest'
import { mapTeamError } from './error-copy'

describe('mapTeamError', () => {
  it('mapea slugs internos a copy en español sin filtrar el slug', () => {
    const cases = [
      'miembro-no-encontrado',
      'usuario-no-encontrado',
      'respuesta-inesperada',
      'datos-invalidos',
      'ya-es-miembro',
      'sin-permiso',
    ]
    for (const slug of cases) {
      const out = mapTeamError(slug)
      expect(out).not.toContain(slug)
      expect(out).not.toContain('-') // ningún slug kebab-case sobrevive
      expect(out.length).toBeGreaterThan(10)
    }
  })

  it('nunca instruye configurar SMTP ni el dashboard de Supabase (acción de plataforma)', () => {
    const out = mapTeamError('rate limit exceeded')
    expect(out.toLowerCase()).not.toContain('smtp')
    expect(out.toLowerCase()).not.toContain('supabase')
  })

  it('detecta rate-limit por varias señales', () => {
    for (const s of ['rate limit', 'email rate limit exceeded', 'too many requests']) {
      expect(mapTeamError(s).toLowerCase()).toContain('demasiados')
    }
  })

  it('no devuelve el mensaje crudo de Supabase en inglés como fallback', () => {
    const raw = 'User already been registered with weird internal detail'
    const out = mapTeamError(raw)
    expect(out).not.toContain(raw)
    // fallback en español
    expect(out.toLowerCase()).toContain('no se pudo completar')
  })

  it('mapea permission/unauthorized ingleses a copy accionable', () => {
    expect(mapTeamError('permission denied').toLowerCase()).toContain('permiso')
    expect(mapTeamError('Unauthorized').toLowerCase()).toContain('permiso')
  })
})
