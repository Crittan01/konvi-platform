# Seguridad Multi-Tenant — Contratos de RLS

## Principio Base

**Ningún dato de un tenant puede ser visible, modificable ni borrable por otro tenant.**  
Esta garantía se cumple en dos capas:

1. **Capa de aplicación**: API Gateway y Server Components inyectan el `tenant_id` del usuario autenticado en cada query.
2. **Capa de base de datos**: Row Level Security (RLS) en PostgreSQL es la barrera final e inviolable.

## Función Central: `app_current_tenant()`

```sql
CREATE OR REPLACE FUNCTION app_current_tenant()
RETURNS UUID
LANGUAGE sql STABLE
AS $$
  SELECT COALESCE(
    NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
    (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );
$$;
```

**Dos vías de resolución:**
- **Usuarios web (Next.js)**: El JWT de Supabase Auth contiene `app_metadata.tenant_id`, inyectado por el trigger `20260406181239`.
- **Workers backend (Orchestrator, Webhooks)**: Usan `service_role` y setean `SET app.current_tenant_id = '<uuid>'` en cada sesión Postgres antes de cualquier query.

## Políticas RLS Activas

| Tabla | Política | Condición |
|---|---|---|
| `tenants` | Tenant Isolation | `id = app_current_tenant()` |
| `products` | Tenant Isolation | `tenant_id = app_current_tenant()` |
| `product_variations` | Tenant Isolation | `tenant_id = app_current_tenant()` |
| `conversations` | Tenant Isolation | `tenant_id = app_current_tenant()` |
| `messages` | Tenant Isolation | `tenant_id = app_current_tenant()` |

## Roles de Base de Datos

| Rol Supabase | Uso | Nivel de Acceso |
|---|---|---|
| `anon` | Usuarios no autenticados | Solo endpoints públicos (verify webhook) |
| `authenticated` | Usuarios del frontend | Acceso filtrado por RLS con JWT |
| `service_role` | Workers backend (Orchestrator, Webhook) | Bypass de RLS — **DEBE** setear `app.current_tenant_id` manualmente |

> [!WARNING]
> El `service_role` bypasea RLS por diseño. Todo código que use este key DEBE validar el `tenant_id` explícitamente antes de cualquier operación destructiva.

## Patrón Correcto para Workers (service_role)

```python
# CORRECTO: Resolver tenant por identidad real, setear contexto
tenant_res = supabase.table("tenants").select("id").eq("meta_waba_id", meta_waba_id).execute()
if not tenant_res.data:
    raise ValueError(f"Tenant no encontrado para WABA ID: {meta_waba_id}")
tenant_id = tenant_res.data[0]['id']

# Setear contexto de sesión para RLS consistency
supabase.rpc("set_config", {"setting": "app.current_tenant_id", "value": str(tenant_id)}).execute()
```

## Patrón INCORRECTO (Hardcode — BLOQUEANTE)

```python
# ❌ INCORRECTO: Hardcode del primer tenant — rompe multi-tenancy
tenant_res = supabase.table("tenants").select("id").limit(1).execute()
tenant_id = tenant_res.data[0]['id']
```

**Archivo afectado**: `services/connector-whatsapp/services/db_persistence.py` línea 37.  
**Fix pendiente**: Resolver por `meta_waba_id`.

## RBAC — Roles de Usuario

Los roles de usuario en `tenant_users.role` definen permisos de aplicación (no de DB):

| Rol | Acceso |
|---|---|
| `owner` | Control total del tenant, configuración WABA |
| `manager` | Gestión de catálogo y conversaciones |
| `agent` | Solo lectura de conversaciones (Inbox) |

La validación de RBAC se hace en el API Gateway (`services/api`), no en el frontend.

## Auditoría

Toda operación que mute datos debe loguear:
- `tenant_id`
- `user_id` (si aplica)
- Timestamp UTC
- Acción realizada
- Resultado (success/failure)

Implementar cuando se construya `services/api` real.
