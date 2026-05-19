'use client'

import { useState, useMemo, useTransition, useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { ShieldCheck, ShieldOff, Users, Phone, Search, Loader2, Trash2, MapPin, Mail, Pencil, AlertTriangle, CheckCircle2, Paperclip, ExternalLink } from 'lucide-react'
import { getConsentEvidenceSignedUrl } from './helpers/upload-evidence'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import AddressSelector from '@/components/address-selector'
import { validateColombianDocument } from '@/lib/validators/document'
import { validateAddress, type StructuredAddress, type BuildingType, type ConjuntoType, type DeliveryContext } from '@/lib/validators/address'
import HabeasDataActions from './habeas-data-actions'
import DocumentFields, { type DocType } from './document-fields'
import { PHONE_COUNTRIES, formatPhone } from './helpers/phone-countries'
import { CONSENT_SOURCE_HELP } from './helpers/consent-source-help'

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
  // Sem 7 F2 cierre 2026-05-19 — sub-modalidades address
  conjunto_type?: 'torres' | 'casas'
  delivery_context?: 'residencia' | 'oficina' | 'otro'
  company_name?: string
}

type Contact = {
  id: string
  phone: string
  shipping_phone?: string | null   // rev. 103 — phone alternativo de envío
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
  // Rev. 105 H.4.1.x — Reactivar consent tras soft opt-out (STOP keyword).
  reactivateConsentAction?: (fd: FormData) => Promise<{ ok: boolean; status: number; message: string }>
  // Rev. 105 H.4.1.x.gov — userRole para gobierno regulatorio: reactivar
  // consent es owner-only (Habeas Data ART. 11).
  userRole?: string
  deleteAction: (fd: FormData) => Promise<void>
  sarAction?:   (fd: FormData) => Promise<SarResult>
  sarPrintableAction?: (fd: FormData) => Promise<{ ok: boolean; status: number; html?: string; error?: string }>
}

const ITEMS_PER_PAGE = 30

// Rev. 103 (F10) — Card visible que muestra que el contact tiene evidencia
// física adjunta + botón "Ver archivo" que genera signed URL on-demand
// (5 min TTL). Bucket privado obliga a este patrón: getPublicUrl() devuelve
// 404 contra buckets privados.
function ExistingAttachmentCard({
  contactId,
  mime,
  size,
  uploadedAt,
}: {
  contactId: string
  mime: string | null
  size: number | null
  uploadedAt: string | null
}) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const handleView = async () => {
    setError(null)
    setLoading(true)
    try {
      const result = await getConsentEvidenceSignedUrl(contactId)
      if ('url' in result) {
        window.open(result.url, '_blank', 'noopener,noreferrer')
      } else {
        setError(result.error)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al generar URL')
    } finally {
      setLoading(false)
    }
  }
  const sizeKb = size != null ? Math.max(1, Math.round(size / 1024)) : null
  const mimeShort = mime?.replace('application/', '').replace('image/', '').toUpperCase() ?? '—'
  return (
    <div className="rounded-md border border-emerald-700/40 bg-emerald-700/5 p-2.5 space-y-1.5">
      <div className="flex items-center gap-2">
        <Paperclip className="h-3.5 w-3.5 text-emerald-700 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-emerald-700">Evidencia física adjunta</p>
          <p className="text-[10px] text-muted-foreground">
            {mimeShort}{sizeKb != null && ` · ${sizeKb} KB`}
            {uploadedAt && ` · subida ${new Date(uploadedAt).toLocaleDateString('es-CO')}`}
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-7 gap-1 text-xs"
          onClick={handleView}
          disabled={loading}
        >
          {loading ? <Loader2 className="h-3 w-3 animate-spin" /> : <ExternalLink className="h-3 w-3" />}
          Ver archivo
        </Button>
      </div>
      {error && (
        <p className="text-[10px] text-destructive">No se pudo abrir: {error}</p>
      )}
      <p className="text-[10px] text-muted-foreground">
        Si subes otro archivo abajo, se reemplaza.
      </p>
    </div>
  )
}

