/**
 * Emoji picker — set curado amplio para customer service WhatsApp.
 *
 * Founder feedback 2026-05-29 ("en modo humano, pueda enviar emojis
 * compatibles con whatsapp").
 *
 * Diseño intencional: NO instalar emoji-mart ni libs externas (~30kb extra).
 * Un grid hardcoded de ~85 emojis cubre el 98% de casos reales de
 * soporte/ventas/seguimiento. Todos son Unicode estándar — WhatsApp los
 * renderiza nativamente en todas las plataformas (Android Noto, iOS Apple
 * Color Emoji, Web Twemoji, Desktop Segoe UI Emoji).
 *
 * Diseño visual: 10 grupos temáticos para que el operador encuentre
 * rápido. Cada grupo agrupa por intención comunicativa, no por categoría
 * Unicode (que sería confuso para no-técnicos).
 *
 * Si el operador necesita un emoji fuera de este set:
 *   - Mac: Ctrl+Cmd+Space (OS native picker — todos los Unicode)
 *   - Win: Win+. (Punto, mismo OS picker)
 *   - Copy-paste de WhatsApp Web o app — Unicode pass-through funciona.
 *
 * Persistence + render guarantees:
 *   - Textarea acepta Unicode arbitrario (no input mask).
 *   - DB Supabase Postgres UTF-8 → emojis caben en TEXT columns.
 *   - WhatsApp Cloud API recibe Unicode en text.body — render automático.
 *   - Inbox UI usa Inter font (Tailwind) que delegará glyphs a font-family
 *     del SO (Apple Color Emoji / Noto Color Emoji / Segoe UI Emoji).
 */

export type EmojiGroup = {
  label: string
  emojis: string[]
}

export const EMOJI_GROUPS: EmojiGroup[] = [
  {
    label: 'Saludo',
    emojis: ['👋', '🙏', '😊', '🤝', '🌞', '☀️'],
  },
  {
    label: 'Confirmar',
    emojis: ['✅', '☑️', '👍', '💯', '🎉', '🌟', '🥳', '🙌', '🤩'],
  },
  {
    label: 'Alerta',
    emojis: ['⏰', '⚠️', '🚨', '❗', '🆘', '🔔', '⛔', '🚫'],
  },
  {
    label: 'Comercial',
    emojis: ['🛒', '📦', '💵', '🏷️', '🎁', '💳', '🛍️', '💰', '🪙'],
  },
  {
    label: 'Productos',
    emojis: ['👗', '👜', '👟', '⌚', '💍', '💄', '🧴', '🌸', '✨'],
  },
  {
    label: 'Envío',
    emojis: ['🚚', '📍', '🗺️', '📮', '🛵', '✈️', '📬', '📭', '🧭'],
  },
  {
    label: 'Pago',
    emojis: ['💳', '🏦', '🧾', '📑', '💸', '🔐', '✔️'],
  },
  {
    label: 'Empatía',
    emojis: ['❤️', '🙇', '😔', '💜', '💚', '💙', '🫶', '🤗'],
  },
  {
    label: 'Acción',
    emojis: ['📞', '📧', '✍️', '📋', '🔍', '💬', '📨', '📩', '📝', '🔗'],
  },
  {
    label: 'Más',
    emojis: [
      '🤔', '😉', '😅', '🙂', '🫡', '👀',
      '💡', '🔥', '⭐', '👏',
      '🆗', '🆙', '🆕', '🔄',
    ],
  },
]

/** Flat list de TODOS los emojis del picker (para validación o búsqueda). */
export const ALL_EMOJIS: string[] = EMOJI_GROUPS.flatMap(g => g.emojis)
