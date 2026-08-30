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
  // Meta-evento: exportación del propio registro (self-audit, action='exported').
  // Fuera de ENTITY_CHIP_ORDER a propósito — no es una entidad de negocio filtrable.
  audit_log:            'Registro de auditoría',
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
const GREEN  = 'bg-success-bg text-success-fg border border-success-border'
const BLUE   = 'bg-info-bg text-info-fg border border-info-border'
const RED     = 'bg-danger-bg text-danger-fg border border-danger-border'
const PURPLE = 'bg-ai-bg text-ai-fg border border-ai-border'
const AMBER  = 'bg-warning-bg text-warning-fg border border-warning-border'
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
  // Movimientos de inventario (orders/purchases/meli_webhook/order_cancellation)
  // y ajustes de configuración — antes caían al fallback genérico.
  change:              'Cambio',
  delta:               'Ajuste de stock',
  old_stock:           'Stock anterior',
  new_stock:           'Stock nuevo',
  low_stock_threshold: 'Umbral de stock bajo',
  // Meta-evento de exportación (self-audit del propio registro).
  row_count:           'Eventos exportados',
  filters:             'Filtros aplicados',
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

// ─────────────────────────────────────────────────────────────────────────────
// pii_access_log — vista "Accesos a datos personales" (Habeas Data Ley 1581 Art. 9).
// El árbol funcional (.context/00-product.md) promete "log de acceso/cambios";
// esta capa surface los ACCESOS a PII, no solo los cambios. Fuente separada del
// audit_log humano (decisión F4: no fusionar esquemas, solo lectura yuxtapuesta).
// ─────────────────────────────────────────────────────────────────────────────

/**
 * purpose (DB) → etiqueta operador es-CO. Cubre los propósitos reales que
 * services/ai-orchestrator + services/api escriben hoy (verificado 2026-07-04):
 *   agentic_flow, pii_update, contact_create, contact_update, sar_export,
 *   sar_export_printable, sic_report, contact_list_view, data_export.
 * Nuevos propósitos caen al fallback legible sin romper.
 */
export const PII_PURPOSE_LABELS: Record<string, string> = {
  data_export:          'Exportación de datos',
  sar_export:           'Solicitud del titular (SAR)',
  sar_export_printable: 'Solicitud del titular (impresa)',
  sic_report:           'Reporte a la SIC',
  contact_list_view:    'Vista del listado de contactos',
  contact_create:       'Alta de contacto',
  contact_update:       'Edición de contacto',
  pii_update:           'Actualización de datos personales',
  agentic_flow:         'Atención automatizada (bot)',
  wompi_checkout:       'Checkout de pago',
  inbox_view:           'Vista de conversación',
  order_create:         'Creación de pedido',
  support:              'Soporte',
}

/** fields_accessed[] (DB) → etiqueta es-CO de cada campo PII leído. */
export const PII_FIELD_LABELS: Record<string, string> = {
  name:            'Nombre',
  email:           'Correo',
  phone:           'Teléfono',
  document_number: 'Documento',
  address:         'Dirección',
}

/** Etiqueta es-CO de un purpose; fallback legible (sin guiones bajos). */
export function piiPurposeLabel(purpose: string): string {
  return PII_PURPOSE_LABELS[purpose] ?? purpose.replace(/_/g, ' ')
}

/** Etiqueta es-CO de un campo PII; fallback al identificador crudo. */
export function piiFieldLabel(field: string): string {
  return PII_FIELD_LABELS[field] ?? field.replace(/_/g, ' ')
}

/**
 * Descompone `accessed_by` ('user:<email>' | 'agent:...' | 'agentic_tool:...' |
 * 'integration:...') en un actor legible es-CO + su identificador crudo.
 */
export function describeActor(accessedBy: string): { kind: string; detail: string } {
  const idx = accessedBy.indexOf(':')
  const prefix = idx >= 0 ? accessedBy.slice(0, idx) : accessedBy
  const detail = idx >= 0 ? accessedBy.slice(idx + 1) : ''
  const kind =
    prefix === 'user'         ? 'Usuario del equipo'
    : prefix === 'agent'        ? 'Bot (orquestador)'
    : prefix === 'agentic_tool' ? 'Herramienta del bot'
    : prefix === 'integration'  ? 'Integración'
    : prefix
  return { kind, detail }
}
