-- F7 (auditoría 2026-07-02) — DROP de schema muerto verificado (0 lectores/writers en runtime).
-- Autorizado explícitamente por el founder. Ledger con drift → DROP IF EXISTS (no editar migraciones
-- históricas, que son inmutables). Verificado por 14 agentes: ninguna de estas tablas/columnas tiene
-- lector ni writer en services/, apps/, scripts/ ni tests (salvo el fixture de esquema, que se regenera).
--
-- 1. Tablas fantasma ADR-0029 F0/F1: category_attributes + attribute_values eran una capa de atributos
--    curados GLOBAL que NUNCA se pobló. El contrato de atributos VIVO es product_attribute_definitions
--    (per-tenant). attribute_values → category_attributes (FK ON DELETE CASCADE): drop la hija primero.
--    Las policies RLS caen con la tabla.
-- 2. Columnas Envia-legacy en shipments: pickup_id + last_polled_at (+ índice de polling). El provider
--    activo es Aveonline (ADR-0019), que notifica por webhooks, no por polling. Ningún path las llena.
--    (envia_shipment_id ya fue dropeada por 20260601120000.)

DROP TABLE IF EXISTS public.attribute_values;
DROP TABLE IF EXISTS public.category_attributes;

DROP INDEX IF EXISTS public.shipments_polling_candidate_idx;
ALTER TABLE public.shipments DROP COLUMN IF EXISTS last_polled_at;
ALTER TABLE public.shipments DROP COLUMN IF EXISTS pickup_id;
