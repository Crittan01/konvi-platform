import { PauseCircle } from 'lucide-react'

export const metadata = {
  title: 'Cuenta suspendida — Konvi',
}

export default function CuentaSuspendidaPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-6">
      <div className="max-w-md w-full text-center space-y-5">
        <div className="flex justify-center">
          <div className="h-16 w-16 rounded-2xl bg-amber-500/15 border border-amber-700/30 flex items-center justify-center">
            <PauseCircle className="h-8 w-8 text-amber-700" />
          </div>
        </div>
        <div className="space-y-2">
          <h1 className="text-xl font-bold text-foreground">Cuenta suspendida</h1>
          <p className="text-sm text-muted-foreground leading-relaxed">
            Tu acceso a esta consola fue suspendido temporalmente por el administrador del negocio.
          </p>
          <p className="text-sm text-muted-foreground">
            Contacta al administrador para que reactive tu cuenta.
          </p>
        </div>
        <a
          href="/login"
          className="inline-block text-xs text-muted-foreground hover:text-foreground underline underline-offset-4 transition-colors"
        >
          Volver al inicio de sesión
        </a>
      </div>
    </div>
  )
}
