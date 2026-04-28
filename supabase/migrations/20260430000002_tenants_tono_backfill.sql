-- Rev. 69 — Backfill tono_comunicacion + NOT NULL guard
--
-- Razón: "Estado del bot" rev. 68 muestra el check 'Tono' en rojo si el
-- tenant tiene tono_comunicacion=NULL. La migración 20260426030000 ya
-- definió DEFAULT 'amigable' a nivel de columna, pero hay tenants antiguos
-- con NULL (creados antes o con INSERT que pasó NULL explícito).
--
-- Solución:
--   1. Backfill UPDATE para tenants con NULL → 'amigable'.
--   2. ALTER COLUMN ... SET NOT NULL para prevenir NULLs futuros.
--
-- IMPORTANTE: el UPDATE va ANTES del ALTER. Si quedara algún NULL al
-- aplicar SET NOT NULL, la migración fallaría — el orden garantiza éxito.

UPDATE public.tenants
   SET tono_comunicacion = 'amigable'
 WHERE tono_comunicacion IS NULL OR TRIM(tono_comunicacion) = '';

ALTER TABLE public.tenants
  ALTER COLUMN tono_comunicacion SET NOT NULL;

COMMENT ON COLUMN public.tenants.tono_comunicacion IS
  'Tono de comunicación del bot (rev. 69 NOT NULL). Valores: formal/profesional/amigable/cercano/juvenil. Default ''amigable''.';
