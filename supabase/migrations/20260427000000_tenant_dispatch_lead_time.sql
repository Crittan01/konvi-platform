-- Tiempo de despacho por tenant
-- Campo de texto libre para que el comercio describa cuánto tarda en alistar y despachar pedidos.
-- El orquestador lo inyecta en el system prompt para responder preguntas de clientes.
-- Ejemplos: "1-2 días hábiles", "Pedidos antes de las 2pm salen el mismo día"

ALTER TABLE public.tenants
  ADD COLUMN IF NOT EXISTS dispatch_lead_time TEXT DEFAULT NULL;
