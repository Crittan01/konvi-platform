-- FASE 1 compliance (audit F125 · LOW) — drop de tabla muerta con PII cruda. Autorizado (drop/purgar).
--
-- envia_webhook_capture_log era una tabla TEMPORAL de descubrimiento (declarado en su propia migración
-- 20260514190000: "se DROPea o renombra cuando Fase B implemente procesadores reales"). El pivote
-- Envia→Aveonline (20260601120000) deprecó el provider y F7 (20260702200000) dropeó el resto del schema
-- Envia muerto, pero esta quedó fuera. 0 lectores/writers (grep services/apps/scripts). Al capturar
-- raw_body/headers de webhooks contiene direcciones/teléfonos sin política de retención → guardarla es un
-- riesgo de minimización de datos (Ley 1581). Founder autorizó purga directa (Envia está muerto).

DROP TABLE IF EXISTS public.envia_webhook_capture_log;
