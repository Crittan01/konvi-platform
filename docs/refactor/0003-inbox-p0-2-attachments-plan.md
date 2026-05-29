# P0-2 — Adjuntar imagen/PDF al outbound humano (plan ejecutable)

**Estado:** PENDIENTE — requiere sesión dedicada (~3-5h).
**Razón de diferir:** alcance real es mayor que P0-1/P0-3; hacerlo apurado introduce bugs cross-layer (cola → worker → Meta API → storage).

## Infraestructura existente reutilizable

- ✅ Bucket Supabase Storage `tenant-media` (public) — usado en catálogo (`image-upload-box.tsx`).
- ✅ `whatsapp_sender.send_whatsapp_message(image_link=..., image_caption=...)` — soporta `type=image` con link HTTPS público (Meta Cloud API v22.0).
- ✅ Patrón canónico de upload Next.js client-side: `supabase.storage.from('tenant-media').upload(path, file)`.

## Gaps a cerrar

### Cola outbound + worker
- `enqueue_whatsapp_outbound_message` payload hoy solo carga `text`.
- `worker._poll_whatsapp_outbound_messages` llama `send_whatsapp_message(text=...)`.
- **Extender payload** con `image_link?` + `image_caption?` opcionales.
- **Worker decide** por presencia de `image_link`: si existe → `send_whatsapp_message(image_link=...)`, sino → `text`.

### API endpoint
- Nuevo: `POST /api/v1/conversations/{id}/send-image` o extender `POST /send` con campos opcionales.
- Validar URL HTTPS (Meta lo exige).
- Validar conv en `human_takeover` + ventana 24h (igual que send text).
- Persistir message con `content_type='image'` + `media_url=<URL>` + `content=<caption>`.

### Proxy Next.js
- `apps/web/app/api/conversations/[conversationId]/send-image/route.ts`.

### UI
- Botón clip 📎 en `chat-editor-toolbar.tsx` (al lado de emoji picker).
- File picker: accept `image/*` (PDFs requieren `type=document` Meta — diferido).
- Validación: tamaño máx 5MB (Meta image limit), MIME en {jpeg, png, webp}.
- Preview thumbnail inline antes de enviar.
- Upload directo del cliente a `tenant-media/inbox-attachments/{tenant_id}/{conv_id}/{uuid}.{ext}`.
- Tras upload exitoso → obtener URL pública → POST a `/send-image`.
- Mensaje de error claro si Meta rechaza (típico: URL no HTTPS, contenido bloqueado).

### Render de imágenes en el chat
- ✅ Ya soportado en `chat-panel.tsx`: detecta `content_type='image'` y renderiza `<img>` con `media_url`.

## PDFs / documents (out-of-scope MVP)

- Meta Cloud API requiere `type=document` con su propio handling.
- Tamaño máximo 100MB.
- Mostrar como adjunto en WhatsApp.
- Caso de uso: factura PDF al cliente post-compra.
- **Decisión arquitectónica**: diferir a sesión dedicada porque cambia el contrato de send + worker payload + render UI.

## Riesgos identificados

1. **URL pública del bucket**: `tenant-media` es público — cualquier persona con la URL puede acceder. Para conversaciones, esto es **aceptable** (es lo que Meta hace internamente al cargar el `link`). PERO documentar para cumplimiento Habeas Data.
2. **Validación MIME server-side**: cliente envía cualquier MIME, server debe re-validar.
3. **Rate limiting**: operador puede mandar 100 imágenes seguidas. Idempotency-Key + rate limit en endpoint.
4. **Cleanup**: archivos pueden quedar huérfanos si el send falla post-upload. Cron job para limpiar attachments sin message asociado >24h.

## Estimación

- Backend (extend payload + worker + endpoint): ~1.5h
- Proxy Next.js: ~15min
- UI (botón + picker + preview + upload + send): ~1h
- Tests unitarios + UAT live con imagen real: ~1h
- Documentación + ADR: ~30min

**Total: 3-4.5h** en sesión dedicada con focus.

## Cómo retomar

1. Crear branch `feat/inbox-p0-2-attachments` desde `refactor/inbox-components`.
2. Leer este doc + `apps/web/app/dashboard/(products)/catalog/_components/image-upload-box.tsx` (patrón canónico upload).
3. Implementar en orden: backend endpoint → proxy → UI → smoke local → UAT live con imagen real.
4. PR a `refactor/inbox-components` (o directo a `phase-2-agentic-rewrite`).
