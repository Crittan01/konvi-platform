# Integración Courier / Shipping — Envia

Última actualización: 2026-04-09

---

## Estado

🟡 **Fase Inicial implementada — Fases 2 y 3 pendientes**

Última actualización: 2026-04-09 (rev. 2 — Fase 10 completada)

### Qué está implementado (Fase Inicial — ✅)

| Componente | Archivo | Estado |
|-----------|---------|--------|
| HTTP client para Envia API | `services/api/integrations/envia_client.py` | ✅ Bearer per-tenant, sandbox/prod |
| Quote endpoint | `services/api/routers/shipping.py` → `POST /api/v1/shipping/quote` | ✅ Rates + persistencia en `shipments` |
| Historial endpoint | `services/api/routers/shipping.py` → `GET /api/v1/shipping/history` | ✅ |
| UI historial | `apps/web/app/dashboard/shipping/page.tsx` | ✅ Listado, estados, banner si Envia no conectado |
| Tabla `shipments` | `supabase/migrations/20260409230000_shipments.sql` | ✅ Aplicada |
| Gestión de credenciales | `services/api/routers/integrations.py` | ✅ Envia connect/disconnect por tenant |
| Sandbox conectado | Empresa #5017 en Envia Sandbox | ✅ Token en `tenant_integrations` |
| PV-03 resuelto | Bearer per-tenant (no global) | ✅ Validado 2026-04-09 |

### Qué falta (Fase 2 y 3 — ❌ Pendiente)

| Capacidad | Fase | Endpoint Envia |
|-----------|------|----------------|
| Formulario UI interactivo de cotización | Inmediato (deuda) | — (backend existe) |
| Generación de label | Fase 2 | `POST /ship/` |
| Tracking de envío | Fase 2 | `GET /track/` |
| Programar pickup | Fase 2 | `POST /pickup/` |
| Cancelar envío | Fase 2 | `DELETE /ship/{id}` |
| Manifest | Fase 3 | `POST /manifest/` |
| Webhooks de estado | Fase 3 | Configuración en Envia portal |
| Queries API (carriers/services/country) | Fase 2 | `GET /carrier/`, `GET /service/` |

Este documento establece el diseño funcional, arquitectónico y de contrato para la integración completa de Envia dentro de la Commerce Ops Platform.

---

## Qué es Envia

Envia es un agregador de servicios de paquetería que permite a los negocios:

- Cotizar envíos comparando múltiples carriers
- Generar etiquetas (labels)
- Programar recolecciones (pickups)
- Rastrear envíos (tracking)
- Generar manifests de consolidación
- Cancelar envíos no usados
- Recibir actualizaciones via webhooks

**APIs relevantes para este proyecto**:

- **Shipping API**: quotes, labels, tracking, pickups, manifests, cancellations, invoices
- **Queries API**: consulta y validación operativa (carriers, servicios disponibles, country/state data, pickup options)

> Validar siempre contra la documentación oficial vigente de Envia antes de implementar endpoints o flujos.

---

## Principio fundamental

**No acoplar Shipping directamente al LLM.**

Toda cotización, pickup, label o tracking es responsabilidad del backend/connector.
El LLM (Gemini) nunca genera ni inventa información de envío.

El sistema puede responder cotizaciones o estados de envío por WhatsApp **solo si**:

1. Existen datos mínimos válidos (dirección origen, destino, peso/dimensiones)
2. El backend puede consultar el conector real de Envia
3. La respuesta se basa en datos transaccionales reales
4. No se improvisa información ante datos faltantes

Si faltan datos, el sistema debe:

- Solicitar al cliente la información faltante
- O escalar a un operador humano

---

## Módulo en Tenant Console

### A.10 Shipping / Courier (`/dashboard/shipping`)

Ver `docs/product/admin-ui-modules.md` para el detalle completo.

**Capacidades diseñadas (progresivas)**:

| Capacidad                     | Fase    | Dependencia                      |
| ----------------------------- | ------- | -------------------------------- |
| Cotización de envío           | Inicial | Envia Shipping API → rates       |
| Selección de carrier/servicio | Inicial | Envia Queries API → services     |
| Dirección de origen y destino | Inicial | Validación via Envia Queries API |
| Programar pickup              | Fase 2  | Envia → pickups, pickup options  |
| Generación de label           | Fase 2  | Envia → labels                   |
| Tracking de envío             | Fase 2  | Envia → tracking                 |
| Manifest                      | Fase 3  | Envia → manifests                |
| Webhooks de estado            | Fase 3  | Envia → webhooks config          |
| Historial de cotizaciones     | Inicial | Tabla local `shipments`          |
| Intervención humana           | Siempre | Cuando faltan datos o hay error  |

