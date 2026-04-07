import { createClient } from '@/utils/supabase/server'
import { redirect } from 'next/navigation'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'

export default async function DashboardPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  if (!user) {
    redirect('/login')
  }

  // Comprobar enlace del Tenant
  const { data: tenantUsers } = await supabase
    .from('tenant_users')
    .select('role, tenants:tenant_id(name)')
    .eq('user_id', user.id)

  const theTenant = tenantUsers?.[0]?.tenants as any

  return (
    <div className="flex h-screen w-full items-center justify-center bg-background p-6">
      <Card className="w-full max-w-3xl border-primary/20">
        <CardHeader>
          <CardTitle className="text-3xl tracking-tight text-primary">
            ¡Arquitectura Viva!
          </CardTitle>
          <CardDescription className="text-lg">
            Plataforma Multi-Tenant Iniciada Exitosamente.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-lg border p-4">
              <p className="text-sm text-muted-foreground mb-1">Identidad de Sesión</p>
              <p className="font-medium text-foreground">{user.email}</p>
            </div>
            <div className="rounded-lg border p-4">
              <p className="text-sm text-muted-foreground mb-1">Empresa Acoplada (Tenant RLS)</p>
              <p className="font-medium text-foreground">{theTenant?.name || "Matriz Commerce Dev"}</p>
            </div>
          </div>
          <div className="mt-8 rounded-md bg-muted p-4">
            <p className="text-sm">
             Tus flujos del Orquestador de Meta y el Supabase Cloud ahora están amparados gráficamente.
             El Router de Next.js está protegiendo tus datos.
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
