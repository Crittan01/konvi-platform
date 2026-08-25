'use client'

/**
 * Isla realtime del detalle de pedido (T7.4).
 *
 * El detalle es un Server Component (data fresca por request) pero NO se
 * actualizaba solo: el operador tenía que dar F5 para ver un pago confirmado
 * o una guía generada. Esta isla escucha los UPDATE de ESTA orden vía
 * postgres_changes y:
 *   1. celebra la transición a `confirmed`/`delivered` (micro-celebración de
 *      dinero — `money-celebration.tsx`, dedupe por evento), y
 *   2. hace `router.refresh()` para re-renderizar la data server-side.
 *
 * No renderiza nada. El filtro es por id de orden (RLS del canal lo acota al
 * tenant de la sesión).
 */
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/utils/supabase/client'
import { maybeCelebrateFromPayload } from '@/app/dashboard/money-celebration'

export function OrderStatusLive({ orderId }: { orderId: string }) {
  const router = useRouter()

  useEffect(() => {
    if (!orderId) return
    const supabase = createClient()
    const channel = supabase
      .channel(`order_live_${orderId}`)
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'orders', filter: `id=eq.${orderId}` },
        (payload) => {
          maybeCelebrateFromPayload(payload as never)
          router.refresh()
        },
      )
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [orderId, router])

  return null
}
