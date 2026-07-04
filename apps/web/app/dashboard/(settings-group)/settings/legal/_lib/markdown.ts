/**
 * Renderizador Markdown mínimo, seguro y sin dependencias.
 *
 * Motivación (F6): los documentos legales (DPA, Privacidad, Subprocesadores) se
 * servían como .md CRUDO desde /public — el tenant que debe aceptar un click-wrap
 * leía texto plano con sintaxis Markdown. Añadir react-markdown tocaría
 * package.json + pnpm-lock.yaml (CI --frozen-lockfile), así que se implementa aquí
 * un subconjunto acotado EXACTAMENTE a lo que usan esos 3 documentos:
 * encabezados, citas (>), regla horizontal, listas (ord/no-ord), tablas GFM,
 * negrita, código inline y párrafos.
 *
 * SEGURIDAD: todo el texto se escapa ANTES de aplicar formato inline. El HTML
 * resultante se inyecta con dangerouslySetInnerHTML, por eso no se permite HTML
 * embebido del documento (se escapa). Los enlaces solo aceptan http(s)/relativos.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** Formato inline sobre texto YA escapado. */
function inline(escaped: string): string {
  let out = escaped
  // Código inline `code`
  out = out.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>')
  // Negrita **texto**
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  // Enlaces [texto](url) — solo http(s) o rutas relativas
  out = out.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, text: string, url: string) => {
    const safe = /^(https?:\/\/|\/)/.test(url) ? url : '#'
    const rel = safe.startsWith('http') ? ' target="_blank" rel="noreferrer noopener"' : ''
    return `<a class="md-link" href="${safe}"${rel}>${text}</a>`
  })
  return out
}

function isTableSeparator(line: string): boolean {
  // | --- | :---: | ---: |  (con o sin pipes de borde)
  return /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/.test(line)
}

function splitRow(line: string): string[] {
  let l = line.trim()
  if (l.startsWith('|')) l = l.slice(1)
  if (l.endsWith('|')) l = l.slice(0, -1)
  return l.split('|').map(c => c.trim())
}

export function renderMarkdown(md: string): string {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let i = 0
  let para: string[] = []

  const flushPara = () => {
    if (para.length === 0) return
    html.push(`<p>${inline(escapeHtml(para.join(' ')))}</p>`)
    para = []
  }

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Línea en blanco → cierra párrafo
    if (trimmed === '') { flushPara(); i++; continue }

    // Regla horizontal
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushPara(); html.push('<hr class="md-hr" />'); i++; continue
    }

    // Encabezado
    const h = /^(#{1,6})\s+(.*)$/.exec(trimmed)
    if (h) {
      flushPara()
      const level = h[1].length
      html.push(`<h${level} class="md-h${level}">${inline(escapeHtml(h[2].trim()))}</h${level}>`)
      i++; continue
    }

    // Cita (bloque consecutivo de >)
    if (/^>\s?/.test(trimmed)) {
      flushPara()
      const quote: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
        quote.push(lines[i].trim().replace(/^>\s?/, ''))
        i++
      }
      html.push(`<blockquote class="md-quote">${inline(escapeHtml(quote.join(' ')))}</blockquote>`)
      continue
    }

    // Tabla GFM: fila con | seguida de separador
    if (trimmed.includes('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flushPara()
      const header = splitRow(lines[i])
      i += 2 // saltar cabecera + separador
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().includes('|') && lines[i].trim() !== '') {
        rows.push(splitRow(lines[i]))
        i++
      }
      const thead = `<thead><tr>${header.map(c => `<th>${inline(escapeHtml(c))}</th>`).join('')}</tr></thead>`
      const tbody = `<tbody>${rows
        .map(r => `<tr>${r.map(c => `<td>${inline(escapeHtml(c))}</td>`).join('')}</tr>`)
        .join('')}</tbody>`
      html.push(`<div class="md-table-wrap"><table class="md-table">${thead}${tbody}</table></div>`)
      continue
    }

    // Lista no ordenada
    if (/^[-*]\s+/.test(trimmed)) {
      flushPara()
      const items: string[] = []
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ''))
        i++
      }
      html.push(`<ul class="md-ul">${items.map(it => `<li>${inline(escapeHtml(it))}</li>`).join('')}</ul>`)
      continue
    }

    // Lista ordenada
    if (/^\d+\.\s+/.test(trimmed)) {
      flushPara()
      const items: string[] = []
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''))
        i++
      }
      html.push(`<ol class="md-ol">${items.map(it => `<li>${inline(escapeHtml(it))}</li>`).join('')}</ol>`)
      continue
    }

    // Texto de párrafo
    para.push(trimmed)
    i++
  }
  flushPara()
  return html.join('\n')
}

/** Whitelist slug → archivo. Previene path traversal en la ruta del viewer. */
export const LEGAL_DOCS: Record<string, { file: string; title: string }> = {
  dpa: { file: 'dpa.md', title: 'Acuerdo de Tratamiento de Datos (DPA)' },
  'privacy-policy': { file: 'privacy-policy.md', title: 'Política de Privacidad (template)' },
  subprocessors: { file: 'subprocessors.md', title: 'Lista de Subprocesadores' },
}
