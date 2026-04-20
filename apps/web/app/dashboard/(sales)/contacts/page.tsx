import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ShieldCheck, ShieldOff, Users, Phone, Search } from 'lucide-react'
import AiInsightPanel from '@/components/ai-insight-panel'
import ContactsManager from './_components/contacts-manager'

type Contact = {
  id: string
  phone: string
  name: string | null
  notes: string | null
  consent_given: boolean
  consent_date: string | null
  created_at: string
  address: Record<string, string> | null
}

export default async function ContactsPage({
  searchParams,
}: {
  searchParams?: { q?: string; consent?: string }
}) {
  const normalizeDaneCode = (raw?: string | null) => {
    const digits = String(raw ?? '').replace(/\D/g, '')
    if (digits.length === 8 && digits.endsWith('000')) return digits.slice(0, 5)
    return digits.slice(0, 5)
  }

  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'operator'
  const canWrite = role === 'owner' || role === 'manager'

  const q = searchParams?.q ?? ''
  const consentFilter = searchParams?.consent ?? 'all'

  let contacts: Contact[] = []

  if (tenantId) {
    let query = supabase
      .from('contacts')
      .select('id, phone, name, notes, consent_given, consent_date, created_at, address')
      .eq('tenant_id', tenantId)
      .order('name', { ascending: true, nullsFirst: false })

    if (consentFilter === 'yes') query = query.eq('consent_given', true)
    if (consentFilter === 'no')  query = query.eq('consent_given', false)

    const { data } = await query
    contacts = (data as Contact[]) || []
  }

  // Filtros iniciales ya no se hacen de forma ruda en query,
  // traemos los primeros 500 contactos para que paginen local.
  // Solo la búsqueda full server haría falta si la DB crece mucho, pero por ahora en memoria es Nivel Pro.

  const consentCount = contacts.filter(c => c.consent_given).length

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function addContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const consentGiven = formData.get('consent_given') === 'on'
    const street   = (formData.get('addr_street') as string) || null
    const addrCity = (formData.get('addr_city')   as string) || null
    const daneCode = normalizeDaneCode(formData.get('addr_dane_code') as string)
    const address  = street ? {
      street,
      number:    (formData.get('addr_number')   as string) || undefined,
      city:      addrCity,
      state:     (formData.get('addr_state')    as string) || undefined,
      country:   'CO',
      dane_code: daneCode || undefined,
    } : null
    const digits = ((formData.get('phone') as string) ?? '').replace(/\D/g, '').slice(0, 10)
    await sb.from('contacts').insert({
      tenant_id:     m.tenant_id,
      phone:         `+57${digits}`,
      name:          (formData.get('name') as string) || null,
      notes:         (formData.get('notes') as string) || null,
      consent_given: consentGiven,
      consent_date:  consentGiven ? new Date().toISOString() : null,
      address,
    })
    revalidatePath('/dashboard/contacts')
  }

  async function editContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const consentGiven = formData.get('consent_given') === 'on'
    const { data: existing } = await sb.from('contacts')
      .select('consent_given, consent_date')
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
      .single()
    const prev = (existing as { consent_given?: boolean; consent_date?: string | null } | null)
    const street   = (formData.get('addr_street') as string) || null
    const addrCity = (formData.get('addr_city')   as string) || null
    const daneCode = normalizeDaneCode(formData.get('addr_dane_code') as string)
    const address  = street ? {
      street,
      number:    (formData.get('addr_number')    as string) || undefined,
      city:      addrCity,
      state:     (formData.get('addr_state')     as string) || undefined,
      country:   'CO',
      dane_code: daneCode || undefined,
    } : null
    await sb.from('contacts').update({
      name:          (formData.get('name') as string) || null,
      notes:         (formData.get('notes') as string) || null,
      address,
      consent_given: consentGiven,
      consent_date:  consentGiven && !prev?.consent_given
        ? new Date().toISOString()
        : consentGiven
          ? (prev?.consent_date ?? new Date().toISOString())
          : null,
    })
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/contacts')
  }

  async function deleteContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    await sb.from('contacts')
      .delete()
      .eq('id', formData.get('contact_id') as string)
      .eq('tenant_id', m.tenant_id)
    revalidatePath('/dashboard/contacts')
  }

  // ── UI ─────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Users className="h-5 w-5 text-primary" /> Contactos
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            {contacts.length} contactos · {consentCount} con consentimiento Habeas Data
          </p>
        </div>
      </div>

      {/* AI Insight — a demanda */}
      {(meta.role === 'owner' || meta.role === 'manager') && (
        <AiInsightPanel module="contacts" label="Contactos" />
      )}

      {/* Habeas Data notice */}
      <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-3 text-sm text-blue-400 flex items-start gap-2">
        <ShieldCheck className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          <span className="font-semibold">Habeas Data — Ley 1581/2012 Colombia.</span>{' '}
          El campo <em>consentimiento</em> registra si el titular autorizó el tratamiento. El tenant es el Responsable ante la SIC.
        </span>
      </div>

      <ContactsManager 
        initialContacts={contacts}
        role={role}
        canWrite={canWrite}
        addAction={addContact}
        editAction={editContact}
        deleteAction={deleteContact}
      />
    </div>
  )
}
