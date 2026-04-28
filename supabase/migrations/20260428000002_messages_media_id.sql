-- Inbox D2 — Persistencia de media_id Meta para procesamiento multimodal
--
-- Hoy `messages.media_url` guarda la URL temporal que Meta retorna en el webhook.
-- Esa URL expira en ~5 minutos. Para reprocesar (audio que el orquestador
-- enviará a Gemini), necesitamos `media_id` (permanente del lado de Meta) y
-- `media_mime` para construir el `Part(inline_data=Blob(...))` de Gemini.
--
-- Columnas nuevas:
--   - media_id   TEXT NULL — id Meta del recurso media (permanente).
--   - media_mime TEXT NULL — mime type reportado por Meta (audio/ogg, image/jpeg, etc).

ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS media_id   TEXT,
  ADD COLUMN IF NOT EXISTS media_mime TEXT;

-- Index opcional: solo si en futuro hay queries por media_id (ej. reproceso masivo).
-- No se crea ahora — agregar cuando aparezca el caso de uso.

COMMENT ON COLUMN public.messages.media_id   IS 'Meta media_id permanente. Usado por orquestador multimodal para descarga fresca.';
COMMENT ON COLUMN public.messages.media_mime IS 'MIME type del media (audio/ogg, image/jpeg, etc).';
