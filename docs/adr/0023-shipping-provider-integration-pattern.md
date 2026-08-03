# ADR-0023 — Shipping Provider Integration Pattern (provider-agnostic playbook)

> ⚠️ **Colisión de numeración**: este archivo y `0023-meta-model-b-direct-provider-per-tenant.md` comparten el número 0023 (ver [`README.md`](README.md)). Referenciar siempre por nombre de archivo completo.

**Estado:** ACTIVO.
**Fecha:** 2026-05-30.
**Branch origen:** `feat/remove-envia-pivot-aveonline`.
**Supersede contexto:** ADR-0019 (Aveonline as primary, alternativa a Envia).

## Contexto

Konvi pivotó de Envia a Aveonline como provider único de shipping en
rev. 109 (ADR-0019). El refactor incluyó la **eliminación completa** del
código y configuración Envia del runtime, manteniendo la arquitectura
**pluggable** para agregar futuros couriers sin re-arquitectar.

Este ADR codifica formalmente el **playbook** para añadir Courier N+1
(Venndelo, Servientrega Directo, DHL eCommerce, etc.) reutilizando la
infraestructura provider-agnostic ya implementada.

Para auditoría del pivote Envia → Aveonline, ver tag git
`archive/envia-investigacion-rev106-2026-05-08` que preserva el dossier
de investigación completo.

## Decisión

Cuando se agregue un nuevo shipping provider:

### 1. Cliente HTTP por provider

Crear `services/api/integrations/{provider}_client.py` extendiendo
`IntegrationClient` (ABC) con:

- Auth schema propio (`get_auth_headers()`)
- Base URL (`get_base_url()`)
- Validación de response (`validate_response()`) si el provider tiene
  semánticas como Envia `meta="error"` HTTP 200 o Aveonline
  `numbererror < 0`.
- Vault pattern para credenciales: `<tenant_id>/{provider}/<credential_name>`

Espejo runtime en `services/ai-orchestrator/integrations/{provider}_client.py`
(o factorizar a shared lib si crece).

### 2. Adapter agentic legacy

Crear `services/ai-orchestrator/agentic/legacy_adapters/{provider}.py`
implementando `quote_shipping_for_cart` con la interfaz dict-returning
provider-agnostic (idéntica al adapter Aveonline existente).

Registrar en `agentic/legacy_adapters/__init__.py` exportando la función
canónica. NO crear nuevo tool agentic — el LLM usa siempre
`quote_shipping_for_cart` y el routing lo hace `tools/shipping.py` por
`tenant_shipping_provider_config.active_provider`.

### 3. Frameworks provider-agnostic (NO modificar — agregar entries)

Agregar el nuevo provider como string canónico (snake_case lowercase) a:

| Frozenset / dict | Archivo |
|---|---|
| `VALID_PROVIDERS` | `services/api/lib/tenant_carriers.py` (×2: api + ai-orchestrator) |
| `CAPABILITIES_BY_PROVIDER` (catálogo per-provider) | `services/api/lib/capabilities_matrix.py` |
| `SUPPORTED_INTEGRATIONS` | `services/api/lib/webhook_secret_manager.py` + `webhook_dedup.py` |
| `SUPPORTED_PROVIDERS` | `services/api/lib/identity_registry.py` |
| `PROVIDER_COLLECTORS` + `PROVIDER_LABELS` | `services/ai-orchestrator/health_metrics.py` + UI `health-grid.tsx` |

### 4. Constraint DB tenant_shipping_provider_config

Crear migración nueva con:

```sql
ALTER TABLE tenant_shipping_provider_config
  DROP CONSTRAINT IF EXISTS tenant_shipping_provider_config_active_provider_check;
ALTER TABLE tenant_shipping_provider_config
  ADD CONSTRAINT tenant_shipping_provider_config_active_provider_check
  CHECK (active_provider IN ('aveonline', '{nuevo_provider}'));
```

### 5. Webhook handler

Crear `services/api/routers/{provider}_webhook.py` usando el framework:
- `webhook_framework.base.WebhookHandler` (template-method base)
- `webhook_framework.signature.URLSecretTokenStrategy()` si provider NO
  tiene HMAC nativo (caso Aveonline)
- `webhook_framework.rate_limit.TokenBucketRule()` si tiene rate limits
- `webhook_dedup.is_duplicate()` para F.4 idempotency

Registrar en `services/api/main.py`:
```python
app.include_router(
    {provider}_webhook.router,
    prefix="/api/v1/webhooks/{provider}"
)
```

### 6. UI Tenant Console

Crear `apps/web/app/dashboard/(settings-group)/integrations/{provider}/`
siguiendo el patrón Aveonline (`page.tsx` + `_components/` tabs Carriers + Capacidades).

