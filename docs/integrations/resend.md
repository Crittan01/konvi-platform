# Resend — Email transaccional (documento canónico)

> Estado: VIGENTE · **Revalidación contra doc oficial vigente (Track 6): 2026-08-22** (fetch live resend.com/docs — URLs citadas por fila abajo §"Alineación doc oficial").

## Estado

**LIVE** — email transaccional en producción (comprobantes de compra, confirmaciones de pago, estados de envío, reembolsos, Habeas Data) + **webhook de eventos con firma svix** (Track 6) que alimenta analítica de entregabilidad, alertas al operador y la suppression list local.

Resend es el ÚNICO proveedor de email de la plataforma. La key es **por ambiente** (no por tenant): STG usa la key `konvi-stg` con permiso *Sending access* (nunca Full access) y el sender compartido de pruebas `onboarding@resend.dev`; PRD usa dominio propio verificado.

## Dónde vive el código

| Pieza | Archivo | Líneas |
|---|---|---|
| Sender async (orchestrator) | `services/ai-orchestrator/notifications.py` (`_send_email_via_resend:157`) | — |
| Sender sync (API, post-pago) | `services/api/lib/client_notifications.py` (`_send_payment_confirmation_email:394`) | — |
| Comprobante legal (email) | `services/ai-orchestrator/receipt_email.py` + `worker_commerce_crons.py:891` | — |
| Estados de envío / reembolso | `services/ai-orchestrator/shipment_status_notifications.py:323` · `refund_notifications.py:295` | — |
| Webhook de eventos (Track 6) | `services/api/routers/resend_webhook.py` | mount en `main.py` (`/api/v1/webhooks/resend`) |
| Tabla de eventos (Track 6) | migración `supabase/migrations/20260822130200_track6_resend_email_events.sql` | — |
| Suppression list local (Track 6) | `services/api/lib/email_suppression.py` | — |
| Templates HTML | `services/api/lib/email_templates.py` | — |

## Flujos implementados

### 1. Outbound: envío transaccional

Ambos senders comparten contrato (Track 6, commit `e03b46d5`):
- **Tags** `tenant_id` / `order_id` / `template` / `event_type` en cada envío — viajan al webhook de eventos y dan routing multi-tenant (la doc multi-tenant oficial prescribe tags para esto).
- **User-Agent explícito** (`konvi-api/1.0`, `konvi-orchestrator/1.0`) — Resend exige uno (403 error 1010 sin él).
- **text/plain siempre** (multipart recomendado por Resend para scoring anti-spam).
- **reply_to al tenant** (sender sync) — las respuestas del cliente van al vendedor, no al noreply de plataforma.
- **Idempotency-Key** determinística por orden+etapa (dedupe Resend 24h, máx 256 chars).
- **Log de cuota** headers `x-resend-daily-quota` / `x-resend-monthly-quota` (free tier: 100/día y 3.000/mes).
- Verdad de entrega: solo 2xx = aceptado; 4xx/5xx = False y el caller decide reintento (BLOQUE H).
- **Suppression check** (Track 6): con `supabase` disponible, los senders consultan `email_events` antes de gastar cuota — destinatario suprimido → skip + log `[EMAIL][SUPPRESSED]` + retorna no-entregado. Fail-open si la consulta falla.

### 2. Inbound: webhook de eventos (Track 6)

Receptor: `POST /api/v1/webhooks/resend` (`resend_webhook.py`; auth por firma, SIN JWT).

