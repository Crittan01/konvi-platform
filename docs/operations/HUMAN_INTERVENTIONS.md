# Intervención humana — cierre del ecosistema tenant (F1–F7 + 114 decisiones)

> **Estado 2026-07-04 (post-implementación).** El ecosistema tenant se cerró en dos capas:
> (1) **F1–F7** — cimientos UX/UI + ~380 gaps de completitud; (2) **114 decisiones** (D-F2…D-F7),
> aprobadas por el founder e implementadas todas las que NO requieren intervención humana.
> Todo está **certificado** (pytest 3392 · web 252 · tsc 0 · Next build EXIT 0 · tenant-lint 0)
> y en `develop`. Además se corrió una **verificación adversarial** (10 targets) sobre los cambios
> de mayor riesgo: 2 CONFIRMED + 1 PLAUSIBLE fueron corregidos; 7 CLEAR (ver §4).
>
> Este documento es la lista **definitiva** de lo que queda en tus manos: aplicar migraciones,
> configurar servicios externos, validar los cambios de comportamiento en UAT, y sellar el gate final.
> El detalle por-módulo de cada decisión vive en `fase0_raw/decision_brief.json` y en los commits
> `D-F2…D-F7` (la versión anterior de este archivo, en git history, enumeraba los gaps como "abiertos";
> ya no lo están).

---

## 1. Migraciones a aplicar a producción (26 archivos, sin aplicar)

Todas creadas como archivo, **ninguna aplicada** (ledger con drift → protocolo manual). El código
**degrada seguro** si la migración no está (feature-detect / fallback), salvo las marcadas **GATE**.

**Protocolo (por bloque, con tu autorización explícita):**
```bash
supabase db query --linked < supabase/migrations/<archivo>.sql
supabase migration repair --status applied <version>
```
Aplicar **en orden de timestamp**. La de storage (140000) exige revisar policies manuales previas.

| # | Migración | Qué habilita | Gate |
|---|---|---|---|
| 1 | `20260704000000_messages_delivery_receipts` | Estado de entrega WhatsApp (✓✓/leído/fallo) | **GATE** — el connector escribe estas columnas |
| 2 | `20260704120000_f3_provision_tenant_audit` | Audit trail de provisión de tenant | No |
| 3 | `20260704130000_f7_offboarding_erasure_orphans_fk` | FK/erasure de huérfanos en offboarding | No |
| 4 | `20260704140000_tenant_media_bucket_rls` | RLS versionada bucket `tenant-media` | **Seguridad** — revisar policies manuales antes |
| 5 | `20260704150000_f2_conversations_contact_name` | Nombre de contacto denormalizado (Inbox lista/búsqueda) | No |
| 6 | `20260704150001_pii_access_log_list_view_nullable` | Log de acceso PII (contactos) | No |
| 7 | `20260704150002_shipment_tracking_events_rls_fix` | RLS del timeline de tracking | No |
| 8 | `20260704150100_shipping_orphan_quotes_pgcron` | Purga automática de cotizaciones huérfanas | No |
| 9 | `20260704153000_orders_channel_source` | Identidad canal/origen de pedido | No |
| 10 | `20260704153001_provider_health_drop_envia` | Retira Envia (shipping activo = Aveonline, ADR-0019) | No |
| 11 | `20260704153002_purchases_supplier_softdelete_fk_status` | Soft-delete proveedor + FK/estado OC | No |
| 12 | `20260704154000_ai_insights_cache_and_metrics_rpc` | Cache de insights IA + RPC de métricas exactas | No (feature-detect) |
| 13 | `20260704154001_audit_export_logging_rpc` | Registro del export CSV de auditoría (PII) | No |
| 14 | `20260704154100_audit_log_retention_policy` | Política de retención de `audit_log` | No |
| 15 | `20260704154200_expenses_reversal_and_integrity` | Anulación auditada de gastos + integridad P&L | No (feature-detect) |
| 16 | `20260704155000_f5_agentic_shadow_total_tokens` | Telemetría de costo LLM por turno | No (retry sin columna) |
| 17 | `20260704155100_reseed_kaiu_templates_tuteo_brand` | Re-seed plantillas HSM KAIU (tuteo + marca) | No (data seed) |
| 18 | `20260704155200_ai_agents_unique_tenant_role` | Único (tenant_id, role) para agentes | No (validación app-level) |
| 19 | `20260704155300_f5_provision_tenant_agentic_default` | Tenant nuevo nace con agente agentic default | No (aditivo) |
| 20 | `20260704156000_f6_payment_methods_closure_fix` | Fix cierre-de-cuenta (42703) + RLS write owner payment methods | **Recomendado** — el cierre de cuenta hoy falla sin esto |
| 21 | `20260704156010_f6_rls_role_hardening` | RLS por rol en `tenants` + `provider_health` | **Recomendado** (defensa en profundidad) |
| 22 | `20260704156020_f7_health_alert_dedup` | Dedup persistente de alertas de salud | No (fallback in-memory) |
| 23 | `20260704156200_f6_single_tenant_membership` | Único (user_id) — membresía single-tenant (ADR-0030) | **Recomendado** (ver §3) |
| 24 | `20260704156300_metrics_timeseries_and_indexes` | RPC de series por período (MoM) + índices | No (degrada a all-time) |
| 25 | `20260704156310_purchases_po_number_sequence` | Numeración humana OC-001 por tenant | No (fallback a UUID) |
| 26 | `20260704157100_offboarding_storage_erasure_purge` | Erasure purga Storage por prefijo (Ley 1581 Art.16) | **Compliance** — sin esto la erasure queda incompleta |

