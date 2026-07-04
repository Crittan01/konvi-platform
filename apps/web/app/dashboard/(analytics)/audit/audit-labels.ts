/**
 * audit-labels — diccionario canónico es-CO del módulo Auditoría (F4 2026-07-04).
 *
 * FUENTE DE VERDAD única, importada por la página y por el route de export para
 * que no vuelvan a divergir (drift kb_document/kb_doc que dejaba chips muertos).
 *
 * Los `entity_type` / `action` de abajo son EXACTAMENTE los que el backend
 * escribe hoy vía `@audit_log(entity_type=..., action=...)` en services/api.
 * Verificado 2026-07-04:
 *   grep -rhoE 'audit_log\(entity_type="[a-z_]+", action="[a-z_]+"' services/api
 * → 17 entity_types, 15 acciones. Si el backend agrega uno nuevo y no aparece
 * aquí, cae al fallback legible (no rompe), pero DEBE añadirse a este mapa.
 * El contrato UI↔backend está pendiente de test automatizado (needs_founder:
 * los tests viven en apps/web/tests, fuera del alcance editable de F4).
 */

/** entity_type (DB) → etiqueta operador es-CO. 17 tipos reales que el backend escribe. */
export const ENTITY_LABELS: Record<string, string> = {
  order:                'Pedido',
  product:              'Producto',
  variation:            'Variación de producto',
  product_category:     'Categoría de producto',
  attribute_definition: 'Atributo de catálogo',
  contact:              'Contacto',
  conversation:         'Conversación',
  claim:                'Reclamo (PQR)',
  coupon:               'Cupón',
  purchase_order:       'Orden de compra',
  supplier:             'Proveedor',
  expense:              'Gasto',
  marketplace_listing:  'Publicación marketplace',
  kb_doc:               'Base de conocimiento',
  integration:          'Integración',
  settings:             'Configuración',
  team_member:          'Miembro del equipo',
}

/** Orden de los chips de filtro (subset de alto uso primero, resto agrupado). */
export const ENTITY_CHIP_ORDER: string[] = [
  'order',
  'product',
  'variation',
  'product_category',
  'attribute_definition',
  'contact',
  'conversation',
  'claim',
  'coupon',
  'purchase_order',
  'supplier',
  'expense',
  'marketplace_listing',
  'kb_doc',
  'integration',
  'settings',
  'team_member',
]

/** action (DB) → etiqueta operador es-CO. 15 acciones reales que el backend escribe. */
export const ACTION_LABELS: Record<string, string> = {
  created:              'Creado',
  updated:              'Actualizado',
  deleted:              'Eliminado',
  purged:               'Purgado (anonimizado)',
  status_changed:       'Cambio de estado',
  connected:            'Conectada',
  disconnected:         'Desconectada',
  role_changed:         'Cambio de rol',
  payment_link_created: 'Link de pago creado',
  message_sent:         'Mensaje enviado',
  image_sent:           'Imagen enviada',
  note_created:         'Nota creada',
  note_updated:         'Nota actualizada',
  note_deleted:         'Nota eliminada',
  reprocessed:          'Reprocesada',
  exported:             'Exportación de auditoría',
}

/**
 * Clase de color por acción — SOLO shades 700/800 sobre wash claro (regla de
 * paleta founder: nunca 300-500). Cobertura completa de las 15 acciones reales;
 * el fallback gris solo aplica a acciones futuras aún no mapeadas.
 */
const GREEN  = 'bg-emerald-500/10 text-emerald-800 border border-emerald-700/25'
const BLUE   = 'bg-blue-500/10 text-blue-800 border border-blue-700/25'
const RED     = 'bg-red-500/10 text-red-800 border border-red-700/25'
const PURPLE = 'bg-purple-500/10 text-purple-800 border border-purple-700/25'
const AMBER  = 'bg-amber-500/10 text-amber-800 border border-amber-700/25'
const NEUTRAL = 'bg-muted text-muted-foreground border border-border'

export const ACTION_COLORS: Record<string, string> = {
  created:              GREEN,
  connected:            GREEN,
  note_created:         GREEN,
  updated:              BLUE,
  note_updated:         BLUE,
  reprocessed:          BLUE,
  message_sent:         BLUE,
  image_sent:           BLUE,
  deleted:              RED,
  purged:               RED,
  note_deleted:         RED,
  disconnected:         RED,
  status_changed:       PURPLE,
  role_changed:         PURPLE,
  payment_link_created: AMBER,
  exported:             AMBER,
}

/** Color exacto por acción (sin substring-match: evita que payment_link_created herede verde de 'created'). */
export function actionColor(action: string): string {
  return ACTION_COLORS[action] ?? NEUTRAL
}

/** Etiqueta es-CO de una acción; fallback legible (sin guiones bajos) para acciones futuras. */
export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action.replace(/_/g, ' ')
}

/** Etiqueta es-CO de una entidad; fallback al identificador crudo si el backend agregó un tipo nuevo. */
export function entityLabel(entityType: string): string {
  return ENTITY_LABELS[entityType] ?? entityType
}

/** Diccionario es-CO para las keys frecuentes del payload (detalle del evento legible para el comerciante). */
export const PAYLOAD_KEY_LABELS: Record<string, string> = {
  id:            'ID',
  name:          'Nombre',
  title:         'Título',
  status:        'Estado',
  old_status:    'Estado anterior',
  new_status:    'Estado nuevo',
  role:          'Rol',
  old_role:      'Rol anterior',
  new_role:      'Rol nuevo',
  email:         'Correo',
  phone:         'Teléfono',
  amount:        'Monto',
  total:         'Total',
  total_amount:  'Total',
  price:         'Precio',
  stock:         'Stock',
  quantity:      'Cantidad',
  sku:           'SKU',
  provider:      'Proveedor',
  reason:        'Motivo',
  note:          'Nota',
  created_at:    'Creado',
  updated_at:    'Actualizado',
}

/** Traduce las keys de primer nivel del payload a es-CO para la vista de detalle. */
export function humanizePayload(payload: Record<string, unknown> | null): Array<{ key: string; value: string }> {
  if (!payload) return []
  return Object.entries(payload).map(([k, v]) => ({
    key: PAYLOAD_KEY_LABELS[k] ?? k.replace(/_/g, ' '),
    value:
      v === null || v === undefined
        ? '—'
        : typeof v === 'object'
          ? JSON.stringify(v)
          : String(v),
  }))
}
