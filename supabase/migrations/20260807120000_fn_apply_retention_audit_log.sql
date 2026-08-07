-- M6 — `fn_apply_retention` no tenía rama para `audit_log`.
--
-- EL DEFECTO (gap de cumplimiento Habeas Data, docs/PLAN.md M6 y
-- docs/flows/opt-out-habeas-data.md):
--   La migración 20260704154100 extendió el CHECK de `retention_policies.entity`
--   para aceptar 'audit_log' e insertó la política default (730 días, hard_delete)
--   con enabled=FALSE. Pero `fn_apply_retention` nunca tuvo la rama: si alguien
--   habilitaba la política (UPDATE ... SET enabled=true), la función resolvía la
--   política efectiva, caía en el `ELSE CONTINUE` y NO BORRABA NADA — en silencio,
--   tenant por tenant. Peor aún que aplicarla mal: el operador creería que la
--   retención de auditoría corre y no corre (cumplimiento ficticio).
--
-- EVIDENCIA PRE-VUELO 2026-08-07 (db query --linked):
--   - pg_get_functiondef('public.fn_apply_retention(text,boolean)') — 4 ramas
--     (messages, conversations, contacts_inactive, pii_access_log), 0 menciones a
--     audit_log. Idéntica a 20260727170000 (única diferencia: el ';' final que
--     pg_get_functiondef omite).
--   - retention_policies: fila (NULL, 'audit_log', 730, 'hard_delete', enabled=false)
--     presente desde 2026-07-05; audit_log tiene 79 filas.
--
-- LA RAMA NUEVA sigue el patrón de pii_access_log (hard_delete por timestamp,
-- scoped por tenant): borra de public.audit_log las filas con created_at más
-- viejas que el TTL efectivo (override per-tenant enabled > default global).
--
-- GUARDA LEGAL — LA RAMA NACE DORMIDA, y eso es exactamente el objetivo:
--   audit_log es evidencia append-only (Habeas Data); la recomendación F4 es
--   ARCHIVAR a Storage antes de borrar, y ese worker sigue external_blocked
--   (ver 20260704154100). La función ya exige enabled=TRUE en AMBOS niveles —
--   el default global (si está disabled sale con NOTICE y retorna 0) y el
--   override per-tenant (cae al default). Hoy la política está enabled=FALSE,
--   así que esta rama no borra nada hasta que el founder la habilite de forma
--   explícita. Lo que cierra M6 es que, cuando alguien la habilite, la
--   retención SÍ se aplique — ya no hay habilitación ficticia.
--
-- El CREATE OR REPLACE reproduce la versión vigente (20260727170000) íntegra y
-- solo agrega la rama: reescribir desde una versión vieja revertiría en silencio
-- arreglos ya aplicados (lección rpc_stock_reservation_consume, 20260726150000).

CREATE OR REPLACE FUNCTION public.fn_apply_retention(p_entity text, p_dry_run boolean DEFAULT true)
 RETURNS integer
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_total_count   INTEGER := 0;
    v_count         INTEGER;
    v_default_ttl   INTEGER;
    v_default_act   TEXT;
    v_eff_ttl       INTEGER;
    v_eff_act       TEXT;
    v_ttl_evidencia INTEGER;
    r_tenant        RECORD;
