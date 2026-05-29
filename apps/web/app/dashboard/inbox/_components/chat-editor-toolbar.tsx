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
import type React from 'react'
import { wrapSelection, prefixLine, prefixLineNumbered } from '../_lib/editor'

interface Props {
  textareaRef: React.RefObject<HTMLTextAreaElement | null>
  setReplyText: (v: string) => void
}

export function ChatEditorToolbar({ textareaRef, setReplyText }: Props) {
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
      </div>
      <p className="text-[10px] text-muted-foreground px-1 leading-tight">
        Formato WhatsApp: <code className="font-mono">*negrita*</code> · <code className="font-mono">_cursiva_</code> · <code className="font-mono">~tachado~</code> · <code className="font-mono">`código`</code> · <code className="font-mono">{'```mono```'}</code> · <code className="font-mono">{'> cita'}</code> · <code className="font-mono">* lista</code> · <code className="font-mono">1. numerada</code>
      </p>
    </>
  )
}
