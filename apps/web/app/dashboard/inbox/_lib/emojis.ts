/**
 * Emoji picker — set curado para customer service WhatsApp.
 *
 * Founder feedback 2026-05-29 ("en modo humano, pueda enviar emojis").
 *
 * Diseño intencional: NO instalar emoji-mart ni libs externas. Un grid
 * hardcoded de ~40 emojis cubre el 95% de casos de soporte/ventas:
 *   - Saludo: 👋 🙏
 *   - Confirmación: ✅ ☑️ 👍 💯
 *   - Atención/alerta: ⏰ ⚠️ 🚨 ❗
 *   - Carrito/comercial: 🛒 📦 💵 🏷️ 🎁
 *   - Envío: 🚚 📍 🗺️
 *   - Emocional/empatía: 😊 🤝 ❤️ 🌟
 *   - Negativos cuidadosos: 😔 🙇 (humilde, no triste excesivo)
 *   - Acción cliente: 📞 📧 ✍️ 📋
 *
 * Si en el futuro se necesita más cobertura, evaluar:
 *   - emoji-picker-react (~30kb gzip, dep adicional)
 *   - Trigger nativo OS (Ctrl+Cmd+Space Mac / Win+. Win) — gratis pero
 *     menos descubrible para operadores no técnicos.
 *
 * Cualquier emoji que el operador escriba a mano (con OS picker o
 * copy-paste) funciona igual — Unicode passa por el textarea sin
 * conversión, persiste en DB UTF-8 y se renderiza en WhatsApp 100%.
 * Este picker es solo "shortcut UX para los más comunes".
 */

export type EmojiGroup = {
  label: string
  emojis: string[]
}

export const EMOJI_GROUPS: EmojiGroup[] = [
  {
    label: 'Saludo',
    emojis: ['👋', '🙏', '😊', '🤝'],
  },
  {
    label: 'Confirmar',
    emojis: ['✅', '☑️', '👍', '💯', '🎉', '🌟'],
  },
  {
    label: 'Alerta',
    emojis: ['⏰', '⚠️', '🚨', '❗', '🆘'],
  },
  {
    label: 'Comercial',
    emojis: ['🛒', '📦', '💵', '🏷️', '🎁', '💳'],
  },
  {
    label: 'Envío',
    emojis: ['🚚', '📍', '🗺️', '📮'],
  },
  {
    label: 'Empatía',
    emojis: ['❤️', '🙇', '😔', '💜'],
  },
  {
    label: 'Acción',
    emojis: ['📞', '📧', '✍️', '📋', '🔍', '💬'],
  },
]

/** Flat list de TODOS los emojis del picker (para validación o búsqueda). */
export const ALL_EMOJIS: string[] = EMOJI_GROUPS.flatMap(g => g.emojis)
