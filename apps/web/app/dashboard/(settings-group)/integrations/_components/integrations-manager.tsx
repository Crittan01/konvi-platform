'use client'

import { useState, useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import { DisconnectIntegrationButton } from './disconnect-button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Plug, CheckCircle2, XCircle, AlertCircle, ExternalLink,
  Bot, SendHorizonal, ShieldCheck, Package, Store, Clock,
  MessageCircle, Settings2, ChevronUp, CreditCard, HelpCircle,
  Loader2,
} from 'lucide-react'

type Category = 'todas' | 'canal' | 'logistica' | 'marketplace' | 'notificaciones' | 'pagos'
type Integration = { provider: string; status: string; meta: Record<string, string> }
type NotifSetting = { channel: string; enabled: boolean; config: Record<string, string> }

interface Props {
  waInt: Integration
  waConnected: boolean
  // Sem 7 F2 — métricas plantillas WhatsApp aprobadas para mostrar en card.
  templatesApproved?: number
  templatesTotal?: number
  aveonlineInt: Integration
  aveonlineConnected: boolean
  meliInt: Integration
  meliConnected: boolean
  wompiInt: Integration
  wompiConnected: boolean
  tgConfig?: NotifSetting
  tgConnected: boolean
  connectedCount: number
  isOwner: boolean
  canWrite: boolean
  connectedParam?: string
  errorParam?: string
  meliSameUser?: string
  tgTest?: string
  tgMsg?: string
  waTest?: string
  waMsg?: string
  aveTest?: string
  aveMsg?: string
  saveAveonline: (fd: FormData) => Promise<void>
  disconnectAveonline: () => Promise<void>
  testAveonline: () => Promise<void>
  // Aveonline carriers + capabilities movidos al panel dedicado
  // /integrations/aveonline (tabs Carriers + Capacidades).
  disconnectMeli: () => Promise<void>
  saveWompi: (fd: FormData) => Promise<void>
  disconnectWompi: () => Promise<void>
  saveTelegram: (fd: FormData) => Promise<void>
  disconnectTelegram: () => Promise<void>
  testTelegram: () => Promise<void>
  testWhatsApp: () => Promise<void>
  saveWhatsApp: (fd: FormData) => Promise<void>
  disconnectWhatsApp: () => Promise<void>
}

const TABS: { key: Category; label: string }[] = [
  { key: 'todas', label: 'Todas' },
  { key: 'canal', label: 'Canal' },
  { key: 'logistica', label: 'Logística' },
  { key: 'marketplace', label: 'Marketplace' },
  { key: 'pagos', label: 'Pagos' },
  { key: 'notificaciones', label: 'Notificaciones' },
]

// WhatsApp, Aveonline, MercadoLibre, Wompi, Telegram
const TOTAL_CONNECTORS = 5

const COMING_SOON = [
  { name: 'Shopify', category: 'canal' as Category },
  { name: 'WooCommerce', category: 'canal' as Category },
  { name: 'Zapier / Make', category: 'notificaciones' as Category },
  { name: 'Stripe', category: 'pagos' as Category },
]

