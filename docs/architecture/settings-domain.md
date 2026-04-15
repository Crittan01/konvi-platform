# Dominio Configuración — Documento Técnico

> Fuente de verdad técnica del dominio `Configuración` del tenant.  
> Rev. 1 — 2026-04-15 (Vuelta 5 + seguridad)

---

## Estructura del dominio

| Submódulo | Ruta | Archivo principal |
|---|---|---|
| General | `/dashboard/settings` | `(settings-group)/settings/page.tsx` |
| Usuarios y Acceso | `/dashboard/team` | `(settings-group)/team/page.tsx` |
| Integraciones | `/dashboard/integrations` | `(settings-group)/integrations/page.tsx` |
| Reglas de Negocio | _pendiente_ | _no existe aún_ |

---

## General (`/dashboard/settings`)

### Capacidades
- Nombre del negocio (editable por Owner)
- Logo del tenant (upload a Supabase Storage `tenant-media`, editable por Owner)
- WABA ID — solo lectura (cambiar contactando soporte)
- **Umbral de stock bajo** (`low_stock_threshold`) — entero 1–999, default 5. Editable por Owner. Afecta directamente al dashboard (query de producto_variations con stock bajo).
- Dirección de origen para despachos (`shipping_origin` JSONB en `tenants`)
- Notificaciones Telegram — bot token + chat ID, `notification_settings` tabla

### Tablas afectadas
- `tenants` — `name`, `logo_url`, `low_stock_threshold`, `shipping_origin`, `meta_waba_id`
- `notification_settings` — `tenant_id`, `channel`, `enabled`, `config`

### Seguridad
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` — cliente SSR, RLS activo en `tenants`
- `logo-upload.tsx` usa `getUser()` — validación server-side (no `getSession()`)
- Todos los Server Actions verifican `role === 'owner'` o `['owner','manager']`

---

## Usuarios y Acceso (`/dashboard/team`)

### Capacidades
- Listado de miembros del tenant vía `get_tenant_team()` (RPC)
- Invite de nuevo miembro por email → flujo completo con email de Supabase
- Cambio de rol (owner → puede cambiar a cualquier miembro que no sea él mismo)
- Eliminar miembro (guard: nunca eliminar `role='owner'`)
- Descripción visual de los 3 roles del sistema

### Flujo de invite

```
Owner ingresa email + rol
  ↓
Server Action inviteMember() [SSR — nunca expuesto al cliente]
  ↓
adminClient.auth.admin.inviteUserByEmail(email, { redirectTo })
  → Supabase envía email de invitación al usuario
  → Si usuario ya existe: buscar por email y asignar directamente
  ↓
adminClient.rpc('add_member_to_tenant', { p_user_id, p_tenant_id, p_role })
  → Función SECURITY DEFINER — inserta en tenant_users
  → Trigger on_tenant_assignment se dispara
  → Inyecta tenant_id + role en raw_app_meta_data del usuario
  ↓
