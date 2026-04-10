import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ShieldCheck, ShieldOff, Users, Phone, Search } from 'lucide-react'

type Contact = {
  id: string
  phone: string
  name: string | null
  notes: string | null
  consent_given: boolean
  consent_date: string | null
  created_at: string
}

export default async function ContactsPage({
  searchParams,
}: {
  searchParams?: { q?: string; consent?: string }
}) {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()
  const meta = (user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const canWrite = role === 'owner' || role === 'manager'

  const q = searchParams?.q ?? ''
  const consentFilter = searchParams?.consent ?? 'all'

  let contacts: Contact[] = []

  if (tenantId) {
    let query = supabase
      .from('contacts')
      .select('id, phone, name, notes, consent_given, consent_date, created_at')
      .eq('tenant_id', tenantId)
      .order('name', { ascending: true, nullsFirst: false })

    if (consentFilter === 'yes') query = query.eq('consent_given', true)
    if (consentFilter === 'no')  query = query.eq('consent_given', false)

    const { data } = await query
    contacts = (data as Contact[]) || []
  }

  // Filtro en memoria para búsqueda de texto (phone/name)
  const filtered = q
    ? contacts.filter(c =>
        (c.name?.toLowerCase().includes(q.toLowerCase()) ?? false) ||
        c.phone.includes(q)
      )
    : contacts

  const consentCount = contacts.filter(c => c.consent_given).length

  // ── Server Actions ─────────────────────────────────────────────────────────

  async function addContact(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    const m = (u?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || !['owner', 'manager'].includes(m.role ?? '')) return
    const consentGiven = formData.get('consent_given') === 'on'
    await sb.from('contacts').insert({
      tenant_id:     m.tenant_id,
      phone:         formData.get('phone') as string,
      name:          (formData.get('name') as string) || null,
      notes:         (formData.get('notes') as string) || null,
      consent_given: consentGiven,
      consent_date:  consentGiven ? new Date().toISOString() : null,
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
    await sb.from('contacts').update({
      name:          (formData.get('name') as string) || null,
      notes:         (formData.get('notes') as string) || null,
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

      {/* Habeas Data notice */}
      <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 px-4 py-3 text-sm text-blue-400 flex items-start gap-2">
        <ShieldCheck className="h-4 w-4 shrink-0 mt-0.5" />
        <span>
          <span className="font-semibold">Habeas Data — Ley 1581/2012 Colombia.</span>{' '}
          El campo <em>consentimiento</em> registra si el titular autorizó el tratamiento. El tenant es el Responsable ante la SIC.
        </span>
      </div>

      {/* Búsqueda y filtros */}
      <div className="flex flex-col sm:flex-row gap-3">
        <form method="GET" className="flex gap-2 flex-1">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              name="q"
              defaultValue={q}
              placeholder="Buscar por nombre o teléfono..."
              className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border border-border bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          {consentFilter !== 'all' && <input type="hidden" name="consent" value={consentFilter} />}
          <Button type="submit" size="sm" variant="outline">Buscar</Button>
        </form>
        <div className="flex gap-1.5">
          {[
            { value: 'all', label: 'Todos' },
            { value: 'yes', label: '✅ Con consent.' },
            { value: 'no',  label: '⚠️ Sin consent.' },
          ].map(opt => (
            <a
              key={opt.value}
              href={`/dashboard/contacts?consent=${opt.value}${q ? `&q=${encodeURIComponent(q)}` : ''}`}
              className={`flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                consentFilter === opt.value
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'border-border text-muted-foreground hover:text-foreground'
              }`}
            >
              {opt.label}
            </a>
          ))}
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">

        {/* Formulario agregar */}
        {canWrite && (
          <div className="xl:col-span-1">
            <div className="rounded-xl border border-border bg-card p-5">
              <h2 className="font-semibold text-base mb-4">Agregar Contacto</h2>
              <form action={addContact} className="space-y-3">
                <div className="space-y-1">
                  <Label className="text-xs">Teléfono *</Label>
                  <Input name="phone" placeholder="+52 55 1234 5678" required />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Nombre</Label>
                  <Input name="name" placeholder="Juan García" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Notas</Label>
                  <Input name="notes" placeholder="Cliente frecuente..." />
                </div>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" name="consent_given" className="h-4 w-4 mt-0.5 rounded" />
                  <span className="text-xs text-muted-foreground leading-snug">
                    El contacto autorizó el tratamiento de sus datos (Habeas Data — Ley 1581/2012)
                  </span>
                </label>
                <Button type="submit" className="w-full">Guardar contacto</Button>
              </form>
            </div>
          </div>
        )}

        {/* Lista */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 rounded-xl border border-dashed border-border text-center">
              <Users className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm">
                {q ? `Sin resultados para "${q}"` : 'No hay contactos registrados.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {filtered.map((c) => (
                <div key={c.id} className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 transition-all">
                  <div className="flex items-start justify-between gap-3">
                    {/* Datos principales */}
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className="h-9 w-9 rounded-full bg-primary/15 flex items-center justify-center shrink-0 font-semibold text-primary text-sm">
                        {c.name ? c.name.charAt(0).toUpperCase() : <Phone className="h-4 w-4" />}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-medium text-sm">{c.name ?? <span className="text-muted-foreground italic">Sin nombre</span>}</p>
                          {c.consent_given ? (
                            <span className="flex items-center gap-1 text-[11px] text-emerald-400">
                              <ShieldCheck className="h-3 w-3" /> Consent.{' '}
                              {c.consent_date && <span className="opacity-60">{new Date(c.consent_date).toLocaleDateString('es-MX')}</span>}
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                              <ShieldOff className="h-3 w-3" /> Sin consent.
                            </span>
                          )}
                        </div>
                        <p className="text-xs font-mono text-muted-foreground">{c.phone}</p>
                        {c.notes && <p className="text-xs text-muted-foreground mt-0.5 italic">{c.notes}</p>}
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground shrink-0">
                      {new Date(c.created_at).toLocaleDateString('es-MX', { day: '2-digit', month: 'short' })}
                    </p>
                  </div>

                  {/* Edición inline */}
                  {canWrite && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-xs text-muted-foreground hover:text-primary select-none transition-colors">
                        ✏️ Editar datos
                      </summary>
                      <form action={editContact} className="mt-3 space-y-3 pt-3 border-t border-border">
                        <input type="hidden" name="contact_id" value={c.id} />
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-xs">Nombre</Label>
                            <Input name="name" defaultValue={c.name ?? ''} className="h-8 text-xs" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">Notas</Label>
                            <Input name="notes" defaultValue={c.notes ?? ''} className="h-8 text-xs" />
                          </div>
                        </div>
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" name="consent_given" defaultChecked={c.consent_given} className="h-3.5 w-3.5 rounded" />
                          <span className="text-xs text-muted-foreground">Consentimiento de tratamiento de datos otorgado</span>
                        </label>
                        <Button type="submit" size="sm" variant="outline" className="h-7 text-xs">Guardar cambios</Button>
                      </form>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
