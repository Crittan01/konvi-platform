-- =============================================================================
-- ML reliability (follow-up ADR-0037) — SINGLE-FLIGHT del refresh de token MeLi
-- + surfacing SEGURO del 401-loop (marcado status='error') vía FENCING TOKEN +
--   CONTADOR de fallos consecutivos.
--
-- PROBLEMA (verificado + hallado en 2 revisiones adversariales de get_valid_token):
--   Los ~8 callsites async comparten el refresh_token de UN SOLO USO (MeLi rota en cada
--   refresh). Sin coordinación cross-loop/worker/réplica: el 1º rota y los demás fallan con un
--   token ya inválido. Un asyncio.Lock a nivel proceso NO sirve (get_valid_token corre en el
--   loop principal Y en loops efímeros de asyncio.run → Lock cross-loop → RuntimeError → None →
--   oversell). Y marcar status='error' en un solo 400 es RACY: el 'perdedor' de un refresh
--   concurrente marcaría 'error' a una integración SANA (el filtro status='connected' bloquea el
--   auto-heal) → oversell. Un lease simple con TTL NO basta: si el holder tarda > TTL (latencia
--   Vault/DB), un 2º caller también gana el lease (double-win) y reabre el falso-positivo.
--
-- FIX (2 capas, hallazgo de la 2ª revisión):
--   1) LEASE con FENCING TOKEN: rpc_meli_try_refresh_lease hace un UPDATE condicional atómico
--      (gana exactamente uno; el row-lock de Postgres serializa) y devuelve un NONCE (uuid). El
--      release y el marcado de error se hacen SOLO si el nonce sigue siendo el nuestro (compare-
--      and-set) → un holder cuyo lease expiró y fue retomado NO puede liberar ni marcar error.
--   2) CONTADOR de fallos consecutivos: marcar 'error' NO en un solo 400 (ambiguo por el
--      persist-timing window) sino tras N fallos CONSECUTIVos. Un 400 falso aislado (perdedor
--      concurrente) no acumula porque el ÉXITO del ganador RESETEA el contador; solo una
--      integración GENUINAMENTE muerta (refresh falla en cada ciclo) llega al umbral. Inmune al
--      double-win: aunque dos "won" coexistan, el éxito de uno resetea el contador del otro.
--
-- ⚠️ INTERVENCIÓN HUMANA: aplicar con protocolo seguro + migration repair. ADITIVO PURO
--    (columnas nullable / DEFAULT + funciones nuevas) → backward-compatible: el código degrada
--    con gracia si las RPC no existen (no marca error → comportamiento seguro previo).
-- =============================================================================

ALTER TABLE public.tenant_integrations
  ADD COLUMN IF NOT EXISTS refresh_lease_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS refresh_lease_token UUID,
  ADD COLUMN IF NOT EXISTS refresh_fail_count  INTEGER NOT NULL DEFAULT 0;

-- ── Adquirir el lease (atómico) → devuelve el NONCE si lo ganó, NULL si no ────
CREATE OR REPLACE FUNCTION public.rpc_meli_try_refresh_lease(
  p_tenant_id   UUID,
  p_provider    TEXT DEFAULT 'mercadolibre',
  p_ttl_seconds INTEGER DEFAULT 90
)
RETURNS UUID   -- fencing token (uuid) si ganó; NULL si otro lo tiene
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_token UUID := gen_random_uuid();
  v_got   UUID;
BEGIN
  UPDATE public.tenant_integrations
     SET refresh_lease_until = NOW() + make_interval(secs => GREATEST(1, p_ttl_seconds)),
         refresh_lease_token = v_token
   WHERE tenant_id = p_tenant_id
     AND provider  = p_provider
     AND (refresh_lease_until IS NULL OR refresh_lease_until < NOW())
  RETURNING refresh_lease_token INTO v_got;
  RETURN v_got;  -- = v_token si actualizó (ganamos); NULL si el WHERE no matcheó (perdimos)
END;
$$;

COMMENT ON FUNCTION public.rpc_meli_try_refresh_lease(UUID, TEXT, INTEGER) IS
  'ML reliability — single-flight del refresh de token: UPDATE condicional atómico. Devuelve un fencing token (uuid) si este caller ganó el lease, NULL si otro lo tiene. TTL evita deadlock si el holder crashea.';

-- ── Liberar el lease — FENCED por el token (no clobbea un lease retomado) ─────
CREATE OR REPLACE FUNCTION public.rpc_meli_release_refresh_lease(
  p_tenant_id   UUID,
  p_lease_token UUID,
  p_provider    TEXT DEFAULT 'mercadolibre'
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE public.tenant_integrations
     SET refresh_lease_until = NULL, refresh_lease_token = NULL
   WHERE tenant_id = p_tenant_id
     AND provider  = p_provider
     AND refresh_lease_token = p_lease_token;  -- solo si SEGUIMOS siendo el holder
END;
$$;

COMMENT ON FUNCTION public.rpc_meli_release_refresh_lease(UUID, UUID, TEXT) IS
  'ML reliability — libera el lease SOLO si el fencing token coincide (compare-and-set). Un holder cuyo lease expiró y fue retomado NO clobbea al holder actual.';

-- ── Registrar un fallo de refresh — FENCED + contador; marca error en umbral ──
CREATE OR REPLACE FUNCTION public.rpc_meli_note_refresh_failure(
  p_tenant_id   UUID,
  p_lease_token UUID,
  p_provider    TEXT DEFAULT 'mercadolibre',
  p_max_fails   INTEGER DEFAULT 3
)
RETURNS BOOLEAN   -- true si marcó status='error'
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count INTEGER;
BEGIN
  -- Incrementa SOLO si seguimos siendo el holder (fencing) → un stale/retomado no cuenta.
  UPDATE public.tenant_integrations
     SET refresh_fail_count = refresh_fail_count + 1
   WHERE tenant_id = p_tenant_id
     AND provider  = p_provider
     AND refresh_lease_token = p_lease_token
  RETURNING refresh_fail_count INTO v_count;

  IF v_count IS NULL THEN
    RETURN FALSE;  -- no somos el holder (lease retomado) → no acumular ni marcar
  END IF;

  -- Marcar 'error' SOLO tras N fallos CONSECUTIVOS (un 400 falso aislado no acumula: el ÉXITO
  -- de un refresh resetea el contador). Fenced por el token también en el marcado.
  IF v_count >= GREATEST(1, p_max_fails) THEN
    UPDATE public.tenant_integrations
       SET status = 'error'
     WHERE tenant_id = p_tenant_id
       AND provider  = p_provider
       AND refresh_lease_token = p_lease_token;
    RETURN TRUE;
  END IF;
  RETURN FALSE;
END;
$$;

COMMENT ON FUNCTION public.rpc_meli_note_refresh_failure(UUID, UUID, TEXT, INTEGER) IS
  'ML reliability — cuenta fallos de refresh CONSECUTIVOS (fenced por el token). Marca status=error solo al alcanzar el umbral → un 400 falso de un perdedor concurrente no marca (el éxito resetea el contador). Surfacing seguro del 401-loop.';
