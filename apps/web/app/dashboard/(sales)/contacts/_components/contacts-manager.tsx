'use client'

import { useState, useMemo, useTransition, useEffect } from 'react'
import { ShieldCheck, ShieldOff, Users, Phone, Search, Loader2, Trash2, MapPin, Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import AddressSelector from '@/components/address-selector'

type ContactAddress = {
  street?: string; number?: string; city?: string
  state?: string; country?: string; dane_code?: string
  // Rev. 69 — schema canónico extendido
  neighborhood?: string
  building_type?: 'casa' | 'edificio' | 'conjunto'
  tower?: string
  apartment?: string
  complex_name?: string
  reference?: string
}

type Contact = {
  id: string
  phone: string
  name: string | null
  email: string | null
  notes: string | null
  document_type?: string | null   // rev. 69 — CC/CE/NIT/PP/TI/OTHER
  document_number?: string | null // rev. 69
  consent_given: boolean
  consent_date: string | null
  consent_source?: string | null
  consent_notice_version?: string | null
  consent_evidence?: Record<string, unknown> | null
  consent_actor_email?: string | null
  consent_revoked_at?: string | null
  consent_revoked_reason?: string | null
  created_at: string
  address: ContactAddress | null
}

type Props = {
  initialContacts: Contact[]
  canWrite: boolean
  addAction:    (fd: FormData) => Promise<void>
  editAction:   (fd: FormData) => Promise<void>
  deleteAction: (fd: FormData) => Promise<void>
}

const ITEMS_PER_PAGE = 30

// Mismo formato que Inbox: +57 312 583 5649
const formatPhone = (raw: string): string => {
  const digits = (raw || '').replace(/\D/g, '')
  if (digits.startsWith('57') && digits.length === 12)
    return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`
  return digits ? `+${digits}` : (raw || '')
}

export default function ContactsManager({ initialContacts, canWrite, addAction, editAction, deleteAction }: Props) {
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
        (c.name?.toLowerCase().includes(q) ?? false) ||
        c.phone.includes(q) ||
        (c.email?.toLowerCase().includes(q) ?? false)
      )
    }

    return result
  }, [initialContacts, search, consentFilter])

  // Reset página cuando cambian filtros
  useEffect(() => { setCurrentPage(1) }, [search, consentFilter])

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

  const handleDeleteById = (contactId: string) => {
    const fd = new FormData()
    fd.set('contact_id', contactId)
    handleDelete(fd)
  }

  const extractEvidenceNote = (evidence: Contact['consent_evidence']): string | null => {
    if (!evidence || typeof evidence !== 'object') return null
    const rootNote = evidence.note
    if (typeof rootNote === 'string' && rootNote.trim()) return rootNote.trim()
    const lastUpdate = evidence.last_update as Record<string, unknown> | undefined
    const nestedNote = lastUpdate?.note
    if (typeof nestedNote === 'string' && nestedNote.trim()) return nestedNote.trim()
    return null
  }

  return (
    <div className="space-y-4">
      {/* Búsqueda y Filtros */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Buscar por nombre, teléfono o email..."
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
                  <Label className="text-xs">Email</Label>
                  <Input name="email" type="email" placeholder="cliente@email.com" autoComplete="email" />
                </div>
                {/* Rev. 69 — Documento de identidad (Wompi pre-fill checkout) */}
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Tipo doc.</Label>
                    <select
                      name="document_type"
                      defaultValue=""
                      className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                    >
                      <option value="">—</option>
                      <option value="CC">CC</option>
                      <option value="CE">CE</option>
                      <option value="NIT">NIT</option>
                      <option value="PP">PP</option>
                      <option value="TI">TI</option>
                      <option value="OTHER">Otro</option>
                    </select>
                  </div>
                  <div className="col-span-2 space-y-1">
                    <Label className="text-xs">Número doc.</Label>
                    <Input name="document_number" placeholder="1.234.567.890" />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Notas</Label>
                  <Input name="notes" placeholder="Cliente frecuente..." />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs flex items-center gap-1"><MapPin className="h-3 w-3" /> Dirección de entrega</Label>
                  <AddressSelector fieldPrefix="addr" showBuildingDetails />
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">Canal de consentimiento</Label>
                    <select
                      name="consent_source"
                      className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                      defaultValue="manual_console"
                    >
                      <option value="manual_console">Consola</option>
                      <option value="whatsapp">WhatsApp</option>
                      <option value="web_form">Formulario web</option>
                      <option value="phone_call">Llamada</option>
                      <option value="in_person">Presencial</option>
                      <option value="import">Importación</option>
                      <option value="other">Otro</option>
                    </select>
                  </div>
                  <div className="space-y-1">
                    <Label className="text-xs">Versión aviso/política</Label>
                    <Input name="consent_notice_version" placeholder="v2026-04" className="h-8 text-xs" />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Evidencia (nota interna)</Label>
                  <Input name="consent_evidence_note" placeholder="Ej: autorizó por chat y aceptó política" className="h-8 text-xs" />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Razón de revocatoria (si aplica)</Label>
                  <Input name="consent_revoked_reason" placeholder="Ej: solicitó eliminación de datos" className="h-8 text-xs" />
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
                              <ShieldOff className="h-3 w-3" />
                              {c.consent_revoked_at ? 'Revocado' : 'Sin consent.'}
                            </span>
                          )}
                        </div>
                        <p className="text-xs font-mono text-muted-foreground">
                          {formatPhone(c.phone)}
                        </p>
                        {c.email && (
                          <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                            <Mail className="h-3 w-3 shrink-0" />
                            {c.email}
                          </p>
                        )}
                        {c.notes && <p className="text-xs text-muted-foreground mt-0.5 italic">{c.notes}</p>}
                        {(c.consent_source || c.consent_notice_version) && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {c.consent_source ? `Canal: ${c.consent_source}` : ''}
                            {c.consent_source && c.consent_notice_version ? ' · ' : ''}
                            {c.consent_notice_version ? `Aviso: ${c.consent_notice_version}` : ''}
                          </p>
                        )}
                        {c.consent_revoked_at && (
                          <p className="text-xs text-amber-400 mt-0.5">
                            Revocado: {new Date(c.consent_revoked_at).toLocaleDateString('es-CO')}
                            {c.consent_revoked_reason ? ` · ${c.consent_revoked_reason}` : ''}
                          </p>
                        )}
                        {extractEvidenceNote(c.consent_evidence) && (
                          <p className="text-xs text-muted-foreground/80 mt-0.5">
                            Evidencia: {extractEvidenceNote(c.consent_evidence)}
                          </p>
                        )}
                        {c.document_type && c.document_number && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            Doc: <span className="font-mono">{c.document_type} {c.document_number}</span>
                          </p>
                        )}
                        {c.address?.street && (
                          <p className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                            <MapPin className="h-3 w-3 shrink-0" />
                            {c.address.street}
                            {c.address.neighborhood ? `, ${c.address.neighborhood}` : ''}
                            {c.address.city ? `, ${c.address.city}` : ''}
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
                            <Label className="text-xs">Email</Label>
                            <Input name="email" type="email" defaultValue={c.email ?? ''} className="h-8 text-xs" autoComplete="email" />
                          </div>
                        </div>
                        {/* Rev. 69 — Documento de identidad (edición) */}
                        <div className="grid grid-cols-3 gap-2">
                          <div className="space-y-1">
                            <Label className="text-xs">Tipo doc.</Label>
                            <select
                              name="document_type"
                              defaultValue={c.document_type ?? ''}
                              className="h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                            >
                              <option value="">—</option>
                              <option value="CC">CC</option>
                              <option value="CE">CE</option>
                              <option value="NIT">NIT</option>
                              <option value="PP">PP</option>
                              <option value="TI">TI</option>
                              <option value="OTHER">Otro</option>
                            </select>
                          </div>
                          <div className="col-span-2 space-y-1">
                            <Label className="text-xs">Número doc.</Label>
                            <Input name="document_number" defaultValue={c.document_number ?? ''} className="h-8 text-xs" />
                          </div>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-xs">Notas</Label>
                            <Input name="notes" defaultValue={c.notes ?? ''} className="h-8 text-xs" />
                          </div>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs flex items-center gap-1"><MapPin className="h-3 w-3" /> Dirección de entrega</Label>
                          <AddressSelector fieldPrefix="addr" defaultValue={c.address ?? {}} showBuildingDetails />
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-xs">Canal de consentimiento</Label>
                            <select
                              name="consent_source"
                              defaultValue={c.consent_source ?? 'manual_console'}
                              className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                            >
                              <option value="manual_console">Consola</option>
                              <option value="whatsapp">WhatsApp</option>
                              <option value="web_form">Formulario web</option>
                              <option value="phone_call">Llamada</option>
                              <option value="in_person">Presencial</option>
                              <option value="import">Importación</option>
                              <option value="other">Otro</option>
                            </select>
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">Versión aviso/política</Label>
                            <Input
                              name="consent_notice_version"
                              defaultValue={c.consent_notice_version ?? ''}
                              className="h-8 text-xs"
                            />
                          </div>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Evidencia (nota interna)</Label>
                          <Input
                            name="consent_evidence_note"
                            defaultValue={extractEvidenceNote(c.consent_evidence) ?? ''}
                            className="h-8 text-xs"
                          />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Razón de revocatoria (si aplica)</Label>
                          <Input
                            name="consent_revoked_reason"
                            defaultValue={c.consent_revoked_reason ?? ''}
                            className="h-8 text-xs"
                          />
                        </div>
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input type="checkbox" name="consent_given" defaultChecked={c.consent_given} className="h-3.5 w-3.5 rounded" />
                          <span className="text-xs text-muted-foreground">Consentimiento Habeas Data</span>
                        </label>
                        <div className="flex items-center gap-2">
                          <Button type="submit" disabled={isPending} size="sm" variant="outline" className="h-7 text-xs gap-1.5">
                            {isPending ? <><Loader2 className="h-3 w-3 animate-spin" />Guardando...</> : 'Guardar cambios'}
                          </Button>
                          <Button
                            type="button"
                            disabled={isPending}
                            size="sm"
                            variant="ghost"
                            className="h-7 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10"
                            onClick={() => handleDeleteById(c.id)}
                          >
                            <Trash2 className="h-3 w-3 mr-1" /> Eliminar
                          </Button>
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
