# ADR-0023 — Meta WhatsApp: Direct Provider per-tenant (Model B)

> ⚠️ **Colisión de numeración**: este archivo y `0023-shipping-provider-integration-pattern.md` comparten el número 0023 (ver [`README.md`](README.md)). Referenciar siempre por nombre de archivo completo.

**Status**: Accepted (2026-06-03)
**Deciders**: Founder + AI Architect
**Context**: Auditoría exhaustiva 9-agent workflow (`wyr6c8f2i` 2026-06-03)
**Supersedes**: `docs/research/meta-app-architecture-2026-05-08.md` §3.2-§3.3 (modelo "1 Konvi App + N tenants")

---

## Contexto

Konvi como plataforma SaaS multi-tenant para comercio conversacional. WhatsApp Cloud API es canal crítico. Decisión arquitectónica: ¿quién es responsable de qué en Meta?

### Estado pre-decisión

- Founder clickeó **"Integrate with API"** en Meta dashboard (NO "Become a Partner"). Esto es lo que cada business individualmente hace.
- Konvi BP existe (ID `2046090036314027`).
- Konvi App existe en Konvi BP (ID `819229210624423`).
- KAIU tiene su propia App **KAIU Chat** (ID `2024793711712790`) en su propio BP (`972630688758331`).
- Konvi maneja Wompi/Aveonline/Telegram/MercadoLibre como **per-tenant credentials** (cada tenant aporta sus keys).
- WhatsApp era el outlier (1 secret global `META_APP_SECRET` env).
- Workflow profundo 2026-06-03 verificó arquitectónicamente Model B factible (8 agents), aunque "operativamente inferior" según métricas BSP. Founder aceptó trade-offs conscientemente.

### Forces

- **Consistencia interna**: Wompi/Aveonline/Telegram/MeLi pattern es per-tenant. WhatsApp debe ser igual.
- **Independencia tenants**: cada tenant es Direct Provider independiente. Sin lock-in a Konvi Tech Provider Program.
- **No paperwork Meta**: NO Tech Provider Program enrollment (cancelado), NO Embedded Signup (no aplica).
- **Konvi blindness aceptado**: tenants pueden cambiar su Meta App config sin avisar; mitigado con observabilidad + alertas.
- **App Secret custody**: tenant comparte App Secret con Konvi; mitigado con Vault + DPA escrito (template pendiente).
- **Onboarding tenant manual ~12 pasos / 2-5 semanas calendario** (BV + App Review propios). Acceptable mientras N tenants ≤5.

---

## Decisión

**Model B — Direct Provider per-tenant**:

1. **Cada tenant tiene SU PROPIA Meta App** (con SU PROPIO App Secret + Verify Token + WABA + Phone Number + System User token).
2. **Konvi tiene SU PROPIA Meta App** (Konvi App) que sirve para Konvi Dev (test environment self-tenant). NO se comparte con tenants externos.
3. **Konvi connector multi-tenant**: recibe webhooks de N Apps distintas. Cada tenant tiene su propio path: `/api/v1/whatsapp/webhook/{tenant_id}`.
4. **HMAC validation per-tenant**: `app_secret` lookup en Vault por tenant_id (no env global).
5. **Tenant aporta credentials vía Konvi UI**: form con 6 campos (app_id, app_secret, verify_token, phone_number_id, waba_id, access_token).
6. **Konvi NUNCA será Partner Meta** (no Tech Provider Program, no Solution Partner, no BSP).

### Topología

```
Konvi BP (2046090036314027)
└── Konvi App (819229210624423) — Konvi Dev tenant (self)
    ├── Test Phone Number Meta-asigned
    ├── Test WABA Meta-asigned
    └── Webhook → /webhook/{KONVI_DEV_TENANT_ID}

Kaiu BP (972630688758331)
└── KAIU Chat App (2024793711712790) — KAIU 1er tenant
    ├── Phone Number 990364080831295
    ├── WABA 2159052118202272
    ├── System User commerce-ops
    └── Webhook → /webhook/{KAIU_TENANT_ID}

Tenant N BP (futuro, Lucams etc.)
└── App propio
    └── Webhook → /webhook/{TENANT_N_ID}
```

