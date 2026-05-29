'use client'

/**
 * Toolbar de formato WhatsApp para el editor del chat.
 *
 * Refactor 2026-05-29 paso 3/10 — extraído de inbox-manager.tsx.
 *
 * Cubre TODAS las opciones de la doc oficial de Meta:
 *   Inline: *negrita* _cursiva_ ~tachado~ `código` ```mono```
 *   Bloque: > cita · viñetas · numerada
 *
 * Atajos: Ctrl+B negrita · Ctrl+I cursiva · Ctrl+E código
 * (los atajos los maneja el textarea padre via keydown — esta toolbar
 * solo provee los botones clickables).
 *
 * Interfaz mínima: 2 props (textareaRef + setReplyText). Las utilidades
 * editor.ts (wrapSelection/prefixLine/prefixLineNumbered) son puras y
 * testables sin DOM con jsdom.
 */
import { useEffect, useRef, useState } from 'react'
import type React from 'react'
import { Smile } from 'lucide-react'
import {
  insertAtCursor,
  prefixLine,
  prefixLineNumbered,
  wrapSelection,
} from '../_lib/editor'
import { EMOJI_GROUPS } from '../_lib/emojis'

interface Props {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  setReplyText: (v: string) => void
}

export function ChatEditorToolbar({ textareaRef, setReplyText }: Props) {
  // Rev. 109 founder 2026-05-29 — emoji picker integrado.
  // State local del botón: abierto/cerrado. Click-outside cierra.
  const [emojiOpen, setEmojiOpen] = useState(false)
  const pickerWrapperRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!emojiOpen) return
    const handler = (e: MouseEvent) => {
      if (!pickerWrapperRef.current?.contains(e.target as Node)) {
        setEmojiOpen(false)
      }
    }
    // Defer para que el click que ABRE el picker no lo cierre inmediato.
    const t = setTimeout(() => document.addEventListener('mousedown', handler), 0)
    return () => {
      clearTimeout(t)
      document.removeEventListener('mousedown', handler)
    }
  }, [emojiOpen])

  const onEmojiClick = (emoji: string) => {
    insertAtCursor(textareaRef, setReplyText, emoji)
    // Mantenemos el picker abierto para inserción rápida de varios emojis.
    // Si el operador quiere cerrar, click fuera o tecla Esc.
  }

  return (
    <>
      <div className="flex items-center gap-0.5 px-1 flex-wrap">
        {/* — Inline format — */}
        <button
          type="button"
          onClick={() => wrapSelection(textareaRef, setReplyText, '*')}
          title="Negrita — *texto*  (Ctrl+B)"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm font-bold"
        >B</button>
        <button
          type="button"
          onClick={() => wrapSelection(textareaRef, setReplyText, '_')}
          title="Cursiva — _texto_  (Ctrl+I)"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm italic"
        >I</button>
        <button
          type="button"
          onClick={() => wrapSelection(textareaRef, setReplyText, '~')}
          title="Tachado — ~texto~"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm line-through"
        >S</button>
        <button
          type="button"
          onClick={() => wrapSelection(textareaRef, setReplyText, '`')}
          title="Código alineado — `texto`  (Ctrl+E)"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-xs font-mono"
        >{'<>'}</button>
        <button
          type="button"
          onClick={() => wrapSelection(textareaRef, setReplyText, '```')}
          title="Bloque monoespaciado — ```texto```"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-xs font-mono"
        >{'</>'}</button>

        {/* Separador visual */}
        <span className="h-5 w-px bg-border mx-1" aria-hidden="true" />

        {/* — Block format — */}
        <button
          type="button"
          onClick={() => prefixLine(textareaRef, setReplyText, '> ')}
          title="Cita — > texto"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-sm"
        >&ldquo;&rdquo;</button>
        <button
          type="button"
          onClick={() => prefixLine(textareaRef, setReplyText, '* ')}
          title="Lista con viñetas — * texto"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-base"
        >•</button>
        <button
          type="button"
          onClick={() => prefixLineNumbered(textareaRef, setReplyText)}
          title="Lista numerada — 1. texto"
          className="h-7 min-w-[28px] px-1.5 rounded hover:bg-accent text-foreground inline-flex items-center justify-center text-xs font-medium"
        >1.</button>

        {/* Separador visual */}
        <span className="h-5 w-px bg-border mx-1" aria-hidden="true" />

        {/* — Emoji picker — */}
        <div ref={pickerWrapperRef} className="relative">
          <button
            type="button"
            onClick={() => setEmojiOpen(o => !o)}
            title="Emojis — abre selector"
            aria-expanded={emojiOpen}
            className={`h-7 min-w-[28px] px-1.5 rounded inline-flex items-center justify-center text-foreground ${
              emojiOpen ? 'bg-accent' : 'hover:bg-accent'
            }`}
          >
            <Smile className="h-4 w-4" />
          </button>
          {emojiOpen && (
            <div
              role="dialog"
              aria-label="Selector de emojis"
              className="absolute left-0 bottom-9 z-50 w-[260px] max-h-[280px] overflow-y-auto rounded-lg border border-border bg-card shadow-lg p-2 space-y-2"
            >
              {EMOJI_GROUPS.map(group => (
                <div key={group.label}>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1 px-0.5">
                    {group.label}
                  </p>
                  <div className="grid grid-cols-8 gap-0.5">
                    {group.emojis.map(emoji => (
                      <button
                        key={emoji}
                        type="button"
                        onClick={() => onEmojiClick(emoji)}
                        title={emoji}
                        className="h-7 w-7 inline-flex items-center justify-center rounded hover:bg-accent text-lg leading-none"
                      >
                        {emoji}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <p className="text-[10px] text-muted-foreground italic px-0.5 pt-1 border-t border-border">
                Tip: también podés usar el selector del sistema (Ctrl+Cmd+Espacio en Mac · Win+. en Windows) para cualquier otro emoji.
              </p>
            </div>
          )}
        </div>
      </div>
      <p className="text-[10px] text-muted-foreground px-1 leading-tight">
        Formato WhatsApp: <code className="font-mono">*negrita*</code> · <code className="font-mono">_cursiva_</code> · <code className="font-mono">~tachado~</code> · <code className="font-mono">`código`</code> · <code className="font-mono">{'```mono```'}</code> · <code className="font-mono">{'> cita'}</code> · <code className="font-mono">* lista</code> · <code className="font-mono">1. numerada</code>
      </p>
    </>
  )
}
