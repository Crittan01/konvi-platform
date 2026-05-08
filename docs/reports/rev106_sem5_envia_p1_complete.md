# Rev. 106 — Cierre Sem 5 (Envia P1 productivo + Cupones I.2 + GUI consistency)

**Branch**: `phase-0-pre-prod` (sin commits a `main`/`develop` — constraint vivo).
**Fechas sesiones**: 2026-05-05 → 2026-05-08.
**Estado**: Sem 5 del roadmap K cerrado. **47 commits** desde 2026-05-04, 17 migraciones aplicadas a remote, suite **1867 tests verde**, 0 bugs alta severidad abiertos.

---

## 1. Resumen ejecutivo

| Métrica | Inicio Sem 5 | Fin Sem 5 | Δ |
|---|---|---|---|
| Tests unit | 1414 ✓ | **1867 ✓** | +453 |
| Migraciones aplicadas remote | — | 17 nuevas | — |
| Items roadmap K cerrados | F.1-F.4 | F.1-F.12 + H.2 + I.2 + RLS + Perf | +28 |
| Bugs runtime alta severidad | 0 | 0 | = |
| Branch `phase-0-pre-prod` commits | 60 | 107 | +47 |
| Dossiers persistidos | 9 | 9 + 4 evidencias empíricas | +4 JSON |
| ADRs nuevos | — | ADR-0015 cupones | +1 |

**Veredicto**: Sem 5 del plan K (F.* framework + H.2 Envia P1 + I.2 cupones esencial) cerrado al 100%. **Sem 6 (cupones)** del plan original quedó **adelantada e integrada** en Sem 5 — el founder priorizó cupones como P1 esencial MVP y se ejecutó en paralelo. Pendientes próximos: Sem 6 framework común reuso (D.X) + Sem 7 WhatsApp HSM + MeLi.

---

## 2. Items ejecutados (por bloque)

### 2.1 H.2 — Envia P1 productivo Colombia (Sem 5 core)

| Item | Commit | Resultado |
|---|---|---|
| **H.2.1** Idempotency local pre-`/ship/generate/` | `e4ed060` | EnviaClient opt-in con `outbound_idempotency_cache` (F.5/MA-1) |
| **H.2.2** Webhook Envia HMAC propio | `08ff0a1` + `f4af0e3` + `b53d5bb` + `e207ee2` | Capture endpoint + Fase A (auth bug fix + captura empírica) + Fase B (procesador con schema empírico) |
| **H.2.3** Polling tracking backup | `684a0d9` | Cron 6h diff vs webhook (MA-9 universal pattern) |
| **H.2.4** COD Cash-on-Delivery | `e81c9ac` + `3b71081` + `66e645b` + `5745c64` | **PAUSADO** formalmente — V.1+V.4 no certificables empíricamente. Todo código asociado (back+front+DB) eliminado. Dossiers Envia + Ecart Pay preservados como referencia futura. |
| **H.2.5 v2** Insurance carrier-aware | `97a7538` | **Reescrito** post-investigación dossier Queries API + empírico prod. `envia_insurance` (id=125) solo aplica a `carrier="envia"` propio; `declaredValue` siempre. Drop `tenant_carriers.supports_insurance`. |
| **H.2.6** Capabilities Fase 2 per-tenant | `a85cd11` | UI granular toggles + RLS fix posterior `c19ee22` (FOR ALL en lugar de FOR SELECT) |
| **H.2.7** Carriers per-tenant matrix | `3513545` + `7c3621a` | Tabla `tenant_carriers` + UI Settings sección jerárquica |
| **H.2.8** Smoke E2E sandbox Envia | `b37cafd` | Script `scripts/uat/smoke_envia_sandbox.py` rate→generate→track→cancel paridad |

### 2.2 H.3 — Wompi resilience (Sem 4 P0 cerrados en Sem 5)

| Item | Commit | Resultado |
|---|---|---|
| **H.3.1** GET transaction sync+async | `0139b5e` | Auditoría sin webhook |
| **H.3.2** Retry + circuit breaker wrappers | `7f1afd6` | Resilience pattern reusa F.2 |

### 2.3 H.4 — WhatsApp opt-out (Sem 4 P0)