BEGIN
    SELECT ttl_days, action
      INTO v_default_ttl, v_default_act
      FROM public.retention_policies
     WHERE tenant_id IS NULL AND entity = p_entity AND enabled = TRUE
     LIMIT 1;

    IF v_default_ttl IS NULL THEN
        RAISE NOTICE 'No default policy for entity=%; skipping.', p_entity;
        RETURN 0;
    END IF;

    -- Plazo de conservación de la PRUEBA. Si la política no está, se usa el legal: nunca
    -- se borra evidencia por falta de configuración.
    SELECT COALESCE((
        SELECT ttl_days FROM public.retention_policies
         WHERE tenant_id IS NULL AND entity = 'messages_evidencia' AND enabled = TRUE
         LIMIT 1
    ), 3653) INTO v_ttl_evidencia;

    FOR r_tenant IN
        SELECT id AS tenant_id FROM public.tenants
    LOOP
        SELECT ttl_days, action
          INTO v_eff_ttl, v_eff_act
          FROM public.retention_policies
         WHERE tenant_id = r_tenant.tenant_id
           AND entity = p_entity
           AND enabled = TRUE
         LIMIT 1;

        IF v_eff_ttl IS NULL THEN
            v_eff_ttl := v_default_ttl;
            v_eff_act := v_default_act;
        END IF;

        v_count := 0;

        -- ── messages: DOS pasadas SARGABLES, no un CASE por fila ────────────
        IF p_entity = 'messages' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.messages m
                 WHERE m.tenant_id = r_tenant.tenant_id
                   AND (
                        m.created_at < NOW() - make_interval(days => v_ttl_evidencia)
                     OR (m.created_at < NOW() - make_interval(days => v_eff_ttl)
                         AND NOT EXISTS (
                             SELECT 1 FROM public.orders o
                              WHERE o.conversation_id = m.conversation_id
                                AND o.tenant_id = m.tenant_id
                                AND (o.status IN ('confirmed','processing','shipped','delivered')
                                  OR EXISTS (SELECT 1 FROM public.payments p
                                              WHERE p.order_id = o.id AND p.status = 'approved')
                                  OR EXISTS (SELECT 1 FROM public.order_receipts r
                                              WHERE r.order_id = o.id))))
                   );
            ELSE
                -- Pasada A: lo vencido a TTL corto que NO sostiene relación comercial.
                -- El EXISTS va inline para que el planner pueda hacer anti-join en vez de
                -- llamar a una función no inlineable una vez por fila.
                WITH del AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - make_interval(days => v_eff_ttl)
                       AND NOT EXISTS (
                           SELECT 1 FROM public.orders o
                            WHERE o.conversation_id = m.conversation_id
                              AND o.tenant_id = m.tenant_id
                              AND (o.status IN ('confirmed','processing','shipped','delivered')
                                OR EXISTS (SELECT 1 FROM public.payments p
                                            WHERE p.order_id = o.id AND p.status = 'approved')
                                OR EXISTS (SELECT 1 FROM public.order_receipts r
                                            WHERE r.order_id = o.id)))
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;

                -- Pasada B: lo vencido al plazo legal de conservación, sea lo que sea.
                -- Un mensaje sin conversación (`conversation_id IS NULL`) cae acá y no en
                -- la pasada A: el NOT EXISTS con NULL no lo alcanzaría, así que sin esta
                -- pasada viviría para siempre.
                WITH del2 AS (
                    DELETE FROM public.messages m
                     WHERE m.tenant_id = r_tenant.tenant_id
                       AND m.created_at < NOW() - make_interval(days => v_ttl_evidencia)
                     RETURNING 1
                )
                SELECT v_count + COUNT(*) INTO v_count FROM del2;
            END IF;

        -- ── conversations: soft_delete (set archived_at) ────────────────────
        ELSIF p_entity = 'conversations' AND v_eff_act = 'soft_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.conversations
                 WHERE tenant_id = r_tenant.tenant_id
                   AND last_interaction_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                   AND archived_at IS NULL;
            ELSE
                WITH upd AS (
                    UPDATE public.conversations
                       SET archived_at = NOW()
                     WHERE tenant_id = r_tenant.tenant_id
                       AND last_interaction_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                       AND archived_at IS NULL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM upd;
            END IF;

        -- ── contacts_inactive: soft_delete por updated_at sin consent ───────
        ELSIF p_entity = 'contacts_inactive' AND v_eff_act = 'soft_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.contacts
                 WHERE tenant_id = r_tenant.tenant_id
                   AND COALESCE(updated_at, created_at) < NOW() - (v_eff_ttl || ' days')::INTERVAL
                   AND deleted_at IS NULL
                   AND consent_given = FALSE;
            ELSE
                WITH upd AS (
                    UPDATE public.contacts
                       SET deleted_at = NOW()
                     WHERE tenant_id = r_tenant.tenant_id
                       AND COALESCE(updated_at, created_at) < NOW() - (v_eff_ttl || ' days')::INTERVAL
                       AND deleted_at IS NULL
                       AND consent_given = FALSE
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM upd;
            END IF;

        -- ── pii_access_log: hard_delete ─────────────────────────────────────
        ELSIF p_entity = 'pii_access_log' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.pii_access_log
                 WHERE tenant_id = r_tenant.tenant_id
                   AND accessed_at < NOW() - (v_eff_ttl || ' days')::INTERVAL;
            ELSE
                WITH del AS (
                    DELETE FROM public.pii_access_log
                     WHERE tenant_id = r_tenant.tenant_id
                       AND accessed_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;
            END IF;

        -- ── audit_log: hard_delete (M6) ─────────────────────────────────────
        -- Evidencia Habeas Data append-only: SOLO aplica si la política está
        -- enabled=TRUE (guard de los dos niveles de arriba). Hoy está FALSE —
        -- rama dormida hasta el worker de archivado a Storage + firma del
        -- founder (20260704154100). Lo que se cierra acá es la habilitación
        -- ficticia: quien la habilite obtiene borrado real, no silencio.
        ELSIF p_entity = 'audit_log' AND v_eff_act = 'hard_delete' THEN
            IF p_dry_run THEN
                SELECT COUNT(*) INTO v_count
                  FROM public.audit_log
                 WHERE tenant_id = r_tenant.tenant_id
                   AND created_at < NOW() - (v_eff_ttl || ' days')::INTERVAL;
            ELSE
                WITH del AS (
                    DELETE FROM public.audit_log
                     WHERE tenant_id = r_tenant.tenant_id
                       AND created_at < NOW() - (v_eff_ttl || ' days')::INTERVAL
                     RETURNING 1
                )
                SELECT COUNT(*) INTO v_count FROM del;
            END IF;

        ELSE
            CONTINUE;
        END IF;

        v_total_count := v_total_count + v_count;
    END LOOP;

    RETURN v_total_count;
END;
$function$;

-- El GRANT sigue siendo solo backend: el CREATE OR REPLACE conserva los privilegios,
-- cerrados en 20260727150000 y re-afirmados en 20260727170000. Se re-afirma por si
-- alguien re-crea la función desde una versión vieja del repo.
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM anon;
REVOKE EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.fn_apply_retention(TEXT, BOOLEAN) TO service_role;
