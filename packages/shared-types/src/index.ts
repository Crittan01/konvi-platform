export type TenantRole = 'owner' | 'manager' | 'operator'

export type ConversationStatus = 'bot_active' | 'human_takeover' | 'closed'

export type MessageProcessingStatus = 'pending' | 'processed' | 'skipped' | 'failed'

export type PlanCode = 'basic' | 'pro' | 'enterprise'

export type PlanCapability =
  | 'orders.create'
  | 'shipping.quote'
  | 'shipping.confirm_rate'
  | 'conversations.send'
  | 'integrations.mercadolibre'
  | 'ai.agents.configure'
  | 'analytics.audit.export'