| Item | Commit | Resultado |
|---|---|---|
| **H.4.1** STOP keyword detector + soft opt-out | `9432d2d` + `957dc15` + `ced14ec` + `2356403` + `d1fae6b` + `3d194a6` + `38b8f50` + `3ac9cbd` + `a594cd0` + `4cab76c` + `293d1cd` + `3418153` + `9ac2853` | CHECK constraint conversations.status='opted_out', frontend Inbox conoce status, audit log, fix #5 persistir outbound STOP, fix #6 whitelist, BUG-105-02 reportado, Op-A.2 mark_conversation_opted_out, reactivar consent UI + endpoint, owner-only + tooltip, sync conversation back to bot_active |

### 2.4 I.2 — Cupones engine completo (P1 esencial MVP)

| Item | Commit | Resultado |
|---|---|---|
| **I.2.1** DB schema + helpers + ADR-0015 | `05b11b8` | `coupons` + `coupon_redemptions` con RLS |
| **I.2.2** Detector pre-LLM + dispatch | `f4bc09d` + `a83f87c` (UAT S43-S47) | "tengo el cupón XXX" → engine determinístico. **10/10 PASS dual-mode** |
| **I.2.3** Cart events extend | `3517e47` | `coupon_applied/revoked/consumed` |
| **I.2.4 + I.2.7 + I.2.9** Lifecycle completo | `8d2d55c` | Recompute cart total + resumen "Descuento aplicado: -$X (CÓDIGO)" + release on cancel |
| **I.2.8** UI Settings → Promociones CRUD | `8cf160e` + `ab06441` (DELETE condicional Habeas Data) + `1cba290` (UX tooltips) | Owner/manager admin coupons. Hard-delete blocked si has_historical_redemptions. |

### 2.5 F.* Framework común (Sem 2 — pre-requisito de TODO)

| Item | Commit | Resultado |
|---|---|---|
| **F.1** Webhook framework genérico | `1aa7ccc` | BaseWebhookHandler reutilizable |
| **F.2** IntegrationClient base + retry+CB+idempotency | `6aca128` | MA-1 idempotency baseline universal |
| **F.3** tenant_provider_capabilities matrix | `a60e2e3` | Runtime gating per-(tenant, provider, capability) |
| **F.4** webhook_events_seen genérica + RPC | `05f7417` | Dedup at-least-once universal |
| **F.9** Compliance decoradores 7+ | `62cd778` | Habeas Data + Meta 24h + scoped_to_country + audit_data_access + más |
| **F.10** WebhookSecretManager rotación trimestral | `85394b7` | MA-2 rotación per-tenant per-integration |
| **F.11** TenantCredentialsFacade + audit | `4d24f1e` | MA-3 unifica 9 esquemas auth Vault |
| **F.12** tenant_provider_identity registry | `b0a737f` | MA-10 cross-mapping + Telegram bug fix |

### 2.6 Hardening DB + seguridad

| Migración | Propósito |
|---|---|
| `20260514100000` → `20260514190000` (10 archivos) | Framework común DB |
| `20260515000000_coupons.sql` | Cupones core |
| `20260516000000_coupon_release_on_cart_terminal.sql` | Lifecycle release |
| `20260517000000_tenant_carriers.sql` | Per-tenant carriers |
| `20260518000000_fix_consent_view_security_invoker.sql` | **CVE potencial Habeas Data**: `vw_consent_events_unified` ahora `WITH (security_invoker=true)`. SECURITY DEFINER permitía cross-tenant reads vía RLS bypass. Fix `7349dbc`. |
| `20260519000000_drop_cod_columns.sql` | Cleanup post-pausa COD |
| `20260520000000_fix_capabilities_rls_for_all.sql` | RLS bug: policy `FOR SELECT` con `current_setting()` rompía UPSERT desde JWT user. Cambio a `FOR ALL` con `app_current_tenant()`. |
| `20260521000000_drop_supports_insurance.sql` | Cleanup post-H.2.5 v2 |

### 2.7 Performance VM local

| Item | Commit | Impacto |
|---|---|---|
| Turbopack en `next dev --turbo` | `30a631d` | Compile 4x más rápido |
| `React.cache(getUser/getTenantMeta)` | `03b1a4c` | Deduplica `auth.getUser` 13 server pages → 1 call/request |
| `compress: true` en next.config | `7cfb0a2` | Bundle dev 6.5MB→1.8MB sobre SSH tunnel |

