'use client'

import { useState } from 'react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { SubmitButton } from '@/components/ui/submit-button'
import { Input } from '@/components/ui/input'
import { Plus, User, Mail, Phone, CalendarClock } from 'lucide-react'
import { addSupplier } from '../actions'

type Props = {
  suppliers: any[]
  canWrite: boolean
}

export default function SuppliersManager({ suppliers, canWrite }: Props) {
  const [showAdd, setShowAdd] = useState(false)

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center bg-muted/20 p-3 rounded-lg border border-border/50">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            Directorio de Proveedores
          </h2>
          <p className="text-xs text-muted-foreground">{suppliers.length} registrados</p>
        </div>
        {canWrite && !showAdd && (
          <Button onClick={() => setShowAdd(true)} size="sm" className="h-8 text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" /> Agregar proveedor
          </Button>
        )}
      </div>

      {showAdd && (
        <Card className="border-primary/30">
          <CardHeader className="pb-3 border-b">
            <CardTitle className="text-sm">Nuevo Proveedor</CardTitle>
          </CardHeader>
          <CardContent className="pt-4">
            <form action={async (fd) => { await addSupplier(fd); setShowAdd(false) }} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Nombre de la Empresa *</label>
                  <Input name="name" placeholder="Ej: Importadora Gato" required className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Email de Contacto</label>
                  <Input name="contact_email" type="email" placeholder="ventas@empresa.com" className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Teléfono</label>
                  <Input name="phone" placeholder="+57 300 0000000" className="h-8 text-sm" />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-muted-foreground uppercase">Lead Time (Días de Envío)</label>
                  <Input name="lead_time_days" type="number" min="0" placeholder="Ej: 5" className="h-8 text-sm" />
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2 border-t">
                <Button type="button" variant="ghost" size="sm" onClick={() => setShowAdd(false)} className="text-xs">
                  Cancelar
                </Button>
                <SubmitButton size="sm" pendingText="Guardando..." savedText="Guardado" className="text-xs">
                  Guardar Proveedor
                </SubmitButton>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {suppliers.map(s => (
          <Card key={s.id} className="hover:border-primary/40 transition-colors">
            <CardContent className="p-4 flex flex-col h-full">
              <div className="mb-3">
                <h3 className="font-semibold text-base truncate flex items-center gap-2">
                  <User className="h-4 w-4 text-primary" /> {s.name}
                </h3>
              </div>
              <div className="space-y-2 mt-auto text-sm text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Mail className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{s.contact_email || 'Sin email'}</span>
                </div>
                <div className="flex items-center gap-2">
                  <Phone className="h-3.5 w-3.5 shrink-0" />
                  <span>{s.phone || 'Sin teléfono'}</span>
                </div>
                <div className="flex items-center gap-2 pt-2 border-t border-border mt-2">
                  <CalendarClock className="h-3.5 w-3.5 shrink-0" />
                  <span className="text-xs font-medium">Lead Time: {s.lead_time_days} días</span>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
        {suppliers.length === 0 && !showAdd && (
          <div className="col-span-full border border-dashed rounded-xl p-8 text-center text-muted-foreground">
            Aún no tienes proveedores registrados.
          </div>
        )}
      </div>
    </div>
  )
}
