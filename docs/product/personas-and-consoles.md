# Personas y Consolas — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Principio fundamental

Este producto tiene **dos superficies administrativas completamente separadas**.

No mezclarlas. No unificarlas. No compartir navegación, layout ni permisos entre ambas.

---

## 1. Tenant Console

### Qué es

La interfaz que usa el **cliente/tenant** que compra la plataforma para operar su negocio e-commerce.

### Quién la usa

| Persona | Rol en sistema | Responsabilidades |
|---------|---------------|-------------------|
| Dueño del negocio | `owner` | Configuración total, catálogo, pedidos, WABA |
| Gerente de operaciones | `manager` | Gestión de catálogo, conversaciones, pedidos |
| Agente de atención | `agent` | Solo lectura de inbox, tomar control de conversaciones |

### Qué puede ver

- Su propia información de negocio (catálogo, conversaciones, pedidos, contactos, métricas)
- Sus integraciones activas (MeLi, Envia)
- Sus cotizaciones y envíos
- Sus reportes y auditoría de su propia operación

### Qué NO puede ver

- Información de otros tenants
- Configuración global de la plataforma
- Estado de infraestructura o servicios
- Datos de billing/planes internos de la plataforma
- Otros tenants de ninguna forma

### URL base (diseño objetivo)

```
/tenant/[tenant-slug]/dashboard
/tenant/[tenant-slug]/inbox
/tenant/[tenant-slug]/catalog
...
```

> Estado actual: La ruta `/dashboard` cumple la función de Tenant Console pero sin segmentación por tenant en URL. Esto es una simplificación del estado inicial que deberá formalizarse.

### Módulos base de la Tenant Console

Ver `docs/product/admin-ui-modules.md` para la lista completa con estados.

---

## 2. Platform Console

### Qué es

La interfaz que usa el **dueño de la plataforma, superadmin y equipo de soporte** para operar el SaaS.

### Quién la usa

| Persona | Rol en sistema | Responsabilidades |
|---------|---------------|-------------------|
| Superadmin / Founder | `platform_superadmin` | Control total de la plataforma |
| Soporte técnico | `platform_support` | Acceso de soporte (auditado) a tenants |
| DevOps interno | `platform_ops` | Health center, jobs, integraciones globales |

### Qué puede ver

- Estado global de todos los tenants
- Métricas agregadas de la plataforma
- Estado de infraestructura y servicios
- Billing y planes de cada tenant
- Feature flags globales y por tenant
- Auditoría global de todas las acciones
- Vista de soporte en tenants específicos (con trazabilidad)

### Qué NO puede ver

- No se le presenta como "su negocio" — opera el SaaS, no una tienda
- No puede acceder arbitrariamente a datos de tenants sin registro de soporte

### URL base (diseño objetivo)

```
/platform/overview
/platform/tenants
/platform/tenants/[tenant-id]
/platform/health
...
```

> Estado actual: La Platform Console **no existe en código todavía**. Es completamente pendiente de implementación.

### Módulos base de la Platform Console

Ver `docs/product/admin-ui-modules.md` para la lista completa con estados.

---

## Separación técnica requerida

| Aspecto | Tenant Console | Platform Console |
|---------|---------------|------------------|
| Layout | Sidebar con módulos del negocio | Sidebar con módulos del SaaS |
| Auth / JWT | Rol `owner/manager/agent` en `tenant_users` | Rol `platform_*` en tabla separada |
| RLS | Filtrado por `tenant_id` del usuario | Acceso a vistas agregadas o filtrado por scope |
| Ruta base | `/dashboard` o `/tenant/[slug]` | `/platform` |
| Estado actual | 🟡 Parcial (3 de 13 módulos) | ❌ No implementada |

---

## Regla de acceso de soporte

Si un operador de Platform Console necesita ver datos de un tenant específico:
1. Debe registrarse la acción en la tabla de auditoría global
2. El acceso debe ser explícitamente otorgado (no implícito)
3. El tenant afectado debe poder ver ese acceso en su propia auditoría
4. No puede haber acceso silencioso ni sin trazabilidad

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Módulos detallados de ambas consolas
- `docs/product/navigation-map.md` — Mapa de navegación
- `docs/architecture/multi-tenant-security.md` — Contratos RLS y RBAC
