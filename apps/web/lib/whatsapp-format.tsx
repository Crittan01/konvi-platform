/**
 * Rev. 103 — Renderizado de formato WhatsApp en React.
 *
 * WhatsApp soporta:
 *   • *texto*  → bold
 *   • _texto_  → italic
 *   • ~texto~  → strikethrough
 *   • ```texto``` → monospace (un bloque o inline)
 *   • > texto  → blockquote (línea entera)
 *   • URLs → autolink
 *   • \n\n → párrafos
 *
 * Diseño:
 *   • Sin `dangerouslySetInnerHTML` — escape automático por React.
 *   • Procesa por líneas para detectar blockquote.
 *   • Dentro de cada línea, parsing recursivo de inline markers.
 *   • Reusable en chat messages + previews.
 */
import React from 'react'

// Reglas de formato inline (orden importa: monospace primero para no
// romper su contenido con otros markers).
type InlineRule = {
  pattern: RegExp                // captura: 1 = contenido
  render: (content: string, key: string) => React.ReactNode
}

const URL_RE = /\b(https?:\/\/[^\s<>"]+|www\.[^\s<>"]+)\b/g

const INLINE_RULES: InlineRule[] = [
  // Monospace ```...``` o ``...`` — primero porque su contenido es literal
  {
    pattern: /```([^`\n]{1,500})```/g,
    render: (c, k) => (
      <code
        key={k}
        className="px-1 py-0.5 rounded bg-border/40 text-[0.95em] font-mono"
      >
        {c}
      </code>
    ),
  },
  // Bold *texto*
  {
    pattern: /(?<!\w)\*([^*\n]{1,500}?)\*(?!\w)/g,
    render: (c, k) => (
      <strong key={k} className="font-semibold">
        {parseInlineRecursive(c, INLINE_RULES.slice(2), `${k}.b`)}
      </strong>
    ),
  },
  // Italic _texto_
  {
    pattern: /(?<!\w)_([^_\n]{1,500}?)_(?!\w)/g,
    render: (c, k) => (
      <em key={k} className="italic">
        {parseInlineRecursive(c, INLINE_RULES.slice(3), `${k}.i`)}
      </em>
    ),
  },
  // Strikethrough ~texto~
  {
    pattern: /(?<!\w)~([^~\n]{1,500}?)~(?!\w)/g,
    render: (c, k) => (
      <s key={k} className="line-through opacity-75">
        {parseInlineRecursive(c, [], `${k}.s`)}
      </s>
    ),
  },
]

/** Parsing recursivo de inline markers. `rules` permite saltar reglas
 *  ya aplicadas (evita re-bolding bold). */
function parseInlineRecursive(
  text: string,
  rules: InlineRule[],
  keyPrefix: string,
): React.ReactNode[] {
  if (!text) return []
  if (rules.length === 0) {
    // Sin más reglas → autolink + plain text
    return autoLinkText(text, keyPrefix)
  }

  const [first, ...rest] = rules
  const out: React.ReactNode[] = []
  let lastIdx = 0
  let m: RegExpExecArray | null
  // Reset regex state (lastIndex) — global flags conservan estado entre calls
  first.pattern.lastIndex = 0
  let count = 0
  while ((m = first.pattern.exec(text)) !== null) {
    if (m.index > lastIdx) {
      // Texto antes del match: parsear con las reglas RESTANTES
      out.push(
        ...parseInlineRecursive(
          text.slice(lastIdx, m.index),
          rest,
          `${keyPrefix}.${count}.pre`,
        ),
      )
    }
    out.push(first.render(m[1] ?? '', `${keyPrefix}.${count}.m`))
    lastIdx = m.index + m[0].length
    count += 1
    if (count > 200) break // safety
  }
  if (lastIdx < text.length) {
    out.push(
      ...parseInlineRecursive(text.slice(lastIdx), rest, `${keyPrefix}.tail`),
    )
  }
  return out
}

/** Autolink + escape de plain text. */
function autoLinkText(text: string, keyPrefix: string): React.ReactNode[] {
  if (!text) return []
  const out: React.ReactNode[] = []
  let lastIdx = 0
  let m: RegExpExecArray | null
  URL_RE.lastIndex = 0
  let count = 0
  while ((m = URL_RE.exec(text)) !== null) {
    if (m.index > lastIdx) {
      out.push(text.slice(lastIdx, m.index))
    }
    const url = m[0]
    const href = url.startsWith('http') ? url : `https://${url}`
    out.push(
      <a
        key={`${keyPrefix}.url.${count}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-primary underline decoration-primary/40 hover:decoration-primary break-all"
      >
        {url}
      </a>,
    )
    lastIdx = m.index + url.length
    count += 1
    if (count > 50) break
  }
  if (lastIdx < text.length) {
    out.push(text.slice(lastIdx))
  }
  return out
}

/**
 * Renderiza un texto WhatsApp-formatted como JSX seguro.
 * Maneja blockquotes (líneas que empiezan con `> `) y formato inline.
 */
export function renderWhatsAppFormat(text: string): React.ReactNode {
  if (!text) return null

  const lines = text.split('\n')
  const blocks: React.ReactNode[] = []

  // Agrupar líneas consecutivas de blockquote en un solo bloque.
  let i = 0
  let blockKey = 0
  while (i < lines.length) {
    const line = lines[i] ?? ''
    if (line.startsWith('> ')) {
      // Recolectar todas las líneas blockquote consecutivas
      const quoteLines: string[] = []
      while (i < lines.length && (lines[i] ?? '').startsWith('> ')) {
        quoteLines.push((lines[i] ?? '').slice(2))
        i += 1
      }
      blocks.push(
        <blockquote
          key={`bq.${blockKey++}`}
          className="border-l-2 border-border pl-2 my-1 text-muted-foreground italic"
        >
          {quoteLines.map((ql, qi) => (
            <div key={`bq.${blockKey}.${qi}`}>
              {parseInlineRecursive(ql, INLINE_RULES, `bq.${blockKey}.${qi}`)}
            </div>
          ))}
        </blockquote>,
      )
    } else {
      blocks.push(
        <span key={`ln.${blockKey++}`}>
          {parseInlineRecursive(line, INLINE_RULES, `ln.${blockKey}`)}
          {i < lines.length - 1 && <br />}
        </span>,
      )
      i += 1
    }
  }

  return <>{blocks}</>
}

/**
 * Versión "plain" para previews truncados (sin JSX, solo texto plano
 * con los markers removidos). Útil en lista de conversaciones donde
 * solo mostramos los primeros N chars.
 */
export function stripWhatsAppFormat(text: string): string {
  if (!text) return ''
  return text
    .replace(/```([^`\n]+)```/g, '$1')
    .replace(/(?<!\w)\*([^*\n]+)\*(?!\w)/g, '$1')
    .replace(/(?<!\w)_([^_\n]+)_(?!\w)/g, '$1')
    .replace(/(?<!\w)~([^~\n]+)~(?!\w)/g, '$1')
    .replace(/^>\s+/gm, '')
}