---

## Flujo núcleo (Fase Inicial)

```
Tenant selecciona "Cotizar envío" (desde Pedido o desde Shipping)
    │
    ▼
UI muestra formulario:
  - Origen (dirección del tenant o bodega)
  - Destino (dirección del cliente)
  - Peso y dimensiones del paquete
    │
    ▼
services/api → POST /api/v1/shipping/quote
    │
    ▼
services/connector-envia → Envia Shipping API → GET /rates
    │
    ▼
Respuesta: lista de opciones (carrier, servicio, precio, tiempo estimado)
    │
    ▼
Tenant selecciona opción
    │
    ▼
Cotización guardada en tabla `shipments` (status: quoted)
    │
    ▼ (Fase 2)
Tenant confirma → POST /labels → Label generado → shipments (status: labeled)
```

---

## Flujo desde WhatsApp (controlado)

```
Cliente pregunta por el costo de envío
    │
    ▼
AI Orchestrator detecta intent de cotización de envío
    │
    ▼
Verifica: ¿Existe pedido activo con dirección de destino?
  - SÍ: solicitar a services/connector-envia los rates reales
  - NO: solicitar datos al cliente (dirección, código postal) o escalar a humano
    │
    ▼
SI hay datos válidos:
  → tools/shipping_tool.py llama services/connector-envia
  → Devuelve opciones reales (carrier, precio, tiempo)
  → Orchestrator responde al cliente con esa información real
    │
    ▼
SI faltan datos o hay error:
  → Orchestrator pide datos faltantes al cliente
  → O escala a humano (human_takeover)
```

---

## Arquitectura del conector

### Ubicación actual (implementada en Fase 10)

> **Nota**: La Fase 10 implementó Envia directamente dentro de `services/api` como cliente integrado,
> no como un microservicio separado. Esta decisión fue tomada por simplicidad operativa en la Fase Inicial.
> Si el volumen justifica separarlo en Fase 2/3, se puede extraer a `services/connector-envia/`.

```
services/api/integrations/
└── envia_client.py       ← HTTP client Bearer per-tenant (sandbox + prod)

services/api/routers/
└── shipping.py           ← Endpoints: /quote, /history
                            Pydantic schemas: Address, Parcel, QuoteRequest

services/api/routers/
└── integrations.py       ← Connect/disconnect Envia (gestión de credenciales en tenant_integrations)
```

### Endpoints activos (Fase Inicial)

| Endpoint | Estado |
|----------|--------|
| `POST /api/v1/shipping/quote` | ✅ Llama Envia `POST /ship/rate/`, persiste en `shipments` |
| `GET /api/v1/shipping/history` | ✅ Lista `shipments` del tenant |

### Endpoints internos diseñados (Fases 2-3)

```
POST /api/v1/shipping/quote      ← ✅ IMPLEMENTADO — cotización de envío
GET  /api/v1/shipping/history    ← ✅ IMPLEMENTADO — historial del tenant
POST /api/v1/shipping/label      ← ❌ Fase 2 — generación de label
GET  /api/v1/shipping/tracking/{id} ← ❌ Fase 2 — estado de envío
POST /api/v1/shipping/pickup     ← ❌ Fase 2 — programar recogida
DELETE /api/v1/shipping/{id}     ← ❌ Fase 2 — cancelar envío
GET  /api/v1/shipping/carriers   ← ❌ Fase 2 — carriers disponibles (Queries API)
GET  /api/v1/shipping/services   ← ❌ Fase 2 — servicios por carrier (Queries API)
```

### Path vs Background

| Operación           | Tipo                  | Justificación                    |
| ------------------- | --------------------- | -------------------------------- |
| Quote (cotización)  | Request path síncrono | Respuesta inmediata al tenant    |
| Label generation    | Request path síncrono | Tenant espera el label           |
| Tracking query      | Request path síncrono | Tenant consulta en tiempo real   |
| Pickup scheduling   | Request path síncrono | Confirmación inmediata           |
| Webhook processing  | Background async      | Eventos de estado del envío      |
| Manifest generation | Background async      | Consolidación puede tomar tiempo |

---

## Schema de base de datos requerido

### Tabla `shipments`

