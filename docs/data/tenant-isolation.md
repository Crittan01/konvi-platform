# Aislamiento de Tenant — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Modelo de aislamiento

La plataforma usa un **esquema único de PostgreSQL con separación lógica por tenant via Row Level Security (RLS)**.

No hay schemas separados por tenant. Toda la data vive en el schema `public` y la separación se garantiza a nivel de fila con la columna `tenant_id` en cada tabla y las políticas RLS correspondientes.

---

## Por qué este modelo

- Menor overhead operativo que múltiples schemas o bases de datos
- Supabase gestiona Auth + RLS de forma integrada
- Escala bien para la fase actual del producto
- PostgreSQL RLS es la barrera final e inviolable incluso si la capa de aplicación tiene un bug

---

## Columna `tenant_id`

Toda tabla con datos de negocio tiene:
```sql
tenant_id UUID NOT NULL REFERENCES tenants(id)
```

Esta columna es el pivote del aislamiento. **Toda query de la aplicación** debe filtrar por `tenant_id`.

---

## Función `app_current_tenant()`

Función SQL estabilizadora que resuelve el tenant activo de dos formas:

```sql
CREATE OR REPLACE FUNCTION app_current_tenant()
RETURNS UUID
LANGUAGE sql STABLE
AS $$
  SELECT COALESCE(
    -- Vía 1: Worker backend (service_role) setea este valor antes de cada query
    NULLIF(current_setting('app.current_tenant_id', true), '')::uuid,
    -- Vía 2: Usuario web (JWT de Supabase Auth contiene app_metadata.tenant_id)
    (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
  );
$$;
```

---

## Política RLS universal

Todas las tablas con `tenant_id` tienen exactamente esta política:

```sql
CREATE POLICY "Tenant Isolation"
ON public.<tabla>
FOR ALL USING (tenant_id = app_current_tenant());
```

Esto abarca: SELECT, INSERT, UPDATE, DELETE.

---

## Dos vías de resolución del tenant

### Vía 1 — Frontend (usuarios web)

El JWT de Supabase Auth contiene `app_metadata.tenant_id` (inyectado por trigger `20260406181239`).
Cuando el frontend hace una query con el rol `authenticated`, RLS lee el JWT automáticamente.

### Vía 2 — Workers backend (service_role)

Los workers usan `service_role` key que **bypasea RLS por diseño**.
Por eso, **antes de toda query**, el worker debe setear el contexto de sesión:

```python
# CORRECTO — patrón obligatorio en workers
supabase.rpc("set_config", {
    "setting": "app.current_tenant_id",
    "value": str(tenant_id)
}).execute()
```

⚠️ Si un worker usa `service_role` sin setear `app.current_tenant_id`, tiene acceso a datos de **todos** los tenants. Esto es un riesgo crítico (R-13).

---

## Límites del aislamiento actual

| Límite | Descripción |
|--------|-------------|
| Sin separación física | Toda data en el mismo schema — backup/restore afecta a todos |
| service_role es omnipotente | Un bug en un worker puede acceder a cualquier tenant |
| Sin auditoría automática | Las mutaciones no se loguean automáticamente (pendiente) |

---

## Consideraciones futuras

- Implementar tabla `audit_log` para trazabilidad completa de mutaciones
- Evaluar schemas separados por tenant si el volumen lo justifica (no previsto a corto plazo)
- Tests de aislamiento: verificar que query de tenant A no retorna datos de tenant B

---

## Documentos relacionados

- `docs/data/rls-policies.md` — Detalle de políticas RLS por tabla
- `docs/architecture/multi-tenant-security.md` — Contratos de seguridad
- `docs/data/schema.md` — Esquema completo de tablas