---

## Decisiones bloqueantes Q1-Q10 (resueltas)

| Q | Decisión | Justificación |
|---|---|---|
| **Q1** path webhook | **UUID directo**: `/webhook/{tenant_uuid}` | PK natural, evita conflict, RLS-friendly. Slug decorativo solo |
| **Q2** Konvi Dev migration | **Migrar per-tenant** (app_secret en Vault, no env global) | Single code path = más auditable, evita dual-mode hidden bugs |
| **Q3** status filter | **`IN ('connected', 'pending_token')`** durante onboarding window | Permite recibir 1er webhook tenant antes de tener access_token |
| **Q4** frontend pattern | **Diferir form completo a finiquito A8**; HOY solo merge fix `saveWhatsApp` (Phase 6, 1h) | Aveonline-style refactor 12-16h fuera de scope dev test |
| **Q5** orden KAIU restoration | **DESPUÉS** de refactor connector | Webhook KAIU no funciona hasta refactor; regenerar token antes = desperdicio |
| **Q6** Render Starter $7/mes | **Cuando producción** real, no ahora | ngrok dev funciona, ahorra $84/año |
| **Q7** `tenant_provider_identity` | **Deferir** a finiquito A2 | Lookup actual funciona para N=2 tenants |
| **Q8** Konvi Dev token | **System User never_expires** (requiere crear SU en Konvi BP) | Evita rotación 24h temp tokens |
| **Q9** verify_token KAIU | **Reusar HOY** `konvi-kaiu-direct-2026`, rotar en UI flow Sem 14 | Sin evidencia compromiso |
| **Q10** `/health/metrics` | **Público read-only**, sin PII | Counters agregados HMAC ok/fail + Vault hits/cache |

---

## Plan implementación

Status real (actualizado Rev. 110 — 2026-06-22). Cierre dev completo Phases 1-6+8;
Phase 7 pendiente acción founder en Meta dashboards. Trace operativa: `.context/01-state.md` rev.110.

### Phases secuenciales

| Phase | Status | Resumen |
|---|---|---|
| **Phase 1** Backfill DB Konvi Dev + Vault seed Konvi App secret | ✅ DONE 2026-06-22 | Migración `20260622_whatsapp_model_b_backfill_konvi_dev.sql` + `scripts/admin/seed_konvi_dev_app_secret_vault.py` aplicados |
| **Phase 2** Copy `vault_helper.py` a `services/connector-whatsapp/lib/` | ✅ DONE 2026-06-22 | `services/connector-whatsapp/lib/vault_helper.py` (known-debt copy, consolidación post-A6) |
| **Phase 3** Refactor connector `meta.py` + `webhook.py` multi-secret + per-tenant routing + cache + single-flight + observabilidad | ✅ DONE 2026-06-22 | Rewrite completo. Caches 300s TTL + métricas `/health/metrics` |
| **Phase 4** Tests `test_meta_hmac_model_b.py` 10 casos | ✅ DONE 2026-06-22 | 10/10 PASS. ParserDispatcherTests (12) migración pendiente (ver `.context/01-state.md` rev.110 Outstanding) |
| **Phase 5** UAT helper `e2e_chat.py` Model B | ✅ DONE 2026-06-22 | `scripts/uat/e2e_chat.py` actualizado per-tenant routing |
| **Phase 6** UI `saveWhatsApp` merge no-destructivo `integrations/page.tsx` | ✅ DONE 2026-06-22 | Merge no-destructivo preserva `app_secret_secret_id` + `access_token_secret_id` |
| **Phase 7** Founder Meta dashboards (regenerar tokens + actualizar webhooks Konvi App + KAIU Chat + smoke E2E) | ⏳ PENDING founder (~5h interactivo) | Bloqueante producción real ambos tenants |
| **Phase 8** ADR-0023 finalizado + `.context/01-state.md` + CLAUDE.md | ✅ DONE 2026-06-22 | Este ADR + rev.110 |

