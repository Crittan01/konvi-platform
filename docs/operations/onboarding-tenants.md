# Onboarding de Tenants — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Estado

❌ **Proceso de onboarding no automatizado todavía**

El onboarding actual es completamente manual. Se documenta aquí el estado actual y el objetivo futuro.

---

## Proceso de onboarding actual (manual)

### Paso 1 — Crear el tenant en Supabase

```sql
-- Ejecutar via supabase db query --linked
INSERT INTO public.tenants (name, status, meta_waba_id)
VALUES ('Nombre del Tenant', 'active', 'WABA_ID_DEL_CLIENTE');
```

### Paso 2 — Crear el usuario en Supabase Auth

1. Ir a [Supabase Dashboard](https://supabase.com/dashboard) → Proyecto → Authentication → Users
2. Clic en **"Add user"**
3. Ingresar email y contraseña del operador principal del tenant
4. El trigger `20260406181239` inyecta automáticamente el `tenant_id` en `app_metadata` del JWT

### Paso 3 — Asociar el usuario al tenant

```sql
-- Obtener el user_id del usuario recién creado
SELECT id FROM auth.users WHERE email = 'email@tenant.com';

-- Asociar al tenant con rol owner
INSERT INTO public.tenant_users (user_id, tenant_id, role)
VALUES ('USER_UUID', 'TENANT_UUID', 'owner');
```

### Paso 4 — Configurar el WABA ID

El `meta_waba_id` del tenant debe coincidir con el WhatsApp Business Account ID de Meta del cliente.
Ver `docs/operations/HUMAN_INTERVENTIONS.md` → IH-002 para instrucciones.

### Paso 5 — Verificar acceso

El nuevo operador debe poder:
1. Hacer login en `https://commerce-ops-web.onrender.com/login`
2. Ver el dashboard con su nombre de tenant
3. Navegar a Catálogo e Inbox

---

## Proceso de onboarding objetivo (self-serve)

El objetivo a largo plazo es un onboarding self-serve sin intervención manual:

1. El futuro cliente se registra en la plataforma
2. Completa el formulario de configuración (nombre, email, WABA ID)
3. La plataforma crea automáticamente el tenant, el usuario y las asociaciones
4. Se envía un email de confirmación con credenciales
5. El cliente conecta su cuenta de WhatsApp Business siguiendo el flujo guiado

**Prerrequisitos**:
- Platform Console implementada (Fase 11)
- API de onboarding en `services/api`
- Flujo de verificación de WABA (requiere integración Meta Business Management API)

---

## Checklist de onboarding completo

- [ ] Tenant creado en tabla `tenants` con `status=active` y `meta_waba_id` correcto
- [ ] Usuario creado en Supabase Auth con email verificado
- [ ] Usuario asociado al tenant en `tenant_users` con rol `owner`
- [ ] JWT con `app_metadata.tenant_id` inyectado correctamente (verificar con decode del JWT)
- [ ] Login funcional desde la interfaz web
- [ ] Inbox mostrando conversaciones del tenant (vacío es OK)
- [ ] Catálogo accesible (vacío es OK)

---

## Documentos relacionados

- `docs/operations/HUMAN_INTERVENTIONS.md` — IH-002 (configurar WABA ID)
- `docs/architecture/multi-tenant-security.md` — Contratos de aislamiento
- `docs/data/schema.md` — Tablas `tenants`, `tenant_users`
