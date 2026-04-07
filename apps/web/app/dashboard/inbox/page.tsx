import { createClient } from '@/utils/supabase/server'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'

export default async function InboxPage() {
  const supabase = createClient()
  const { data: { user } } = await supabase.auth.getUser()

  // 1. Resolver Tenant
  const { data: tenantUsers } = await supabase
    .from('tenant_users')
    .select('tenant_id')
    .eq('user_id', user?.id)
  
  const tenantId = tenantUsers?.[0]?.tenant_id

  // 2. Traer threads del Inbox
  let conversations = []
  if (tenantId) {
    const { data } = await supabase
      .from('conversations')
      .select(`
        id, 
        customer_phone, 
        status, 
        created_at,
        messages (
            id, direction, content, created_at
        )
      `)
      .eq('tenant_id', tenantId)
      .order('created_at', { ascending: false })
      
    conversations = data || []
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <div>
            <h1 className="text-3xl font-bold tracking-tight text-primary">Inbox Auditoría AI</h1>
            <p className="text-muted-foreground mt-1">Supervisa cómo tu Orquestador atiende por WhatsApp</p>
        </div>
      </div>
      
      <div className="space-y-4">
        {conversations.length === 0 ? (
          <div className="p-8 border rounded-lg border-dashed text-center mt-6">
            <p className="text-muted-foreground">Tu Central Asterisk Meta está vacía.</p>
            <p className="text-sm">En cuanto los clientes envíen Webhooks aparecerán aquí.</p>
          </div>
        ) : (
          conversations.map((conv) => {
            // Ordenar mensajes cronológicamente
            const msgs = conv.messages?.sort((a: any, b: any) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()) || []
            
            return (
              <Card key={conv.id} className="w-full">
                <CardHeader className="bg-muted/50 pb-4">
                  <div className="flex justify-between items-center">
                    <CardTitle className="text-lg flex items-center gap-2">
                        📱 Cliente: +{conv.customer_phone}
                    </CardTitle>
                    <span className={`px-3 py-1 rounded-full text-xs font-bold ${conv.status === 'bot_active' ? 'bg-primary/20 text-primary' : 'bg-destructive/20 text-destructive'}`}>
                        {conv.status.toUpperCase()}
                    </span>
                  </div>
                </CardHeader>
                <CardContent className="pt-6 space-y-4 max-h-[400px] overflow-y-auto">
                    {msgs.map((msg: any) => (
                        <div key={msg.id} className={`flex w-full ${msg.direction === 'inbound' ? 'justify-start' : 'justify-end'}`}>
                            <div className={`max-w-[70%] p-3 rounded-lg ${msg.direction === 'inbound' ? 'bg-secondary text-secondary-foreground rounded-tl-none' : 'bg-primary text-primary-foreground rounded-tr-none'}`}>
                                <p className="text-sm">{msg.content}</p>
                                <p className="text-[10px] opacity-50 mt-1 text-right">
                                    {new Date(msg.created_at).toLocaleTimeString()}
                                </p>
                            </div>
                        </div>
                    ))}
                    {msgs.length === 0 && (
                        <p className="text-center text-sm text-muted-foreground italic">Hilo creado pero sin mensajes crudos adjuntos.</p>
                    )}
                </CardContent>
              </Card>
            )
          })
        )}
      </div>
    </div>
  )
}
