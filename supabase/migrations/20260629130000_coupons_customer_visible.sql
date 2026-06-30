-- Auditoría 2026-06-29 (F4.2) — flag de visibilidad cara-cliente para cupones.
--
-- Problema: el bot inyecta TODOS los cupones activos al system_prompt → podría mencionar
-- proactivamente un cupón interno/targeted que el tenant no quería anunciar.
--
-- Solución: is_customer_visible. Si false, el bot NO lo menciona proactivamente, PERO el cupón
-- SIGUE funcionando cuando el cliente provee el código exacto (apply_coupon hace lookup por `code`
-- en DB, independiente de la inyección al prompt — verificado services/api/lib/coupons.py:326).
--
-- Aditiva, idempotente, DEFAULT true → los cupones existentes siguen visibles (cero regresión).

ALTER TABLE public.coupons
  ADD COLUMN IF NOT EXISTS is_customer_visible BOOLEAN NOT NULL DEFAULT true;

COMMENT ON COLUMN public.coupons.is_customer_visible IS
  'Si true, el bot puede mencionar el cupón proactivamente al cliente. Si false, es interno/targeted: '
  'NO se anuncia, pero se aplica cuando el cliente provee el código exacto.';
