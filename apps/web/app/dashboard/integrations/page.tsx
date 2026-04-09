import { createClient } from '@/utils/supabase/server'
import { revalidatePath } from 'next/cache'
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'

type Integration = {
  provider: string
  status: string
  meta: Record<string, string>
  platform_configured?: boolean
}

const PROVIDER_LABELS: Record<string, string> = {
  envia: 'Envia (Shipping)',
  mercadolibre: 'Mercado Libre',
}

export default async function IntegrationsPage({
  searchParams,
}: {
  searchParams: { connected?: string; error?: string }
}) {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const meta = (session?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
  const tenantId = meta.tenant_id
  const role = meta.role ?? 'agent'
  const isOwner = role === 'owner'

  let integrations: Integration[] = []

  if (tenantId) {
    const { data } = await supabase
      .from('tenant_integrations')
      .select('provider, status, meta')
      .eq('tenant_id', tenantId)
    integrations = (data as Integration[]) || []
  }

  // Asegurar que siempre aparezcan ambas integraciones aunque no existan en DB
  const providers = ['envia', 'mercadolibre']
  const fullList: Integration[] = providers.map(p =>
    integrations.find(i => i.provider === p) ?? { provider: p, status: 'disconnected', meta: {} }
  )

  const enviaConnected = fullList.find(i => i.provider === 'envia')?.status === 'connected'

  // ── Server Actions ────────────────────────────────────────────────────────

  async function saveEnviaKey(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    const token = formData.get('api_token') as string
    const sandbox = formData.get('sandbox') === 'on'

    await sb.from('tenant_integrations').upsert({
      tenant_id: m.tenant_id,
      provider: 'envia',
      status: 'connected',
      credentials: { api_token: token, sandbox },
      meta: {
        token_preview: `${token.slice(0, 6)}...${token.slice(-4)}`,
        environment: sandbox ? 'sandbox' : 'production',
      },
    }, { onConflict: 'tenant_id,provider' })

    revalidatePath('/dashboard/integrations')
  }

  async function disconnectEnvia(formData: FormData) {
    'use server'
    const sb = createClient()
    const { data: { session: s } } = await sb.auth.getSession()
    const m = (s?.user?.app_metadata ?? {}) as { tenant_id?: string; role?: string }
    if (!m.tenant_id || m.role !== 'owner') return

    await sb.from('tenant_integrations').update({
      status: 'disconnected',
      credentials: {},
    }).eq('tenant_id', m.tenant_id).eq('provider', 'envia')

    revalidatePath('/dashboard/integrations')
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold tracking-tight text-primary">Integraciones</h1>
        <Badge variant="outline" className="text-xs capitalize">{role}</Badge>
      </div>

      {/* Banner de resultado OAuth */}
      {searchParams.connected && (
        <div className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
          ✅ {PROVIDER_LABELS[searchParams.connected] ?? searchParams.connected} conectado exitosamente.
        </div>
      )}
      {searchParams.error && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          ❌ Error al conectar: {searchParams.error}. Intenta de nuevo.
        </div>
      )}

      <div className="grid gap-6 md:grid-cols-2">

        {/* ── Envia ── */}
        <Card>
          <CardHeader>
            <div className="flex justify-between items-start">
              <div>
                <CardTitle>Envia — Shipping</CardTitle>
                <CardDescription>Cotiza envíos, genera etiquetas y hace tracking con múltiples carriers.</CardDescription>
              </div>
              <Badge variant={enviaConnected ? 'default' : 'secondary'} className="shrink-0">
                {enviaConnected ? 'Conectado' : 'Desconectado'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            {enviaConnected ? (
              <div className="space-y-3">
                <div>
                  <p className="text-xs text-muted-foreground">Token</p>
                  <p className="font-mono text-sm">
                    {fullList.find(i => i.provider === 'envia')?.meta?.token_preview ?? '***'}
                  </p>
                  <p className="text-xs text-muted-foreground capitalize">
                    Entorno: {fullList.find(i => i.provider === 'envia')?.meta?.environment ?? '—'}
                  </p>
                </div>
                {isOwner && (
                  <form action={disconnectEnvia}>
                    <Button type="submit" size="sm" variant="destructive">Desconectar</Button>
                  </form>
                )}
              </div>
            ) : isOwner ? (
              <form action={saveEnviaKey} className="space-y-3">
                <div className="space-y-1">
                  <Label>API Token de Envia</Label>
                  <Input name="api_token" type="password" placeholder="Tu Bearer token de Envia" required />
                  <p className="text-xs text-muted-foreground">
                    Obtenlo en <span className="font-mono">app.envia.com</span> → Configuración → API.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <input type="checkbox" name="sandbox" id="envia_sandbox" className="h-4 w-4" />
                  <Label htmlFor="envia_sandbox" className="text-sm font-normal">Usar entorno sandbox</Label>
                </div>
                <Button type="submit" size="sm">Conectar Envia</Button>
              </form>
            ) : (
              <p className="text-sm text-muted-foreground">Solo el owner puede configurar integraciones.</p>
            )}
          </CardContent>
        </Card>

        {/* ── MercadoLibre ── */}
        <Card>
          <CardHeader>
            <div className="flex justify-between items-start">
              <div>
                <CardTitle>Mercado Libre</CardTitle>
                <CardDescription>Sincroniza catálogo y pedidos con tu cuenta de vendedor MeLi.</CardDescription>
              </div>
              <Badge
                variant={fullList.find(i => i.provider === 'mercadolibre')?.status === 'connected' ? 'default' : 'secondary'}
                className="shrink-0"
              >
                {fullList.find(i => i.provider === 'mercadolibre')?.status === 'connected' ? 'Conectado' : 'Desconectado'}
              </Badge>
            </div>
          </CardHeader>
          <CardContent>
            {fullList.find(i => i.provider === 'mercadolibre')?.status === 'connected' ? (
              <div className="space-y-3">
                <div>
                  <p className="text-xs text-muted-foreground">Usuario MeLi ID</p>
                  <p className="font-mono text-sm">
                    {fullList.find(i => i.provider === 'mercadolibre')?.meta?.user_id ?? '—'}
                  </p>
                </div>
                {isOwner && (
                  <Button size="sm" variant="destructive" disabled>
                    Desconectar (próximamente)
                  </Button>
                )}
              </div>
            ) : isOwner ? (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  Conecta tu cuenta de vendedor via OAuth. Necesitas:
                </p>
                <ul className="text-xs text-muted-foreground list-disc list-inside space-y-1">
                  <li>Haber completado IH-007 (registrar app en MeLi Developers)</li>
                  <li>MELI_CLIENT_ID y MELI_CLIENT_SECRET configurados en Render</li>
                </ul>
                <Button size="sm" disabled className="w-full">
                  Conectar con Mercado Libre
                  <span className="ml-2 text-xs">(requiere IH-007)</span>
                </Button>
                <p className="text-xs text-muted-foreground">
                  Ver <code>docs/operations/HUMAN_INTERVENTIONS.md</code> — IH-007.
                </p>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Solo el owner puede configurar integraciones.</p>
            )}
          </CardContent>
        </Card>

      </div>
    </div>
  )
}