```sql
CREATE TABLE public.shipments (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id),
  order_id        UUID REFERENCES orders(id),          -- nullable si es cotización independiente
  status          TEXT NOT NULL DEFAULT 'quoted',       -- quoted, labeled, picked_up, in_transit, delivered, cancelled
  carrier         TEXT,
  service         TEXT,
  origin_address  JSONB NOT NULL,
  destination_address JSONB NOT NULL,
  parcels         JSONB NOT NULL,                       -- peso, dimensiones
  quote_response  JSONB,                                -- respuesta raw de Envia
  selected_rate   JSONB,                                -- tarifa seleccionada
  label_url       TEXT,
  tracking_number TEXT,
  tracking_url    TEXT,
  envia_shipment_id TEXT,
  pickup_id       TEXT,
  estimated_delivery DATE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ
);

-- RLS
ALTER TABLE public.shipments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Tenant Isolation" ON public.shipments
  FOR ALL USING (tenant_id = app_current_tenant());
```

---

## Variables de entorno y autenticación

**Modelo de auth resuelto (PV-03 — validado 2026-04-09):**
- Bearer token **per-tenant** — cada tenant tiene su propia API key de Envia
- Tokens almacenados en `tenant_integrations.credentials.api_token`
- Ambiente configurable: `sandbox: true/false` en `tenant_integrations.credentials`
- Producción: `https://api.envia.com` / Sandbox: `https://api-test.envia.com`

> No hay variables de entorno globales de Envia en el backend — el token se extrae por tenant desde la DB en cada request.

**Sandox activo**: Empresa #5017 conectada en el tenant dev `Matriz Commerce Dev`.

---

## Integración con AI Orchestrator

Cuando el Orchestrator detecte intent de shipping, debe:

1. Invocar `tools/shipping_tool.py` (a crear)
2. El tool llama internamente a `services/connector-envia`
3. Retorna datos reales — nunca los genera el LLM
4. Si el tool falla o falta información → escalar o pedir datos

```python
# tools/shipping_tool.py (diseño)
async def get_shipping_quote(
    tenant_id: UUID,
    origin: dict,
    destination: dict,
    parcels: list
) -> list[dict]:
    """
    Obtiene cotizaciones reales de envío via Envia.
    Nunca inventa información. Si falla, lanza excepción para escalación.
    """
    ...
```

---

## Validaciones con Queries API de Envia

Antes de cotizar, usar la Queries API para:

- **Carriers disponibles**: verificar qué carriers cubren el origen/destino
- **Servicios por carrier**: qué niveles de servicio están disponibles (estándar, express, etc.)
- **Datos de país/estado**: validar códigos postales y municipios
- **Pickup options**: verificar disponibilidad de recogida en el origen

Esto evita errores en la Shipping API por datos de entrada inválidos.

---

## Webhooks de Envia (Fase 3)

Cuando Envia notifique cambios de estado de un envío:

1. El webhook llega a un endpoint de `services/connector-envia`
2. Actualizar `shipments.status` y datos de tracking
3. Notificar al tenant (Telegram interno o Supabase Realtime)
4. Si el envío está vinculado a un pedido (`order_id`), actualizar `orders.shipping_status`

---

## Precauciones operativas

- No generar labels para envíos que no tienen pedido confirmado
- No cancelar un envío sin verificar si ya fue recolectado
- Guardar siempre la respuesta raw de Envia en `quote_response` para trazabilidad
- Si Envia retorna error → loguear completo, nunca silenciar
- No exponer API Keys de Envia en el frontend

---

## Intervención humana

Casos que siempre requieren operador humano:

- Configuración inicial de cuenta Envia (creación, credenciales)
- Resolución de disputas con carriers
- Envíos con incidencias no resueltas automáticamente
- Manifests que requieren confirmación del transportista

---

## Riesgos identificados

| ID    | Riesgo                                                     | Severidad  |
| ----- | ---------------------------------------------------------- | ---------- |
| R-E01 | Envia API down → cotizaciones no disponibles               | 🟠 Alto    |
| R-E02 | Token Envia expirado → falla silenciosa en cotizaciones    | 🟠 Alto    |
| R-E03 | Datos de dirección inválidos → error en Shipping API       | 🟡 Medio   |
| R-E04 | Rate limit de Envia en volumen alto                        | 🟡 Medio   |
| R-E05 | LLM inventando cotizaciones si el tool falla sin guardrail | 🔴 Crítico |

---

## Documentos relacionados

- `docs/architecture/connector-framework.md` — Framework de conectores
- `docs/architecture/front-back-separation.md` — A.10 Shipping
- `docs/product/admin-ui-modules.md` — A.10 Shipping / Courier
- `docs/data/schema.md` — Tabla `shipments`

## URL

https://docs.envia.com/docs/getting-started