> **Nota (23):** aplicar 156200 requiere que NINGÚN usuario sea miembro de 2+ tenants. Su guard
> aborta con mensaje accionable si hay duplicados. `scripts/admin/provision_tenant.py` ya NO puede
> crear multi-membresía (`--allow-multi-tenant` hard-falla por ADR-0030).

---

## 2. Configuración externa (fuera del repo)

El **código** de cada punto ya está listo; falta la parte externa (DNS, keys, buzones, dashboards, legal).

### 2.1 Correo / Resend (emails transaccionales — hoy inertes)
- **RESEND_API_KEY + RESEND_FROM_EMAIL** en los 2 servicios Render (`api`, `ai-orchestrator`). El default
  `noreply@commerce-ops.local` es NO productivo a propósito. Sin esto, ningún email transaccional sale.
- **Verificar dominio remitente** (SPF/DKIM/DMARC en DNS) + subir el rate-limit (el default comparte
  remitente ~2–4 emails/h → cuello de botella al invitar varios seguidos).
- **Buzón `soporte@konvi.co`** (rescate ante lockout total de MFA): confirmar que existe en Cloudflare
  Email Routing y que **un humano lo monitorea**. Es el único canal de rescate. (El código ya usa `konvi.co`.)

### 2.2 DNS / hosts de webhook (ADR-0023 OQ-4)
- **`api.konvi.co`**: hoy el host live es `konvi-api.onrender.com`. Al provisionar el DNS, setear
  `NEXT_PUBLIC_WEBHOOK_HOST=https://api.konvi.co` y `WHATSAPP_CONNECTOR_URL` en `render.yaml`. Es un cambio
  de una línea; sin DNS, la URL de webhook per-tenant que muestra el panel no es servible por ambos servicios.

### 2.3 Supabase dashboard (Auth)
- **Site URL + Redirect allow-list**: fijar la URL web productiva y agregar `/auth/callback` y `/auth/confirm`.
  Sin esto, los links de invite/recovery salen a `127.0.0.1:3000`.
- **Plantillas de email es-CO**: copiar `supabase/templates/*.html` en Authentication → Emails (si se gestiona por dashboard).
- **Custom SMTP** (si se adopta Resend como SMTP de Auth).

### 2.4 Proveedores / IA
- **GEMINI_API_KEY fuera del web** (`render.yaml`, servicio `web`): tras el fix de §4, los endpoints espejo
  `/api/v1/ai/*` YA funcionan en el servicio `api`. El cutover (apuntar el web al `api` y **retirar la key
  del bundle web**) es un cambio de infra/secret — tu decisión de cuándo. Reduce la superficie de exfiltración.
- **Credenciales DEMO Aveonline** (`demointegracion` / `demointegra2021`): confirmar si son la cuenta sandbox
  pública oficial (aceptable como placeholder) o removerlas de ambas superficies.

