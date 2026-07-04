// F1 2026-07-04: migrado de tests/marketplace-badges.test.mjs (node:test, que
// ningún runner ejecutaba — huérfano) a vitest.
import { describe, it, expect } from 'vitest'
import { getMarketplaceBadgeCount, shouldRenderMarketplaceBadge } from './marketplace-badges.js'

describe('marketplace-badges', () => {
  it('cuenta solo estados de marketplace que requieren atención', () => {
    const count = getMarketplaceBadgeCount([
      { status: 'active' },
      { status: 'paused' },
      { status: 'closed' },
      { status: 'ACTIVE' },
    ])
    expect(count).toBe(2)
  })

  it('renderiza el badge solo en la ruta marketplace con conteo positivo', () => {
    expect(shouldRenderMarketplaceBadge('/dashboard/marketplace', 1)).toBe(true)
    expect(shouldRenderMarketplaceBadge('/dashboard/marketplace', 0)).toBe(false)
    expect(shouldRenderMarketplaceBadge('/dashboard/orders', 3)).toBe(false)
  })
})
