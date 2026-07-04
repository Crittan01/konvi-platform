/**
 * Rev. 103 — Help text contextual por canal de consent.
 *
 * Guía al operador sobre qué evidencia debe registrar/archivar para
 * audit ante SIC. Modelo SaaS B2B (Wati/Mailchimp): el operador decide
 * qué canal aplica; el tenant es responsable bajo el DPA firmado.
 *
 * NOTA: 'marketplace_meli' NO aparece aquí — se escribe solo via webhook
 * MeLi backend, no se ofrece en el dropdown UI.
 */
export const CONSENT_SOURCE_HELP: Record<string, string> = {
  manual_console: 'El operador registra el consentimiento dado fuera del sistema (e.g., conversación previa). El operador asume responsabilidad de evidencia externa.',
  whatsapp: 'Evidencia: el hilo de WhatsApp donde el titular dijo "Sí acepto". El sistema lo enlaza al registro de consentimiento automáticamente.',
  web_form: 'Evidencia: captura del formulario web (timestamp + IP + checkbox). Asegúrate que tu sitio persiste estos datos.',
  phone_call: 'Llamada con el titular. Si grabaste la llamada, referencia su archivo. Si no, anota fecha+hora+nombre del operador que llamó.',
  in_person: 'Evidencia: documento físico firmado por el titular. Archiva el papel y referencia su ubicación en Evidencia abajo.',
  import: 'Importación: el consent fue capturado en otro sistema. Eres responsable de demostrarlo ante SIC.',
  other: 'Catch-all. La Evidencia es OBLIGATORIA (mínimo 20 caracteres). Si no puedes describir de dónde vino, este canal NO aplica.',
}

/**
 * Etiqueta legible del canal de consentimiento para mostrar en la card
 * del contacto (evita exponer el valor crudo tipo `manual_console`).
 * Coincide con las etiquetas del dropdown del formulario.
 */
export const CONSENT_SOURCE_LABEL: Record<string, string> = {
  manual_console: 'Consola (operador)',
  whatsapp: 'WhatsApp',
  web_form: 'Formulario web',
  phone_call: 'Llamada telefónica',
  in_person: 'Presencial',
  import: 'Importación',
  other: 'Otro',
  marketplace_meli: 'Marketplace Mercado Libre',
}

export const consentSourceLabel = (raw?: string | null): string =>
  raw ? (CONSENT_SOURCE_LABEL[raw] ?? raw) : ''

/**
 * Rev. F2 — Mensaje legible para el operador cuando la subida del adjunto
 * de evidencia física (F10) falló. El motivo crudo (`too_large`,
 * `mime_not_allowed`, `storage_error`) queda en `consent_evidence`, pero
 * la card lo traduce a lenguaje accionable para que el operador sepa que
 * el escaneo del consent firmado NO quedó guardado y pueda reintentar.
 */
export const ATTACHMENT_SKIP_MESSAGE: Record<string, string> = {
  too_large: 'El archivo superaba el máximo de 5 MB.',
  mime_not_allowed: 'El formato no es válido (solo PDF, JPG, PNG o WEBP).',
  storage_error: 'Hubo un error al guardar el archivo en el almacenamiento.',
}

export const attachmentSkipMessage = (reason?: string | null): string | null =>
  reason ? (ATTACHMENT_SKIP_MESSAGE[reason] ?? 'No se pudo guardar el archivo adjunto.') : null
