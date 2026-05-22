# ADR-0019 — Pivote a Aveonline como provider primario de shipping (Envia como fallback)

**Estado:** PROPUESTO (pre-implementación rev. 107).
**Fecha:** 2026-05-21.
**Branch target:** `feat/rev107-aveonline-primary` (a crear post-aprobación founder).
**Punto de partida:** `phase-1-orchestrator-refactor` @ commit `acf2592` (Sem 1.3 cerrada).
**Documento maestro:** [`docs/research/aveonline-dossier.md`](../research/aveonline-dossier.md) (versión 101% — 2015 líneas).

## Contexto

El agentic orchestrator (ADR-0018) usa hoy Envia.com como provider de shipping vía `agentic/legacy_adapters.py::quote_shipping_for_cart`. En UAT real con conv `5cef2503` (2026-05-21) el tool falló con `ENVIA_NO_OPTIONS` — error opaco que el LLM no pudo recuperar y rompió experiencia cliente.

Investigación paralela del dossier Aveonline al 101% reveló:

1. **Aveonline soporta COD nativo** (Ecart Pay backbone) — elimina ~2 días-dev del plan H.2.4 + ledger propio + reconciliación de Envia.
2. **Más carriers Colombia integrados** (≥10 vs 6-8 Envia), incluyendo Mensajeros Urbanos last-mile.
3. **Diagnóstico de errores documentado** (`numbererror` -1 a -8 + 999) vs error codes parciales Envia.
4. **Rol legal explícito** como Encargado de tratamiento en contrato — reduce trabajo legal Habeas Data.
5. **Cliente Bancolombia gratis** — barrera onboarding más baja si tenant ya banquea con Bancolombia.

Score consolidado (dossier §21.6): **Aveonline 8.0/10 vs Envia 7.0/10**.

## Decisión

Pivotar a Aveonline como provider primario de shipping en rev. 107, **manteniendo Envia como fallback técnico** detrás de feature flag per-tenant. Estrategia: **strangler-fig adapter pluggable** dentro de `agentic/legacy_adapters.py` — el tool `QuoteShippingTool` no cambia su interface, el adapter routea según `tenant_shipping_provider_config.primary_provider`.

### Lo que CAMBIA (rev. 107)

**A. Runtime (cliente HTTP + adapters)**:

- Nuevo cliente `services/api/lib/clients/aveonline_client.py` (auth v1.0 + cotización + label + tracking + cancel + pickup + boomerang RMA).
- Adapter `quote_shipping_for_cart_aveonline` espejo del Envia adapter actual.
- Routing dinámico en `QuoteShippingTool.execute` por `tenant_shipping_provider_config.primary_provider`.
- Nueva tabla `tenant_shipping_provider_config` (migración Supabase) con `primary_provider`, `fallback_provider`, `enabled_carriers[]`, `cod_enabled`, `insurance_strategy`.

**B. Onboarding tenant (UI + auth + Vault)** — **revisión 2026-05-22 post-WARN founder UAT**:

La auth Aveonline v1.0 (dossier §2.1) requiere `usuario+clave` per-tenant. NO se puede cotizar sin credenciales del tenant. Esto NO era un "detalle de implementación" sino una fase explícita del plan. Se agregan O.1-O.5:

- **O.1** Schema: extender constraint `provider` en `tenant_integrations` para `'aveonline'` + RPC helper `get_aveonline_credentials(tenant_id)` (espejo `get_envia_api_key`).
- **O.2** UI `apps/web/app/dashboard/(settings-group)/integrations/aveonline/page.tsx` con tabs **Setup** (form usuario+password+versión auth+tiempoToken) + **Carriers** + **Capacidades** + **Tracking** — clon estructural del de Envia.
- **O.3** Server action `connectAveonline(formData)`: POST de prueba a `autenticarusuario.php`, si `status=ok` persiste `empresa_id + jwt_token + jwt_expires_at + meta` en `tenant_integrations`, password → Vault (`aveonline_password_<tenant_id>`).
- **O.4** `AveonlineClient._refresh_jwt(tenant_id)` lee Vault, invoca auth endpoint, cachea JWT con TTL según `tiempoToken` (v1.0) o 12h fijo (v2.0). Auto-refresh con buffer 10min antes de expirar.
- **O.5** Migración `tenant_provider_identity` aceptar `provider='aveonline'` registrando `empresa_id` como `provider_internal_id`.

**C. Patrón replicado del repo existente** — no inventar nada:

- Wompi, Envia, WhatsApp, MercadoLibre y Telegram ya tienen este flujo (UI + server action + Vault + tenant_integrations + tenant_provider_identity).
- Vault setup migración base: `20260426020000_vault_setup_and_migration.sql`.
- Identity registry migración base: `20260514100000_tenant_provider_identity.sql`.

### Esfuerzo revisado

- Runtime (M.1-M.8): **8 días-dev**.
- Onboarding (O.1-O.5): **2.25 días-dev**.
- **Total: 10.25 días-dev** (~2.5 semanas calendario).

El plan original mencionó 8d pero subestimó O.1-O.5. La revisión 2026-05-22 corrige esto sin inventar — siguiendo el patrón del repo para los 5 providers ya integrados.

### Lo que NO cambia

