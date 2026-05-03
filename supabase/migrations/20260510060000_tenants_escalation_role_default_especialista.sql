-- =============================================================================
-- Rev. 103 — Default de tenants.escalation_role: 'asesor' → 'especialista'.
--
-- Razón UX: el bot ya se posiciona como asesor/asesora virtual (Sara
-- Camila "asesora" de KAIU Living Natural). Si el bot dice "te conecto con
-- un asesor" para escalar a humano, crea ambigüedad — ¿con cuál asesor?,
-- ¿no eres tú asesora? "Especialista" diferencia al humano del bot, suena
-- profesional y cabe en cualquier vertical.
--
-- Comportamiento esta migración:
--   • Cambia el column_default para nuevos tenants.
--   • NO modifica data existente (cada tenant decide su término vía UI).
--
-- Si un tenant existente quiere adoptar el nuevo default, puede:
--   1. UPDATE tenants SET escalation_role='especialista' WHERE id=...
--   2. O dejar NULL para que el orchestrator caiga al fallback.
-- =============================================================================

ALTER TABLE public.tenants
    ALTER COLUMN escalation_role SET DEFAULT 'especialista';

COMMENT ON COLUMN public.tenants.escalation_role IS
    'Rol del humano al que se escala (default ''especialista'' rev. 103). '
    'El bot dice "te conecto con un {escalation_role}". Configurable por '
    'tenant — vertical define término preferido (asesor/agente/experto/etc).';