1. **Rate-limit** per-IP fail-open (paridad con wompi/meli/aveonline).
2. **Verificación svix**: lib oficial `svix` (standardwebhooks) valida HMAC-SHA256 sobre `{svix-id}.{svix-timestamp}.{body}` + frescura del timestamp (tolerancia 5 min, anti-replay). Sin `RESEND_WEBHOOK_SECRET` → 503; firma inválida → 401 y nada se persiste.
3. **Persistencia ANTES del ACK** en `email_events` (durabilidad patrón W2): payload crudo verificado, routing tenant/order desde `data.tags`, recipient normalizado. **Dedup por `svix_id`** (UNIQUE) — la entrega de Resend es *at-least-once* (FAQ oficial); la re-entrega responde 200 `duplicate` sin reprocesar.
4. **200 rápido + BackgroundTask**: en `email.bounced` / `email.complained` / `email.failed` / `email.suppressed` → alerta Telegram al operador del tenant (`notify_operator_telegram`) con destinatario, asunto, plantilla, pedido y motivo.
5. **Correlación suppression**: `suppression.added/removed` NO traen tags (verificado en doc) → tenant por correlación `data.source_id` → `email_events.email_id` (best-effort).
6. **Suppression list local**: `suppression.added`/`removed` quedan en `email_events` y los senders consultan el ÚLTIMO evento de supresión del destinatario (orden por `occurred_at` — la entrega no garantiza orden) antes de enviar.

Reintentos oficiales de Resend si no hay 200: 5s, 5m, 30m, 2h, 5h, 10h.

## Config por tenant vs global

Resend es **plataforma, no per-tenant**: no hay config en `notification_settings` ni Vault para el proveedor. (El *canal* email del tenant — destinatarios de notificaciones operativas — sí vive en `notification_settings.config.to_email`, ADR-0021.)

### Globales (env vars)

| Var | Valor | Servicio | Qué controla |
|---|---|---|---|
| `RESEND_API_KEY` | `sync:false` | api + orchestrator | Envío. Sin ella: fallback a log, no rompe flujos |
| `RESEND_FROM_EMAIL` | valor | api + orchestrator | Sender verificado (PRD: dominio propio; STG: `onboarding@resend.dev`) |
| `RESEND_WEBHOOK_SECRET` | `sync:false` | api | Firma svix (`whsec_...`) del webhook de eventos. Sin ella el endpoint responde 503 |

## Seguridad

- **Firma svix obligatoria**: nada se persiste ni procesa sin HMAC válido + timestamp fresco.
- **`email_events` es tabla de infra** (patrón Track 9 M1-M4): `REVOKE ALL` a `anon`/`authenticated`, `GRANT` solo a `service_role`, RLS `Tenant Isolation` como defensa en profundidad. Un cliente no puede leer los payloads (PII de destinatarios) ni insertar un `suppression.added` forjado (DoS de notificaciones) — ambos ataques cubiertos en `tests/dbharness/test_track6_email_events.py`.
- **PII enmascarada en logs** (`_mask_email`); el destinatario completo solo va al grupo Telegram autorizado del tenant (mismo criterio que el teléfono en alertas de takeover).
- Key STG con *Sending access* (mínimo privilegio); el signing secret del webhook es independiente de la API key (compromiso de una no expone la otra).

## Modo de fallo

| Fallo | Comportamiento |
|---|---|
| Sin `RESEND_API_KEY` | Fallback a log (`[EMAIL][NO_KEY]`); los flujos no se rompen |
| Resend 4xx/5xx en envío | False (no entregado); el caller decide reintento (crons de comprobante/reembolso reintentan el próximo ciclo; Idempotency-Key evita duplicados) |
| 429 cuota agotada | Log ERROR distintivo `[EMAIL][ERROR]`/quota headers — señal alertable |
| Webhook sin secret configurado | 503 explícito (feature muerta visible, no silenciosa) |
| Firma inválida | 401 genérico; cero persistencia/procesamiento |
| Re-entrega (at-least-once) | 200 `duplicate` por UNIQUE(svix_id), sin doble alerta |
| Evento sin tags (email de plataforma) | Se persiste con tenant NULL; sin alerta (no hay a quién rutear) |
| Destinatario suprimido | Sender lo omite ANTES de llamar a la API (ahorra cuota y falsos "enviado") |

## Operación