### 2.8 GUI consistency (rev. 2026-05-08)

| Item | Commit | Razón |
|---|---|---|
| Tabla rates Conectores: badge Envia color brand orange | `6e242db` | Único provider sin coincidir con su color (founder feedback) |
| Spinner toggles ON/OFF carriers + capabilities | `6e242db` | Sin feedback visible durante async |
| Paneles "¿Cómo funciona?" carriers consolidados (2→1 verde) + capabilities azul→verde | `f6a725f` | Founder: "no 2 separados, agruparlos" |
| Promociones page header alineado al patrón (`text-foreground`/`text-primary`) | `f6a725f` | 20 refs hardcoded slate → 0; theme variables consistentes con resto del dashboard |

---

## 3. Decisiones arquitectónicas registradas

### 3.1 H.2.5 v2 — Insurance carrier-aware (NO opt-in tenant)

**Disparador founder**: "no sería conveniente validar cuáles requieren seguro o no? Más allá de eso, dejar funcional a la realidad de cómo funciona acorde a la transportadora".

**Investigación**:
- Empírico sandbox single-route (10 carriers, BOG→MDE).
- Empírico sandbox multi-route (BOG→MDE/BOG/CLO/MDE→BOG).
- Empírico **prod** para los 5 no certificables en sandbox (Coordinadora, interRapidisimo, envia, tcc, deprisa).
- Documental: `GET https://queries-test.envia.com/additional-services` (catálogo OFICIAL de 170+ servicios).

**Hallazgos definitorios**:
- `envia_insurance` (id=125, "Seguro Envía") es del **carrier propio Envia** únicamente. Coordinadora con `additional_services:["envia_insurance"]` + valor alto → **Bad Gateway**.
- `carrier_insurance` **NO existe** en docs oficiales — el identifier real es `insurance` (id=52, "Insurance (Carrier)"). Dossier corregido.
- Coordinadora aplica prima automática sobre `declaredValue` ($50k=$17.270 vs $3M=$18.850, Δ +$1.580 sin pedirlo).

**Decisión**:
1. `declaredValue` se envía SIEMPRE en cada package (campo de paquete, NO opt-in).
2. `additional_services:["envia_insurance"]` SOLO si `carrier == "envia"`.
3. Drop `tenant_carriers.supports_insurance` (abstracción errada).
4. UI carriers: removida columna "Seguro" + panel informativo verde explicando comportamiento real.

**Evidencia persistida**:
- `docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07.json` (sandbox single-route)
- `docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-v2.json` (sandbox multi-route)
- `docs/research/empirical-evidence/envia-insurance-carriers-CO-2026-05-07-PROD.json` (prod, 5 carriers no-sandbox)
- `docs/research/empirical-evidence/envia-additional-services-queries-api-2026-05-08.json` (catálogo oficial completo)
- `docs/research/envia-dossier-2026-05-05.md` sec. 2.5 + L.10 corregidas 2026-05-08

### 3.2 H.2.4 COD Pausado formalmente

**Disparador founder**: "ajusta desarrollo en general, sea back, front, db, midleware, etc, para que no haya nada asociado a COD nada!" (tras V.1 + V.4 no certificables sólo a voz del ejecutivo Envia).

**Decisión**: aplicar regla "no suposiciones — solo data verificable". Backend/frontend/DB completamente limpio. Dossiers `envia-dossier-2026-05-05.md` (sec. L.10-L.12) + `ecartpay-dossier-2026-05-07.md` preservados como referencia para reactivación futura cuando KAIU complete Ecart Pay Colombia KYC + V.4 confirme por contrato escrito.

### 3.3 ADR-0015 Cupones engine

Nuevo ADR consolidando 12 decisiones (D1-D12) sobre engine:
- D1: Schema con discount_type ENUM + min_subtotal_cents + max_redemptions
- D6: Hard-delete condicional (solo si `coupon_redemptions` count = 0) por preservación Habeas Data Ley 1581 Art. 4 + 9
- D10: UI Settings → Promociones owner/manager
- Resto en `docs/adr/0015-coupon-engine.md`

---

## 4. Verification

