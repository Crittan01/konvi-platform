// @vitest-environment jsdom
// Smoke tests de la escena compartida de auth (Track 7 T7.1): monta, renderiza
// la marca (logo real — el "Logo mock" murió), el tagline y los children.
// jsdom no anima; se verifica el contrato de render y que no haya dependencia
// de red externa (el grano es data URL inline, el de terceros fue eliminado).
import { describe, it, expect, beforeAll } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AuthBrand, AuthCardReveal, AuthScene } from './auth-scene'

beforeAll(() => {
  // jsdom no implementa matchMedia; useReducedMotion lo consulta al montar.
  window.matchMedia = window.matchMedia ?? ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

describe('AuthScene (T7.1)', () => {
  it('renderiza children en el canvas de auth con tema claro forzado', () => {
    render(<AuthScene><p>Formulario</p></AuthScene>)
    expect(screen.getByText('Formulario')).toBeInTheDocument()
    // `.light` forzado en el canvas (patrón auth — no tocar, §1.8 del DS).
    expect(document.querySelector('.light')).not.toBeNull()
  })

  it('el grano es data URL inline (sin asset externo de terceros)', () => {
    const { container } = render(<AuthScene><p>x</p></AuthScene>)
    const html = container.innerHTML
    expect(html).toContain('data:image/svg+xml')
    // Sin URL EXTERNA fetcheada: ni CSS url(http…) ni el dominio que mfa traía.
    expect(html).not.toMatch(/url\((&quot;|')?https?:/)
    expect(html).not.toContain('grainy-gradients')
  })

  it('AuthBrand muestra wordmark Konvi + tagline y el logo real (K, no mock)', () => {
    render(<AuthBrand subtitle="Consola de administración de tu negocio" />)
    expect(screen.getByText('Konvi')).toBeInTheDocument()
    expect(screen.getByText('Consola de administración de tu negocio')).toBeInTheDocument()
    // Logo real: letterform K en el tile degradado (el mock de casa murió).
    expect(screen.getByText('K')).toBeInTheDocument()
  })

  it('AuthCardReveal renderiza la card contenida', () => {
    render(<AuthCardReveal><p>Card de login</p></AuthCardReveal>)
    expect(screen.getByText('Card de login')).toBeInTheDocument()
  })
})
