# Integraciones — Índice canónico

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Documentos maestros de las integraciones activas de la plataforma. Cada doc declara su estado real (LIVE / PARCIAL / SANDBOX), dónde vive el código, flujos con `archivo:línea`, config por tenant vs global, seguridad, modo de fallo, operación y gaps con ID de auditoría (`.audit/findings/2026-08-02-consolidated-audit.md`).

## Integraciones activas

| Proveedor | Doc | Estado | Qué significa |
|---|---|---|---|
| **Wompi** (pagos) | `wompi.md` | LIVE | Payment links reales, webhook firmado SHA256 per-tenant, reconciliación 3 capas + runbook manual |
| **Aveonline** (shipping) | `aveonline.md` | PARCIAL | Cotización live; guías DRY-RUN por flag global (B1); webhook de estados activo; sin polling de respaldo (A10) |
| **Telegram** (canal interno) | `telegram.md` | LIVE | Alertas de takeover + comandos `/resolver` `/estado` con RBAC chat_id→tenant; `setWebhook` manual por tenant (M17) |
| **Mercado Libre** (marketplace) | `mercadolibre.md` | LIVE | OAuth endurecido, webhook IPN (IP allowlist + dedup + anti-SSRF), sync stock bidireccional |
| **WhatsApp / Meta Cloud API** | `whatsapp-meta.md` | LIVE | Model B per-tenant (ADR-0023), HMAC per-tenant, inbox durable, Graph v22.0, ventana 24h con 131047 sin reintento |
| **Supabase** (plataforma base: Postgres+RLS+Auth+Realtime+Vault+Storage) | `supabase.md` | LIVE | Alineación doc oficial Track 6 (2026-08-22): realtime select+anti-truncamiento, keys sin fallback legacy, runbook DR vault |
| **Gemini** (LLM del bot) | `gemini.md` | LIVE | Track 6 (2026-08-22): telemetría caching fase 0, SDK 2.19, VALIDATED tras flag; EOL 3.1-flash-lite 2027-05-07 calendarizado |
| **Resend** (email transaccional) | — (sin doc maestro) | LIVE | `services/ai-orchestrator/notifications.py:157` (`_send_email_via_resend`), `receipt_email.py`, `refund_notifications.py`; env `RESEND_API_KEY` (sync:false) + `RESEND_FROM_EMAIL`; sin key → fallback a log, no rompe flujos. Cubre Habeas Data, comprobantes y notificaciones post-venta fuera de ventana 24h |

## Proveedores retirados

- **Envia (shipping)**: eliminado del runtime en rev. 109 (ADR-0019, `docs/adr/0019-aveonline-as-primary-shipping-provider.md`). No queda código activo — solo comentarios históricos y el default legacy `active_provider='envia'` en migraciones viejas (M12). Histórico: `docs/research/_archive/envia-dossier-2026-05-05.md`, evidencia empírica en `docs/research/_archive/empirical-evidence/envia-*`, branch de investigación `archive/envia-investigacion-rev106-2026-05-08`.

## Futuros / preparación (sin runtime)

- `custom-store-prep.md`, `shopify-prep.md` — placeholders de preparación (Fase 13, futuro lejano).

## Documentos históricos en esta carpeta (supersedidos, pendientes de decisión)

Estos docs quedaron redundantes tras la consolidación de 2026-08-02. **No borrados** — reportados para decisión de archivo:

| Doc viejo | Supersedido por | Nota |
|---|---|---|
| `whatsapp.md` | `whatsapp-meta.md` | Describe Model B pre-refinamiento (aún cita Meta v21.0 y env vars Meta eliminadas como vigentes) |
| `meta-suite.md` | `whatsapp-meta.md` | Diseño "Embedded Signup / Tech Provider" (OQ-W01/W02) — modelo NO implementado; el implementado es Model B (ADR-0023) |
| `wompi-prep.md` | `wompi.md` | Prep de Fase C ("runtime aún no implementado") — la integración ya está LIVE |

## Reglas transversales (todas las integraciones)

1. **Cero suposión**: endpoints, scopes y capacidades se validan contra docs oficiales (dossiers en `docs/research/`) antes de afirmarse.
2. **Credenciales per-tenant en Vault** (`tenant_integrations` / `notification_settings`), nunca en env vars globales ni en el repo. Excepciones globales legítimas: app de plataforma MeLi (`MELI_CLIENT_*`), secret de webhook Telegram, knobs operativos.
3. **Webhooks endurecidos**: firma/secret/IP allowlist según lo que ofrezca el proveedor + dedup + inbox durable cuando el proveedor no garantiza entrega.
4. **Confirmación de dinero solo server-side**: nunca por interpretación de texto en chat.
5. RLS + filtros `tenant_id` explícitos en cada operación; `service_role` no es atajo para saltarse el aislamiento.
