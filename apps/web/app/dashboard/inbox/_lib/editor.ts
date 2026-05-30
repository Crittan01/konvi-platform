/**
 * Utilidades del editor de texto WhatsApp del chat.
 *
 * Refactor 2026-05-29 — extraído del monolito `page.tsx`.
 *
 * Estas son utilidades del textarea de respuesta (toolbar B/I/S/code/quote/
 * lists). Dependen de un ref a HTMLTextAreaElement y de un setText callback.
 * Puro en lógica (sin React state directo), testable con jsdom.
 *
 * Marcadores WhatsApp aplicados:
 *   `*texto*` negrita, `_texto_` cursiva, `~texto~` strikethrough,
 *   `` `código` ``, ```` ```bloque código``` ```` (multi-línea),
 *   `> cita` (al inicio de línea), `• item` y `1. item` (listas).
 */
import type React from 'react'

// `wrapSelection` envuelve la selección actual con el marker (ej. *).
// Si no hay selección, inserta `marker marker` y deja el cursor entre.
export function wrapSelection(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  setText: (v: string) => void,
  marker: string,
): void {
  const ta = ref.current
  if (!ta) return
  const start = ta.selectionStart ?? 0
  const end = ta.selectionEnd ?? start
  const before = ta.value.slice(0, start)
  const sel = ta.value.slice(start, end)
  const after = ta.value.slice(end)
  const wrapped = `${marker}${sel || 'texto'}${marker}`
  const newVal = `${before}${wrapped}${after}`
  setText(newVal)
  // Re-focus + select el texto envuelto para edición fluida.
  setTimeout(() => {
    ta.focus()
    const newStart = before.length + marker.length
    const newEnd = newStart + (sel.length || 'texto'.length)
    ta.setSelectionRange(newStart, newEnd)
  }, 0)
}

// `prefixLine` agrega el prefix al inicio de cada línea seleccionada
// (o de la línea donde está el cursor si no hay selección).
export function prefixLine(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  setText: (v: string) => void,
  prefix: string,
): void {
  const ta = ref.current
  if (!ta) return
  const start = ta.selectionStart ?? 0
  const end = ta.selectionEnd ?? start
  const value = ta.value
  // Localizar inicio y fin de las líneas tocadas
  const lineStart = value.lastIndexOf('\n', start - 1) + 1
  const lineEndRaw = value.indexOf('\n', end)
  const lineEnd = lineEndRaw === -1 ? value.length : lineEndRaw
  const block = value.slice(lineStart, lineEnd)
  const prefixed = block.split('\n').map(l => `${prefix}${l}`).join('\n')
  const newVal = `${value.slice(0, lineStart)}${prefixed}${value.slice(lineEnd)}`
  setText(newVal)
  setTimeout(() => {
    ta.focus()
    ta.setSelectionRange(lineStart + prefix.length, lineStart + prefixed.length)
  }, 0)
}

/**
 * Inserta texto literal en la posición del cursor (o reemplaza la selección).
 * A diferencia de `wrapSelection` no envuelve — sólo inyecta.
 *
 * Usado por el emoji picker para insertar el emoji clickado en el cursor
 * sin sobreescribir lo que el operador ya escribió.
 */
export function insertAtCursor(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  setText: (v: string) => void,
  text: string,
): void {
  const ta = ref.current
  if (!ta) {
    // Textarea no montado — no hay cursor donde insertar. No-op silent
    // (el click del operador no produce efecto pero tampoco rompe).
    return
  }
  const start = ta.selectionStart ?? ta.value.length
  const end = ta.selectionEnd ?? start
  const before = ta.value.slice(0, start)
  const after = ta.value.slice(end)
  const newVal = `${before}${text}${after}`
  setText(newVal)
  // Mover cursor justo después del texto insertado.
  setTimeout(() => {
    ta.focus()
    const newPos = start + text.length
    ta.setSelectionRange(newPos, newPos)
  }, 0)
}

// Rev. 103 — Lista numerada: cada línea recibe un número auto-incrementado
// arrancando en 1. Si solo hay una línea, simple `1. `.
export function prefixLineNumbered(
  ref: React.RefObject<HTMLTextAreaElement | null>,
  setText: (v: string) => void,
): void {
  const ta = ref.current
  if (!ta) return
  const start = ta.selectionStart ?? 0
  const end = ta.selectionEnd ?? start
  const value = ta.value
  const lineStart = value.lastIndexOf('\n', start - 1) + 1
  const lineEndRaw = value.indexOf('\n', end)
  const lineEnd = lineEndRaw === -1 ? value.length : lineEndRaw
  const block = value.slice(lineStart, lineEnd)
  const numbered = block.split('\n')
    .map((l, i) => `${i + 1}. ${l}`)
    .join('\n')
  const newVal = `${value.slice(0, lineStart)}${numbered}${value.slice(lineEnd)}`
  setText(newVal)
  setTimeout(() => {
    ta.focus()
    ta.setSelectionRange(lineStart + 3, lineStart + numbered.length)
  }, 0)
}
