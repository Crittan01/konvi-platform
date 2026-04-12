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
}

export interface Product {
  id: string
  title: string
  description: string | null
  cover_image_url: string | null
  platform_category_id: string | null
  product_variations: Variation[]
}

export interface Category {
  id: string
  name: string
}
