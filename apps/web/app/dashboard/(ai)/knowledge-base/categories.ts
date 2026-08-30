/**
 * Categorías canónicas de la Base de Conocimiento (rev. 68 — fuente única).
 *
 * ANTES este enum vivía duplicado en page.tsx, doc-card.tsx y templates-section.tsx
 * con taxonomías divergentes ('politica'/'producto'/'general' pre-rev.68 en las
 * dos últimas) → editar un doc lo recategorizaba en silencio a FAQ y los badges
 * de plantillas renderizaban la clase literal 'undefined'. Centralizado aquí para
 * empatar EXACTAMENTE el CHECK constraint de DB y VALID_CATEGORIES del router
 * (services/api/routers/knowledge_base.py). El test categories.test.ts lo verifica.
 */
import {
  HelpCircle,
  Building2,
  FileText,
  Package,
  Truck,
  CreditCard,
  type LucideIcon,
} from 'lucide-react'

export interface KbCategory {
  value: string
  label: string
  icon: LucideIcon
}

// 6 categorías canónicas — mismo orden y valores que el CHECK constraint en DB.
export const KB_CATEGORIES: KbCategory[] = [
  { value: 'faq', label: 'FAQ', icon: HelpCircle },
  { value: 'negocio', label: 'Negocio', icon: Building2 },
  { value: 'politicas', label: 'Políticas', icon: FileText },
  { value: 'productos', label: 'Productos', icon: Package },
  { value: 'envios', label: 'Envíos', icon: Truck },
  { value: 'pagos', label: 'Pagos', icon: CreditCard },
]

export const KB_CATEGORY_VALUES: string[] = KB_CATEGORIES.map((c) => c.value)

export const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  KB_CATEGORIES.map((c) => [c.value, c.label]),
)

// Paleta founder: texto/border en shade 700; el bg 500/xx es solo tinte de fondo.
export const CATEGORY_COLORS: Record<string, string> = {
  faq: 'bg-info-bg text-info-fg border border-info-border',
  negocio: 'bg-success-bg text-success-fg border border-success-border',
  politicas: 'bg-ai-bg text-ai-fg border border-ai-border',
  productos: 'bg-warning-bg text-warning-fg border border-warning-border',
  envios: 'bg-success-bg text-success-fg border border-success-border',
  pagos: 'bg-warning-bg text-warning-fg border border-warning-border',
}

/** Clase de badge para una categoría; fallback neutro si llega un slug desconocido. */
export function categoryBadgeClass(value: string): string {
  return CATEGORY_COLORS[value] ?? 'bg-muted text-muted-foreground border border-border'
}

/** Etiqueta legible; fallback al slug crudo si es desconocido. */
export function categoryLabel(value: string): string {
  return CATEGORY_LABELS[value] ?? value
}