### 2.5 Meta / legal (Model B per-tenant, ADR-0023)
- **DPA tenant-Konvi** (custodia del `app_secret` de terceros, OQ-1): cláusula legal vinculante. La guía de
  onboarding ya lo referencia como prerequisito. Bloquea onboardear tenants externos en producción.
- **Lista canónica de buckets con PII** para la erasure (§1 #26): confirmar todos los bucket-ids con PII
  per-tenant además de `tenant-media` (el mecanismo ya es parametrizado; default seguro `['tenant-media']`).

---

## 3. Cambios de comportamiento introducidos por las decisiones — validar en UAT

Estos son cambios **intencionales** que alteran el runtime respecto al estado previo. Verificarlos con un operador real:

1. **Guardar Settings General ahora enruta por el API** (`PATCH /api/v1/settings/tenant`, fuente única con
   Pydantic + audit_log + rate-limit). Implica: (a) depende de que `CORE_API` esté arriba; (b) durante el
   grace-period de cierre de cuenta, editar settings queda **bloqueado por el gate de offboarding** (correcto,
   pero nuevo); (c) campos con patrón estricto (teléfono de tienda 10 dígitos, DANE 5 dígitos) validan al guardar.
2. **RLS por rol** (si aplicas 156010): un `operator` ya no puede `UPDATE tenants` ni leer el JSONB de
   `provider_health` vía PostgREST directo (defensa en profundidad; la UI ya lo gateaba).
3. **Membresía single-tenant** (ADR-0030): un usuario auth pertenece a un solo tenant. La CLI de provisión
   lo enforce siempre; el índice único (156200) lo sella a nivel DB.
4. **"Sugerir con IA" ahora invoca Gemini de verdad.** Antes, en producción, `/suggest` degradaba SIEMPRE
   (import roto — ver §4); ahora produce sugerencias reales con el cascade 3.x. Validar calidad/latencia.
5. **Telegram disconnect ahora revoca identity** (cierra hueco: un ex-operador conservaba autoridad de escalación).
6. **VALIDAR en doc oficial Gemini** (`ai.google.dev/gemini-api/docs/deprecations`): fechas de retiro de la
   familia 2.5 (2026-10-16) y equivalencias 3.1-flash-lite / 3.1-pro. El código usa IDs ya productivos del
   orchestrator; override por `GEMINI_SUGGEST_TIERS`.

---

## 4. Verificación adversarial (2026-07-04) — hallazgos y correcciones

10 targets de mayor riesgo revisados por agentes adversariales. **7 CLEAR**; 3 con hallazgo, los 3 corregidos
(commit `fix(verify)`):

- **[CONFIRMED/high] `/api/ai` + `/suggest` rotos en el servicio `api`.** Importaban `from orchestrator import`
  / `from llm_cascade import` — módulos que viven solo en `ai-orchestrator` → `ModuleNotFoundError` en runtime.
  Efecto **pre-existente**: "Sugerir con IA" degradaba siempre; el preview espejo daba 502.
  **Fix:** copia byte-equal `services/api/lib/llm_cascade.py` + cliente local `lib/gemini_client.py` (patrón
  `llm_embed`); 3 call sites migrados; test de paridad + guard anti-regresión.
- **[CONFIRMED/medium] `--allow-multi-tenant` contradecía ADR-0030** y podía bloquear el apply de 156200.
  **Fix:** el flag hard-falla; el guard de membresía single-tenant es incondicional.
- **[PLAUSIBLE/low] Dedup de alertas de salud se auto-deshabilitaba** de forma permanente tras un blip
  transitorio del RPC → tabla persistente stale. **Fix:** se reintenta el RPC cada ciclo; el fallback in-memory
  cubre solo el ciclo que falló.

---

## 5. Gate final — UAT del journey completo (requiere stack live)

El cierre 100% se sella con un UAT end-to-end con un **tenant fresco**:
provisión → primer login → configurar Telegram/notificaciones → primer template aprobado → salud en verde →
cliente por WhatsApp → pedido → pago Wompi → email → guía Aveonline → tracking → entregado → reclamo.

Requiere **levantar el stack** (como la validación de coherencia) — **intervención humana** para levantarlo;
yo conduzco el UAT analítico turn-a-turn (verificando bot vs DB) cuando esté arriba.
