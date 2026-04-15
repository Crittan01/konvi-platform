import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Package, Clock, ChevronRight, Plus, Hourglass, CheckCircle2, Settings2, MapPin, X, LayoutList } from 'lucide-react'
import OrdersNewForm from './orders-new-form'
import OrdersManager from './_components/orders-manager'
import Link from 'next/link'
import AiInsightPanel from '@/components/ai-insight-panel'

type Variation = { id: string; price: number | null; attributes: Record<string, string> | null }
type Product   = { id: string; title: string; product_variations: Variation[] }
type Contact   = { id: string; phone: string; name: string | null }
type OrderItem = { title: string; quantity: number; unit_price: number }
type Order = {
  id: string
  status: string
  total_amount: number
  notes: string | null
  created_at: string
  contacts: Contact | Contact[] | null
  order_items: OrderItem[]
}

const STATUS_LABELS: Record<string, string> = {
  pending:    'Pendiente',
  confirmed:  'Confirmado',
  processing: 'En proceso',
  shipped:    'Enviado',
  delivered:  'Entregado',
  cancelled:  'Cancelado',
}

const STATUS_NEXT: Record<string, string> = {
  pending:    'confirmed',
  confirmed:  'processing',
  processing: 'shipped',
  shipped:    'delivered',
}

const STATUS_COLORS: Record<string, string> = {
  pending:    'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',
  confirmed:  'bg-blue-500/15 text-blue-400 border-blue-500/30',
  processing: 'bg-purple-500/15 text-purple-400 border-purple-500/30',
  shipped:    'bg-indigo-500/15 text-indigo-400 border-indigo-500/30',
  delivered:  'bg-green-500/15 text-green-400 border-green-500/30',
  cancelled:  'bg-red-500/15 text-red-400 border-red-500/30',
}

const STATUS_ICONS: Record<string, React.ElementType> = {
  all:        LayoutList,
  pending:    Hourglass,
  confirmed:  CheckCircle2,
  processing: Settings2,
  shipped:    Package,
  delivered:  MapPin,
  cancelled:  X,
}

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'https://commerce-ops-api.onrender.com'

export default async function OrdersPage({
  searchParams,
}: {
  searchParams?: { status?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  const filterStatus = searchParams?.status ?? 'all'

  let orders: Order[] = []
  let products: Product[] = []
  let contacts: Contact[] = []
  let counts: Record<string, number> = {}

  if (tenantId) {
    const [ordersRes, productsRes, contactsRes, allOrdersRes] = await Promise.all([
      supabase
        .from('orders')
        .select('id, status, total_amount, notes, created_at, contacts(id, phone, name), order_items(title, quantity, unit_price)')
        .eq('tenant_id', tenantId)
        .order('created_at', { ascending: false })
        .limit(100),
      supabase
        .from('products')
        .select('id, title, product_variations(id, price, attributes)')
        .eq('tenant_id', tenantId)
        .eq('status', 'active'),
      supabase
        .from('contacts')
        .select('id, phone, name')
        .eq('tenant_id', tenantId)
        .order('name'),
      supabase
        .from('orders')
        .select('status')
        .eq('tenant_id', tenantId),
    ])

    const allOrders = (allOrdersRes.data as unknown as { status: string }[]) || []
    counts = allOrders.reduce((acc, o) => {
      acc[o.status] = (acc[o.status] ?? 0) + 1
      return acc
    }, {} as Record<string, number>)
    counts['all'] = allOrders.length

    let fetched = (ordersRes.data as unknown as Order[]) || []
    if (filterStatus !== 'all') {
      fetched = fetched.filter(o => o.status === filterStatus)
    }
    orders = fetched
    products = (productsRes.data as Product[]) || []
    contacts = (contactsRes.data as Contact[]) || []
  }

  // ── Server Actions ────────────────────────────────────────────────────────
  async function updateOrderStatus(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    
    const orderId = formData.get('order_id') as string
    const isCancel = formData.get('cancel') === 'true'
    const nextStatus = formData.get('next_status') as string
    
    if (isCancel) {
      await sb.from('orders').update({ status: 'cancelled' })
        .eq('id', orderId)
        .eq('tenant_id', m.tenant_id)
      revalidatePath('/dashboard/orders')
      return
    }

    const { data: { session: s } } = await sb.auth.getSession()
    const token = s?.access_token
    if (!token) return
    
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 15000)
      await fetch(`${API_URL}/api/v1/orders/${orderId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
        body: JSON.stringify({ status: nextStatus }),
        signal: ctrl.signal,
      })
      clearTimeout(timeout)
    } catch { /* non-fatal */ }
    
    revalidatePath('/dashboard/orders')
  }

  // ── UI ────────────────────────────────────────────────────────────────────
  return (
    <OrdersManager
      initialOrders={orders}
      products={products}
      contacts={contacts}
      role={role}
      canWrite={canWrite}
      apiUrl={API_URL}
      updateStatusAction={updateOrderStatus}
    />
  )
}
