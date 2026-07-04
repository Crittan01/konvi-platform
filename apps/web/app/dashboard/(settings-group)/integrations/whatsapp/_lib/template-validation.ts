/**
 * Validación y preview de plantillas WhatsApp HSM — lógica pura, testeable.
 *
 * Extraída de la page server-action (antes inline, sin red de regresión) para
 * poder cubrirla con vitest y reutilizar el mismo parser en el preview del cliente.
 *
 * Sin dependencias de Next/Supabase: 100% funciones puras. NO importar 'server-only'
 * aquí — este módulo lo consume tanto la server action como el componente cliente.
 */

// ─── Enums canónicos (espejo del CHECK constraint en la migración) ──────────
// 20260522000000_whatsapp_templates.sql:68-70 declara 8 estados. FLAGGED y
// LIMIT_EXCEEDED los persiste el connector (template_events.py) cuando Meta
// pausa el template por baja calidad / exceso de envíos.
export type TemplateCategory = 'UTILITY' | 'MARKETING' | 'AUTHENTICATION'
export type ParameterFormat = 'POSITIONAL' | 'NAMED'
export type TemplateStatus =
  | 'LOCAL_DRAFT'
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'DISABLED'
  | 'PAUSED'
  | 'FLAGGED'
  | 'LIMIT_EXCEEDED'

export type TemplateComponent = {
  type: 'HEADER' | 'BODY' | 'FOOTER' | 'BUTTONS'
  text?: string
  format?: string
  buttons?: Array<Record<string, unknown>>
  example?: Record<string, unknown>
}

export const VALID_CATEGORIES = new Set<TemplateCategory>([
  'UTILITY',
  'MARKETING',
  'AUTHENTICATION',
])
export const VALID_PARAMETER_FORMATS = new Set<ParameterFormat>([
  'POSITIONAL',
  'NAMED',
])
// Solo LOCAL_DRAFT y REJECTED son editables (los estados Meta son inmutables).
export const EDITABLE_STATUSES = new Set<TemplateStatus>(['LOCAL_DRAFT', 'REJECTED'])

export const NAME_PATTERN = /^[a-z][a-z0-9_]{2,49}$/
export const LANGUAGE_PATTERN = /^[a-z]{2}(_[A-Z]{2})?$/

export function isValidName(name: string): boolean {
  return NAME_PATTERN.test(name)
}
export function isValidLanguage(language: string): boolean {
  return LANGUAGE_PATTERN.test(language)
}

export function validateComponents(components: TemplateComponent[]): string | null {
  if (!Array.isArray(components) || components.length === 0) {
    return 'components debe ser una lista no vacía.'
  }
  const validTypes = new Set(['HEADER', 'BODY', 'FOOTER', 'BUTTONS'])
  const seenTypes = new Set<string>()
  let bodyCount = 0
  for (let i = 0; i < components.length; i++) {
    const c = components[i]
    if (typeof c !== 'object' || c === null) {
      return `components[${i}] debe ser un objeto.`
    }
    const t = (c.type || '').toUpperCase()
    if (!validTypes.has(t)) {
      return `components[${i}].type "${t}" inválido. Válidos: HEADER, BODY, FOOTER, BUTTONS.`
    }
    if (t !== 'BUTTONS' && seenTypes.has(t)) {
      return `components[${i}]: type "${t}" duplicado. Solo BUTTONS puede repetirse.`
    }
    seenTypes.add(t)
    if (t === 'BODY') {
      bodyCount++
      if (!(c.text || '').trim()) {
        return `components[${i}] BODY requiere campo 'text' no vacío.`
      }
    }
  }
  if (bodyCount !== 1) {
    return 'components requiere exactamente 1 BODY.'
  }
  return null
}

export function parseComponentsJSON(
  raw: string,
):
  | { ok: true; value: TemplateComponent[] }
  | { ok: false; error: string } {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return { ok: false, error: 'components: JSON inválido. Revisa llaves y comillas.' }
  }
  if (!Array.isArray(parsed)) {
    return { ok: false, error: 'components: debe ser un array JSON.' }
  }
  const err = validateComponents(parsed as TemplateComponent[])
  if (err) return { ok: false, error: err }
  return { ok: true, value: parsed as TemplateComponent[] }
}

// ─── Preview: cómo vería el mensaje el cliente final ────────────────────────
// El editor es JSON crudo formato Meta; este helper lo traduce a un preview
// legible sustituyendo las variables {{n}}/{{name}} con el `example` embebido
// (o dejando el placeholder visible cuando no hay ejemplo). Lo usa el diálogo
// de creación/edición para dar feedback inmediato sin depender de Meta.

export type TemplatePreview = {
  headerText: string | null
  headerFormat: string | null
  bodyText: string
  footerText: string | null
  buttonLabels: string[]
  /** true si se pudo resolver al menos una variable con el `example`. */
  usedExample: boolean
}

function firstExampleRow(example: Record<string, unknown> | undefined, key: string): string[] {
  if (!example) return []
  const val = example[key]
  if (Array.isArray(val)) {
    // body_text: [["a","b"]]  |  header_text: ["a"]
    if (val.length > 0 && Array.isArray(val[0])) {
      return (val[0] as unknown[]).map((v) => String(v))
    }
    return (val as unknown[]).map((v) => String(v))
  }
  return []
}

/**
 * Sustituye placeholders {{1}}, {{2}}… (o {{cualquier_token}}) por los valores
 * del example en orden de aparición. Si no hay valor, deja «token» visible.
 * Devuelve [texto, huboSustitucion].
 */
function substituteVars(text: string, values: string[]): [string, boolean] {
  let idx = 0
  let used = false
  const out = text.replace(/\{\{\s*([^}]+?)\s*\}\}/g, (_m, token: string) => {
    const val = values[idx]
    idx += 1
    if (val !== undefined && val !== '') {
      used = true
      return val
    }
    return `«${String(token).trim()}»`
  })
  return [out, used]
}

export function buildTemplatePreview(
  components: TemplateComponent[] | null | undefined,
): TemplatePreview | null {
  if (!Array.isArray(components) || components.length === 0) return null
  let headerText: string | null = null
  let headerFormat: string | null = null
  let bodyText = ''
  let footerText: string | null = null
  const buttonLabels: string[] = []
  let usedExample = false

  for (const c of components) {
    if (!c || typeof c !== 'object') continue
    const t = (c.type || '').toUpperCase()
    if (t === 'HEADER') {
      const fmt = (c.format || 'TEXT').toUpperCase()
      headerFormat = fmt
      if (c.text) {
        const [txt, used] = substituteVars(c.text, firstExampleRow(c.example, 'header_text'))
        headerText = txt
        usedExample = usedExample || used
      }
    } else if (t === 'BODY') {
      if (c.text) {
        const [txt, used] = substituteVars(c.text, firstExampleRow(c.example, 'body_text'))
        bodyText = txt
        usedExample = usedExample || used
      }
    } else if (t === 'FOOTER') {
      footerText = c.text ?? null
    } else if (t === 'BUTTONS') {
      const btns = Array.isArray(c.buttons) ? c.buttons : []
      for (const b of btns) {
        const label = (b as Record<string, unknown>)?.text
        if (typeof label === 'string' && label.trim()) buttonLabels.push(label.trim())
      }
    }
  }

  return { headerText, headerFormat, bodyText, footerText, buttonLabels, usedExample }
}
