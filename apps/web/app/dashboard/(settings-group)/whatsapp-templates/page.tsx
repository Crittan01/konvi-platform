/**
 * /dashboard/whatsapp-templates — redirect tras restructura Integraciones.
 *
 * Las plantillas WhatsApp ahora viven dentro del panel de la integración:
 *   /dashboard/integrations/whatsapp?tab=plantillas
 *
 * Esta página solo redirige para preservar URLs en bookmarks/emails viejos.
 */
import { redirect } from 'next/navigation'

export default function WhatsAppTemplatesRedirect() {
  redirect('/dashboard/integrations/whatsapp?tab=plantillas')
}
