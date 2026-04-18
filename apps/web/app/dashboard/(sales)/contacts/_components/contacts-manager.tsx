'use client'

import { useState, useMemo, useTransition } from 'react'
import { ShieldCheck, ShieldOff, Users, Phone, Search, Loader2, Trash2, MapPin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import AddressSelector from '@/components/address-selector'

type ContactAddress = {
  street?: string; number?: string; city?: string
  state?: string; country?: string; dane_code?: string
}

type Contact = {
  id: string
  phone: string
  name: string | null
  notes: string | null
  consent_given: boolean
  consent_date: string | null
  created_at: string
  address: ContactAddress | null
}

type Props = {
  initialContacts: Contact[]
  role: string
  canWrite: boolean
  addAction:    (fd: FormData) => Promise<void>
  editAction:   (fd: FormData) => Promise<void>
  deleteAction: (fd: FormData) => Promise<void>
}

const ITEMS_PER_PAGE = 30

export default function ContactsManager({ initialContacts, role, canWrite, addAction, editAction, deleteAction }: Props) {
  const [search, setSearch] = useState('')
  const [consentFilter, setConsentFilter] = useState('all')
  const [currentPage, setCurrentPage] = useState(1)
  const [isPending, startTransition] = useTransition()

  // Filtro en memoria
  const filteredContacts = useMemo(() => {
    let result = initialContacts
    
    // Status Filter
    if (consentFilter === 'yes') result = result.filter(c => c.consent_given)
    if (consentFilter === 'no') result = result.filter(c => !c.consent_given)

    // Text Filter
    const q = search.trim().toLowerCase()
    if (q) {
      result = result.filter(c => 
        (c.name?.toLowerCase().includes(q) ?? false) || c.phone.includes(q)
      )
    }

    return result
  }, [initialContacts, search, consentFilter])

  // Reset pagina al tipear
  useMemo(() => { setCurrentPage(1) }, [search, consentFilter])

  const totalPages = Math.ceil(filteredContacts.length / ITEMS_PER_PAGE) || 1
  const paginatedContacts = filteredContacts.slice(
    (currentPage - 1) * ITEMS_PER_PAGE,
    currentPage * ITEMS_PER_PAGE
  )

  const handleAdd = (fd: FormData) => {
    startTransition(async () => {
      await addAction(fd)
    })
  }

  const handleEdit = (fd: FormData) => {
    startTransition(async () => {
      await editAction(fd)
    })
  }

  const handleDelete = (fd: FormData) => {
    if (!confirm('¿Eliminar este contacto? Esta acción no se puede deshacer.')) return
    startTransition(async () => {
      await deleteAction(fd)
    })
  }

  return (
    <div className="space-y-4">
      {/* Búsqueda y Filtros */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Buscar por nombre o teléfono..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 text-sm rounded-xl border border-border bg-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="flex gap-1.5 overflow-x-auto pb-1">
          {[
            { value: 'all', label: 'Todos' },
            { value: 'yes', label: 'Con consent.' },
            { value: 'no',  label: 'Sin consent.' },
          ].map(opt => (
            <button
              key={opt.value}
              onClick={() => setConsentFilter(opt.value)}
              className={`flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                consentFilter === opt.value
                  ? 'bg-primary/15 text-primary border-primary/40'
                  : 'border-border text-muted-foreground hover:text-foreground hover:bg-accent'
              }`}
            >
              {opt.label}
            </button>
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
              <form action={handleAdd} className="space-y-3">
                <div className="space-y-1">
                  <Label className="text-xs">Teléfono *</Label>
                  <div className="flex">
                    <span className="inline-flex items-center px-2.5 h-9 border border-r-0 border-input rounded-l-md text-xs text-muted-foreground bg-muted select-none shrink-0">+57</span>
                    <Input
                      name="phone"
                      type="tel"
                      inputMode="numeric"
                      maxLength={10}
                      placeholder="3001234567"
                      className="rounded-l-none"
                      required
                      onInput={e => { const el = e.currentTarget; el.value = el.value.replace(/\D/g, '').slice(0, 10) }}
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Nombre</Label>
                  <Input name="name" placeholder="Juan García" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Notas</Label>
                  <Input name="notes" placeholder="Cliente frecuente..." />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs flex items-center gap-1"><MapPin className="h-3 w-3" /> Dirección de entrega</Label>
                  <AddressSelector fieldPrefix="addr" />
                </div>
                <label className="flex items-start gap-2 cursor-pointer">
                  <input type="checkbox" name="consent_given" className="h-4 w-4 mt-0.5 rounded" />
                  <span className="text-xs text-muted-foreground leading-snug">
                    El contacto autorizó el tratamiento de sus datos (Ley 1581)
                  </span>
                </label>
                <Button type="submit" disabled={isPending} className="w-full">
                  {isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Guardar contacto'}
                </Button>
              </form>
            </div>
          </div>
        )}

        {/* Lista */}
        <div className={canWrite ? 'xl:col-span-2' : 'xl:col-span-3'}>
          {paginatedContacts.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 rounded-xl border border-dashed border-border text-center">
              <Users className="h-10 w-10 text-muted-foreground/40 mb-3" />
              <p className="text-muted-foreground text-sm">
                {search ? `Sin resultados para "${search}"` : 'No hay contactos registrados.'}
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {paginatedContacts.map((c) => (
                <div key={c.id} className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 transition-all focus-within:border-primary/50">
                  <div className="flex items-start justify-between gap-3">
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
                              {c.consent_date && <span className="opacity-60">{new Date(c.consent_date).toLocaleDateString('es-CO')}</span>}
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                              <ShieldOff className="h-3 w-3" /> Sin consent.
                            </span>
                          )}
                        </div>
                        <p className="text-xs font-mono text-muted-foreground">
                          {c.phone.startsWith('+57') ? <><span className="text-muted-foreground/60">+57 </span>{c.phone.slice(3)}</> : c.phone}
                        </p>
                        {c.notes && <p className="text-xs text-muted-foreground mt-0.5 italic">{c.notes}</p>}
                        {c.address?.street && (
                          <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                            <MapPin className="h-3 w-3 shrink-0" />
                            {c.address.street}{c.address.city ? `, ${c.address.city}` : ''}
                          </p>
                        )}
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground shrink-0">
                      {new Date(c.created_at).toLocaleDateString('es-CO', { day: '2-digit', month: 'short' })}
                    </p>
                  </div>

                  {canWrite && (
                    <details className="mt-3">
                      <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground hover:text-primary select-none transition-colors">
                        Editar datos
                      </summary>
                      <form action={handleEdit} className="mt-3 space-y-3 pt-3 border-t border-border">
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
                        <div className="space-y-1">
                          <Label className="text-xs flex items-center gap-1"><MapPin className="h-3 w-3" /> Dirección de entrega</Label>
                          <AddressSelector fieldPrefix="addr" defaultValue={c.address ?? {}} />
                        </div>
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" name="consent_given" defaultChecked={c.consent_given} className="h-3.5 w-3.5 rounded" />
                          <span className="text-xs text-muted-foreground">Consentimiento Habeas Data</span>
                        </label>
                        <div className="flex items-center gap-2">
                          <Button type="submit" disabled={isPending} size="sm" variant="outline" className="h-7 text-xs">
                            {isPending ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : null} Guardar cambios
                          </Button>
                          <form action={handleDelete}>
                            <input type="hidden" name="contact_id" value={c.id} />
                            <Button type="submit" disabled={isPending} size="sm" variant="ghost" className="h-7 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10">
                              <Trash2 className="h-3 w-3 mr-1" /> Eliminar
                            </Button>
                          </form>
                        </div>
                      </form>
                    </details>
                  )}
                </div>
              ))}
              
              {/* Paginación */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between py-2 px-1 text-sm text-muted-foreground">
                  <span>Mostrando {(currentPage - 1) * ITEMS_PER_PAGE + 1} - {Math.min(currentPage * ITEMS_PER_PAGE, filteredContacts.length)} de {filteredContacts.length}</span>
                  <div className="flex items-center gap-1">
                    <Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>
                       <span>{'<'}</span>
                    </Button>
                    <span className="text-xs font-medium w-8 text-center">{currentPage}</span>
                    <Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>
                       <span>{'>'}</span>
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