Crear endpoints CRUD en `services/api/routers/integrations.py`:
- POST `/integrations/{provider}` — conectar (guardar credentials en Vault)
- DELETE `/integrations/{provider}` — desconectar
- GET/PUT/DELETE `/integrations/{provider}/carriers` — preferencias

Mostrar tarjeta en `integrations/_components/integrations-manager.tsx`
agregando entry a `cardCategories` + `allCards`.

### 7. Tests

Replicar el patrón existente:
- `tests/api/test_{provider}_client.py` — HTTP client unit tests
- `tests/test_{provider}_webhook.py` — webhook handler con payloads mock
- `tests/agentic/test_quote_shipping_routing.py` — agregar caso routing
- Tests framework actualizan automáticamente vía `VALID_PROVIDERS` updates

### 8. Docs

- Dossier de investigación: `docs/research/{provider}-dossier-{YYYY-MM-DD}.md`
- Empirical evidence (webhook payloads, schemas reales):
  `docs/research/empirical-evidence/{provider}-*.json`
- ADR formal para el pivote o adición:
  `docs/adr/00XX-{provider}-shipping-integration.md` (siguiendo plantilla
  ADR-0019)
- Update `docs/legal/subprocessors.md` + `docs/legal/privacy-policy.md`
  agregando el nuevo provider como subprocesador (LEGAL Habeas Data
  Ley 1581).
- Update `docs/integrations/courier-{provider}.md` (runtime doc canónica).

### 9. Render config

Agregar env vars necesarias a `render.yaml` + `.env.example`:
- API URL/endpoints
- Rate limits (si configurables)
- Webhook IPs allowlist (si provider las publica)

### 10. Seed inicial

Migration con seed mínimo:
- Capabilities por defecto en `tenant_provider_capabilities` (opcional;
  default open = todas habilitadas)
- Carriers conocidos del provider en `tenant_carriers` template (opcional)

## Single-active-provider invariante

Konvi opera con **1 provider shipping activo por tenant** (ADR-0019).
NO se implementa fallback automático cross-provider:

- `tenant_shipping_provider_config.active_provider` = único valor enum
- Si el tenant quiere migrar a otro provider: UI switch + SQL trigger
- En runtime, `_get_active_shipping_provider()` retorna el activo único

Si se necesita marketplace shipping con N providers paralelos por orden,
eso requiere ADR separado (no encaja en este pattern).

## Patrones técnicos transversales (NO crear nuevos)

- **Vault secrets**: pattern `<tenant_id>/{provider}/<credential_name>`
- **Webhook deduplication**: tabla `webhook_events_seen` (F.4)
- **Webhook secrets**: `tenant_webhook_secrets` con rotación (F.10)
- **Circuit breaker**: `lib/integration_client/circuit.py` per provider key
- **Idempotency outbound**: `lib/integration_client/idempotency.py` con
  cache 24h
- **Provider health metrics**: `health_metrics.py` con collector function
  per provider
- **Compliance Habeas Data**: decoradores en `lib/compliance/` para
  audit log + scoped_to_country('CO')

## Consecuencias

### Positivas
- Agregar Courier N+1 NO requiere refactor del orchestrator agentic ni
  del FSM.
- Misma interfaz `quote_shipping_for_cart` para todos los providers.
- Tests framework cubren automáticamente nuevos providers (vía frozensets).
- Audit Habeas Data + compliance docs siguen patrón único.

### Negativas
- Cambio de proveedor de un tenant existente requiere intervención humana
  (modificar `tenant_shipping_provider_config.active_provider`) + KYC con
  el nuevo provider.
- Mantenimiento de N clientes HTTP per provider escala linealmente con #
  providers (esperado: ≤3 providers shipping en 12 meses).

## Referencias

- [ADR-0019](0019-aveonline-as-primary-shipping-provider.md) — Pivote
  Envia → Aveonline (justificación arquitectónica).
- [ADR-0020](0020-shipment-lifecycle-true-state.md) — Lifecycle estados
  ciertos.
- [ADR-0021](0021-notification-channels-unified-source.md) — Notification
  channels unified.
- Tag git `archive/envia-investigacion-rev106-2026-05-08` — Investigación
  Envia preservada para audit trail.
- [docs/research/aveonline-dossier.md](../research/aveonline-dossier.md) —
  Dossier técnico Aveonline.

## Estado

ACTIVO. Re-evaluar si:
- Se cambia el modelo de single-active-provider a marketplace multi-provider.
- Algún provider futuro requiere capabilities que rompen el pattern
  (e.g., providers que NO tienen webhooks ni polling).
- Se decide refactorizar el orchestrator agentic.