revalidatePath('/dashboard/team')
```

### Tablas afectadas
- `auth.users` — gestionado por Supabase Auth Admin API
- `tenant_users` — `user_id`, `tenant_id`, `role`, `created_at`

### RLS en `tenant_users`
- Política: `tenant_id = app_current_tenant()` — un usuario solo ve miembros de su tenant
- `add_member_to_tenant` usa `SECURITY DEFINER` — bypasea RLS de forma controlada para el insert inicial

### Variables de entorno requeridas

| Variable | Dónde | Propósito |
|---|---|---|
| `SUPABASE_SERVICE_ROLE_KEY` | Render — web service env | Requerida para `adminClient` en Server Actions |
| `NEXT_PUBLIC_APP_URL` | Render — web service env | URL base para `redirectTo` en el email de invite |

> **INTERVENCION HUMANA REQUERIDA — IH-001**  
> Ver sección de Intervenciones Humanas al final de este documento.

### Roles del sistema

| Rol | Acceso |
|---|---|
| `owner` | Acceso total — configura integraciones, equipo, datos del negocio |
| `manager` | Operaciones: pedidos, catálogo, inventario, métricas, conocimiento |
| `agent` | Solo Inbox, Pedidos, Contactos y Reclamos |

---

## Integraciones (`/dashboard/integrations`)

### Capacidades
- Envia: conectar API token (sandbox / producción), desconectar
- Mercado Libre: OAuth 2.0, conectar vía redirect a MeLi, desconectar
- Estado visual por integración (conectado / desconectado)
- Banner de resultado post-OAuth (searchParams: `connected`, `error`)

### Tablas afectadas
- `tenant_integrations` — `tenant_id`, `provider`, `status`, `credentials` (cifrado en reposo por Supabase), `meta`

### Variables de entorno requeridas (FastAPI)
| Variable | Dónde |
|---|---|
| `MELI_CLIENT_ID` | Render — api service env |
| `MELI_REDIRECT_URI` | Render — api service env |
| `MELI_AUTH_URL` | Render — api service env (default: auth.mercadolibre.com.co) |

---

## Reglas de Negocio (PENDIENTE)

**No implementado.** No exponer en el menú hasta:
1. Definir el caso de uso real (¿márgenes?, ¿precios automáticos?, ¿horarios WhatsApp?)
2. Aprobar el diseño funcional
3. Crear la migración de DB correspondiente

**Ruta futura:** `/dashboard/rules` dentro del Route Group `(settings-group)/`

---

## Seguridad del dominio completo

### RLS (Row Level Security)
| Tabla | RLS | Política |
|---|---|---|
| `tenants` | ✅ | `id = app_current_tenant()` |
| `tenant_users` | ✅ | `tenant_id = app_current_tenant()` |
| `tenant_integrations` | ✅ | `tenant_id = app_current_tenant()` |
| `notification_settings` | ✅ | `tenant_id = app_current_tenant()` |

### CORS (FastAPI — `services/api/main.py`)
- `allow_origins=ALLOWED_ORIGINS` (desde env var `ALLOWED_ORIGINS`)
- Métodos: GET, POST, PUT, DELETE, PATCH
- Headers: Authorization, Content-Type
- **INTERVENCION HUMANA REQUERIDA — IH-002** para configurar `ALLOWED_ORIGINS` en Render

### Security Headers (Next.js — `next.config.js`)
| Header | Valor |
|---|---|
| `X-Frame-Options` | SAMEORIGIN |
| `X-Content-Type-Options` | nosniff |
| `Referrer-Policy` | strict-origin-when-cross-origin |
| `Permissions-Policy` | camera=(), microphone=(), geolocation=() |
| `Strict-Transport-Security` | max-age=31536000; includeSubDomains |
| `Content-Security-Policy` | CSP estricto — ver `next.config.js` para lista completa |

> **Nota:** Si se añaden nuevos proveedores externos (CDN, analytics, etc.), actualizar `connect-src` y `img-src` en `next.config.js`. Documentar aquí.

---

## Intervenciones Humanas

### IH-001 — Variables de entorno del invite en Render

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | DevOps / Owner del proyecto |
| **PASOS** | 1. Ir a Render Dashboard → Service `commerce-ops-web` → Environment <br> 2. Agregar `NEXT_PUBLIC_APP_URL=https://commerce-ops-platform.onrender.com` (ajustar al dominio real) <br> 3. Verificar que `SUPABASE_SERVICE_ROLE_KEY` ya está configurado (fue añadido en deployments previos) <br> 4. Hacer redeploy del servicio web |
| **INSUMOS** | URL de producción del frontend en Render; Service Role Key de Supabase (Project Settings → API) |
| **CRITERIO DE ÉXITO** | Al invitar un miembro desde `/dashboard/team`, el usuario recibe un email con un link que apunta al dominio correcto de Render |

### IH-002 — ALLOWED_ORIGINS en FastAPI (Render)

**INTERVENCION HUMANA REQUERIDA**

| Campo | Detalle |
|---|---|
| **RESPONSABLE** | DevOps / Owner del proyecto |
| **PASOS** | 1. Render Dashboard → Service `commerce-ops-api` → Environment <br> 2. Variable `ALLOWED_ORIGINS` debe incluir el dominio real del frontend: `https://commerce-ops-platform.onrender.com` <br> 3. Si hay múltiples dominios, separar con comas: `https://commerce-ops-platform.onrender.com,http://localhost:3000` <br> 4. Redeploy del servicio api |
| **INSUMOS** | URL de producción del frontend |
| **CRITERIO DE ÉXITO** | Requests del frontend a la API no fallan por CORS en producción |
