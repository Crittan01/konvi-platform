-- ═══════════════════════════════════════════════════════════════════════════
-- El CHECK del plazo de reembolso estaba INVERTIDO: era un piso etiquetado como techo.
--
--     CHECK (manual_refund_legal_days >= 30)   -- comentado "Ley 1480 máximo"
--
-- Un techo se escribe con <=. Con >= 30, ningún tenant de la plataforma podía
-- configurar un plazo que cumpliera la ley, aunque quisiera. El incumplimiento no
-- era un error de configuración de un comerciante: era una propiedad del esquema.
--
-- LA NORMA, verificada hoy en el texto vigente
-- (alcaldiabogota.gov.co/sisjur/normas/Norma1.jsp?i=44306, art. 47 mod. por el
-- art. 3 de la Ley 2439 de 2024), literal:
--
--     "En los casos de comercio electrónico la devolución del dinero a favor del
--      consumidor no podrá exceder de quince (15) días calendario"
--
-- Bajó de 30 a 15. Y toda venta que pasa por esta plataforma es comercio
-- electrónico por definición, así que el 30 no aplica en ningún caso.
--
-- POR QUÉ NO SON DOS COLUMNAS
-- Se consideró conservar 30 para un escenario no-electrónico. Se descartó: un
-- tenant de Konvi vende por WhatsApp, y una segunda columna que nadie puede usar
-- solo reintroduce la ambigüedad que causó este bug. Si algún día hay un canal
-- presencial, se agrega entonces, con su nombre propio.
--
-- EL OTRO CHECK SE DEJA COMO ESTÁ: `retracto_window_business_days >= 5` sí es
-- correcto, porque ahí la ley es un PISO (5 días hábiles mínimo, se puede ofrecer
-- más). Los dos plazos operan en direcciones OPUESTAS, y confundirlo fue el bug.
-- ═══════════════════════════════════════════════════════════════════════════

-- Primero los datos: el constraint nuevo rechazaría las filas existentes en 30.
-- Se baja a 15 (el máximo legal) en vez de a un número menor: no le cambiamos al
-- comerciante una promesa más exigente sin que lo decida.
UPDATE public.tenant_cancellation_policy
   SET manual_refund_legal_days = 15
 WHERE manual_refund_legal_days > 15;

ALTER TABLE public.tenant_cancellation_policy
  DROP CONSTRAINT IF EXISTS tenant_cancellation_policy_manual_refund_legal_days_check;

ALTER TABLE public.tenant_cancellation_policy
  ADD CONSTRAINT tenant_cancellation_policy_manual_refund_legal_days_check
  CHECK (manual_refund_legal_days BETWEEN 1 AND 15);

ALTER TABLE public.tenant_cancellation_policy
  ALTER COLUMN manual_refund_legal_days SET DEFAULT 15;

COMMENT ON COLUMN public.tenant_cancellation_policy.manual_refund_legal_days IS
    'TECHO en días CALENDARIO para devolver el dinero. Ley 1480 art. 47 inc. final '
    '(mod. art. 3 Ley 2439 de 2024): en comercio electrónico no puede exceder 15. '
    'Se puede prometer menos, nunca más — al revés que retracto_window_business_days, '
    'que es un PISO.';