- **Registro del webhook (una vez por ambiente)** [F]: dashboard Resend → Webhooks → Add Webhook → URL `{PUBLIC_WEBHOOK_URL}/api/v1/webhooks/resend` (STG: la ngrok del api, `make -C .local print-urls`) → eventos `email.*` + `suppression.*` → copiar el signing secret (`whsec_...`) a `RESEND_WEBHOOK_SECRET` en Render/.env.local. El plan gratis permite 1 endpoint.
- **E2E STG (procedimiento)**: enviar por el path de código a `bounced+test@resend.dev` / `complained+test@resend.dev` (direcciones sintéticas oficiales) → fila en `email_events` + alerta Telegram al grupo de operadores STG. NUNCA desde el dominio prod hacia sintéticas (daña reputación).
- **Monitoreo**: logs `[RESEND][WH]` (firma, dedup, alertas), `[EMAIL][SUPPRESSED]`, quota headers en `[EMAIL]`/`[WOMPI][EMAIL]`.
- **Replays**: el dashboard Resend permite re-enviar eventos (incl. exitosos) — el dedup por svix_id los hace inertes.

## Alineación doc oficial (Track 6 — fetch live 2026-08-22)

| Capacidad | Doc oficial | Estado en código |
|---|---|---|
| Webhooks + firma svix | [webhooks/introduction](https://resend.com/docs/webhooks/introduction) (at-least-once, dedup por svix-id, retries 5s→10h) | ✅ Implementado (este dossier §2) |
| Eventos email.*/suppression.* | [webhooks/event-types](https://resend.com/docs/webhooks/event-types) (11 email + 2 suppression; payloads verificados: `email.bounced` trae `bounce{type,subType,message}`, `suppression.added` trae `{email,origin,source_id}` SIN tags) | ✅ Router + tabla + correlación |
| Tags para routing multi-tenant | send-email + payload webhook (`data.tags` es `Record<string,string>` — NO el array name/value del send) | ✅ Senders etiquetan; router enruta |
| Suppression list | suppression.added/removed (hard bounce/queja → supresión automática) | ✅ Espejo local en `email_events` + exclusión en senders |
| Idempotency-Key | 256 chars, dedupe 24h | ✅ Ya vigente (rev. 112) |
| User-Agent obligatorio | 403 error 1010 sin UA | ✅ Explícito en ambos senders |
| Cuota free tier | 100/día, 3.000/mes, headers `x-resend-*-quota` | ✅ Log de cuota vigente |
| IP allowlist del webhook | 44.228.126.217, 50.112.21.217, 52.24.126.164, 54.148.139.208, 2600:1f24:64:8000::/52 | ⬜ No adoptada: la firma svix ya autentica; allowlist es defensa extra innecesaria tras Cloudflare/Render (re-evaluar si hay abuso) |
| Inbound email (`email.received`) | Recibir emails en la plataforma | ⬜ Diseñado, no adoptado: punto de extensión para "responder al comprobante llega al tenant" (hoy reply_to cubre el 95% del caso sin operar un buzón) |

## Gaps conocidos

| ID | Severidad | Gap |
|---|---|---|
| — | Bajo | Webhook aún no registrado en el dashboard Resend de PRD (va con el deploy que incluya este router; STG primero). Hasta entonces `email_events` solo se puebla en STG |
| — | Bajo | `suppression.removed` manual del dashboard se refleja solo vía webhook; sin webhook registrado la lista local puede quedar stale (fail-open: Resend aplica la suya server-side) |

## Referencias oficiales (fetcheadas 2026-08-22)

- [webhooks/introduction](https://resend.com/docs/webhooks/introduction) · [webhooks/event-types](https://resend.com/docs/webhooks/event-types) · [payload email.bounced](https://resend.com/docs/webhooks/emails/bounced) · [payload suppression.added](https://resend.com/docs/webhooks/suppressions/added)
- [send-email](https://resend.com/docs/api-reference/emails/send-email) (tags, reply_to, Idempotency-Key)
- Lib oficial de verificación: [`svix` PyPI](https://pypi.org/project/svix/) (standardwebhooks — HMAC-SHA256 + tolerancia de timestamp 5 min)