- Cart-as-SoT (ADR-0011) — el adapter retorna la misma forma de dict que Envia.
- System prompt — el LLM sigue invocando `quote_shipping(city="...")` sin saber qué provider hay debajo.
- Invariantes Python (consent, resumen-before-link, no-emoji) — siguen aplicando idéntico.
- Wompi lifecycle — el payment_link se genera después de `select_carrier`, ajeno al provider de cotización.
- Tools agentic registrados — NO se agregan tools dedicados Aveonline (preserva abstracción provider-agnostic).

### Modelo de cutover

1. **Sem 0 (post-aprobación ADR)**: branch `feat/rev107-aveonline-primary` creada.
2. **Sem 1**: M.1-M.5 implementados, seed `tenant_shipping_provider_config.primary_provider='envia'` por defecto (sin cambio de comportamiento).
3. **Sem 1**: UI permite a tenants pilotos cambiar a Aveonline manualmente.
4. **Sem 2-3**: 3-5 tenants pilotos en Aveonline + Envia fallback durante ≥30 días.
5. **Sem 4 (si métricas §25.6 OK)**: default tenants nuevos cambia a Aveonline + Envia fallback.
6. **Sem 6**: ofrecer mass-flip a tenants existentes con onboarding concierge.

### Métricas de éxito (cierre rev. 107)

Documentadas exhaustivamente en dossier §25.6:
- ≥3 tenants piloto activos ≥30 días con Aveonline primary.
- Quote success rate ≥98% per tenant.
- P95 latency ≤8s sostenido.
- Fallback to Envia ≤2% rate.
- Webhook delivery ≥99%.
- 0 cobros duplicados por idempotency rota.
- COD reconciliation 100% (scraping o manual) últimos 30 días.

### Rollback plan

UI Tenant Console → "Provider principal" cambiar a `Envia` (un click, sin deploy). O SQL único `UPDATE tenant_shipping_provider_config SET primary_provider='envia';` global.

Triggers de rollback definidos en dossier §22.4: quote success <90% sostenido 1h, circuit abierto >30 min, fraude COD detectado, cobro doble cliente.

## Consecuencias

### Positivas

- **Bug `5cef2503` resuelto estructuralmente**: errores Aveonline son tipados (`numbererror` -1 a -8), el LLM puede componer mensajes específicos al cliente en lugar del opaco "no opciones".
- **COD nativo ya** sin esperar 2 días-dev H.2.4 Envia.
- **Cobertura carriers Colombia más amplia** mejora UX tenants en ciudades intermedias.
- **Compliance Habeas Data más claro** (rol Encargado explícito).
- **Onboarding cliente Bancolombia gratis** baja fricción comercial.

### Negativas

- **Onboarding Aveonline más lento** que Envia (requiere contrato + asesor + plan mensual). Mitigación: script `scripts/aveonline_onboarding.py` + soporte concierge primeros 10 tenants.
- **Latencia ligeramente peor** (Aveonline P95 ~8s vs Envia ~3-5s single-carrier). Mitigación: cache L1 60s + L2 5 min + warm-up cron nocturno.
- **Sin SLA 24/7 de Aveonline** (solo L-V 8-5). Mitigación parcial: circuit breaker + fallback a Envia automático.
- **Sin endpoint API histórico COD** (§7.5) — workaround scraping autenticado o reporte manual hasta que Aveonline expongan.

### Validaciones humanas obligatorias antes de prod (dossier §25.5 H1-H10)

- **H1 Bloqueante**: SLA contractual respuesta P0/P1/P2 + canal escalación nocturno (`asesorlogistico` per tenant).
- **H8 Bloqueante**: revisión legal contrato DPA Aveonline (Habeas Data §15.4).
- **H9 Bloqueante per-tenant**: firma contrato + selección plan mensual.
- **H2, H4, H5**: escalación a `desarrollo1@aveonline.co` (no bloquean prod — mitigaciones tácticas ya documentadas).

## Implementación detallada

Ver dossier:
- [§22 Plan de migración Envia → Aveonline](../research/aveonline-dossier.md#22-plan-de-migración-envia--aveonline-rev-106--rev-107) (8 días-dev, M.1-M.8).
- [§23 Bug `5cef2503` + resolución](../research/aveonline-dossier.md#23-bug-5cef2503).
- [§24 Integración tool agentic](../research/aveonline-dossier.md#24-integración-aveonline-en-agentic).
- [§25 Runbook operacional](../research/aveonline-dossier.md#25-runbook-operacional-aveonline-errores--acciones).

## Pendientes para activación

1. Aprobación founder de este ADR (firma + estado → ACTIVO).
2. Creación branch `feat/rev107-aveonline-primary`.
3. Ejecutar §22.1 M.1-M.8 secuencialmente con tests + UAT per fase.
4. Cerrar validaciones humanas H1, H8, H9 antes de cutover a primer tenant prod.

## Referencias

- Dossier maestro: [`docs/research/aveonline-dossier.md`](../research/aveonline-dossier.md) (versión 101%, 2015 líneas, 23+ fuentes oficiales).
- ADR-0011 — Payment Link Lifecycle (preservado sin cambios).
- ADR-0018 — Agentic Orchestrator Hybrid (provider-agnostic preservation).
- Plan estratégico Sección H — Hardening integraciones (este ADR sustituye la sub-sección H.2 Envia en parte).
- Bug runtime conv `5cef2503` (UAT 2026-05-21, founder).
