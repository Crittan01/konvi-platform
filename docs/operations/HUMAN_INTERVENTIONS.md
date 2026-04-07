# Intervenciones Humanas Requeridas

Este documento registra **cada paso que requiere acción manual** fuera del automatismo del agente.
Debe actualizarse cada vez que se identifique una nueva intervención.

---

## [IH-001] Aplicar Migración SQL: `messages.processed`

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

## [IH-003] Verificar Token de Producción de Meta (WhatsApp)

**Estado**: ⚠️ IMPORTANTE — El token actual en `.env` es temporal (expira cada 24h)  
**Responsable**: Operador con cuenta de Meta Developers  
**Fecha identificada**: 2026-04-07

### Contexto

El `META_ACCESS_TOKEN` en el `.env` actual es un **User Access Token temporal** que Meta Developers genera para pruebas. Expira en ~24 horas.

Para producción se necesita un **System User Access Token permanente** (no expira).

### Pasos para Token de Producción

1. Ve a [Meta Business Suite](https://business.facebook.com/) → **Configuración del negocio**.
2. En el menú izquierdo: **Usuarios** → **Usuarios del sistema**.
3. Haz clic en **"Agregar"** → Nombre: `commerce-ops-bot` → Rol: **Admin**.
4. Haz clic en el usuario creado → **"Generar nuevo token"**.
5. Selecciona tu App de WhatsApp.
6. Permisos MÍNIMOS requeridos (según [docs Meta](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started)):
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
7. Establece **"Nunca"** como fecha de expiración.
8. Copia el token generado y actualiza en Render Environment Variables (nunca en `.env` del repo).

### Para Entorno de Pruebas

El token actual es suficiente para desarrollo. Solo recuerda que debes regenerarlo desde Meta Developers cada 24h o cuando expire.

---

## [IH-004] Primer Deploy en Render

**Estado**: ❌ Pendiente (Fase E del roadmap)  
**Responsable**: Operador con cuenta de Render  

Ver guía completa en: `docs/deployment/DEPLOYMENT_GUIDE.md`

---

## Regla de Actualización

Cada vez que se resuelva una intervención, cambiar su estado a `✅ COMPLETADO` y agregar la fecha de resolución.  
Cada vez que el agente identifique un nuevo paso manual, agregarlo a este documento.
