-- F5 ADR-0017 — Índice único (tenant_id, role) para agentes IA.
--
-- CONTEXTO:
-- ─────────
-- La unicidad "1 agente por rol por tenant" se garantizaba SOLO en el server
-- action (apps/web/app/dashboard/(ai)/ai-agents/page.tsx → createAgent hace
-- read-then-write: SELECT roles existentes, valida, INSERT). Dos submits
-- concurrentes del mismo owner/manager pueden intercalarse entre el SELECT y el
-- INSERT → 2 agentes con el mismo `role`. El router multi-agente
-- (agentic/agent_router.py:select_agent_for_inbound) quedaría ambiguo: elige uno
-- arbitrario y el operador no sabría cuál atiende.
--
-- DECISIÓN (founder, F5):
-- Cerrar la carrera a nivel DB con un índice único. `role` es TEXT NOT NULL
-- DEFAULT 'sales' (migración 20260610000000), así que el índice cubre los 5
-- roles canónicos, incluido 'custom' (el UI ya trata custom como 1-por-tenant:
-- takenRoles en agents-list.tsx). No se excluye custom — refleja el invariante
-- real de la app (1 agente por rol).
--
-- IDEMPOTENCIA / SEGURIDAD:
-- Idempotente (IF NOT EXISTS). Si ya existe data con duplicados (creados por la
-- carrera antes de este índice), CREATE UNIQUE INDEX fallaría con un error
-- opaco de PostgreSQL. El bloque de pre-check aborta ANTES con un mensaje
-- accionable que lista los (tenant_id, role) ofensores para limpieza manual.
--
-- CÓDIGO SIN MIGRAR: degrada seguro. Sin este índice, la validación app-level
-- read-then-write sigue vigente (cierra el 99% de casos no concurrentes). El
-- índice solo endurece el borde de concurrencia. No hay dependencia de código
-- nuevo sobre este índice.

-- Paso 1: pre-check — abortar con guía si hay duplicados preexistentes.
DO $$
DECLARE
    dup_count INTEGER;
    dup_list TEXT;
BEGIN
    SELECT COUNT(*), string_agg(format('tenant=%s role=%s x%s', tenant_id, role, cnt), '; ')
      INTO dup_count, dup_list
      FROM (
        SELECT tenant_id, role, COUNT(*) AS cnt
          FROM public.ai_agents
         GROUP BY tenant_id, role
        HAVING COUNT(*) > 1
      ) d;

    IF COALESCE(dup_count, 0) > 0 THEN
        RAISE EXCEPTION
          'ai_agents tiene % combinación(es) (tenant_id, role) duplicada(s) — '
          'limpiar antes de crear el índice único. Ofensores: %',
          dup_count, dup_list
          USING HINT = 'Conserva 1 agente por (tenant_id, role) — preferir el is_default=true o el más reciente — y borra/renombra los demás.';
    END IF;
END $$;

-- Paso 2: índice único parcial-total (role es NOT NULL, cubre los 5 roles).
CREATE UNIQUE INDEX IF NOT EXISTS ai_agents_tenant_role_unique
  ON public.ai_agents (tenant_id, role);

COMMENT ON INDEX public.ai_agents_tenant_role_unique IS
  'F5 ADR-0017 — 1 agente por rol por tenant. Cierra la carrera read-then-write '
  'del server action createAgent. Espejo del invariante de UI (takenRoles).';