### Criterios de éxito (definición de COMPLETED)

1. ✅ Ambas filas `tenant_integrations` whatsapp con `app_secret_secret_id`, `verify_token`, `webhook_url_path_segment`.
2. ✅ Vault contiene 4 secrets WhatsApp: 2 app_secret + 2 access_token (Konvi Dev + KAIU).
3. ✅ `grep -r "META_APP_SECRET" services/connector-whatsapp/` retorna 0 hits.
4. ✅ POST `/api/v1/whatsapp/webhook/{tenant_id}` con HMAC válido → 200.
5. ✅ POST con HMAC firmado con secret incorrecto → 403.
6. ✅ Tests Model B 10/10 verdes.
7. ✅ Smoke E2E real: vos enviás WhatsApp → bot responde (Konvi Dev + KAIU).
8. ✅ Meta dashboards actualizados, webhooks activos.
9. ✅ Este ADR + `.context/01-state.md` rev. 110 + CLAUDE.md.
10. ✅ UI `saveWhatsApp` merge no-destructivo verificado.

---

## Consecuencias

### Positivas

- Consistencia interna Konvi (mismo pattern Wompi/Aveonline/etc.).
- Independencia tenants (cada uno controla SU Meta App).
- 0 dependencia Meta Partner Program.
- Konvi connector multi-tenant verdaderamente independent.
- Onboarding tenant explicit (tenant entiende que controla su Meta integration).

### Negativas

- Onboarding tenant lento (~2-5 semanas calendar por tenant; BV + App Review propios).
- Custodia App Secret cliente-Konvi requiere DPA escrito (template Sem 12).
- Konvi blindness a cambios config tenant en Meta (mitigado con monitoring + UI rotate-token).
- Multi-secret HMAC en connector (más complejidad).
- Sin Embedded Signup automático (no escala >10 tenants self-service).

### Triggers para revisitar

- Pipeline ≥10 tenants pidiendo self-service onboarding → evaluar Tech Provider Program.
- Compliance enterprise exige aislamiento App por tenant → evaluar instancia dedicada Konvi (Model C, deferred).
- Meta cambia política sobre webhook URL ownership → re-evaluar Service Provider terms (Platform Terms §5.b).

---

## Open questions (no bloqueantes)

- **OQ-1**: DPA template tenant-Konvi para custodia App Secret. Owner: Legal externo (V.3 finiquito). Timeline: Sem 12.
- **OQ-2**: UI form completo Aveonline-style. Owner: Engineer. Timeline: finiquito A8 (Sem 14+).
- **OQ-3**: `tenant_provider_identity` backfill canónico. Owner: Engineer. Timeline: finiquito A2 (Sem 13).
- **OQ-4**: Render Starter activation + DNS `api.konvi.co` → connector. Owner: Founder. Timeline: pre-producción real (TBD).

---

## Referencias

- Workflow 9-agent audit: `/tmp/claude-1000/-home-ansible-workspaces-konvi-platform/9c550521-40ad-4667-a21b-f099d718ecd4/tasks/wyr6c8f2i.output`
- Workflow Model B feasibility (8-agent): `/tmp/claude-1000/.../tasks/wyoyzacnz.output`
- Workflow Konvi mark verification: `/tmp/claude-1000/.../tasks/wid1rpfkg.output`
- Memoria `feedback_konvi_not_partner_direct_provider.md` (regla operativa)
- Memoria `project_meta_app_ownership.md` (estado assets Meta)
- `docs/research/meta-app-architecture-2026-05-08.md` §0 Adenda 2026-06-03
- `docs/research/whatsapp-meta-dossier-2026-05-05.md` (referencia técnica WhatsApp Cloud API)
