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
  whatsapp: 'Evidencia: el hilo de WhatsApp donde el titular dijo "Sí acepto". El sistema lo enlaza al consent_audit_log automáticamente.',
  web_form: 'Evidencia: captura del formulario web (timestamp + IP + checkbox). Asegúrate que tu sitio persiste estos datos.',
  phone_call: 'Llamada con el titular. Si grabaste la llamada, referencia su archivo. Si no, anota fecha+hora+nombre del operador que llamó.',
  in_person: 'Evidencia: documento físico firmado por el titular. Archiva el papel y referencia su ubicación en Evidencia abajo.',
  import: 'Importación: el consent fue capturado en otro sistema. Eres responsable de demostrarlo ante SIC.',
  other: 'Catch-all. La Evidencia es OBLIGATORIA (mínimo 20 caracteres). Si no puedes describir de dónde vino, este canal NO aplica.',
}
