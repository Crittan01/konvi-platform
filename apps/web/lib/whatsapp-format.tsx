/**
 * Rev. 103 — Renderizado completo de formato WhatsApp en React.
 *
 * Soporta TODAS las opciones oficiales de WhatsApp
 * (https://faq.whatsapp.com/539178204879377):
 *
 *   Inline (dentro de una línea):
 *     • *texto*       → bold
 *     • _texto_       → italic
 *     • ~texto~       → strikethrough
 *     • `texto`       → código alineado (inline)
 *     • ```texto```   → monospace (bloque)
 *
 *   Block (línea entera):
 *     • > texto       → blockquote
 *     • * texto       → lista con viñetas
 *     • - texto       → lista con viñetas
 *     • 1. texto      → lista numerada
 *
 *   Adicional:
 *     • URLs → autolink
 *     • \n\n → párrafos
 *
 * Diseño:
 *   • Sin `dangerouslySetInnerHTML` — escape automático por React.
 *   • Procesa por líneas para detectar blockquote/listas.
 *   • Dentro de cada línea, parsing recursivo de inline markers.
 *   • Reusable en chat messages + previews + editor preview.
 */
import React from 'react'

// ── Inline rules ──────────────────────────────────────────────────────────
type InlineRule = {
  pattern: RegExp                // captura: 1 = contenido
  render: (content: string, key: string) => React.ReactNode
}

const URL_RE = /\b(https?:\/\/[^\s<>"]+|www\.[^\s<>"]+)\b/g

// Orden importa: monospace (triple y single) primero porque su contenido
// es literal y NO debe parsearse para otros markers.
//
// Rev. 103 — colores adaptan al contexto del bubble:
//   • `bg-foreground/10` y `text-current` → mono code legible en cualquier
//     bubble (gris inbound + verde outbound).
//   • `decoration-current` para URLs → preserva color del texto del bubble.
//   • `border-current/30 + opacity-80` para blockquote → respeta tono
//     del bubble pero diferenciado.
const INLINE_RULES: InlineRule[] = [
  // 1. Monospace BLOQUE ```...``` (triple backtick)
  {
    pattern: /```([^`\n]{1,500})```/g,
    render: (c, k) => (
      <code
        key={k}
        className="px-1.5 py-0.5 rounded bg-foreground/10 text-[0.92em] font-mono"
      >
        {c}
      </code>
    ),
  },
  // 2. Código INLINE `...` (single backtick — distinto del bloque mono)
  {
    pattern: /(?<!`)`([^`\n]{1,500}?)`(?!`)/g,
    render: (c, k) => (
      <code
        key={k}
        className="px-1 py-0.5 rounded bg-foreground/10 text-[0.92em] font-mono"
      >
        {c}
      </code>
    ),
  },
  // 3. Bold *...*
  {
    pattern: /(?<!\w)\*([^*\n]{1,500}?)\*(?!\w)/g,
    render: (c, k) => (
      <strong key={k} className="font-semibold">
        {parseInlineRecursive(c, INLINE_RULES.slice(3), `${k}.b`)}
      </strong>
    ),
  },
  // 4. Italic _..._
  {
    pattern: /(?<!\w)_([^_\n]{1,500}?)_(?!\w)/g,
    render: (c, k) => (
      <em key={k} className="italic">
        {parseInlineRecursive(c, INLINE_RULES.slice(4), `${k}.i`)}
      </em>
    ),
  },
  // 5. Strikethrough ~...~
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
 *  ya aplicadas (evita re-bolding de bold). */
