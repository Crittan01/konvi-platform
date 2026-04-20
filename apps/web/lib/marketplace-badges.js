const ATTENTION_STATUSES = new Set(['paused', 'closed', 'error'])

export function getMarketplaceBadgeCount(listings) {
  if (!Array.isArray(listings)) return 0
  return listings.filter((listing) => ATTENTION_STATUSES.has(String(listing?.status || '').toLowerCase())).length
}

export function shouldRenderMarketplaceBadge(href, badgeCount) {
  return href === '/dashboard/marketplace' && Number(badgeCount) > 0
}
