'use client'

import { useState, useMemo, useTransition, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { ShieldCheck, ShieldOff, Users, Phone, Search, Loader2, Trash2, MapPin, Mail, Pencil, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import AddressSelector from '@/components/address-selector'
import { validateColombianDocument } from '@/lib/validators/document'
import { validateAddress, type StructuredAddress, type BuildingType } from '@/lib/validators/address'
import HabeasDataActions from './habeas-data-actions'

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

type SarResult = {
  ok: boolean
  status: number
  type: string
  payload?: unknown
  error?: string
}

type Props = {
  initialContacts: Contact[]
  canWrite: boolean
  addAction:    (fd: FormData) => Promise<void>
  editAction:   (fd: FormData) => Promise<void>
  deleteAction: (fd: FormData) => Promise<void>
  sarAction?:   (fd: FormData) => Promise<SarResult>
  sarPrintableAction?: (fd: FormData) => Promise<{ ok: boolean; status: number; html?: string; error?: string }>
}

const ITEMS_PER_PAGE = 30

// Mismo formato que Inbox: +57 312 583 5649
const formatPhone = (raw: string): string => {
  const digits = (raw || '').replace(/\D/g, '')
  if (digits.startsWith('57') && digits.length === 12)
    return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`
  return digits ? `+${digits}` : (raw || '')
}

export default function ContactsManager({ initialContacts, canWrite, addAction, editAction, deleteAction, sarAction, sarPrintableAction }: Props) {
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

  // Validación cliente-side espejo del backend (services/api/dependencies/contact_validators.py).
  // Reglas oficiales: validateColombianDocument + validateAddress + addressRequiredFields.
  // Bloquea el submit ANTES de enviar al server para feedback inmediato.
  const validateFormData = (fd: FormData): string | null => {
    // 1) Documento: tipo + número juntos o ambos vacíos
    const docType = (fd.get('document_type') as string) || ''
    const docNumber = (fd.get('document_number') as string) || ''
    const docResult = validateColombianDocument(docType, docNumber)
    if (!docResult.ok) return docResult.error || 'Documento inválido'

    // 2) Address: building_type + sub-campos según tipo
    const addr: StructuredAddress = {
      street: (fd.get('addr_street') as string) || '',
      neighborhood: (fd.get('addr_neighborhood') as string) || '',
      city: (fd.get('addr_city') as string) || '',
      state: (fd.get('addr_state') as string) || '',
      dane_code: (fd.get('addr_dane_code') as string) || '',
      building_type: ((fd.get('addr_building_type') as string) || null) as BuildingType | null,
      tower: (fd.get('addr_tower') as string) || '',
      apartment: (fd.get('addr_apartment') as string) || '',
    }
    // Solo valido address si hay AL MENOS un campo de address presente
    // (el form permite crear contactos sin dirección — el bot la pide después).
    const hasAnyAddr = !!(addr.street || addr.city || addr.building_type)
    if (hasAnyAddr) {
      const addrResult = validateAddress(addr)
      if (!addrResult.ok) {
        return `Faltan campos de la dirección: ${addrResult.missing.join(', ')}.`
      }
    }
    return null
  }

  // Rev. 102 — ref al form de Agregar para limpiarlo tras save exitoso.
  // Sin esto, el operador queda con datos del último contacto guardado en
  // los inputs, lo que confunde y genera duplicados accidentales.
  const addFormRef = useRef<HTMLFormElement>(null)
  const [addressResetKey, setAddressResetKey] = useState(0)

  // Rev. 102 — toggle expand/collapse del panel de edición por contacto.
  // Antes era <details>/<summary> y la opción "Editar datos" quedaba oculta
  // como link gris pequeño. Ahora botón visible con icono Pencil.
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const toggleExpand = (id: string) => setExpandedId(prev => prev === id ? null : id)

  const router = useRouter()

  // Rev. 102 — feedback visual de éxito tras Guardar (no usamos modal
  // para no agregar fricción a la acción explícita del operador).
  // Banner verde efímero (3s) que confirma que la operación se ejecutó.
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const showSuccess = (msg: string) => {
    setSuccessMessage(msg)
    setTimeout(() => setSuccessMessage(null), 3500)
  }

  const handleAdd = (fd: FormData) => {
    const error = validateFormData(fd)
    if (error) {
      window.alert(`No se puede guardar: ${error}`)
      return
    }
    startTransition(async () => {
      await addAction(fd)
      addFormRef.current?.reset()
      setAddressResetKey(k => k + 1)
      router.refresh()
      showSuccess('Contacto guardado correctamente.')
    })
  }

  const handleEdit = (fd: FormData) => {
    const error = validateFormData(fd)
    if (error) {
      window.alert(`No se puede actualizar: ${error}`)
      return
    }
    startTransition(async () => {
      await editAction(fd)
      router.refresh()
      showSuccess('Cambios guardados correctamente.')
    })
  }

  // Rev. 102 — Eliminar ahora usa Dialog shadcn/ui (no `confirm()` nativo).
  // Coherente con el patrón de Anonimizar; warning visual destructivo.
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const pendingDeleteContact = useMemo(
    () => initialContacts.find(c => c.id === pendingDeleteId) ?? null,
    [initialContacts, pendingDeleteId],
  )
  const handleDeleteById = (contactId: string) => {
    setPendingDeleteId(contactId)
  }
  const confirmDelete = () => {
    if (!pendingDeleteId) return
    const fd = new FormData()
    fd.set('contact_id', pendingDeleteId)
    setPendingDeleteId(null)
    startTransition(async () => {
      await deleteAction(fd)
      router.refresh()
      showSuccess('Contacto eliminado.')
    })
  }

  // Rev. 102 — handlers SAR/printable movidos a <HabeasDataActions />
  // (apps/web/.../contacts/_components/habeas-data-actions.tsx). Allí está
  // la lógica de descargas + dialogs de confirmación + dialog (?) de info.
  // Aquí solo pasamos las server actions como props.

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
      {/* Rev. 102 — Banner efímero de éxito */}
      {successMessage && (
        <div
          role="status"
          aria-live="polite"
          className="fixed top-4 right-4 z-50 rounded-lg border border-emerald-700/50 bg-emerald-700/10 px-4 py-2.5 text-sm text-emerald-700 flex items-center gap-2 shadow-lg animate-in fade-in slide-in-from-top-2"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {successMessage}
        </div>
      )}

      {/* Rev. 102 — Dialog confirmación Eliminar (sustituye confirm() nativo) */}
      <Dialog
        open={pendingDeleteId !== null}
        onOpenChange={(o) => !o && setPendingDeleteId(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-700">
              <AlertTriangle className="h-5 w-5" />
              Eliminar contacto
            </DialogTitle>
            <DialogDescription>Esta acción es destructiva y no se puede deshacer.</DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              Vas a eliminar el contacto{' '}
              <strong className="text-foreground">
                {pendingDeleteContact?.name || 'sin nombre'}{' '}
                ({pendingDeleteContact ? formatPhone(pendingDeleteContact.phone) : ''})
              </strong>.
            </p>
            <div className="rounded-md border border-red-700/40 bg-red-700/5 p-2.5 text-xs text-red-700">
              <p className="font-semibold mb-1">Diferencia con &quot;Anonimizar&quot;:</p>
              <ul className="list-disc list-inside space-y-0.5">
                <li><strong>Eliminar</strong>: borra el contacto completo de la base. No queda registro Habeas Data.</li>
                <li><strong>Anonimizar</strong>: borra solo PII pero conserva el registro inmutable para auditoría legal.</li>
              </ul>
              <p className="mt-2">
                Si el motivo es una solicitud Habeas Data del titular, usa <strong>Anonimizar</strong> en lugar de Eliminar.
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setPendingDeleteId(null)}
              size="sm"
            >
              Cancelar
            </Button>
            <Button
              type="button"
              onClick={confirmDelete}
              size="sm"
              className="bg-red-700 hover:bg-red-800 text-white"
            >
              Sí, eliminar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
              <form ref={addFormRef} action={handleAdd} className="space-y-3">
                <div className="space-y-1">
                  <Label className="text-xs">Teléfono <span className="text-destructive">*</span></Label>
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
                  <Label className="text-xs">
                    Nombre completo <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Wompi y Envia lo requieren)</span>
                  </Label>
                  <Input name="name" placeholder="Juan García López" required />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">
                    Correo electrónico <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Wompi customer_data)</span>
                  </Label>
                  <Input name="email" type="email" placeholder="cliente@email.com" autoComplete="email" required />
                </div>
                {/* Documento de identidad — Wompi PSE/Bancolombia lo exigen en checkout */}
                <div className="grid grid-cols-3 gap-2">
                  <div className="space-y-1">
                    <Label className="text-xs">
                      Tipo doc. <span className="text-destructive">*</span>
                    </Label>
                    <select
                      name="document_type"
                      defaultValue=""
                      required
                      className="h-9 w-full rounded-md border border-input bg-transparent px-2 text-xs"
                    >
                      <option value="">— Selecciona —</option>
                      <option value="CC">CC (Cédula)</option>
                      <option value="CE">CE (Extranjería)</option>
                      <option value="NIT">NIT (Empresa)</option>
                      <option value="PP">PP (Pasaporte)</option>
                      <option value="TI">TI (Tarjeta Identidad)</option>
                      <option value="OTHER">Otro</option>
                    </select>
                  </div>
                  <div className="col-span-2 space-y-1">
                    <Label className="text-xs">
                      Número doc. <span className="text-destructive">*</span>
                    </Label>
                    <Input
                      name="document_number"
                      placeholder="1234567890"
                      required
                      pattern="[\d\-]+"
                      title="Solo dígitos. NIT acepta guion para dígito de verificación."
                    />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs flex items-center gap-1">
                    <MapPin className="h-3 w-3" /> Dirección de entrega <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Envia exige street + city + state + postal)</span>
                  </Label>
                  <AddressSelector key={addressResetKey} fieldPrefix="addr" showBuildingDetails />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Notas internas (opcional)</Label>
                  <Input name="notes" placeholder="Cliente frecuente..." />
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
                            <span className="flex items-center gap-1 text-[11px] text-emerald-700">
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
                          <p className="text-xs text-amber-700 mt-0.5">
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
                    <div className="mt-3">
                      <Button
                        type="button"
                        size="sm"
                        variant={expandedId === c.id ? 'default' : 'outline'}
                        className="h-7 text-xs gap-1.5"
                        onClick={() => toggleExpand(c.id)}
                      >
                        <Pencil className="h-3 w-3" />
                        {expandedId === c.id ? 'Cerrar edición' : 'Editar datos / Acciones Habeas Data'}
                      </Button>
                      {expandedId === c.id && (
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
                        {/* ── Acciones principales (guardar) ─────────────────── */}
                        <div className="flex items-center gap-2 pt-1">
                          <Button
                            type="submit"
                            disabled={isPending}
                            size="sm"
                            className="h-8 text-xs gap-1.5 px-3"
                          >
                            {isPending
                              ? <><Loader2 className="h-3 w-3 animate-spin" />Guardando...</>
                              : 'Guardar cambios'}
                          </Button>
                          <Button
                            type="button"
                            disabled={isPending}
                            size="sm"
                            variant="outline"
                            className="h-8 text-xs gap-1.5 px-3 border-red-700/50 text-red-700 hover:bg-red-700/10 hover:text-red-800 hover:border-red-700"
                            onClick={() => handleDeleteById(c.id)}
                          >
                            <Trash2 className="h-3 w-3" /> Eliminar
                          </Button>
                        </div>

                        {/* Rev. 102 — Acciones Habeas Data unificadas con (?) info + confirm dialogs */}
                        {sarAction && (
                          <HabeasDataActions
                            contactId={c.id}
                            contactDisplayName={
                              c.name
                                ? `${c.name} (${formatPhone(c.phone)})`
                                : formatPhone(c.phone)
                            }
                            sarAction={sarAction}
                            sarPrintableAction={sarPrintableAction}
                          />
                        )}
                      </form>
                      )}
                    </div>
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