// Mismo formato que Inbox: +57 312 583 5649. Rev. 102: detección
// de country code. Para CO formato bonito; otros países muestra +N+digits.
export default function ContactsManager({ initialContacts, canWrite, userRole, addAction, editAction, deleteAction, sarAction, sarPrintableAction, reactivateConsentAction }: Props) {
  const isOwner = userRole === 'owner'
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
    // Sem 7 F2 cierre — `conjunto_type` (torres|casas) y `delivery_context`
    // (residencia|oficina|otro) son sub-modalidades ortogonales documentadas
    // en lib/validators/address.ts.
    const addr: StructuredAddress = {
      street: (fd.get('addr_street') as string) || '',
      neighborhood: (fd.get('addr_neighborhood') as string) || '',
      city: (fd.get('addr_city') as string) || '',
      state: (fd.get('addr_state') as string) || '',
      dane_code: (fd.get('addr_dane_code') as string) || '',
      building_type: ((fd.get('addr_building_type') as string) || null) as BuildingType | null,
      tower: (fd.get('addr_tower') as string) || '',
      apartment: (fd.get('addr_apartment') as string) || '',
      conjunto_type: ((fd.get('addr_conjunto_type') as string) || null) as ConjuntoType | null,
      delivery_context: ((fd.get('addr_delivery_context') as string) || null) as DeliveryContext | null,
      company_name: (fd.get('addr_company_name') as string) || '',
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

  // Rev. 102 (Opción B Habeas Data) — checkbox per-contact que confirma
  // consentimiento renovado del titular, requisito para volver a editar
  // PII después de una anonimización.
  const [renewedConsent, setRenewedConsent] = useState<Record<string, boolean>>({})
  const toggleRenewedConsent = (id: string) =>
    setRenewedConsent(prev => ({ ...prev, [id]: !prev[id] }))

  // Rev. 102 — state controlled del check "consent_given" para form Add
  // y para forms Edit (per-contact). Permite condicionar UX:
  //   - inputs PII disabled si check OFF (Ley 1581 Art. 9 — sin consent
  //     no se pueden tratar datos personales)
  //   - mostrar "Evidencia" si ON / "Razón de revocatoria" si OFF
  //     (mutuamente excluyente, antes ambos siempre visibles confundía)
  const [addConsentChecked, setAddConsentChecked] = useState(false)
  const [addConsentSource, setAddConsentSource] = useState('')
  // Rev. 102 — country code para Add. Default Colombia, lista corta
  // priorizando América Latina + USA + España.
  const [addPhoneCountry, setAddPhoneCountry] = useState('57')
  const [editConsentChecked, setEditConsentChecked] = useState<Record<string, boolean>>({})
  const [editConsentSource, setEditConsentSource] = useState<Record<string, string>>({})
  const toggleEditConsent = (id: string, defaultValue: boolean) =>
    setEditConsentChecked(prev => ({
      ...prev,
      [id]: prev[id] === undefined ? !defaultValue : !prev[id],
    }))
  const isEditConsentChecked = (id: string, defaultValue: boolean): boolean =>
    editConsentChecked[id] === undefined ? defaultValue : editConsentChecked[id]
  const getEditConsentSource = (id: string, defaultValue: string): string =>
    editConsentSource[id] === undefined ? defaultValue : editConsentSource[id]
  const setEditConsentSourceFor = (id: string, value: string) =>
    setEditConsentSource(prev => ({ ...prev, [id]: value }))

  // Rev. 102 — Lista de países soportados para el phone (E.164).
  const phoneCountryMeta = PHONE_COUNTRIES.find(c => c.code === addPhoneCountry) ?? PHONE_COUNTRIES[0]

  /** Contact que fue anonimizado y aún no tiene consent renovado. */
  const isAwaitingRenewal = (c: Contact): boolean =>
    !c.consent_given && !!c.consent_revoked_at

  // Rev. 102 — Optimistic update post-Anonimizar.
  // Cuando una acción erase tiene éxito en el server, el contact_id se
  // añade a este Set y la card se renderiza con PII ya anonimizada
  // localmente, sin esperar a que router.refresh() complete el round-trip
  // del RSC payload. Cuando initialContacts se actualiza vía RSC fresh,
  // useEffect limpia el Set para no acumular IDs.
  const [optimisticErasedIds, setOptimisticErasedIds] = useState<Set<string>>(new Set())
  useEffect(() => {
    // Cuando cambian los initialContacts (RSC fresh tras router.refresh),
    // los IDs en el Set ya tienen su PII anonimizada en el server, así
    // que el override local ya no es necesario.
    setOptimisticErasedIds(new Set())
  }, [initialContacts])
  const markErasedOptimistically = (contactId: string) => {
    setOptimisticErasedIds(prev => {
      const next = new Set(prev)
      next.add(contactId)
      return next
    })
    // Cierra el panel de edición si estaba abierto sobre ese contacto.
    if (expandedId === contactId) setExpandedId(null)
  }

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
      setAddConsentChecked(false)
      setAddConsentSource('')
      setAddPhoneCountry('57')
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
  // Rev. 103 — motivo opcional + audit log antes del DELETE.
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const [pendingDeleteReason, setPendingDeleteReason] = useState<string>('')
  const pendingDeleteContact = useMemo(
    () => initialContacts.find(c => c.id === pendingDeleteId) ?? null,
    [initialContacts, pendingDeleteId],
  )
  const handleDeleteById = (contactId: string) => {
    setPendingDeleteId(contactId)
    setPendingDeleteReason('')
  }
  const confirmDelete = () => {
    if (!pendingDeleteId) return
    const fd = new FormData()
    fd.set('contact_id', pendingDeleteId)
    if (pendingDeleteReason.trim()) {
      fd.set('delete_reason', pendingDeleteReason.trim())
    }
    setPendingDeleteId(null)
    setPendingDeleteReason('')
    startTransition(async () => {
      await deleteAction(fd)
      router.refresh()
      showSuccess('Contacto eliminado.')
    })
  }

  // Rev. 105 H.4.1.x — Reactivar consent tras soft opt-out (STOP keyword).
  const [pendingReactivateId, setPendingReactivateId] = useState<string | null>(null)
  const [pendingReactivateReason, setPendingReactivateReason] = useState<string>('')
  const pendingReactivateContact = useMemo(
    () => initialContacts.find(c => c.id === pendingReactivateId) ?? null,
    [initialContacts, pendingReactivateId],
  )
  const handleReactivateById = (contactId: string) => {
    setPendingReactivateId(contactId)
    setPendingReactivateReason('')
  }
  const confirmReactivate = () => {
    if (!pendingReactivateId || !reactivateConsentAction) return
    const reason = pendingReactivateReason.trim()
    if (reason.length < 10) {
      window.alert('La razón debe tener al menos 10 caracteres (auditoría Habeas Data).')
      return
    }
    const fd = new FormData()
    fd.set('contact_id', pendingReactivateId)
    fd.set('reason', reason)
    const targetId = pendingReactivateId
    setPendingReactivateId(null)
    setPendingReactivateReason('')
    startTransition(async () => {
      const res = await reactivateConsentAction(fd)
      if (res.ok) {
        router.refresh()
        showSuccess(res.message || 'Consent reactivado.')
      } else {
        window.alert(`Error reactivando consent (${targetId.slice(0, 8)}…): ${res.message}`)
      }
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
                <li><strong>Eliminar</strong>: borra el contacto completo de la base. Queda audit log inmutable (event=&quot;deleted&quot;) con phone hasheado para trazabilidad ante SIC.</li>
                <li><strong>Anonimizar</strong>: nullifica solo PII pero conserva el contact_id y todos los registros relacionados (orders, claims) intactos.</li>
              </ul>
              <p className="mt-2">
                Si el titular pidió ejercer su derecho Habeas Data, normalmente <strong>Anonimizar</strong> es la vía correcta.
              </p>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Motivo (opcional)</Label>
              <Input
                value={pendingDeleteReason}
                onChange={e => setPendingDeleteReason(e.target.value)}
                placeholder="Ej: contacto duplicado, registro de prueba, etc."
                className="h-8 text-xs"
                maxLength={300}
              />
              <p className="text-[10px] text-muted-foreground">
                Se guarda en audit log junto con tu email. Útil si el tenant necesita justificar la eliminación después.
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

      {/* Rev. 105 H.4.1.x — Dialog confirmación Reactivar consent */}
      <Dialog
        open={pendingReactivateId !== null}
        onOpenChange={(o) => !o && setPendingReactivateId(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-emerald-700">
              <ShieldCheck className="h-5 w-5" />
              Reactivar consent marketing
            </DialogTitle>
            <DialogDescription>
              Esta acción permite que el cliente vuelva a recibir HSM templates marketing.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            <p className="text-muted-foreground">
              Vas a reactivar consent del contacto{' '}
              <strong className="text-foreground">
                {pendingReactivateContact?.name || 'sin nombre'}{' '}
                ({pendingReactivateContact ? formatPhone(pendingReactivateContact.phone) : ''})
              </strong>.
            </p>
            <div className="rounded-md border border-amber-700/40 bg-amber-700/5 p-2.5 text-xs text-amber-700">
              <p className="font-semibold mb-1">Habeas Data Ley 1581 ART. 9:</p>
              <ul className="list-disc list-inside space-y-0.5">
                <li>El cliente debió haber dado consent renovado <strong>explícito</strong> (idealmente vía WhatsApp con confirmación).</li>
                <li>Si solo te pidió por teléfono o presencial, la razón debe documentarlo claramente para audit ante SIC.</li>
                <li>La razón quedará en <code>consent_audit_log</code> (append-only, 7 años retención).</li>
              </ul>
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Razón explícita (mínimo 10 caracteres) *</Label>
              <Input
                value={pendingReactivateReason}
                onChange={e => setPendingReactivateReason(e.target.value)}
                placeholder="Ej: Cliente llamó al 312-583-5649 a las 3pm pidiendo volver a recibir promociones..."
                className="h-8 text-xs"
                minLength={10}
                maxLength={500}
              />
              <p className="text-[10px] text-muted-foreground">
                Se guarda con tu email + timestamp. Esencial para defensa ante una queja regulatoria.
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setPendingReactivateId(null)}
              size="sm"
            >
              Cancelar
            </Button>
            <Button
              type="button"
              onClick={confirmReactivate}
              size="sm"
              className="bg-emerald-700 hover:bg-emerald-800 text-white"
              disabled={pendingReactivateReason.trim().length < 10}
            >
              Sí, reactivar consent
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
                    <select
                      name="phone_country"
                      value={addPhoneCountry}
                      onChange={e => setAddPhoneCountry(e.target.value)}
                      title="Código de país"
                      className="inline-flex items-center px-2 h-9 border border-r-0 border-input rounded-l-md text-xs bg-muted shrink-0 focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      {PHONE_COUNTRIES.map(c => (
                        <option key={c.code} value={c.code}>
                          +{c.code} {c.label}
                        </option>
                      ))}
                    </select>
                    <Input
                      name="phone"
                      type="tel"
                      inputMode="numeric"
                      maxLength={14}
                      placeholder={phoneCountryMeta.placeholderDigits}
                      className="rounded-l-none"
                      required
                      onInput={e => { const el = e.currentTarget; el.value = el.value.replace(/\D/g, '').slice(0, 14) }}
                    />
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    Default Colombia. Cambia el código si el cliente es extranjero.
                    Mín. 7 / máx. 14 dígitos.
                  </p>
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">
                    Nombre completo <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Pasarela de pagos y Transportadora lo requieren)</span>
                  </Label>
                  <Input name="name" placeholder="Juan García López" required />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">
                    Correo electrónico <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Pasarela de pagos)</span>
                  </Label>
                  <Input name="email" type="email" placeholder="cliente@email.com" autoComplete="email" required />
                </div>
                {/* Rev. 103 — phone para envío. Si vacío defaultea al WhatsApp. */}
                <div className="space-y-1">
                  <Label className="text-xs">
                    Celular para envío
                    <span className="ml-1 text-[10px] text-muted-foreground">(default = WhatsApp; usar otro solo si el envío va a otra persona)</span>
                  </Label>
                  <div className="flex">
                    <span
                      title="Código país (Colombia)"
                      className="inline-flex items-center px-2 h-9 border border-r-0 border-input rounded-l-md text-xs bg-muted shrink-0 text-muted-foreground"
                    >
                      +57
                    </span>
                    <Input
                      name="shipping_phone"
                      type="tel"
                      inputMode="numeric"
                      placeholder="3001234567"
                      pattern="[3]\d{9}"
                      maxLength={10}
                      autoComplete="off"
                      className="rounded-l-none"
                      onInput={e => { const el = e.currentTarget; el.value = el.value.replace(/\D/g, '').slice(0, 10) }}
                    />
                  </div>
                  <p className="text-[10px] text-muted-foreground">
                    Vacío = la transportadora contacta al celular WhatsApp principal.
                  </p>
                </div>
                {/* Documento de identidad — Pasarela de pagos PSE/Bancolombia lo exigen en checkout */}
                <DocumentFields required showRequiredAsterisk layout="default" />
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
                {/* Bloque Habeas Data — check primero para que UX cuadre */}
                <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      name="consent_given"
                      checked={addConsentChecked}
                      onChange={e => setAddConsentChecked(e.target.checked)}
                      className="h-4 w-4 mt-0.5 rounded"
                    />
                    <span className="text-xs text-foreground leading-snug">
                      <strong>El titular autorizó el tratamiento de sus datos</strong> (Ley 1581/2012).
                      <span className="block text-muted-foreground mt-0.5 text-[11px]">
                        Sin esta autorización solo se guarda el teléfono. Los demás
                        campos personales se rechazan en el servidor.
                      </span>
                    </span>
                  </label>

                  {addConsentChecked && (
                    <div className="space-y-1 pt-1">
                      <Label className="text-xs">
                        Canal de consentimiento <span className="text-destructive">*</span>
                      </Label>
                      <select
                        name="consent_source"
                        required
                        value={addConsentSource}
                        onChange={e => setAddConsentSource(e.target.value)}
                        className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                      >
                        <option value="" disabled>— Selecciona —</option>
                        <option value="manual_console">Consola (operador)</option>
                        <option value="whatsapp">WhatsApp</option>
                        <option value="web_form">Formulario web</option>
                        <option value="phone_call">Llamada telefónica</option>
                        <option value="in_person">Presencial</option>
                        <option value="import">Importación</option>
                        <option value="other">Otro</option>
                      </select>
                      <p className="text-[10px] text-muted-foreground leading-snug">
                        {addConsentSource && CONSENT_SOURCE_HELP[addConsentSource]
                          ? CONSENT_SOURCE_HELP[addConsentSource]
                          : 'De dónde vino el consentimiento (selecciona uno).'}
                      </p>
                    </div>
                  )}

                  {addConsentChecked && (
                    <div className="space-y-1">
                      <Label className="text-xs">
                        Evidencia (nota interna)
                        {addConsentSource === 'other' && (
                          <span className="text-destructive ml-1">*</span>
                        )}
                      </Label>
                      <Input
                        name="consent_evidence_note"
                        required={addConsentSource === 'other'}
                        minLength={addConsentSource === 'other' ? 20 : undefined}
                        placeholder="Ej: WhatsApp 2026-05-01 14:30, dijo 'Sí acepto' en hilo conv-abc"
                        className="h-8 text-xs"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        {addConsentSource === 'other'
                          ? 'OBLIGATORIO (mínimo 20 caracteres) — describe de dónde vino el consent.'
                          : 'Detalle textual de cómo se capturó. Crítico para responder a SIC.'}
                      </p>
                    </div>
                  )}

                  {/* Rev. 103 (F10) — Adjuntar evidencia física cuando canal=in_person. */}
                  {addConsentChecked && addConsentSource === 'in_person' && (
                    <div className="space-y-1">
                      <Label className="text-xs">
                        Adjuntar evidencia física <span className="text-[10px] text-muted-foreground">(PDF o imagen, opcional, máx. 5 MB)</span>
                      </Label>
                      <input
                        type="file"
                        name="consent_evidence_file"
                        accept=".pdf,application/pdf,image/jpeg,image/png,image/webp"
                        className="block w-full text-xs file:mr-2 file:rounded file:border-0 file:bg-muted file:px-2 file:py-1 file:text-foreground"
                      />
                      <p className="text-[10px] text-muted-foreground">
                        Sube el escaneo del documento firmado. Queda guardado en el bucket privado del tenant. La SAR export incluye el link automáticamente.
                      </p>
                    </div>
                  )}

                  {!addConsentChecked && (
                    <div className="space-y-1 pt-1">
                      <Label className="text-xs text-muted-foreground">
                        Razón de revocatoria
                        <span className="text-[10px] ml-1">(solo si creas un contacto que ya nace revocado)</span>
                      </Label>
                      <Input
                        name="consent_revoked_reason"
                        placeholder="Ej: importación de clientes que pidieron borrarse"
                        className="h-8 text-xs"
                      />
                    </div>
                  )}
                </div>
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
              {paginatedContacts.map((rawContact) => {
                // Rev. 102 — Optimistic erase override: si el contact está
                // en optimisticErasedIds, mostrar PII como nullificada
                // localmente (la DB ya está anonimizada por el server
                // action, solo esperamos a router.refresh()).
                const c = optimisticErasedIds.has(rawContact.id)
                  ? {
                      ...rawContact,
                      name: null, email: null,
                      document_type: null, document_number: null,
                      address: null, notes: null,
                      consent_given: false,
                      consent_revoked_at: rawContact.consent_revoked_at ?? new Date().toISOString(),
                      consent_revoked_reason: rawContact.consent_revoked_reason ?? 'Solicitud de supresión vía SAR',
                    }
                  : rawContact
                return (
                <div key={c.id} className="rounded-xl border border-border bg-card p-4 hover:border-primary/30 transition-all focus-within:border-primary/50">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 min-w-0 flex-1">
                      <div className="h-9 w-9 rounded-full bg-primary/15 flex items-center justify-center shrink-0 font-semibold text-primary text-sm">
                        {c.name ? c.name.charAt(0).toUpperCase() : <Phone className="h-4 w-4" />}
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <p className="font-medium text-sm">{c.name ?? <span className="text-muted-foreground italic">Sin nombre</span>}</p>
                          {c.consent_given && c.consent_revoked_at ? (
                            // Rev. 105 H.4.1.x — Soft opt-out (STOP keyword).
                            // PII intacta + consent_given=true + revoked_at populated.
                            // Marketing bloqueado pero chat activo (Q3 + Op-A.2).
                            <span
                              className="flex items-center gap-1 text-[11px] text-rose-700"
                              title="Cliente envió STOP/BAJA por WhatsApp. Templates HSM marketing bloqueados. Conversación puede continuar normalmente — bot responde a mensajes inbound. Para reactivar marketing, usar 'Reactivar consent' (requiere doble opt-in del cliente preferiblemente)."
                            >
                              <ShieldOff className="h-3 w-3" /> Marketing bloqueado · Chat activo
                            </span>
                          ) : c.consent_given ? (
                            <span className="flex items-center gap-1 text-[11px] text-emerald-700">
                              <ShieldCheck className="h-3 w-3" /> Consent.{' '}
                              {c.consent_date && <span className="opacity-60">{new Date(c.consent_date).toLocaleDateString('es-CO')}</span>}
                            </span>
                          ) : c.consent_revoked_at ? (
                            <span className="flex items-center gap-1 text-[11px] text-amber-700">
                              <ShieldOff className="h-3 w-3" /> Revocado
                            </span>
                          ) : (
                            <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                              <ShieldOff className="h-3 w-3" /> Sin consent.
                            </span>
                          )}
                        </div>
                        <p className="text-xs font-mono text-muted-foreground">
                          {formatPhone(c.phone)}
                        </p>
                        {c.shipping_phone && c.shipping_phone !== c.phone && (
                          <p className="text-xs font-mono text-amber-700 mt-0.5 flex items-center gap-1" title="Phone alternativo para envío (transportadora contacta a este número)">
                            <Phone className="h-3 w-3 shrink-0" />
                            Envío: {formatPhone(c.shipping_phone)}
                          </p>
                        )}
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
                          <div className="mt-0.5 flex flex-wrap items-center gap-2">
                            <p className="text-xs text-amber-700">
                              Revocado: {new Date(c.consent_revoked_at).toLocaleDateString('es-CO')}
                              {c.consent_revoked_reason ? ` · ${c.consent_revoked_reason}` : ''}
                            </p>
                            {/* Rev. 105 H.4.1.x — Reactivar consent solo aplicable
                                en soft opt-out (PII intacta, consent_given=true).
                                NO mostrar para SAR-erase (consent_given=false +
                                anonimización requiere consentimiento renovado vía
                                edit form existente).
                                Rev. 105 H.4.1.x.gov — Owner-only (Habeas Data
                                ART. 11). Manager ve botón disabled con tooltip
                                educativo. */}
                            {canWrite && c.consent_given && reactivateConsentAction && (
                              <Button
                                type="button"
                                size="sm"
                                variant="outline"
                                className={
                                  isOwner
                                    ? 'h-6 text-[11px] px-2 gap-1 border-emerald-700/40 text-emerald-700 hover:bg-emerald-700/10'
                                    : 'h-6 text-[11px] px-2 gap-1 border-muted-foreground/30 text-muted-foreground cursor-not-allowed opacity-60'
                                }
                                onClick={isOwner ? () => handleReactivateById(c.id) : undefined}
                                disabled={isPending || !isOwner}
                                title={
                                  isOwner
                                    ? 'Reactivar consent marketing. Habeas Data: requiere razón explícita para audit.'
                                    : 'Solo el owner puede reactivar consent (Habeas Data ART. 11 — responsable legal certifica re-consent del titular). Contacta al owner del tenant para que ejecute la acción.'
                                }
                              >
                                <ShieldCheck className="h-3 w-3" />
                                {isOwner ? 'Reactivar consent' : 'Reactivar (solo owner)'}
                              </Button>
                            )}
                          </div>
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
                      {expandedId === c.id && (() => {
                        const awaitingRenewal = isAwaitingRenewal(c)
                        const consentChecked = isEditConsentChecked(c.id, c.consent_given)
                        // Rev. 103 (SaaS B2B) — PII libre para editar EXCEPTO en
                        // post-anonimización (Art. 15 sigue siendo ritual legal serio:
                        // re-introducir PII requiere consentimiento renovado del titular).
                        const piiUnlocked = !awaitingRenewal || !!renewedConsent[c.id]
                        return (
                      <form action={handleEdit} className="mt-3 space-y-3 pt-3 border-t border-border">
                        <input type="hidden" name="contact_id" value={c.id} />

                        {/* Rev. 102 — Opción B Habeas Data: contact post-anonimización.
                            Bloque ÚNICO: checkbox renewed + canal + evidencia.
                            Cuando este flow está activo, el bloque consent normal de
                            abajo NO se renderiza (era redundancia). */}
                        {awaitingRenewal && (
                          <div className="rounded-lg border border-amber-700/40 bg-amber-700/5 p-3 space-y-2">
                            <div className="flex items-start gap-2 text-xs text-amber-700">
                              <ShieldOff className="h-4 w-4 shrink-0 mt-0.5" />
                              <div className="flex-1">
                                <p className="font-semibold">Contacto anonimizado el {c.consent_revoked_at && new Date(c.consent_revoked_at).toLocaleDateString('es-CO')}.</p>
                                <p className="mt-0.5 text-muted-foreground">
                                  Para volver a registrar PII el sistema requiere consentimiento
                                  renovado del titular. Confirma que cuentas con esa autorización,
                                  indica el canal por el que la diste, y describe la evidencia.
                                </p>
                              </div>
                            </div>
                            <label className="flex items-start gap-2 cursor-pointer text-xs">
                              <input
                                type="checkbox"
                                name="renewed_consent"
                                checked={!!renewedConsent[c.id]}
                                onChange={() => toggleRenewedConsent(c.id)}
                                className="h-3.5 w-3.5 mt-0.5 rounded"
                              />
                              <span className="text-foreground">
                                <strong>Confirmo</strong> que el titular ha otorgado consentimiento renovado.
                              </span>
                            </label>
                            {!!renewedConsent[c.id] && (() => {
                              const renewedSource = getEditConsentSource(c.id, '')
                              const isOther = renewedSource === 'other'
                              return (
                              <div className="space-y-2 pt-1">
                                {/* Hidden: re-activar consent_given y persistir versión política. */}
                                <input type="hidden" name="consent_given" value="on" />

                                <div className="space-y-1">
                                  <Label className="text-xs text-amber-700">
                                    Canal del consentimiento renovado <span className="text-destructive">*</span>
                                  </Label>
                                  <select
                                    name="consent_source"
                                    required
                                    value={renewedSource}
                                    onChange={e => setEditConsentSourceFor(c.id, e.target.value)}
                                    className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                                  >
                                    <option value="" disabled>— Selecciona —</option>
                                    <option value="manual_console">Consola (operador)</option>
                                    <option value="whatsapp">WhatsApp</option>
                                    <option value="web_form">Formulario web</option>
                                    <option value="phone_call">Llamada telefónica</option>
                                    <option value="in_person">Presencial</option>
                                    <option value="import">Importación</option>
                                    <option value="other">Otro</option>
                                  </select>
                                  <p className="text-[10px] text-muted-foreground leading-snug">
                                    {renewedSource && CONSENT_SOURCE_HELP[renewedSource]
                                      ? CONSENT_SOURCE_HELP[renewedSource]
                                      : 'Cómo capturaste la nueva autorización.'}
                                  </p>
                                </div>

                                <div className="space-y-1">
                                  <Label className="text-xs text-amber-700">
                                    Evidencia del consentimiento renovado <span className="text-destructive">*</span>
                                  </Label>
                                  <Input
                                    name="renewed_consent_evidence"
                                    required
                                    minLength={isOther ? 20 : 10}
                                    maxLength={500}
                                    placeholder="Ej: WhatsApp 2026-05-01 14:30 — el titular respondió 'Sí, autorizo nuevamente'."
                                    className="h-8 text-xs"
                                  />
                                  <p className="text-[10px] text-muted-foreground">
                                    {isOther
                                      ? 'OBLIGATORIO mínimo 20 caracteres (canal "Otro" exige descripción detallada).'
                                      : 'Mínimo 10 caracteres. Se guarda inmutablemente en audit log.'}
                                  </p>
                                </div>
                              </div>
                              )
                            })()}
                          </div>
                        )}

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-xs">Nombre</Label>
                            <Input name="name" defaultValue={c.name ?? ''} disabled={!piiUnlocked} className="h-8 text-xs" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">Email</Label>
                            <Input name="email" type="email" defaultValue={c.email ?? ''} disabled={!piiUnlocked} className="h-8 text-xs" autoComplete="email" />
                          </div>
                        </div>
                        {/* Rev. 103 — phone para envío (edit). Defaultea al
                            WhatsApp cuando no se da uno alternativo. */}
                        <div className="space-y-1">
                          <Label className="text-xs">
                            Celular envío
                            <span className="ml-1 text-[10px] text-muted-foreground">(default = WhatsApp; cambiar solo si recibe otra persona)</span>
                          </Label>
                          <div className="flex">
                            <span
                              title="Código país (Colombia)"
                              className="inline-flex items-center px-2 h-8 border border-r-0 border-input rounded-l-md text-[11px] bg-muted shrink-0 text-muted-foreground"
                            >
                              +57
                            </span>
                            <Input
                              name="shipping_phone"
                              type="tel"
                              inputMode="numeric"
                              placeholder={(c.phone || '3001234567').replace(/^\+?57\s*/, '')}
                              defaultValue={(c.shipping_phone || '').replace(/^\+?57\s*/, '')}
                              pattern="[3]\d{9}"
                              maxLength={10}
                              autoComplete="off"
                              disabled={!piiUnlocked}
                              className="h-8 text-xs rounded-l-none"
                              onInput={e => { const el = e.currentTarget; el.value = el.value.replace(/\D/g, '').slice(0, 10) }}
                            />
                          </div>
                          <p className="text-[10px] text-muted-foreground">
                            {c.shipping_phone && c.shipping_phone !== c.phone
                              ? 'Distinto al WhatsApp — la transportadora contactará a este número.'
                              : 'Igual al WhatsApp — la transportadora usa este mismo número.'}
                          </p>
                        </div>
                        {/* Rev. 69 — Documento de identidad (edición) */}
                        {piiUnlocked ? (
                          <DocumentFields
                            layout="compact"
                            defaultDocType={(c.document_type ?? '') as DocType}
                            defaultDocNumber={c.document_number ?? ''}
                          />
                        ) : (
                          <div className="text-[10px] text-muted-foreground italic">
                            Documento de identidad bloqueado — confirma consentimiento renovado para editar.
                          </div>
                        )}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          <div className="space-y-1">
                            <Label className="text-xs">Notas</Label>
                            <Input name="notes" defaultValue={c.notes ?? ''} disabled={!piiUnlocked} className="h-8 text-xs" />
                          </div>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs flex items-center gap-1"><MapPin className="h-3 w-3" /> Dirección de entrega</Label>
                          {piiUnlocked ? (
                            <AddressSelector fieldPrefix="addr" defaultValue={c.address ?? {}} showBuildingDetails />
                          ) : (
                            <div className="text-[10px] text-muted-foreground italic">
                              Dirección bloqueada — confirma consentimiento renovado para editar.
                            </div>
                          )}
                        </div>
                        {/* Rev. 102 — Bloque Habeas Data reorganizado.
                            Si awaitingRenewal=true, NO renderizar (toda la lógica
                            ya vive en el bloque renewed_consent arriba para evitar
                            redundancia con el operador). */}
                        {!awaitingRenewal && (
                        <div className="rounded-md border border-border bg-muted/30 p-3 space-y-2">
                          {(() => {
                            // Estado actual del consent del contact:
                            //   "active"   → consent_given=true (read-only; revocar via Anonimizar)
                            //   "revoked"  → consent_given=false + consent_revoked_at (flujo renewed_consent)
                            //   "no_consent" → contact sin consent y sin revocación (legacy/raro,
                            //                  permite activar)
                            const consentState =
                              c.consent_given ? 'active'
                              : c.consent_revoked_at ? 'revoked'
                              : 'no_consent'

                            if (consentState === 'active') {
                              // Read-only: para revocar usar el botón Anonimizar.
                              return (
                                <>
                                  <input type="hidden" name="consent_given" value="on" />
                                  <div className="flex items-start gap-2">
                                    <ShieldCheck className="h-4 w-4 text-emerald-700 shrink-0 mt-0.5" />
                                    <div className="text-xs text-foreground leading-snug">
                                      <strong>Consentimiento activo</strong> (Ley 1581/2012)
                                      {c.consent_date && (
                                        <span className="text-muted-foreground">
                                          {' '}desde {new Date(c.consent_date).toLocaleDateString('es-CO')}
                                        </span>
                                      )}.
                                      <p className="text-[11px] text-muted-foreground mt-0.5">
                                        Para revocar el consentimiento usa el botón
                                        <strong className="text-amber-700"> Anonimizar </strong>
                                        en la sección Habeas Data abajo. Esa acción borra la PII
                                        + deja audit inmutable + notifica al tenant. Desmarcar
                                        este check NO es la vía correcta de revocación legal.
                                      </p>
                                    </div>
                                  </div>
                                </>
                              )
                            }

                            // consentState === 'revoked' o 'no_consent':
                            // permite el checkbox interactivo
                            return (
                              <label className="flex items-start gap-2 cursor-pointer">
                                <input
                                  type="checkbox"
                                  name="consent_given"
                                  checked={consentChecked}
                                  onChange={() => toggleEditConsent(c.id, c.consent_given)}
                                  className="h-3.5 w-3.5 mt-0.5 rounded"
                                />
                                <span className="text-xs text-foreground leading-snug">
                                  <strong>El titular autoriza el tratamiento de sus datos</strong> (Ley 1581/2012).
                                  <span className="block text-muted-foreground mt-0.5 text-[11px]">
                                    Marca el check + canal para registrar el consent. Si lo dejas sin marcar, el contacto queda con consent_given=false (el bot pedirá consent al titular en su próxima interacción).
                                  </span>
                                </span>
                              </label>
                            )
                          })()}

                          {consentChecked && (() => {
                            const currentSource = getEditConsentSource(c.id, c.consent_source ?? '')
                            return (
                            <div className="space-y-1 pt-1">
                              <Label className="text-xs">
                                Canal de consentimiento <span className="text-destructive">*</span>
                              </Label>
                              <select
                                name="consent_source"
                                required
                                value={currentSource}
                                onChange={e => setEditConsentSourceFor(c.id, e.target.value)}
                                className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-xs"
                              >
                                <option value="" disabled>— Selecciona —</option>
                                <option value="manual_console">Consola (operador)</option>
                                <option value="whatsapp">WhatsApp</option>
                                <option value="web_form">Formulario web</option>
                                <option value="phone_call">Llamada telefónica</option>
                                <option value="in_person">Presencial</option>
                                <option value="import">Importación</option>
                                <option value="other">Otro</option>
                              </select>
                              <p className="text-[10px] text-muted-foreground leading-snug">
                                {currentSource && CONSENT_SOURCE_HELP[currentSource]
                                  ? CONSENT_SOURCE_HELP[currentSource]
                                  : 'De dónde vino el consentimiento (selecciona uno).'}
                              </p>
                            </div>
                            )
                          })()}

                          {consentChecked && (() => {
                            const currentSource = getEditConsentSource(c.id, c.consent_source ?? '')
                            const isOther = currentSource === 'other'
                            const isInPerson = currentSource === 'in_person'
                            const evidenceObj = (c.consent_evidence ?? {}) as Record<string, unknown>
                            const hasAttachment = typeof evidenceObj.attachment_path === 'string'
                              && (evidenceObj.attachment_path as string).length > 0
                            const attachmentMime = typeof evidenceObj.attachment_mime === 'string'
                              ? evidenceObj.attachment_mime
                              : null
                            const attachmentSize = typeof evidenceObj.attachment_size === 'number'
                              ? evidenceObj.attachment_size
                              : null
                            const attachmentUploadedAt = typeof evidenceObj.attachment_uploaded_at === 'string'
                              ? evidenceObj.attachment_uploaded_at
                              : null
                            return (
                            <>
                            <div className="space-y-1">
                              <Label className="text-xs">
                                Evidencia (nota interna)
                                {isOther && <span className="text-destructive ml-1">*</span>}
                              </Label>
                              <Input
                                name="consent_evidence_note"
                                defaultValue={extractEvidenceNote(c.consent_evidence) ?? ''}
                                required={isOther}
                                minLength={isOther ? 20 : undefined}
                                placeholder="Ej: WhatsApp 2026-05-01 14:30, dijo 'Sí acepto'"
                                className="h-8 text-xs"
                              />
                              <p className="text-[10px] text-muted-foreground">
                                {isOther
                                  ? 'OBLIGATORIO (mínimo 20 caracteres) — describe de dónde vino el consent.'
                                  : 'Detalle textual de cómo se capturó. Crítico para SIC.'}
                              </p>
                            </div>
                            {/* Rev. 103 (F10) — Adjuntar/reemplazar evidencia física en Edit. */}
                            {isInPerson && (
                              <div className="space-y-2">
                                {hasAttachment && (
                                  <ExistingAttachmentCard
                                    contactId={c.id}
                                    mime={attachmentMime}
                                    size={attachmentSize}
                                    uploadedAt={attachmentUploadedAt}
                                  />
                                )}
                                <div className="space-y-1">
                                  <Label className="text-xs">
                                    {hasAttachment ? 'Reemplazar evidencia física' : 'Adjuntar evidencia física'}
                                    <span className="text-[10px] text-muted-foreground ml-1">(PDF o imagen, opcional, máx. 5 MB)</span>
                                  </Label>
                                  <input
                                    type="file"
                                    name="consent_evidence_file"
                                    accept=".pdf,application/pdf,image/jpeg,image/png,image/webp"
                                    className="block w-full text-xs file:mr-2 file:rounded file:border-0 file:bg-muted file:px-2 file:py-1 file:text-foreground"
                                  />
                                </div>
                              </div>
                            )}
                            </>
                            )
                          })()}

                          {!consentChecked && (
                            <div className="space-y-1 pt-1">
                              <Label className="text-xs text-muted-foreground">
                                Razón de revocatoria
                                <span className="text-[10px] ml-1">(opcional, queda en audit)</span>
                              </Label>
                              <Input
                                name="consent_revoked_reason"
                                defaultValue={c.consent_revoked_reason ?? ''}
                                placeholder="Ej: titular pidió por chat el día X"
                                className="h-8 text-xs"
                              />
                            </div>
                          )}
                        </div>
                        )}
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
                            onEraseSuccess={markErasedOptimistically}
                            isAnonymized={!c.consent_given && !!c.consent_revoked_at}
                            anonymizedAt={c.consent_revoked_at}
                          />
                        )}
                      </form>
                      )
                      })()}
                    </div>
                  )}
                </div>
                )
              })}

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
