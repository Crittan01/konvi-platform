import { PauseCircle } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'

export const metadata = {
  title: 'Cuenta suspendida — Konvi',
}

export default function CuentaSuspendidaPage() {
  return (
    <div className="light flex min-h-screen w-full items-center justify-center bg-[#131A19] p-6">
      <div className="w-full max-w-[420px]">
        <div className="flex flex-col items-center mb-6">
          <div className="h-12 w-12 rounded-xl bg-primary/20 text-primary flex items-center justify-center mb-3 shadow-lg ring-1 ring-white/10">
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>
          </div>
          <h1 className="text-2xl font-bold text-white tracking-tight">Konvi</h1>
        </div>
        <Card className="dark border-white/10 bg-card/75 backdrop-blur-xl shadow-2xl">
          <CardContent className="pt-6 text-center space-y-5">
            <div className="flex justify-center">
              <div className="h-16 w-16 rounded-2xl bg-warning-bg border border-warning-border flex items-center justify-center">
                <PauseCircle className="h-8 w-8 text-warning-fg" aria-hidden="true" />
              </div>
            </div>
            <div className="space-y-2">
              <h2 className="text-xl font-bold text-foreground">Cuenta suspendida</h2>
              <p className="text-sm text-muted-foreground leading-relaxed">
                Tu acceso a esta consola fue suspendido temporalmente por el administrador de tu negocio.
                No es un problema con tu contraseña, así que restablecerla no reactivará tu acceso.
              </p>
              <p className="text-sm text-muted-foreground">
                Contacta al administrador de tu negocio para que reactive tu cuenta.
              </p>
            </div>
            <a
              href="/login"
              className="inline-block text-xs text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors"
            >
              Volver al inicio de sesión
            </a>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
