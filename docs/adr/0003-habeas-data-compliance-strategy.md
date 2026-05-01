# ADR-0003: Estrategia de cumplimiento Habeas Data multi-tenant (rev. 93–99)

## 1. Status

**Accepted** · 2026-05-01 (rev. 93–99)
Próxima revisión: cuando la SIC emita guía nueva sobre IA generativa
en atención al cliente, o cuando se sume un tenant en sector altamente
regulado (financiero, salud, menores).

## 2. Context

### Detonante

Hasta rev. 92.e teníamos compliance parcial (consent capture, audit_log
genérico, anonimización al revocar). Auditoría reveló 11 gaps críticos:

1. No `consent_audit_log` dedicado → eventos consent mezclados con audit genérico.
2. No `pii_access_log` → no se registra quién accede a PII.
3. No SAR/ARCO endpoints → cliente no puede ejercer Arts. 14, 16, 19.
4. No notificación al tenant cuando cliente revoca por WhatsApp.
5. No retención automática de mensajes/conversaciones.
6. `document_number` y `phone` en plaintext.
7. No DPA/Privacy Policy/Subprocessor list.
8. No diferenciación Responsable vs Encargado.
9. Cliente no puede pedir SUS datos vía WhatsApp (Art. 14).
10. No PDF export de datos del contacto.
11. No notificación al titular post-revocación.

### Restricción

- Multi-tenant: la solución debe servir a cualquier vertical
  (cosmetics, tech, food, fashion). NO hardcodear KAIU.
- Costo operativo: Render free tier + Supabase free tier para arrancar.
- No romper checkout existente que ya consume `document_number` plaintext.

## 3. Decisión

Compliance Habeas Data como **property cross-cutting**, no ad-hoc por
feature. Implementación en 4 sprints incrementales (rev. 93 → 99) con
infra compartida que TODO el sistema reusa.

### Componentes core

| Componente | Tipo | Cubre |
|---|---|---|
| `consent_audit_log` | Tabla DB append-only + triggers UPDATE/DELETE bloqueados | Art. 9 |
| `pii_access_log` | Tabla DB | Art. 9 trazabilidad |
| `data_subject_request` endpoint | API REST | Arts. 14, 15, 16, 19 |
| Detector "envíame mis datos" | Pre-LLM determinístico | Art. 14 self-service |
| `notify_consent_revoked` / `notify_sar_received` | Email Resend | Art. 9 + transparencia |
| `retention_policies` + `fn_apply_retention` | Tabla + función SQL + pg_cron | Art. 4d / Art. 16 |
| `document_number_hash` + `_last4` | Migración aditiva + trigger | Art. 4 minimización |
| `tenant_legal_acceptance` | Tabla click-wrap | Auditabilidad DPA |
| `docs/legal/*` | Documentación | DPA, privacy, subproc, incident, roles |

### Decisiones específicas

#### D1 — Phone NO se cifra
**Razón:** path crítico WhatsApp lookup. Cifrar rompe S5/S6/S8/S9
flujos. Mitigación: phone_hash en logs (consent_audit_log,
pii_access_log) reemplaza al phone para correlación.

#### D2 — Document_number tokenización aditiva, no destructiva
**Razón:** Wompi checkout ya consume el plaintext. Migración
destructiva rompería pagos. Aditivamos `_hash` + `_last4`. Migración a
Vault queda como follow-up cuando se justifique.

#### D3 — Audit logs append-only vía DB triggers
**Razón:** que ni siquiera service_role pueda alterar. Una respuesta
a SIC con audit modificable no es defendible.

#### D4 — pg_cron sólo para retention
**Razón:** Render free tier limita workers. pg_cron ya está disponible
en Supabase. EXCEPTION WHEN undefined_table cubre instancias locales
sin pg_cron.

#### D5 — Self-service vía WhatsApp NO incluye PDF en rev. 97
**Razón:** Meta document upload + storage de PDFs introduce surface
attack. v1 envía resumen text-only. Tenant Console SAR endpoint genera
JSON estructurado. PDF queda como follow-up.

#### D6 — Resend con fallback graceful sin RESEND_API_KEY
**Razón:** entornos local/CI sin credencial real. Notificaciones se
loguean (no fallan flujo). En producción la var es secret.

#### D7 — `tenant_id IS NULL` = default global en `retention_policies`
**Razón:** baja burden operacional (un default cubre todos los tenants).
Tenant puede override creando row con su `tenant_id`.

## 4. Consequences

### Positivas

- Tenant puede responder a SIC sin asistencia técnica
  (`/api/v1/contacts/{id}/data-subject-request` + `consent_audit_log`).
