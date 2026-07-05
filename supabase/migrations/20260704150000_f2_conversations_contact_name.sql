-- =============================================================================
-- F2 (2026-07-04) — Denormaliza `contact_name` en `conversations`.
--
-- CONTEXTO: el nombre del contacto (Meta `contacts[].profile.name`) sólo vivía
-- en el header del chat (lookup por phone en el panel de contexto). En la LISTA
-- del Inbox el operador sólo veía el teléfono, y la búsqueda por nombre era
-- imposible sin N lookups por render.
--
-- DECISIÓN (aprobada founder): denormalizar en el write-path del connector
-- (services/connector-whatsapp/db_persistence). Es un campo de SÓLO-DISPLAY de
-- alta frecuencia de lectura → el patrón correcto es denormalizar, no join
-- client-side por phone.
--
-- Idempotente: ADD COLUMN IF NOT EXISTS. Sin default (NULL = aún no capturado
-- o row histórico previo al backfill). El connector lo puebla en cada inbound
-- que traiga profile.name; la UI degrada a `customer_phone` si es NULL.
--
-- Aislamiento (ADR-0025): columna sólo-display en una tabla YA tenant-scoped
-- (conversations.tenant_id + RLS existente). No introduce nueva superficie
-- cross-tenant: se lee/escribe siempre dentro del scope de la conversación.
--
-- NO aplicar automáticamente. Protocolo seguro (supabase db query --linked) +
-- migration repair. El código asume degradación segura si la columna no existe.
-- =============================================================================

ALTER TABLE public.conversations
    ADD COLUMN IF NOT EXISTS contact_name TEXT;

COMMENT ON COLUMN public.conversations.contact_name IS
    'Denormalizado sólo-display del nombre del contacto (Meta profile.name). '
    'Poblado por el connector en el write-path del inbound. NULL = no capturado. '
    'F2 2026-07-04.';
