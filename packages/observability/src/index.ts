export type ApiSecurityEventType =
  | 'rate_limit.exceeded'
  | 'idempotency.replay'
  | 'idempotency.payload_mismatch'
  | 'idempotency.in_flight_conflict'
  | 'idempotency.duplicate_conflict'

export type QueueName = 'human_takeover_notifications' | 'whatsapp_outbound_messages'

export interface QueueHealthSnapshot {
  queue: QueueName
  pending: number
  failed: number
  retries: number
  observedAt: string
}