function StatusBadge({ connected, colorClass }: { connected: boolean; colorClass: string }) {
  return (
    <div className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border shrink-0 ${
      connected ? colorClass : 'bg-muted text-muted-foreground border-border'
    }`}>
      {connected ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}
      {connected ? 'Conectado' : 'Desconectado'}
    </div>
  )
}

function ConfigToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <Button type="button" size="sm" variant="outline" onClick={onToggle}
      className="h-7 text-xs gap-1.5 shrink-0">
      {open ? <><ChevronUp className="h-3 w-3" /> Ocultar</> : <><Settings2 className="h-3 w-3" /> Configurar</>}
    </Button>
  )
}

function MetaPill({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg bg-muted px-3 py-2 min-w-0">
      <p className="text-[10px] text-muted-foreground uppercase">{label}</p>
      <p className={`text-xs font-mono font-medium mt-0.5 truncate ${className ?? ''}`}>{value || '—'}</p>
    </div>
  )
}

export function IntegrationsManager(props: Props) {
  const {
    waInt, waConnected, templatesApproved, templatesTotal,
    aveonlineInt, aveonlineConnected,
    meliInt, meliConnected,
    wompiInt, wompiConnected,
    tgConfig, tgConnected, connectedCount,
    isOwner, canWrite, connectedParam, errorParam, meliSameUser,
    tgTest, tgMsg, waTest, waMsg,
    aveTest, aveMsg,
    saveAveonline, disconnectAveonline, testAveonline,
    disconnectMeli,
    saveWompi, disconnectWompi,
    saveTelegram, disconnectTelegram, testTelegram,
    testWhatsApp,
    saveWhatsApp, disconnectWhatsApp,
  } = props

  const router   = useRouter()
  const pathname = usePathname()

  // Limpiar params de test/conexión de la URL después de 4 segundos
  useEffect(() => {
    const hasResult = waTest || aveTest || tgTest || connectedParam
    if (!hasResult) return
    const t = setTimeout(() => router.replace(pathname), 4000)
    return () => clearTimeout(t)
  }, [waTest, aveTest, tgTest, connectedParam, router, pathname])

  const [activeFilter, setActiveFilter] = useState<Category>('todas')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [connectingMeli, setConnectingMeli] = useState(false)
  const [meliStartError, setMeliStartError] = useState<string | null>(null)
  const toggle = (id: string) => setOpen(p => ({ ...p, [id]: !p[id] }))

  const startMeliOAuth = async () => {
    // Rev. 108 Layer B (founder 2026-05-27 — auto-loguea cuenta anterior):
    // antes de redirigir a MeLi, confirmar con el tenant que conoce el
    // comportamiento. Si quiere cambiar de cuenta, instruir paso explícito.
    const confirmed = window.confirm(
      '¿Listo para conectar Mercado Libre?\n\n' +
      'Si tu navegador tiene una sesión activa de Mercado Libre, ' +
      'MeLi puede conectarte automáticamente con esa cuenta. ' +
      'Para cambiar de cuenta:\n\n' +
      '1. Cancela este diálogo\n' +
      '2. Cierra sesión en https://mercadolibre.com.co (ícono usuario → Salir)\n' +
      '3. O usa una ventana de incógnito\n' +
      '4. Vuelve aquí y haz click en "Conectar" otra vez\n\n' +
      'Si ya cerraste sesión o es tu primera conexión, presiona "Aceptar".'
    )
    if (!confirmed) return

    setMeliStartError(null)
    setConnectingMeli(true)
    try {
      const res = await fetch('/api/integrations/meli/auth-url', {
        method: 'GET',
        cache: 'no-store',
      })
      const body = await res.json().catch(() => ({} as { detail?: string; auth_url?: string }))
      if (!res.ok || !body.auth_url) {
        setMeliStartError(body?.detail || 'No se pudo iniciar OAuth de Mercado Libre.')
        return
      }

      window.location.href = body.auth_url
    } catch {
      setMeliStartError('No se pudo contactar el API para iniciar OAuth de Mercado Libre.')
    } finally {
      setConnectingMeli(false)
    }
  }

  const cardCategories: Record<string, Category> = {
    whatsapp: 'canal',
    aveonline: 'logistica',
    mercadolibre: 'marketplace',
    wompi: 'pagos',
    telegram: 'notificaciones',
  }

  const allCards = ['whatsapp', 'aveonline', 'mercadolibre', 'wompi', 'telegram']
  const visibleCards = activeFilter === 'todas'
    ? allCards
    : allCards.filter(c => cardCategories[c] === activeFilter)

  const visibleComingSoon = activeFilter === 'todas'
    ? COMING_SOON
    : COMING_SOON.filter(c => c.category === activeFilter)

  return (
    <div className="space-y-5 max-w-7xl">

      {/* Header */}
      <div>
        <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
          <Plug className="h-5 w-5 text-primary" /> Integraciones
        </h1>
        <p className="text-sm text-muted-foreground mt-0.5">
          Conectores activos para tu negocio · {connectedCount}/{TOTAL_CONNECTORS} conectados
        </p>
      </div>

      {/* Banners */}
      {connectedParam && !meliSameUser && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-green-500/30 bg-green-500/10 text-sm text-green-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          {connectedParam === 'mercadolibre' ? 'Mercado Libre' : connectedParam} conectado exitosamente.
        </div>
      )}
      {/* Rev. 108 Layer C — banner same-user reconnect */}
      {connectedParam === 'mercadolibre' && meliSameUser === '1' && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-sm text-amber-400">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <p className="font-medium">
              Conectado con la MISMA cuenta de Mercado Libre que tenías antes
            </p>
            <p className="text-xs leading-relaxed">
              MeLi te auto-confirmó usando la sesión activa de tu navegador.
              Si querías cambiar de cuenta:
            </p>
            <ol className="text-xs leading-relaxed list-decimal list-inside ml-1 mt-1">
              <li>Desconecta Mercado Libre aquí (botón Desconectar de la tarjeta MeLi).</li>
              <li>Sal manualmente de mercadolibre.com.co (ícono usuario → Salir).</li>
              <li>O usa una ventana de incógnito.</li>
              <li>Vuelve a conectar.</li>
            </ol>
          </div>
        </div>
      )}
      {errorParam && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Error al conectar: {errorParam}. Intenta de nuevo.
        </div>
      )}
      {meliStartError && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {meliStartError}
        </div>
      )}
      {tgTest === 'success' && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Telegram verificado — el bot puede enviar alertas de escalamiento al grupo del asesor.
        </div>
      )}
      {tgTest === 'error' && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Error al probar Telegram</p>
            {tgMsg && <p className="text-xs text-red-400/80 mt-0.5 font-mono">{decodeURIComponent(tgMsg)}</p>}
            {tgMsg?.includes('403') && <p className="text-xs text-red-300/90 mt-1.5">El grupo fue eliminado o el bot fue expulsado. Desconecta Telegram, crea un nuevo grupo, agrega el bot como miembro y reconecta.</p>}
            {tgMsg?.includes('400') && <p className="text-xs text-red-300/90 mt-1.5">El Chat ID no es válido. Debe ser negativo (ej: -1001234567890).</p>}
            {tgMsg?.includes('401') && <p className="text-xs text-red-300/90 mt-1.5">Bot Token inválido o revocado. Desconecta y regenera en @BotFather → /token.</p>}
          </div>
        </div>
      )}

      {/* Banners WhatsApp test */}
      {waTest === 'success' && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          WhatsApp verificado — el token es válido y el número está activo. El bot puede enviar mensajes a los clientes.
        </div>
      )}
      {waTest === 'error' && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Error al probar WhatsApp</p>
            {waMsg && <p className="text-xs text-red-400/80 mt-0.5">{decodeURIComponent(waMsg)}</p>}
          </div>
        </div>
      )}

      {/* Banners Aveonline test/connect */}
      {aveTest === 'success' && (
        <div className="flex items-center gap-2 p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 text-sm text-emerald-400">
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          Aveonline verificado — credenciales válidas. El bot puede cotizar con tus carriers asignados.
        </div>
      )}
      {aveTest === 'error' && (
        <div className="flex items-start gap-2 p-3 rounded-xl border border-red-500/30 bg-red-500/10 text-sm text-red-400">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Error al conectar/probar Aveonline</p>
            {aveMsg && <p className="text-xs text-red-400/80 mt-0.5">{decodeURIComponent(aveMsg)}</p>}
          </div>
        </div>
      )}

      {/* Filter tabs */}
      <div className="flex gap-1 flex-wrap">
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveFilter(tab.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeFilter === tab.key
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-muted-foreground hover:bg-muted/80 hover:text-foreground'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ── SECCIÓN 1: Conectores (overview cards) ─────────────────────────── */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <Plug className="h-4 w-4 text-primary shrink-0" />
          <h2 className="text-sm font-semibold text-foreground">Conectores</h2>
          <span className="text-xs text-muted-foreground">
            {activeFilter === 'todas'
              ? '· Estado de cada integración disponible'
              : `· ${visibleCards.length} en esta categoría`}
          </span>
        </div>

      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">

        {/* ── WhatsApp ──────────────────────────────────────────────────────── */}
        {visibleCards.includes('whatsapp') && (
          <div className={`rounded-xl border bg-card overflow-hidden flex flex-col ${waConnected ? 'border-emerald-500/30' : 'border-border'}`}>
            <div className={`px-4 py-3.5 border-b ${waConnected ? 'border-emerald-500/20 bg-emerald-500/5' : 'border-border bg-muted/20'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="h-9 w-9 rounded-xl bg-green-500/15 border border-green-500/20 flex items-center justify-center shrink-0">
                    <MessageCircle className="h-4 w-4 text-green-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-sm">WhatsApp</p>
                    <p className="text-[11px] text-muted-foreground truncate">WhatsApp Cloud API</p>
                  </div>
                </div>
                <StatusBadge connected={waConnected} colorClass="bg-emerald-500/15 text-emerald-400 border-emerald-500/30" />
              </div>
            </div>
            <div className="px-4 py-3.5 space-y-3 flex-1">
              <p className="text-xs text-muted-foreground">Canal de ventas oficial para recibir y enviar mensajes con clientes.</p>
              {waConnected ? (
                <div className="space-y-2.5">
                  <div className="grid grid-cols-2 gap-2">
                    <MetaPill label="WABA ID" value={waInt.meta?.waba_id ?? ''} />
                    <MetaPill label="Token" value={waInt.meta?.token_preview ?? '●●●●'} />
                  </div>
                  <MetaPill label="Phone Number ID" value={waInt.meta?.phone_id_preview ?? ''} />
                  {typeof templatesTotal === 'number' && templatesTotal > 0 && (
                    <MetaPill
                      label="Plantillas"
                      value={`${templatesApproved ?? 0}/${templatesTotal} aprobadas`}
                    />
                  )}
                  {/* Gestionar panel completo (Sem 7 F2 — restructura Integraciones).
                      Lleva a /integrations/whatsapp con tabs Setup + Plantillas +
                      Calidad + Opt-outs. */}
                  <a
                    href="/dashboard/integrations/whatsapp"
                    className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10 transition-colors group"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Settings2 className="h-3 w-3" />
                      Gestionar panel completo
                    </span>
                    <span className="inline-flex items-center gap-0.5 transition-transform group-hover:translate-x-0.5">
                      →
                    </span>
                  </a>
                  {isOwner && (
                    <div className="flex gap-2">
                      <form action={testWhatsApp} className="flex-1">
                        <SubmitButton size="sm" variant="outline" pendingText="Probando..." savedText="OK"
                          className="w-full h-8 text-xs gap-1.5">
                          <SendHorizonal className="h-3 w-3" /> Probar
                        </SubmitButton>
                      </form>
                      <DisconnectIntegrationButton
                        provider="whatsapp" providerLabel="WhatsApp"
                        action={disconnectWhatsApp}
                        className="h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                      />
                    </div>
                  )}
                </div>
              ) : isOwner ? (
                <div className="space-y-3">
                  <div className="flex justify-end">
                    <ConfigToggle open={!!open.whatsapp} onToggle={() => toggle('whatsapp')} />
                  </div>
                  {open.whatsapp && (
                    <>
                      <div className="rounded-lg border border-green-500/20 bg-green-500/5 p-3 space-y-2">
                        <p className="text-[10px] font-semibold text-green-400 uppercase tracking-wider">Pasos de configuración</p>
                        <div className="space-y-2">
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-green-500/25 text-green-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">1</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Ve a <span className="font-mono text-foreground">developers.facebook.com</span> → My Apps → selecciona tu app de tipo <strong className="text-foreground font-medium">Business</strong>.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-green-500/25 text-green-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">2</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Menú izquierdo → <strong className="text-foreground font-medium">WhatsApp → Configuración API</strong> → copia el <strong className="text-foreground font-medium">WABA ID</strong> y el <strong className="text-foreground font-medium">Phone Number ID</strong>.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-green-500/25 text-green-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">3</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              <strong className="text-foreground font-medium">Meta Business Suite → Usuarios del sistema</strong> → crea System User (Admin) → Generar token → activa <span className="font-mono text-green-400 text-[10px]">whatsapp_business_messaging</span> y <span className="font-mono text-green-400 text-[10px]">whatsapp_business_management</span>.
                            </p>
                          </div>
                        </div>
                      </div>
                      <form action={saveWhatsApp} className="space-y-2.5">
                        <div className="grid grid-cols-2 gap-2">
                          <div className="space-y-1">
                            <Label className="text-xs">WABA ID</Label>
                            <Input name="waba_id" placeholder="123456789…" required className="h-8 text-xs font-mono" />
                          </div>
                          <div className="space-y-1">
                            <Label className="text-xs">Phone Number ID</Label>
                            <Input name="phone_number_id" placeholder="123456789…" required className="h-8 text-xs font-mono" />
                          </div>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Token de Acceso (System User)</Label>
                          <Input type="password" name="access_token" placeholder="EAABs…" required autoComplete="off" className="h-8 text-xs font-mono" />
                        </div>
                        <SubmitButton size="sm" pendingText="Conectando..." savedText="¡Conectado!" className="w-full h-8 text-xs gap-1.5 bg-green-600 hover:bg-green-500 text-white">
                          <MessageCircle className="h-3.5 w-3.5" /> Conectar WhatsApp
                        </SubmitButton>
                      </form>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Solo el Administrador puede configurar esta integración.</p>
              )}
            </div>
          </div>
        )}

        {/* ── Aveonline (provider único activo shipping, ADR-0019) ──────────── */}
        {/*
          Tarjeta paritaria con Wompi/WhatsApp: cuando connected muestra
          meta + acciones Probar/Desconectar. Cuando disconnected expone
          form inline con usuario + password. Config avanzada (auth_version,
          tiempo_token) vive en /integrations/aveonline.
        */}
        {visibleCards.includes('aveonline') && (
          <div className={`rounded-xl border bg-card overflow-hidden flex flex-col ${aveonlineConnected ? 'border-cyan-500/30' : 'border-border'}`}>
            <div className={`px-4 py-3.5 border-b ${aveonlineConnected ? 'border-cyan-500/20 bg-cyan-500/5' : 'border-border bg-muted/20'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="h-9 w-9 rounded-xl bg-cyan-500/15 border border-cyan-500/20 flex items-center justify-center shrink-0">
                    <Package className="h-4 w-4 text-cyan-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-sm">Aveonline</p>
                    <p className="text-[11px] text-muted-foreground truncate">Shipping multi-carrier Colombia</p>
                  </div>
                </div>
                <StatusBadge connected={aveonlineConnected} colorClass="bg-cyan-500/15 text-cyan-400 border-cyan-500/30" />
              </div>
            </div>
            <div className="px-4 py-3.5 space-y-3 flex-1">
              <p className="text-xs text-muted-foreground">Cotiza envíos multi-carrier en Colombia con COD nativo (Ecart Pay).</p>
              {aveonlineConnected ? (
                <div className="space-y-2.5">
                  <div className="grid grid-cols-2 gap-2">
                    <MetaPill
                      label="Empresa"
                      value={String(aveonlineInt.meta?.empresa_id ?? '—')}
                    />
                    <MetaPill
                      label="Auth"
                      value={String(aveonlineInt.meta?.auth_version ?? 'v1.0')}
                    />
                  </div>
                  {aveonlineInt.meta?.nombre_asesor && (
                    <MetaPill
                      label="Asesor logístico"
                      value={String(aveonlineInt.meta.nombre_asesor)}
                    />
                  )}
                  <a
                    href="/dashboard/integrations/aveonline"
                    className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10 transition-colors group"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Settings2 className="h-3 w-3" />
                      Gestionar panel completo
                    </span>
                    <span className="inline-flex items-center gap-0.5 transition-transform group-hover:translate-x-0.5">
                      →
                    </span>
                  </a>
                  {(isOwner || canWrite) && (
                    <div className="flex gap-2">
                      <form action={testAveonline} className="flex-1">
                        <SubmitButton size="sm" variant="outline" pendingText="Probando..." savedText="OK"
                          className="w-full h-8 text-xs gap-1.5">
                          <SendHorizonal className="h-3 w-3" /> Probar
                        </SubmitButton>
                      </form>
                      <DisconnectIntegrationButton
                        provider="aveonline" providerLabel="Aveonline"
                        action={disconnectAveonline}
                        className="h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                      />
                    </div>
                  )}
                </div>
              ) : isOwner || canWrite ? (
                <div className="space-y-3">
                  <div className="flex justify-end">
                    <ConfigToggle open={!!open.aveonline} onToggle={() => toggle('aveonline')} />
                  </div>
                  {open.aveonline && (
                    <>
                      <div className="rounded-lg border border-cyan-500/20 bg-cyan-500/5 p-3 space-y-2">
                        <p className="text-[10px] font-semibold text-cyan-400 uppercase tracking-wider">Pasos de configuración</p>
                        <div className="space-y-2">
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-cyan-500/25 text-cyan-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">1</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Ingresa el <strong className="text-foreground font-medium">usuario y password</strong> de tu cuenta Aveonline (la misma que usas en <span className="font-mono text-foreground">app.aveonline.co</span>).
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-cyan-500/25 text-cyan-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">2</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Validamos contra <span className="font-mono text-[10px] text-foreground">autenticarusuario.php</span> antes de guardar. El password se almacena cifrado en Supabase Vault.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-cyan-500/25 text-cyan-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">3</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              ¿No tienes cuenta? Cuenta DEMO: <span className="font-mono text-foreground">demointegracion</span> / <span className="font-mono text-foreground">demointegra2021</span>.
                            </p>
                          </div>
                        </div>
                      </div>
                      <form action={saveAveonline} className="space-y-2.5">
                        <div className="space-y-1">
                          <Label className="text-xs">Usuario</Label>
                          <Input name="usuario" required minLength={3} placeholder="mi-empresa-ecommerce" autoComplete="username" className="h-8 text-xs font-mono" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Password</Label>
                          <Input type="password" name="password" required minLength={4} placeholder="••••••••" autoComplete="current-password" className="h-8 text-xs font-mono" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Versión de auth</Label>
                          <select name="auth_version" defaultValue="v1.0"
                            className="w-full h-8 rounded-md border border-input bg-background text-xs px-2 text-foreground">
                            <option value="v1.0">v1.0 — legacy (recomendado)</option>
                            <option value="v2.0">v2.0 — JWT 12h fijo</option>
                          </select>
                        </div>
                        <SubmitButton size="sm" pendingText="Conectando..." savedText="¡Conectado!"
                          className="w-full h-8 text-xs gap-1.5 bg-cyan-600 hover:bg-cyan-500 text-white">
                          <Package className="h-3.5 w-3.5" /> Conectar Aveonline
                        </SubmitButton>
                      </form>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Solo el Administrador puede configurar esta integración.</p>
              )}
            </div>
          </div>
        )}

        {/* ── Mercado Libre ─────────────────────────────────────────────────── */}
        {visibleCards.includes('mercadolibre') && (
          <div className={`rounded-xl border bg-card overflow-hidden flex flex-col ${meliConnected ? 'border-yellow-500/30' : 'border-border'}`}>
            <div className={`px-4 py-3.5 border-b ${meliConnected ? 'border-yellow-500/20 bg-yellow-500/5' : 'border-border bg-muted/20'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="h-9 w-9 rounded-xl bg-yellow-400/15 border border-yellow-400/30 flex items-center justify-center shrink-0">
                    <Store className="h-4 w-4 text-yellow-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-sm">Mercado Libre</p>
                    <p className="text-[11px] text-muted-foreground truncate">Marketplace · OAuth 2.0</p>
                  </div>
                </div>
                <StatusBadge connected={meliConnected} colorClass="bg-yellow-500/15 text-yellow-400 border-yellow-500/30" />
              </div>
            </div>
            <div className="px-4 py-3.5 space-y-3 flex-1">
              <p className="text-xs text-muted-foreground">Sincroniza catálogo y recibe pedidos de MeLi vía webhooks.</p>
              {meliInt?.status === 'error' && isOwner ? (
                /* Token expirado o error de refresh — acción clara para el operador */
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/8 p-3 space-y-2">
                  <p className="text-xs font-medium text-amber-400">Token expirado</p>
                  <p className="text-[11px] text-amber-400/70">El acceso a Mercado Libre expiró. Reconecta tu cuenta para restaurar la sincronización.</p>
                  <button onClick={startMeliOAuth} disabled={connectingMeli}
                    className="mt-1 h-7 text-xs px-3 rounded-md border border-amber-500/40 text-amber-400 hover:bg-amber-500/10 transition-colors disabled:opacity-50">
                    {connectingMeli ? 'Conectando...' : 'Reconectar Mercado Libre'}
                  </button>
                </div>
              ) : meliConnected ? (
                <div className="space-y-2.5">
                  <MetaPill label="Usuario MeLi ID" value={meliInt.meta?.user_id ?? '—'} />
                  <a
                    href="/dashboard/integrations/mercadolibre"
                    className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10 transition-colors group"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Settings2 className="h-3 w-3" />
                      Gestionar panel completo
                    </span>
                    <span className="inline-flex items-center gap-0.5 transition-transform group-hover:translate-x-0.5">
                      →
                    </span>
                  </a>
                  {isOwner && (
                    <DisconnectIntegrationButton
                      provider="mercadolibre" providerLabel="Mercado Libre"
                      action={disconnectMeli}
                      className="w-full h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                    />
                  )}
                </div>
              ) : isOwner ? (
                <div className="space-y-3">
                  <div className="flex justify-end">
                    <ConfigToggle open={!!open.meli} onToggle={() => toggle('meli')} />
                  </div>
                  {open.meli && (
                    <>
                      <div className="rounded-lg border border-yellow-500/20 bg-yellow-500/5 p-3 space-y-2.5">
                        <p className="text-[10px] font-semibold text-yellow-400 uppercase tracking-wider">Requisito</p>
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                          Necesitas la <strong className="text-foreground font-medium">cuenta principal vendedor</strong> de Mercado Libre Colombia con verificación de identidad completa — no una cuenta de operador.
                        </p>
                        <div className="border-t border-yellow-500/15 pt-2 space-y-2">
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-yellow-500/25 text-yellow-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">1</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">Presiona <strong className="text-foreground font-medium">Conectar con Mercado Libre</strong> — serás redirigido a MeLi.</p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-yellow-500/25 text-yellow-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">2</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">Inicia sesión con tu cuenta vendedor → revisa permisos → presiona <strong className="text-foreground font-medium">Permitir</strong>.</p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-yellow-500/25 text-yellow-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">3</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">Serás redirigido de vuelta con estado <strong className="text-foreground font-medium">Conectado</strong> y tu MeLi ID visible.</p>
                          </div>
                        </div>
                        <div className="border-t border-yellow-500/15 pt-2">
                          <p className="text-[10px] text-muted-foreground/70 leading-relaxed">
                            <span className="text-yellow-400/80 font-medium">Vigencia:</span> 6 meses. Pasado ese tiempo deberás reconectar.
                          </p>
                          <p className="text-[10px] text-muted-foreground/70 leading-relaxed mt-1">
                            <span className="text-yellow-400/80 font-medium">Error &quot;la aplicación no puede conectarse&quot;:</span> estás usando una cuenta de operador o la verificación de identidad está incompleta.
                          </p>
                        </div>
                      </div>
                      <Button
                        size="sm"
                        className="w-full h-8 text-xs gap-1.5 bg-yellow-500 hover:bg-yellow-400 text-black"
                        onClick={startMeliOAuth}
                        disabled={connectingMeli}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        {connectingMeli ? 'Conectando...' : 'Conectar con Mercado Libre'}
                      </Button>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Solo el Administrador puede configurar esta integración.</p>
              )}
            </div>
          </div>
        )}

        {/* ── Wompi ─────────────────────────────────────────────────────────── */}
        {visibleCards.includes('wompi') && (
          <div className={`rounded-xl border bg-card overflow-hidden flex flex-col ${wompiConnected ? 'border-violet-500/30' : 'border-border'}`}>
            <div className={`px-4 py-3.5 border-b ${wompiConnected ? 'border-violet-500/20 bg-violet-500/5' : 'border-border bg-muted/20'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="h-9 w-9 rounded-xl bg-violet-500/15 border border-violet-500/20 flex items-center justify-center shrink-0">
                    <CreditCard className="h-4 w-4 text-violet-400" />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-sm">Wompi</p>
                    <p className="text-[11px] text-muted-foreground truncate">Pagos en línea Colombia</p>
                  </div>
                </div>
                <StatusBadge connected={wompiConnected} colorClass="bg-violet-500/15 text-violet-400 border-violet-500/30" />
              </div>
            </div>
            <div className="px-4 py-3.5 space-y-3 flex-1">
              <p className="text-xs text-muted-foreground">Genera links de pago y recibe confirmaciones automáticas vía webhook.</p>
              {wompiConnected ? (
                <div className="space-y-2.5">
                  <div className="grid grid-cols-2 gap-2">
                    <MetaPill label="Clave privada" value={wompiInt.meta?.private_key_preview ?? '●●●●'} />
                    <MetaPill
                      label="Entorno"
                      value={wompiInt.meta?.environment === 'production' ? 'Producción' : 'Sandbox'}
                      className={wompiInt.meta?.environment === 'production' ? 'text-emerald-400' : 'text-amber-400'}
                    />
                  </div>
                  <a
                    href="/dashboard/integrations/wompi"
                    className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10 transition-colors group"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Settings2 className="h-3 w-3" />
                      Gestionar panel completo
                    </span>
                    <span className="inline-flex items-center gap-0.5 transition-transform group-hover:translate-x-0.5">
                      →
                    </span>
                  </a>
                  {isOwner && (
                    <DisconnectIntegrationButton
                      provider="wompi" providerLabel="Wompi"
                      action={disconnectWompi}
                      className="w-full h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                    />
                  )}
                </div>
              ) : isOwner ? (
                <div className="space-y-3">
                  <div className="flex justify-end">
                    <ConfigToggle open={!!open.wompi} onToggle={() => toggle('wompi')} />
                  </div>
                  {open.wompi && (
                    <>
                      <div className="rounded-lg border border-violet-500/20 bg-violet-500/5 p-3 space-y-2">
                        <p className="text-[10px] font-semibold text-violet-400 uppercase tracking-wider">Pasos de configuración</p>
                        <div className="space-y-2">
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-violet-500/25 text-violet-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">1</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Regístrate en <span className="font-mono text-foreground">wompi.co</span> y activa tu cuenta de comercio.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-violet-500/25 text-violet-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">2</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              En el Dashboard de Wompi → <strong className="text-foreground font-medium">Desarrolladores</strong> → copia la <strong className="text-foreground font-medium">Llave Privada</strong> y la <strong className="text-foreground font-medium">Llave de Eventos</strong>.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-violet-500/25 text-violet-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">3</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Configura el webhook en Wompi: <span className="font-mono text-[10px] text-foreground break-all">https://konvi-api.onrender.com/api/v1/webhooks/wompi</span>
                            </p>
                          </div>
                        </div>
                      </div>
                      <form action={saveWompi} className="space-y-2.5">
                        <div className="space-y-1">
                          <Label className="text-xs">Entorno</Label>
                          <select name="environment"
                            className="w-full h-8 rounded-md border border-input bg-background text-xs px-2 text-foreground">
                            <option value="sandbox">Sandbox (pruebas)</option>
                            <option value="production">Producción</option>
                          </select>
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Llave Privada</Label>
                          <Input type="password" name="private_key" required autoComplete="off" placeholder="prv_test_..." className="h-8 text-xs font-mono" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Llave de Eventos (Events Key)</Label>
                          <Input type="password" name="events_key" required autoComplete="off" placeholder="test_events_..." className="h-8 text-xs font-mono" />
                        </div>
                        <SubmitButton size="sm" pendingText="Conectando..." savedText="¡Conectado!"
                          className="w-full h-8 text-xs gap-1.5 bg-violet-600 hover:bg-violet-500 text-white">
                          <CreditCard className="h-3.5 w-3.5" /> Conectar Wompi
                        </SubmitButton>
                      </form>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Solo el Administrador puede configurar esta integración.</p>
              )}
            </div>
          </div>
        )}

        {/* ── Telegram ──────────────────────────────────────────────────────── */}
        {visibleCards.includes('telegram') && (
          <div className={`rounded-xl border bg-card overflow-hidden flex flex-col ${tgConnected ? 'border-sky-500/30' : 'border-border'}`}>
            <div className={`px-4 py-3.5 border-b ${tgConnected ? 'border-sky-500/20 bg-sky-500/5' : 'border-border bg-muted/20'}`}>
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className={`h-9 w-9 rounded-xl flex items-center justify-center border ${tgConnected ? 'bg-sky-500/20 border-sky-500/30' : 'bg-white/10 border-white/10'}`}>
                    <Bot className={`h-4 w-4 ${tgConnected ? 'text-sky-400' : 'text-muted-foreground'}`} />
                  </div>
                  <div className="min-w-0">
                    <p className="font-semibold text-sm">Telegram</p>
                    <p className="text-[11px] text-muted-foreground truncate">Alertas Operativas</p>
                  </div>
                </div>
                <StatusBadge connected={tgConnected} colorClass="bg-sky-500/15 text-sky-400 border-sky-500/30" />
              </div>
            </div>
            <div className="px-4 py-3.5 space-y-3 flex-1">
              <p className="text-xs text-muted-foreground">Alertas de pedidos, stock bajo y reclamos en un grupo privado de Telegram.</p>
              {tgConnected ? (
                <div className="space-y-2.5">
                  <div className="grid grid-cols-2 gap-2">
                    <MetaPill label="Bot Token" value={tgConfig?.config?.token_preview ?? '●●●●●●●●'} />
                    <MetaPill label="Chat ID" value={tgConfig?.config?.chat_id ?? '—'} />
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-emerald-400">
                    <ShieldCheck className="h-3 w-3 shrink-0" /> Alertas habilitadas
                  </div>
                  <a
                    href="/dashboard/integrations/telegram"
                    className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs font-medium text-primary hover:bg-primary/10 transition-colors group"
                  >
                    <span className="inline-flex items-center gap-1.5">
                      <Settings2 className="h-3 w-3" />
                      Gestionar panel completo
                    </span>
                    <span className="inline-flex items-center gap-0.5 transition-transform group-hover:translate-x-0.5">
                      →
                    </span>
                  </a>
                  <div className="flex gap-2">
                    <form action={testTelegram} className="flex-1">
                      <SubmitButton size="sm" variant="outline" pendingText="Probando..." savedText="OK"
                        className="w-full h-8 text-xs gap-1.5">
                        <SendHorizonal className="h-3.5 w-3.5" /> Probar
                      </SubmitButton>
                    </form>
                    {canWrite && (
                      <DisconnectIntegrationButton
                        provider="telegram" providerLabel="Telegram"
                        action={disconnectTelegram}
                        className="h-8 text-xs text-destructive border-destructive/30 hover:bg-destructive/10"
                      >
                        Desconectar
                      </DisconnectIntegrationButton>
                    )}
                  </div>
                </div>
              ) : canWrite ? (
                <div className="space-y-3">
                  <div className="flex justify-end">
                    <ConfigToggle open={!!open.telegram} onToggle={() => toggle('telegram')} />
                  </div>
                  {open.telegram && (
                    <>
                      <div className="rounded-lg border border-sky-500/20 bg-sky-500/5 p-3 space-y-2">
                        <p className="text-[10px] font-semibold text-sky-400 uppercase tracking-wider">Pasos de configuración</p>
                        <div className="space-y-2">
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">1</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              En Telegram busca <span className="font-mono text-foreground">@BotFather</span> → <span className="font-mono text-sky-400">/newbot</span> → sigue los pasos → copia el <strong className="text-foreground font-medium">Bot Token</strong>.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">2</span>
                            <p className="text-[11px] text-muted-foreground leading-relaxed">
                              Crea un <strong className="text-foreground font-medium">grupo privado</strong> y agrega el bot como miembro.
                            </p>
                          </div>
                          <div className="flex gap-2">
                            <span className="h-4 w-4 rounded-full bg-sky-500/25 text-sky-400 flex items-center justify-center text-[10px] font-bold shrink-0 mt-px">3</span>
                            <div className="text-[11px] text-muted-foreground leading-relaxed space-y-1 min-w-0">
                              <p>Abre en el navegador:</p>
                              <p className="font-mono text-[10px] text-sky-300/80 bg-black/20 rounded px-2 py-1 break-all leading-normal">
                                api.telegram.org/bot<span className="text-sky-400">TOKEN</span>/getUpdates
                              </p>
                              <p>En el JSON busca <span className="font-mono text-foreground">&quot;chat&quot; → &quot;id&quot;</span>: número negativo.</p>
                            </div>
                          </div>
                        </div>
                      </div>
                      <form action={saveTelegram} className="space-y-2.5">
                        <div className="space-y-1">
                          <Label className="text-xs">Bot Token</Label>
                          <Input type="password" name="bot_token" placeholder="123456789:AAG…" required autoComplete="off" className="h-8 text-xs font-mono" />
                        </div>
                        <div className="space-y-1">
                          <Label className="text-xs">Chat ID del grupo</Label>
                          <Input
                            name="chat_id"
                            placeholder="-1001234567890"
                            required
                            pattern="-\d+"
                            title="El Chat ID de un grupo siempre es un número negativo (ej: -1001234567890)"
                            className="h-8 text-xs font-mono"
                          />
                          <p className="text-[10px] text-muted-foreground">Debe ser un número negativo — los grupos de Telegram siempre tienen ID negativo.</p>
                        </div>
                        <SubmitButton size="sm" pendingText="Conectando..." savedText="¡Conectado!" className="w-full h-8 text-xs gap-1.5">
                          <Bot className="h-3.5 w-3.5" /> Conectar Telegram
                        </SubmitButton>
                      </form>
                    </>
                  )}
                </div>
              ) : (
                <p className="text-xs text-muted-foreground">Solo Administrador o Supervisor pueden configurar Telegram.</p>
              )}
            </div>
          </div>
        )}

        {/* ── Coming Soon ───────────────────────────────────────────────────── */}
        {visibleComingSoon.map(item => (
          <div key={item.name} className="rounded-xl border border-dashed border-border bg-card/50 flex flex-col p-4 opacity-60">
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2.5">
                <div className="h-9 w-9 rounded-xl bg-muted border border-border flex items-center justify-center shrink-0">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                </div>
                <div>
                  <p className="font-semibold text-sm text-muted-foreground">{item.name}</p>
                  <p className="text-[11px] text-muted-foreground/60">Próximamente</p>
                </div>
              </div>
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full border border-border text-muted-foreground">
                En desarrollo
              </span>
            </div>
          </div>
        ))}

      </div>
      </div>{/* ── /SECCIÓN 1 Conectores ── */}

      {/* SECCIÓN 2 (Configuración avanzada Aveonline) movida al panel
          /integrations/aveonline (tabs Carriers + Capacidades). */}

      {/* ── SECCIÓN 3 (futura): tab "Todas" — info contextual ────────────── */}
      {activeFilter === 'todas' && (
        <div className="border-t border-border pt-4 mt-4">
          <div className="rounded-md border border-border bg-muted/20 px-3 py-2.5 text-xs text-muted-foreground flex items-start gap-2">
            <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>
              <b className="text-foreground">¿Necesitas configuración detallada?</b>
              {' '}Selecciona la categoría correspondiente arriba (Logística para Envía,
              Canal para WhatsApp, Pagos para Wompi, etc.) — verás opciones avanzadas
              específicas de cada conector.
            </span>
          </div>
        </div>
      )}

    </div>
  )
}


