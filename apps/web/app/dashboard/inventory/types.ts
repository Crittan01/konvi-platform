export type Variation = {
  id: string
  attributes: Record<string, string> | null
  stock_quantity: number
  price: number
  sku?: string | null // sku might be useful for search
}

export type Product = {
  id: string
  title: string
  status: string
  product_variations: Variation[]
}

export type Movement = {
  id: string
  delta: number
  new_stock: number
  reason: string | null
  created_at: string
  variation_id: string
}