### 4.1 Suite tests
```
1867 tests collected, 0 failures, 0 errors.
```
- Cobertura código orchestrator: ≥70% (target J.5).
- Tests nuevos Sem 5: +453 (insurance helper, cupones engine, capabilities matrix, tenant_carriers, F.* framework, opt-out detector, etc.).

### 4.2 UAT scenarios
- **S27 + S28** (cart-as-SoT subtotal multi-unit + modificación add-category): PASS dual-mode.
- **S43-S47** (cupones lifecycle): 10/10 PASS dual-mode.
- **S10-S25** (UAT residual del plan rev. 103): aún pendientes — bloqueante constraint operacional vivo para PR a `main`.

### 4.3 Validate.sh
```
✅ 13 OK  |  ❌ 0 ERROR  |  ⚠️  0 WARN
```

### 4.4 DB remote (Supabase)
- 17 migraciones aplicadas con protocolo seguro (pre-checks → apply → post-check → ledger repair).
- 0 data loss en migraciones DROP (`supports_insurance`, `cod columns`).
- Ledger sincronizado hasta `20260521000000`.

### 4.5 Smoke manual (founder confirmó 5/5 OK 2026-05-07)
- Color Envia naranja ✓
- Sin columna "Seguro" en carriers ✓
- Panel "¿Cómo funciona el seguro?" verde renderiza ✓
- Spinner toggles funcional ✓
- Sin RLS error en capabilities toggle ✓

---

## 5. Lo que NO se hizo (explícito)

| Item | Razón |
|---|---|
| H.2.4 COD producción | V.1 (Ecart Pay terms) + V.4 (políticas legal) no certificables — pausado formalmente |
| `carrier_insurance` additional_service | NO existe en catálogo oficial Envia (corregido en dossier) |
| `_is_envia_own_carrier` lookup empírico de carriers que rechazan envia_insurance | Cubierto: solo carrier="envia" recibe el additional_service. Resto solo declaredValue. |
| MFA owner/manager (J.2.4.3) | Sem 10 del plan K |
| Penetration testing (J.2.4.6) | Sem 14 — externo |

---

## 6. Próximas prioridades (post-rev106)

Por orden recomendado al founder y aceptado:

### 6.1 Sem 6 (siguiente) — Re-uso framework común para HSM templates

Pre-requisito de F2 WhatsApp HSM templates: validar que `IntegrationClient` base (F.2) + `WebhookHandler` (F.1) cubren el caso Meta Cloud API. Si gaps emergen, completarlos antes de iniciar HSM. Estimado ~2-3 días.

### 6.2 Sem 7-8 — F2 WhatsApp HSM templates

Trigger comercial: 10 tenants en cola de integración Platform Console; 6 de 10 requieren proactivos fuera CSW (`payment_reminder_v1`, `cart_abandonment_v1`, etc.). Specs Meta verificadas en `04-next-steps.md` + dossier `whatsapp-meta-dossier-2026-05-05.md`. Estimado ~11 días-dev.

### 6.3 UAT residual S10-S25 dual-mode

Bloqueante constraint operacional vivo del plan K para PR `phase-0-pre-prod` → `develop` → `main`. Paralelizable con 6.1/6.2 entre items. Estimado 3-5 días.

### 6.4 Sem 9 — H.5 MeLi Q&A + messages

Tras HSM. Estimado ~5 días.

---

## 7. Constraint operacional vivo

> **NO commits a `main` ni `develop`** hasta cumplir los criterios `J.5 ≥95%` del plan maestro:
>
> - UAT S1-S49 dual-mode (~98 corridas) → 100% PASS supported.
> - Bugs alta severidad → 0 (✅ cumplido).
> - Suite tests → ≥1100 verde, 0 flaky (✅ 1867 verde).
> - Penetration test OWASP top 10 ejecutado.
> - DPO designado + revisión legal final DPA + Privacy.
> - Migrar Render Free → Starter ($28/mo).
>
> Trabajo continúa en `phase-0-pre-prod`. Cierre Fase 1 = Sem 14 del plan K.

---

**Punto de referencia estable**: `f6a725f` (cierre rev. 106).
**Branch viva**: `phase-0-pre-prod` (107 commits ahead of `develop`).
**Próxima sesión**: leer este reporte + `.context/04-next-steps.md` actualizado + `docs/research/whatsapp-meta-dossier-2026-05-05.md` antes de tocar HSM.
