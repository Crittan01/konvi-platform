-- =============================================================================
-- coupon_increment_redemption — RPC ATÓMICO de consumo de cupón.
--
-- POR QUÉ: `services/api/lib/coupons.py::consume_redemption` invoca este RPC
-- "para aprovechar PostgreSQL atomicity"… pero la función NUNCA existió en
-- ninguna migración. Verificado en UAT 2026-07-20 sobre un DEV replicado desde
-- las 224 migraciones: PostgREST devuelve
--   PGRST202 "Could not find the function public.coupon_increment_redemption"
-- en CADA redención, así que el código SIEMPRE caía al fallback:
--   SELECT redemptions_count → comparar → UPDATE count+1
-- que es read-modify-write NO atómico. Dos webhooks APPROVED concurrentes del
-- mismo cupón leen el mismo N y ambos escriben N+1 → el contador SUBCUENTA y
-- `max_redemptions` puede excederse (el CHECK `coupons_check2` no lo impide:
-- N+1 <= max sigue siendo válido). Además ensuciaba los logs con un WARNING
-- por cada pago confirmado.
--
-- Aquí el incremento y la comprobación del tope ocurren en UNA sola sentencia,
-- bajo el row lock del UPDATE → sin carrera.
--
-- Devuelve el nuevo redemptions_count, o NULL si no incrementó (cupón agotado,
-- inexistente, o de otro tenant) — que es exactamente lo que el llamador
-- interpreta como `incremented = bool(rpc.data)`.
--
-- p_tenant_id es obligatorio (ADR-0025): el aislamiento multi-tenant no puede
-- depender de que el UUID del cupón sea secreto.
-- =============================================================================

CREATE OR REPLACE FUNCTION public.coupon_increment_redemption(
  p_coupon_id uuid,
  p_tenant_id uuid
)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_count integer;
BEGIN
  UPDATE public.coupons
     SET redemptions_count = redemptions_count + 1,
         updated_at = now()
   WHERE id = p_coupon_id
     AND tenant_id = p_tenant_id
     AND (max_redemptions IS NULL OR redemptions_count < max_redemptions)
  RETURNING redemptions_count INTO v_count;

  RETURN v_count;  -- NULL si no hubo fila que actualizar
END;
$$;

COMMENT ON FUNCTION public.coupon_increment_redemption(uuid, uuid) IS
  'Incrementa coupons.redemptions_count de forma atómica respetando max_redemptions. '
  'Devuelve el nuevo contador o NULL si no incrementó. Solo service_role.';

-- Solo el backend (service_role) consume cupones; nunca el cliente.
REVOKE ALL ON FUNCTION public.coupon_increment_redemption(uuid, uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.coupon_increment_redemption(uuid, uuid) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.coupon_increment_redemption(uuid, uuid) TO service_role;
