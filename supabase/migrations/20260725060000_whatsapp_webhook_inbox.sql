-- Durabilidad del inbound de WhatsApp — inbox transaccional.
--
-- Problema: `receive_message` (services/connector-whatsapp/routers/webhook.py:136-158) parsea el
-- body, hace `background_tasks.add_task(decouple_and_enqueue, ...)` y devuelve **200 inmediato**
-- (política obligatoria de Meta). El procesamiento real —persistir en `messages` y despachar a la
-- cola— ocurre DESPUÉS del ACK, en una tarea in-process.
--
-- Si el proceso muere en ese hueco (deploy, restart por OOM, crash) o si Supabase/Vault tienen un
-- blip, **el mensaje del cliente se pierde PARA SIEMPRE**: Meta ya recibió el 200 y NO reintenta,
-- y el único rastro es un `logger.error`. No hay forma de recuperarlo ni de saber que pasó.
--
-- El repo YA tiene el patrón correcto para esto en `wompi_webhook_inbox` (20260714000000): persistir
-- el payload crudo ANTES del ACK y reconciliar lo no procesado. Esta migración lo replica para
-- WhatsApp en vez de inventar un mecanismo nuevo.
--
-- DIFERENCIA A FAVOR respecto de Wompi: la firma HMAC de Meta se verifica en la DEPENDENCIA
-- (`verify_meta_signature_for_tenant`), que corre ANTES del cuerpo del handler. Así que acá se
-- persiste SOLO payload ya autenticado — no existe la superficie de "filas inertes forjadas" que
-- el inbox de Wompi documenta como tradeoff (Wompi persiste antes de verificar la firma).
--
-- CLAVE DE DEDUP: sha256 del body crudo. Meta no expone un id estable a nivel de payload (el
-- `wamid` es por mensaje y un POST puede traer varios), y el hash del cuerpo dedupea de forma
-- natural los reintentos de Meta ante un no-200.

CREATE TABLE IF NOT EXISTS public.whatsapp_webhook_inbox (
    -- sha256 hex del raw body. Determinístico e idempotente ante reintentos de Meta.
    body_sha256  TEXT PRIMARY KEY,
    -- Tenant HMAC-verificado que venía en el path. Se guarda para poder re-drivear con la MISMA
    -- autoridad de tenant que tuvo el request original (NO se re-resuelve por el body: cerraría
    -- el riesgo de cross-talk que A11/WH-01 ya cerró en el camino normal).
    tenant_id    UUID NOT NULL,
    raw_payload  JSONB NOT NULL,
    received_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- NULL hasta que decouple_and_enqueue termina. Un crash mid-proceso lo deja NULL → el
    -- re-drive lo recupera. Es la diferencia entre "perdido para siempre" y "pendiente, visible".
    processed_at TIMESTAMPTZ,
    -- Backstop dead-letter: tras N intentos se deja de reintentar y queda para revisión manual.
    attempts     INT NOT NULL DEFAULT 0,
    -- Lease de visibilidad: evita que el re-drive re-reclame una fila que se está procesando
    -- ahora mismo (un mensaje LENTO pero válido no debe inflar attempts ni dead-letterarse).
    claimed_at   TIMESTAMPTZ,
    last_error   TEXT
);

-- Re-drive: barre lo no procesado por antigüedad.
CREATE INDEX IF NOT EXISTS idx_wa_inbox_unprocessed
    ON public.whatsapp_webhook_inbox (received_at)
    WHERE processed_at IS NULL;

-- Cleanup: purga de filas procesadas viejas (crecimiento acotado).
CREATE INDEX IF NOT EXISTS idx_wa_inbox_processed
    ON public.whatsapp_webhook_inbox (processed_at)
    WHERE processed_at IS NOT NULL;

-- Infra de webhook: solo el backend (service_role, que tiene BYPASSRLS) escribe y lee.
-- RLS ON sin policies = deny-all para anon/authenticated. Mismo criterio que wompi_webhook_inbox.
ALTER TABLE public.whatsapp_webhook_inbox ENABLE ROW LEVEL SECURITY;

-- Norma del proyecto desde 20260725020000 (ninguna superficie nace expuesta a anon).
REVOKE ALL ON public.whatsapp_webhook_inbox FROM PUBLIC, anon;

COMMENT ON TABLE public.whatsapp_webhook_inbox IS
  'Inbox durable del webhook de WhatsApp: el payload (ya HMAC-verificado) se persiste ANTES del 200 a Meta. Como Meta no reintenta un 200, sin esto un crash entre el ACK y el procesamiento perdía el mensaje del cliente para siempre.';
COMMENT ON COLUMN public.whatsapp_webhook_inbox.tenant_id IS
  'Tenant HMAC-verificado del path. El re-drive lo usa como autoridad en vez de re-resolver por el body (cierra cross-talk, A11/WH-01).';
