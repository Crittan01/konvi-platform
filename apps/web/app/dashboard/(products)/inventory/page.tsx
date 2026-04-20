import { redirect } from 'next/navigation'

export default function LegacyInventoryPage() {
  redirect('/dashboard/catalog')
}
