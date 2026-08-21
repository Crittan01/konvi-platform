import { describe, it, expect } from 'vitest'
import { resolveSupabaseUrl } from './client'

// STG local: el swap loopback→host actual solo aplica cuando la página se ve
// desde otro equipo (LAN); en la propia VM y en PRD (URL pública) no toca nada.
describe('resolveSupabaseUrl', () => {
  const LOCAL = 'http://127.0.0.1:54321'

  it('página vista desde la LAN: swap loopback → host de la página', () => {
    expect(resolveSupabaseUrl(LOCAL, '192.168.20.5')).toBe('http://192.168.20.5:54321')
  })

  it('acepta localhost como valor configurado', () => {
    expect(resolveSupabaseUrl('http://localhost:54321', '192.168.20.5')).toBe('http://192.168.20.5:54321')
  })

  it('en la propia VM (127.0.0.1/localhost) no toca la URL', () => {
    expect(resolveSupabaseUrl(LOCAL, '127.0.0.1')).toBe(LOCAL)
    expect(resolveSupabaseUrl(LOCAL, 'localhost')).toBe(LOCAL)
  })

  it('sin hostname (SSR) no toca la URL', () => {
    expect(resolveSupabaseUrl(LOCAL, '')).toBe(LOCAL)
  })

  it('URL pública de PRD nunca se altera aunque el host difiera', () => {
    const prd = 'https://xmelwnhhphksbpdjmbbp.supabase.co'
    expect(resolveSupabaseUrl(prd, 'app.konvi.co')).toBe(prd)
  })
})
