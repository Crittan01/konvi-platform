/**
 * Types compartidos del Inbox.
 *
 * Refactor 2026-05-29 — extraído del monolito `page.tsx`.
 * Estos types son puros (sin React) — server+client safe.
 *
 * IMPORTANTE: si cambia algo aquí debe coincidir con el contrato de
 * `services/api/routers/conversations.py` y los schemas Supabase.
 */

// Rev. 109 — AgenticState badge en el Inbox.
export type AgenticState =
  | 'GREETING'
  | 'EXPLORING'
  | 'CART_BUILDING'
  | 'PII_COLLECTION'
  | 'SHIPPING_QUOTE'
  | 'CARRIER_SELECTION'
  | 'PAYMENT'
  | 'POST_PAYMENT'
  | 'HUMAN_HANDOFF'

export interface Conversation {
  id: string
  customer_phone: string
  // 2026-07-04 (F2) — nombre del contacto denormalizado en el write-path del
  // connector (contacts.profile.name de Meta). Sólo-display, alta frecuencia de
  // lectura en la lista; evita N lookups por render. Puede ser null en rows
  // históricos previos al backfill o si la columna aún no existe (degrada a phone).
  contact_name?: string | null
  status: 'bot_active' | 'human_takeover' | 'closed' | 'opted_out'
  agentic_state?: AgenticState | null  // Rev. 109 — derivado por state machine.
  created_at: string
  last_interaction_at?: string
  archived_at?: string | null
  last_message?: { content: string; direction: string; created_at: string } | null
  last_read_at?: string | null  // A2: marca de lectura del operador actual
}

// Rev. 72 — content_type tipado (cierra drift M2). Antes era `string` libre,
// el render condicional podía silenciosamente romperse con valores nuevos.
// 'context_snapshot' es interno (snapshots del orchestrator); el filtro `.neq` lo excluye.
//
// 2026-07-04 (F5/F7) — se completa el union con los content_type que ya
// estampan worker/orchestrator pero el Inbox no reconocía:
//   • 'template'         → outbound HSM (recordatorios/reengagement). Se renderiza
//                          con estilo de plantilla (antes: crudo '[TEMPLATE ...]').
//   • 'escalation_audit' → fila de auditoría de escalación (append-only).
//   • 'sla_breach_audit' → fila de auditoría de breach de SLA (cron worker).
// Las dos últimas NO son mensajes conversacionales: se FILTRAN del render
// (ver NON_RENDERABLE_CONTENT_TYPES en constants.ts) — antes se pintaban como
// burbujas vacías.
export type MessageContentType =
  | 'text'
  | 'image'
  | 'audio'
  | 'video'
  | 'document'
  | 'sticker'
  | 'location'
  | 'template'
  | 'context_snapshot'
  | 'escalation_audit'
  | 'sla_breach_audit'

export interface Message {
  id: string
  direction: 'inbound' | 'outbound'
  content: string
  content_type: MessageContentType
  media_url?: string | null
  created_at: string
  processed: boolean
  processing_status?: 'pending' | 'processed' | 'skipped' | 'failed'
  skip_reason?: string | null
  // Estado de entrega REAL reportado por Meta (delivery receipts). Sólo aplica a
  // outbound trackeado; NULL en inbound/históricos → el Inbox cae al heurístico
  // `processed`. Poblado por el connector (persist_outbound_status).
  delivery_status?: 'sent' | 'delivered' | 'read' | 'failed' | null
  delivered_at?: string | null
  read_at?: string | null
  failed_at?: string | null
  delivery_error?: Array<{ code?: number; title?: string; message?: string }> | null
}

export interface ProductVariation {
  id: string
  sku: string
  price: number
  stock_quantity: number
  attributes: Record<string, string>
  weight_kg?: number
  image_url?: string
}

export interface Product {
  id: string
  title: string
  description?: string
  cover_image_url?: string
  stock_total: number
  product_variations: ProductVariation[]
}

export interface OrderRow {
  id: string
  status: string
  total_amount: number
  shipping_cost: number
  created_at: string
  items_count: number
}

export interface ContactRow {
  id: string
  name?: string
  phone: string
  // Rev. 103 — campos PII completos (espejo del system prompt del bot).
  shipping_phone?: string | null
  email?: string | null
  document_type?: string | null
  document_number?: string | null
  address?: Record<string, unknown>
  consent_given?: boolean
  consent_revoked_at?: string | null
}

// Rev. 103 — Cart-as-SoT en vivo. El operador humano ve el mismo carrito
// que el bot está construyendo turn-by-turn.
export interface CartItem {
  product_id: string
  variation_id: string
  quantity: number
  unit_price_cents: number
  title: string
  variant_label: string
  sku: string
}

export interface ActiveCart {
  id: string
  items: CartItem[]
  subtotal_cents: number
  shipping_cents: number              // effective: cart o último quote del history
  discount_cents: number              // Rev. 109 — descuento de cupón aplicado
  coupon_code: string | null          // Rev. 109 — código cupón si aplica
  total_cents: number
  carrier_name: string
  requires_requote: boolean
  // Rev. 103 — estado del shipping para que el operador vea siempre la línea
  // Envío con contexto claro:
  //   "active"  → cotización fresca + cart sin cambios
  //   "stale"   → cotización existe pero cart cambió (bot re-cotizará)
  //   "pending" → aún no se ha cotizado
  shipping_status?: 'active' | 'stale' | 'pending'
  payment_method?: 'credit' | 'cod'   // medio de pago elegido por el cliente (online vs contraentrega)
}

// Rev. 103 — Reclamos abiertos espejo del system prompt.
export interface OpenClaim {
  id: string
  ticket_number: string
  status: string
  reason?: string | null
  created_at: string
}

export interface ConvContext {
  contact: ContactRow | null
  recent_orders: OrderRow[]
  active_cart: ActiveCart | null
  open_claims: OpenClaim[]
  products: Product[]
  product_count: number
  low_stock_count: number
}

export interface SelectedVariation {
  productId: string
  productTitle: string
  variationId: string
  sku: string
  price: number
  stock: number
  label: string
}

export type FilterStatus =
  | 'active'
  | 'sla_breach'
  | 'all'
  | 'bot_active'
  | 'human_takeover'
  | 'closed'
  | 'opted_out'

// Rev. 109 founder 2026-05-28 — agrupación por phone.
// Modelo arquitectónico: "1 conv perpetua per (tenant, phone)". El connector
// reabre conversaciones cerradas (db_persistence._upsert_conversation), pero
// drift histórico (UAT testing, ediciones manuales) puede dejar múltiples
// rows por phone. Esta función agrupa visualmente: 1 fila per cliente,
// expandible para ver sesiones históricas.
// Rev. 109 founder 2026-05-29 — Notas privadas del operador (P0-1).
export interface ConversationNote {
  id: string
  content: string
  is_pinned: boolean
  author_user_id: string
  created_at: string
  updated_at: string
}

export type ConvGroup = {
  phone: string
  primary: Conversation
  others: Conversation[]   // sesiones históricas, ordenadas más-reciente-primero
}
