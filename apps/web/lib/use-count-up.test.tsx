// @vitest-environment jsdom
// useCountUp: reduced-motion devuelve el valor final directo; sin reduced-motion
// llega al target vía rAF (stub con setTimeout — jsdom no agenda rAF real).
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest'
import { renderHook, waitFor, cleanup } from '@testing-library/react'
import { useCountUp } from './use-count-up'

let reduceMotion = false

beforeAll(() => {
  window.matchMedia = ((query: string) => ({
    matches: query.includes('reduce') ? reduceMotion : false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia
})

afterEach(() => cleanup())

describe('useCountUp', () => {
  it('con prefers-reduced-motion devuelve el valor final inmediato', () => {
    reduceMotion = true
    const { result } = renderHook(() => useCountUp(42))
    expect(result.current).toBe(42)
    reduceMotion = false
  })

  it('sin reduced-motion anima hasta el target', async () => {
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) =>
      setTimeout(() => cb(performance.now()), 16) as unknown as number)
    vi.stubGlobal('cancelAnimationFrame', (id: number) => clearTimeout(id))

    const { result } = renderHook(() => useCountUp(10, 50))
    await waitFor(() => expect(result.current).toBe(10), { timeout: 2000 })

    vi.unstubAllGlobals()
  })
})