function parseInlineRecursive(
  text: string,
  rules: InlineRule[],
  keyPrefix: string,
): React.ReactNode[] {
  if (!text) return []
  if (rules.length === 0) {
    return autoLinkText(text, keyPrefix)
  }

  const [first, ...rest] = rules
  const out: React.ReactNode[] = []
  let lastIdx = 0
  let m: RegExpExecArray | null
  first.pattern.lastIndex = 0
  let count = 0
  while ((m = first.pattern.exec(text)) !== null) {
    if (m.index > lastIdx) {
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
    if (count > 200) break
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
        // Rev. 103 — text-current + decoration-current respeta el color
        // del bubble (gris inbound, verde outbound). Antes con
        // `text-primary` el link era invisible sobre bubble verde.
        className="underline decoration-current/60 hover:decoration-current font-medium break-all"
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

// ── Block-level patterns (línea entera) ───────────────────────────────────

const BULLET_RE = /^[*-]\s+(.*)$/         // "* texto" o "- texto"
const NUMBERED_RE = /^(\d+)\.\s+(.*)$/    // "1. texto"
const QUOTE_RE = /^>\s+(.*)$/             // "> texto"

/**
 * Renderiza un texto WhatsApp-formatted como JSX seguro.
 * Maneja blockquotes + listas (viñetas y numeradas) + formato inline.
 */
export function renderWhatsAppFormat(text: string): React.ReactNode {
  if (!text) return null

  const lines = text.split('\n')
  const blocks: React.ReactNode[] = []
  let i = 0
  let blockKey = 0

  while (i < lines.length) {
    const line = lines[i] ?? ''

    // 1. Blockquote (líneas consecutivas con `> `)
    if (QUOTE_RE.test(line)) {
      const quoteLines: string[] = []
      while (i < lines.length && QUOTE_RE.test(lines[i] ?? '')) {
        const m = (lines[i] ?? '').match(QUOTE_RE)
        quoteLines.push(m ? m[1] : '')
        i += 1
      }
      blocks.push(
        <blockquote
          key={`bq.${blockKey++}`}
          // Rev. 103 — border-current/40 hereda color del bubble + opacity-90
          // mejor contraste que muted-foreground en bubble verde. pl-3 da
          // separación clara borde-texto sin alejarse demasiado.
          className="border-l-[3px] border-current/40 pl-3 my-1.5 italic opacity-90"
        >
          {quoteLines.map((ql, qi) => (
            <div key={`bq.${blockKey}.${qi}`}>
              {parseInlineRecursive(ql, INLINE_RULES, `bq.${blockKey}.${qi}`)}
            </div>
          ))}
        </blockquote>,
      )
      continue
    }

    // 2. Lista numerada (líneas consecutivas con "N. texto")
    if (NUMBERED_RE.test(line)) {
      const items: { num: number; text: string }[] = []
      while (i < lines.length && NUMBERED_RE.test(lines[i] ?? '')) {
        const m = (lines[i] ?? '').match(NUMBERED_RE)
        if (m) items.push({ num: parseInt(m[1], 10), text: m[2] })
        i += 1
      }
      const startNum = items[0]?.num ?? 1
      blocks.push(
        <ol
          key={`ol.${blockKey++}`}
          // Rev. 103 — pl-7 da espacio para que el número quepa cómodamente
          // (antes pl-5 cortaba). marker:opacity-80 atenúa los números para
          // que no compitan visualmente con el texto.
          className="list-decimal pl-7 my-1.5 space-y-0.5 marker:opacity-80"
          start={startNum}
        >
          {items.map((it, ii) => (
            <li key={`ol.${blockKey}.${ii}`} className="pl-1">
              {parseInlineRecursive(it.text, INLINE_RULES, `ol.${blockKey}.${ii}`)}
            </li>
          ))}
        </ol>,
      )
      continue
    }

    // 3. Lista con viñetas (líneas consecutivas con "* " o "- ")
    if (BULLET_RE.test(line)) {
      const items: string[] = []
      while (i < lines.length && BULLET_RE.test(lines[i] ?? '')) {
        const m = (lines[i] ?? '').match(BULLET_RE)
        items.push(m ? m[1] : '')
        i += 1
      }
      blocks.push(
        <ul
          key={`ul.${blockKey++}`}
          // Rev. 103 — pl-6 da espacio cómodo para la viñeta separada del
          // borde del bubble. marker:opacity-80 baja intensidad de los dots.
          className="list-disc pl-6 my-1.5 space-y-0.5 marker:opacity-80"
        >
          {items.map((it, ii) => (
            <li key={`ul.${blockKey}.${ii}`} className="pl-1">
              {parseInlineRecursive(it, INLINE_RULES, `ul.${blockKey}.${ii}`)}
            </li>
          ))}
        </ul>,
      )
      continue
    }

    // 4. Línea normal
    blocks.push(
      <span key={`ln.${blockKey++}`}>
        {parseInlineRecursive(line, INLINE_RULES, `ln.${blockKey}`)}
        {i < lines.length - 1 && <br />}
      </span>,
    )
    i += 1
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
    .replace(/(?<!`)`([^`\n]+?)`(?!`)/g, '$1')
    .replace(/(?<!\w)\*([^*\n]+)\*(?!\w)/g, '$1')
    .replace(/(?<!\w)_([^_\n]+)_(?!\w)/g, '$1')
    .replace(/(?<!\w)~([^~\n]+)~(?!\w)/g, '$1')
    .replace(/^>\s+/gm, '')
    .replace(/^[*-]\s+/gm, '• ')
    .replace(/^(\d+)\.\s+/gm, '$1. ')
}
