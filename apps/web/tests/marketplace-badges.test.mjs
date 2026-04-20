import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getMarketplaceBadgeCount,
  shouldRenderMarketplaceBadge,
} from '../lib/marketplace-badges.js'

test('counts only marketplace statuses that require attention', () => {
  const count = getMarketplaceBadgeCount([
    { status: 'active' },
    { status: 'paused' },
    { status: 'closed' },
    { status: 'ACTIVE' },
  ])
  assert.equal(count, 2)
})

test('renders badge only for marketplace route with positive count', () => {
  assert.equal(shouldRenderMarketplaceBadge('/dashboard/marketplace', 1), true)
  assert.equal(shouldRenderMarketplaceBadge('/dashboard/marketplace', 0), false)
  assert.equal(shouldRenderMarketplaceBadge('/dashboard/orders', 3), false)
})
