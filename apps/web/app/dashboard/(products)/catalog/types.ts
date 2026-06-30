// Tipos compartidos del módulo Catálogo
// Definidos en un solo lugar para evitar duplicación entre page.tsx y catalog-table.tsx

export interface Variation {
  id: string
  sku: string | null
  price: number
  compare_at_price: number | null
  stock_quantity: number
  attributes: Record<string, string> | null
  weight_kg: number | null
  length_cm: number | null
  width_cm: number | null
  height_cm: number | null
  image_url: string | null
  cost_price: number | null
}

export interface Product {
  id: string
  title: string
  description: string | null
  safety_note: string | null
  cover_image_url: string | null
  platform_category_id: string | null
  category_id: string | null  // ADR-0027 categoría operativa per-tenant (la que usa el bot)
  product_variations: Variation[]
  // Rev. 109 backlog #1 — Retracto categories multi-tenant.
  // Tenant marca productos excluidos del Art. 47 Ley 1480 parágrafo
  // (cosmética abierta, software descargable, perecederos, etc.).
  retracto_excluded?: boolean | null
  retracto_excluded_reason?: string | null
}

export interface Category {
  id: string
  name: string
}
