/**
 * Tab Opt-outs — WhatsApp.
 *
 * Lista los contactos que revocaron su consentimiento (STOP). Para ellos el
 * worker bloquea TODO outbound proactivo (templates HSM incluidos, gate
 * consent_revoked_at). Read-only: la revocación la dispara el propio cliente.
 */
import { UserX, ShieldCheck } from 'lucide-react'
import type { OptOutRow } from '../page'

type Props = {
  optOuts: OptOutRow[]
  connected: boolean
}

function formatDateTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return d.toLocaleString('es-CO', { timeZone: 'America/Bogota',
    year: 'numeric', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

// Enmascara el número para no exponer el teléfono completo en una tabla operativa.
function maskPhone(phone: string): string {
  if (!phone) return '—'
  if (phone.length <= 4) return phone
  return `${phone.slice(0, phone.length - 4).replace(/\d/g, '•')}${phone.slice(-4)}`
}

export default function WhatsAppOptOuts({ optOuts, connected }: Props) {
  if (!connected) {
    return (
      <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
        <UserX className="h-8 w-8 mx-auto text-muted-foreground/60" />
        <p className="text-sm text-muted-foreground mt-2">
          Conecta WhatsApp en la pestaña Setup para ver los contactos que optaron por no recibir mensajes.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-emerald-700/30 bg-emerald-700/5 p-4 flex items-start gap-3">
        <ShieldCheck className="h-5 w-5 text-emerald-800 mt-0.5 shrink-0" />
        <div className="text-sm text-emerald-900">
          Estos contactos escribieron <strong>STOP</strong> (o revocaron su consentimiento
          por Habeas Data). El bot bloquea todo mensaje proactivo hacia ellos, incluidas
          las plantillas HSM. La lista es de solo lectura: la revocación solo la puede
          reactivar el propio cliente.
        </div>
      </div>

      {optOuts.length === 0 ? (
        <div className="rounded-xl border border-dashed border-muted-foreground/30 p-10 text-center">
          <UserX className="h-8 w-8 mx-auto text-muted-foreground/60" />
          <p className="text-sm text-muted-foreground mt-2">
            Ningún contacto ha optado por no recibir mensajes.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-border overflow-hidden">
          <div className="px-4 py-2.5 border-b border-border bg-muted/30 text-sm font-medium text-foreground">
            {optOuts.length} {optOuts.length === 1 ? 'contacto' : 'contactos'} con opt-out
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="px-4 py-2 font-medium">Contacto</th>
                  <th className="px-4 py-2 font-medium">Teléfono</th>
                  <th className="px-4 py-2 font-medium">Revocado</th>
                </tr>
              </thead>
              <tbody>
                {optOuts.map((c) => (
                  <tr key={c.id} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-2.5 text-foreground">{c.name || '(sin nombre)'}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
                      {maskPhone(c.phone)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-muted-foreground">
                      {formatDateTime(c.consent_revoked_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
