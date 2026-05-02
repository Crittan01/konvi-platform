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
import DocumentFields, { type DocType } from './document-fields'

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

// Mismo formato que Inbox: +57 312 583 5649. Rev. 102: detección
// de country code. Para CO formato bonito; otros países muestra +N+digits.
const formatPhone = (raw: string): string => {
  const digits = (raw || '').replace(/\D/g, '')
  if (!digits) return raw || ''
  // Colombia: 12 dígitos totales (57 + 10).
  if (digits.startsWith('57') && digits.length === 12)
    return `+57 ${digits.slice(2, 5)} ${digits.slice(5, 8)} ${digits.slice(8)}`
  // Otros países comunes: separar prefijo conocido del resto.
  // Detectar prefijo iterando sobre la lista (de más largo a más corto
  // para evitar match prematuro de +1 cuando es +1 vs +193).
  const prefixes = ['593', '52', '54', '55', '56', '51', '57', '58', '34', '1']
  for (const p of prefixes) {
    if (digits.startsWith(p) && digits.length >= p.length + 7) {
      return `+${p} ${digits.slice(p.length)}`
    }
  }
  return `+${digits}`
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
  // Default Colombia. Otros países disponibles si llega extranjero.
  // Sincronizado con SUPPORTED_COUNTRY_CODES en page.tsx server action.
  const PHONE_COUNTRIES: Array<{ code: string; flag: string; label: string; placeholderDigits: string }> = [
    { code: '57',  flag: '🇨🇴', label: 'Colombia',  placeholderDigits: '3001234567' },
    { code: '58',  flag: '🇻🇪', label: 'Venezuela', placeholderDigits: '4141234567' },
    { code: '593', flag: '🇪🇨', label: 'Ecuador',   placeholderDigits: '991234567' },
    { code: '51',  flag: '🇵🇪', label: 'Perú',      placeholderDigits: '912345678' },
    { code: '52',  flag: '🇲🇽', label: 'México',    placeholderDigits: '5512345678' },
    { code: '1',   flag: '🇺🇸', label: 'USA/CA',    placeholderDigits: '5551234567' },
    { code: '34',  flag: '🇪🇸', label: 'España',    placeholderDigits: '612345678' },
    { code: '54',  flag: '🇦🇷', label: 'Argentina', placeholderDigits: '91123456789' },
    { code: '56',  flag: '🇨🇱', label: 'Chile',     placeholderDigits: '912345678' },
    { code: '55',  flag: '🇧🇷', label: 'Brasil',    placeholderDigits: '11912345678' },
  ]
  const phoneCountryMeta = PHONE_COUNTRIES.find(c => c.code === addPhoneCountry) ?? PHONE_COUNTRIES[0]

  // Rev. 102 — Help text contextual por canal. Guía al operador sobre
  // qué evidencia debe registrar/archivar para audit ante SIC.
  const CONSENT_SOURCE_HELP: Record<string, string> = {
    whatsapp: 'Evidencia: el hilo de WhatsApp donde el titular dijo "Sí acepto". El sistema lo enlaza al consent_audit_log automáticamente.',
    web_form: 'Evidencia: captura del formulario web (timestamp + IP + checkbox). Asegúrate que tu sitio persiste estos datos.',
    in_person: 'Evidencia: documento físico firmado por el titular. Archiva el papel y referencia su ubicación en Evidencia abajo.',
    import: 'Importación: el consent fue capturado en otro sistema. Eres responsable de demostrarlo ante SIC.',
    other: 'Catch-all. La Evidencia es OBLIGATORIA (mínimo 20 caracteres). Si no puedes describir de dónde vino, este canal NO aplica.',
  }

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
                    <select
                      name="phone_country"
                      value={addPhoneCountry}
                      onChange={e => setAddPhoneCountry(e.target.value)}
                      title="Código de país"
                      className="inline-flex items-center px-2 h-9 border border-r-0 border-input rounded-l-md text-xs bg-muted shrink-0 focus:outline-none focus:ring-1 focus:ring-primary"
                    >
                      {PHONE_COUNTRIES.map(c => (
                        <option key={c.code} value={c.code}>
                          {c.flag} +{c.code} {c.label}
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
                {/* Rev. 102 — Banner Habeas Data si check OFF: explica
                    por qué los campos PII están bloqueados (Ley 1581 Art. 9). */}
                {!addConsentChecked && (
                  <div className="rounded-md border border-amber-700/40 bg-amber-700/5 px-3 py-2 text-[11px] text-amber-700 flex items-start gap-2">
                    <ShieldOff className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    <span>
                      Marca el check de consentimiento más abajo para habilitar los
                      campos personales. Sin autorización del titular el sistema
                      solo registra el teléfono (canal de comunicación).
                    </span>
                  </div>
                )}
                <div className="space-y-1">
                  <Label className="text-xs">
                    Nombre completo <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Pasarela de pagos y Transportadora lo requieren)</span>
                  </Label>
                  <Input name="name" placeholder="Juan García López" required disabled={!addConsentChecked} />
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">
                    Correo electrónico <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Pasarela de pagos)</span>
                  </Label>
                  <Input name="email" type="email" placeholder="cliente@email.com" autoComplete="email" required disabled={!addConsentChecked} />
                </div>
                {/* Documento de identidad — Pasarela de pagos PSE/Bancolombia lo exigen en checkout */}
                {addConsentChecked ? (
                  <DocumentFields
                    required
                    showRequiredAsterisk
                    layout="default"
                  />
                ) : (
                  <div className="text-[10px] text-muted-foreground italic">
                    Documento de identidad bloqueado — marca el consentimiento.
                  </div>
                )}
                <div className="space-y-1">
                  <Label className="text-xs flex items-center gap-1">
                    <MapPin className="h-3 w-3" /> Dirección de entrega <span className="text-destructive">*</span>
                    <span className="ml-1 text-[10px] text-muted-foreground">(Envia exige street + city + state + postal)</span>
                  </Label>
                  {addConsentChecked ? (
                    <AddressSelector key={addressResetKey} fieldPrefix="addr" showBuildingDetails />
                  ) : (
                    <div className="text-[10px] text-muted-foreground italic">
                      Dirección bloqueada — marca el consentimiento.
                    </div>
                  )}
                </div>
                <div className="space-y-1">
                  <Label className="text-xs">Notas internas (opcional)</Label>
                  <Input name="notes" placeholder="Cliente frecuente..." disabled={!addConsentChecked} />
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
                        <option value="whatsapp">WhatsApp</option>
                        <option value="web_form">Formulario web</option>
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
                      {expandedId === c.id && (() => {
                        const awaitingRenewal = isAwaitingRenewal(c)
                        const consentChecked = isEditConsentChecked(c.id, c.consent_given)
                        // Rev. 102 (Opción A+B Ley 1581):
                        // PII solo editable si HAY consent + (no anonimizado o renovado)
                        const piiUnlocked =
                          consentChecked &&
                          (!awaitingRenewal || !!renewedConsent[c.id])
                        return (
                      <form action={handleEdit} className="mt-3 space-y-3 pt-3 border-t border-border">
                        <input type="hidden" name="contact_id" value={c.id} />

                        {/* Rev. 102 — Opción B Habeas Data: contact post-anonimización */}
                        {awaitingRenewal && (
                          <div className="rounded-lg border border-amber-700/40 bg-amber-700/5 p-3 space-y-2">
                            <div className="flex items-start gap-2 text-xs text-amber-700">
                              <ShieldOff className="h-4 w-4 shrink-0 mt-0.5" />
                              <div className="flex-1">
                                <p className="font-semibold">Contacto anonimizado el {c.consent_revoked_at && new Date(c.consent_revoked_at).toLocaleDateString('es-CO')}.</p>
                                <p className="mt-0.5 text-muted-foreground">
                                  Para volver a registrar PII (nombre, email, documento, dirección, notas)
                                  el sistema requiere que el titular haya otorgado consentimiento renovado.
                                  Confirma que cuentas con esa autorización y describe la evidencia.
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
                                <strong>Confirmo</strong> que el titular ha otorgado consentimiento renovado para tratar nuevamente sus datos personales.
                              </span>
                            </label>
                            {!!renewedConsent[c.id] && (
                              <div className="space-y-1">
                                <Label className="text-xs text-amber-700">
                                  Evidencia del consentimiento renovado <span className="text-destructive">*</span>
                                </Label>
                                <Input
                                  name="renewed_consent_evidence"
                                  required
                                  minLength={10}
                                  maxLength={500}
                                  placeholder="Ej: WhatsApp 2026-05-01 14:30 — el titular respondió 'Sí, autorizo nuevamente'."
                                  className="h-8 text-xs"
                                />
                                <p className="text-[10px] text-muted-foreground">
                                  Mínimo 10 caracteres. Se guarda inmutablemente en el audit log.
                                </p>
                              </div>
                            )}
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
                        {/* Rev. 102 — Bloque Habeas Data reorganizado:
                            check con semántica clara según estado del contact */}
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
                                  {!consentChecked && (
                                    <span className="block text-amber-700 mt-0.5 text-[11px]">
                                      Sin este check los campos personales quedan bloqueados.
                                    </span>
                                  )}
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
                                <option value="whatsapp">WhatsApp</option>
                                <option value="web_form">Formulario web</option>
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
                            return (
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
