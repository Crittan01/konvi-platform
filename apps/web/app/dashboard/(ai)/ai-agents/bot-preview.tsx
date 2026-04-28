'use client'

import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Bot, Send, Loader2, MessageSquare, Zap, Info } from 'lucide-react'

interface PreviewResult {
  response:   string
  kb_used:    boolean
  kb_count:   number
  agent_name: string
}

const EXAMPLE_MESSAGES = [
  '¿Tienen envíos a Medellín?',
  '¿Cuál es la política de devoluciones?',
  '¿Cuánto demoran en despachar?',
  '¿Aceptan pagos contra entrega?',
]

export function BotPreview() {
  const [message,  setMessage]  = useState('')
  const [result,   setResult]   = useState<PreviewResult | null>(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  const handleTest = async (msg?: string) => {
    const text = (msg ?? message).trim()
    if (!text) return
    if (msg) setMessage(msg)
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const res  = await fetch('/api/ai/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.error ?? 'Error desconocido')
      setResult(data as PreviewResult)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al consultar el bot')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4 bg-card border border-border p-6 rounded-xl">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary shrink-0" />
          <div>
            <p className="font-semibold text-sm">Probar el bot</p>
            <p className="text-xs text-muted-foreground">
              Simula cómo respondería con tu configuración actual. Usa RAG real sobre tu KB.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground/60 shrink-0">
          <Info className="h-3 w-3" />
          <span>20 pruebas/hora · No envía mensajes reales</span>
        </div>
      </div>

      {/* Ejemplos rápidos */}
      <div className="flex flex-wrap gap-1.5">
        {EXAMPLE_MESSAGES.map(ex => (
          <button
            key={ex}
            onClick={() => handleTest(ex)}
            disabled={loading}
            className="text-xs px-2.5 py-1 rounded-full border border-border bg-muted/40 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-50"
          >
            {ex}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="space-y-2">
        <Textarea
          value={message}
          onChange={e => setMessage(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleTest() } }}
          placeholder="Escribe un mensaje como si fueras un cliente... (Enter para enviar)"
          className="min-h-[72px] text-sm resize-none"
          maxLength={500}
          disabled={loading}
        />
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-muted-foreground">{message.length}/500</span>
          <Button
            onClick={() => handleTest()}
            disabled={loading || !message.trim()}
            size="sm"
            className="gap-2"
          >
            {loading
              ? <><Loader2 className="h-3.5 w-3.5 animate-spin" />Consultando...</>
              : <><Send className="h-3.5 w-3.5" />Probar</>
            }
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/8 px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Respuesta */}
      {result && (
        <div className="space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <div className="flex items-center gap-1.5">
              <Bot className="h-3.5 w-3.5 text-primary" />
              <span className="text-xs font-medium text-muted-foreground">{result.agent_name}:</span>
            </div>
            {result.kb_used && (
              <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Zap className="h-2.5 w-2.5" />
                RAG activo · {result.kb_count} doc{result.kb_count !== 1 ? 's' : ''} usados
              </span>
            )}
            {!result.kb_used && (
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground border border-border">
                Sin KB — solo config del agente
              </span>
            )}
          </div>
          <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3">
            <p className="text-sm whitespace-pre-wrap leading-relaxed">{result.response}</p>
          </div>
          <p className="text-[10px] text-muted-foreground/60">
            Esta es una simulación. El bot real en WhatsApp también considera el historial de conversación y el estado del pedido.
          </p>
        </div>
      )}
    </div>
  )
}
