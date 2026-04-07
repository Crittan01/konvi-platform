# Intervenciones Humanas Requeridas

Este documento registra **cada paso que requiere acción manual** fuera del automatismo del agente.
Debe actualizarse cada vez que se identifique una nueva intervención.

---

## [IH-001] Aplicar Migración SQL: `messages.processed`

**Estado**: ✅ COMPLETADO — 2026-04-07  
**Resuelto por**: `supabase db query --linked` (Management API — no TCP directo)

### Cómo se aplicó (para futuras migraciones)

La VM no puede conectar a Postgres via TCP (el Supavisor rechaza conexiones de esta IP).
Pero el **Supabase CLI con `--linked`** usa la **Management API REST** que sí funciona.

Instalación única del CLI:

```bash
# Descargar binario oficial desde GitHub Releases
curl -fsSL https://github.com/supabase/cli/releases/latest/download/supabase_linux_amd64.tar.gz \
  -o /tmp/supabase.tar.gz
tar -xzf /tmp/supabase.tar.gz -C /tmp/
sudo mv /tmp/supabase /usr/local/bin/supabase
supabase --version  # Debe mostrar versión
```

Vincular el proyecto (una sola vez):

```bash
cd /home/ansible/workspaces/commerce-ops-platform
supabase link --project-ref ***SUPABASE_PROJECT_REF_REDACTED***
# No pide login si el proyecto es público o está en modo anon
```

Ejecutar SQL / migraciones:

```bash
# Ejecutar un archivo .sql completo
supabase db query --linked -f supabase/migrations/20260407200700_messages_processed_flag.sql

# Ejecutar SQL inline
supabase db query --linked "SELECT * FROM tenants;"
```

Verificación realizada:
```
column_name    | data_type                   | column_default
processed      | boolean                     | false
processed_at   | timestamp with time zone    | null
```

### Por qué psql directo no funciona (investigado)

El Supabase Supavisor (pooler) responde **"Tenant or user not found"** a conexiones TCP desde esta IP.
Esto NO es un bug — el Supavisor usa IPv6 para routing interno y esta VM usa IPv4. El CLI `--linked` sortea este problema usando HTTPS a `api.supabase.com`.

---

## [IH-002] Configurar `meta_waba_id` en el tenant de Supabase

**Estado**: ✅ COMPLETADO — 2026-04-07  
**meta_waba_id configurado**: `2159052118202272`  
**Tenant**: `Matriz Commerce Dev` (id: `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9`)

Verificado vía REST API:
```json
[{"id":"0fb0777e-...","name":"Matriz Commerce Dev","meta_waba_id":"2159052118202272"}]
```

Para futuras consultas:
```bash
supabase db query --linked "SELECT id, name, meta_waba_id FROM tenants;"
```

### Contexto

El campo `meta_waba_id` en la tabla `tenants` es el vínculo entre el número de WhatsApp Business Account (WABA) de Meta y el tenant interno del sistema.

Después del fix del tenant resolver, si el `meta_waba_id` del tenant en la base de datos no coincide con el WABA ID que Meta envía en los webhooks, **los mensajes serán descartados** con el log: `"Tenant no encontrado para meta_waba_id='...'"`.

### Pasos

**PASO 1 — Obtener el WABA ID**

1. Ve a [Meta Business Suite](https://business.facebook.com/) → **WhatsApp** → **Cuentas de WhatsApp**.
2. El número que aparece como **"WhatsApp Business Account ID"** es el WABA ID.  
   *(Formato: número largo, ej: `102938475628374`)*
3. O bien: en [Meta Developers](https://developers.facebook.com/), ve a tu App → **WhatsApp** → **API Setup**. El campo `"WhatsApp Business Account ID"` es lo que necesitas.

**PASO 2 — Actualizar el tenant en Supabase**

1. Ve a `https://supabase.com/dashboard` → proyecto `commerce-ops-dev`.
2. En el menú lateral: **Table Editor** → tabla **`tenants`**.
3. Haz clic en la fila de tu tenant (debería haber 1 fila si es entorno dev).
4. En la columna `meta_waba_id`, haz doble clic y pega el WABA ID del Paso 1.
5. Haz clic fuera de la celda para guardar.

**O via SQL Editor:**

```sql
UPDATE public.tenants
SET meta_waba_id = 'TU_WABA_ID_AQUI'
WHERE name = 'Matriz Commerce Dev';  -- Ajusta el name si es diferente
```

### Criterio de Éxito

```sql
SELECT id, name, meta_waba_id FROM public.tenants;
```

La columna `meta_waba_id` debe tener el valor del WABA ID de Meta (no NULL ni vacío).

---

## [IH-003] META_ACCESS_TOKEN — Renovación Periódica

**Estado**: ⚠️ RENOVACIÓN PENDIENTE PERIÓDICAMENTE  
**Última renovación**: 2026-04-07 (token de ~297 chars)

### Contexto

El `META_ACCESS_TOKEN` es un **User Access Token temporal** de Meta Developers. Expira cada ~24 horas.
Para desarrollo es aceptable renovarlo manualmente. Para producción, usar un **System User Token permanente**.

### Cómo renovar el token temporal (entorno dev)

1. Ir a [Meta Developers](https://developers.facebook.com/) → Tu App → **WhatsApp** → **API Setup**
2. En la sección **"Temporary access token"**, hacer clic en **"Generate access token"**
3. Copiar el token generado
4. Actualizar en `.env`: `META_ACCESS_TOKEN="<nuevo_token>"`
5. Reiniciar el conector: `uvicorn main:app --reload --port 8000`

### Cómo crear un Token Permanente (producción)

Según la [documentación oficial de Meta](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started#get-access-token):

1. Ve a [Meta Business Suite](https://business.facebook.com/) → **Configuración del negocio**
2. Menú izquierdo: **Usuarios** → **Usuarios del sistema** → **+ Agregar**
3. Nombre: `commerce-ops-bot`, Rol: **Admin**
4. Clic en el usuario → **"Generar nuevo token"** → Seleccionar App
5. Permisos mínimos: `whatsapp_business_messaging`, `whatsapp_business_management`
6. Expiración: **Nunca**
7. En Render: configurar como env var `META_ACCESS_TOKEN` (nunca en el repo)

---

## [IH-004] Primer Deploy en Render

**Estado**: ❌ Pendiente (Fase E del roadmap)  
**Responsable**: Operador con cuenta de Render  

Ver guía completa en: `docs/deployment/DEPLOYMENT_GUIDE.md`

---

## Regla de Actualización

Cada vez que se resuelva una intervención, cambiar su estado a `✅ COMPLETADO` y agregar la fecha de resolución.  
Cada vez que el agente identifique un nuevo paso manual, agregarlo a este documento.
