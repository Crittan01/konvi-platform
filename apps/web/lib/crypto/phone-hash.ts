import { createHash } from 'crypto'

/**
 * Rev. 103 — Hash sha256 del phone para `consent_audit_log.phone_hash`.
 *
 * Espejo exacto del helper Python `_hash_phone` en
 * `services/ai-orchestrator/orchestrator.py:676`. Misma regla de
 * normalización (strip de spaces / + / -) para que un mismo phone
 * produzca el mismo hash desde Python o desde TS.
 *
 * Permite lookup post-anonimización del contact sin exponer el phone.
 */
export function hashPhone(phone: string | null | undefined): string | null {
  if (!phone) return null
  const normalized = String(phone).replace(/[\s+-]/g, '')
  return createHash('sha256').update(normalized, 'utf-8').digest('hex')
}