- Audit defensible legalmente (append-only, hash de phone).
- Retención automática elimina riesgo de "datos olvidados".
- Cliente final ejerce derechos por WhatsApp (UX directa).
- Documentación legal disponible para enterprise sales.
- Código vertical-agnostic (válido para todos los tenants).

### Negativas / trade-offs

- 8 nuevas tablas/columnas → más superficie a mantener.
- Triggers DB requieren disciplina en migraciones futuras.
- pg_cron en Render Free podría requerir fallback si la extensión
  no está disponible (mitigado con EXCEPTION).
- Resend free tier 100 emails/día → suficiente para notificaciones
  críticas, pero scale-out requiere paid tier ($20/mo).

## 5. Alternatives considered

### A1 — Compliance ad-hoc por feature (rechazada)
Cada feature implementa su propio audit. Resultado: drift, gaps,
respuesta lenta a SIC. Rechazada por inconsistencia.

### A2 — Hard-delete inmediato sin audit (rechazada)
Borrar PII al revocar y no guardar nada. Imposible probar a SIC que
hubo consent previo o cumplimiento de plazos. Rechazada por riesgo
legal.

### A3 — Cifrar phone con pgcrypto (rechazada en rev. 96)
Rompería WhatsApp lookup. Mitigado parcialmente con phone_hash en logs.
Reabierto si SIC lo exige explícitamente.

### A4 — Delegar SAR al tenant manualmente (rechazada)
Tenant gestiona SARs por correo / Excel. No escala, alta fricción,
respuesta a SIC depende de disciplina humana del tenant.

## 6. Verification

- 1065+ tests OK (unit + structural + coherence).
- Migraciones aplicables idempotentes (IF NOT EXISTS, ON CONFLICT).
- E2E manual scenarios (S8 revoke + nuevo S15 SAR).
- `bash scripts/validate.sh` 13/13 OK.

## 7. Open issues / follow-ups

Estado actualizado al cierre rev. 101:

- **F1** — ✅ DONE rev. 101: HTML imprimible server-side (`GET /api/v1/contacts/{id}/data-subject-request/printable`). Operador hace Cmd+P → Save as PDF. Cero deps nuevas. La opción WeasyPrint + Meta document upload queda parqueada para sprint dedicado cuando aparezca el caso de uso real (envío del reporte al titular vía WhatsApp document message — hoy se devuelve resumen text-only por chat).
- **F2** — ⛔ DEFERRED CONSCIENTE rev. 101. Tokenización completa de `document_number` con Vault. Razones:
  - Riesgo: el plaintext de `document_number` está consumido por el flujo de checkout Wompi. Migrar a Vault token requiere refactor del checkout + migración de datos productivos en una tabla viva. Históricamente las migraciones destructivas en path de pago han sido las que más downtime generan.
  - Valor incremental bajo: rev. 96 ya entregó `document_number_hash` (sha256) + `document_number_last4` aditivos. Los logs (`pii_access_log`, `consent_audit_log`) usan `phone_hash` y nunca exponen `document_number` plaintext. La mitigación de minimización Art. 4 ya está cubierta para el path read-mostly (queries operacionales pueden usar last4).
  - Trigger para reabrir F2: SIC exige cifrado-at-rest específico de identificadores nacionales, O hay un breach que demuestra que el plaintext es vector real, O un enterprise tenant lo pone como precondición de contrato.
- **F3** — ✅ DONE rev. 101: vista SQL `vw_consent_events_unified` que UNION `consent_audit_log` (canónico) + `audit_log` (legacy filtrado entity_type=contact + action consent/revoke/rectify/delete). NO hay migración de data — cada tabla mantiene su rol; la vista es el punto único para reportes SIC.
- **F4** — ✅ DONE rev. 101: UI Tenant Console en `/dashboard/settings/retention` permite override per-tenant de defaults globales con CRUD.
- **F5** — ✅ DONE rev. 101: endpoint `GET /api/v1/sic-report?format=json|csv` con period filter + opcional contact_id. Cada generación se audita en `consent_audit_log`.
- **F6** — ✅ DONE rev. 101: detector pre-LLM `_detect_rectification_intent` + handler que registra evento "rectified" pendiente de revisión + notifica al tenant.
- **F7** — ✅ DONE rev. 101: UI click-wrap en `/dashboard/settings/legal` con aceptación inmutable + histórico (versionada por documento).

## 8. References

- Ley 1581 de 2012 Colombia (Habeas Data).
- Decreto 1377 de 2013 (reglamentario).
- Circular Externa 002 de 2018 SIC (transferencia internacional).
- ADR-0002 (Meta Business Policy compliance).
- Plan rev. 93–99 (commit `1eea615` Sprint 1 inicial).
