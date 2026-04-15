# Arquitectura Híbrida de API — Snapshot Empírico

El sistema opera bajo un modelo híbrido para optimizar latencia (Lecturas directas) y centralizar lógica de negocio (Mutaciones asíncronas).

## Flujos de Comunicación Certificados

### 1. Lecturas (Read-only)
- **Path**: `apps/web` → `Supabase Client` (Client-side o Server-side).
- **Mecanismo**: Acceso directo a tablas mediante SDK de Supabase.
- **Seguridad**: Filtrado automático vía RLS (`tenant_id = app_current_tenant()`).
- **Uso Comprobado**: Listado de pedidos, catálogo, inbox, contactos.

### 2. Operaciones de Negocio (Mutaciones Críticas)
- **Path**: `apps/web` (Server Action) → `services/api` (FastAPI).
- **Mecanismo**: Llamada HTTP con Bearer Token (Supabase JWT).
- **Seguridad**: Dependencia `get_current_tenant` en FastAPI valida el JWT y extrae el `tenant_id`.
- **Uso Comprobado**: 
    - Avanzar estado de pedido (`pending` → `confirmed` → `ship`).
    - Enviar mensaje de WhatsApp (Capa manual).
    - Vincular/Sincronizar stock con Mercado Libre.

### 3. Mutaciones Simples (Metadata)
- **Path**: `apps/web` → `Supabase Client`.
- **Uso Comprobado**: Cancelar pedido, cambiar estado de conversación (Bot/Humano).

---

## Endpoints Certificados (services/api)

| Endpoint | Lógica de Negocio Probada |
|----------|--------------------------|
| `PATCH /orders/{id}` | Decremento de stock automático + Sync MeLi. |
| `POST /conversations/{id}/send` | Integración con WhatsApp Cloud API (Outbound). |
| `POST /marketplace/link` | Persistencia en `marketplace_listings` + Verificación de variante. |
| `POST /marketplace/import` | Creación atómica de Producto + Variante + Vínculo. |

---

## Configuración Operativa (Real)
- **API Gateway URL**: `https://commerce-ops-api.onrender.com`
- **Timeout Crítico**: Se ha identificado un timeout de 60s en el frontend para compensar el "Cold Start" del plan Free de Render.
