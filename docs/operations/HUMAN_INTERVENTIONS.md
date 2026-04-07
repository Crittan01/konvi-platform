# Intervenciones Humanas Requeridas

Este documento registra **cada paso que requiere acción manual** fuera del automatismo del agente.
Debe actualizarse cada vez que se identifique una nueva intervención.

---

## [IH-001] Aplicar Migración SQL: `messages.processed`

**Estado**: ⏳ PENDIENTE  
**Responsable**: Operador con acceso a Supabase Dashboard  
**Fecha identificada**: 2026-04-07

### Contexto

La VM de desarrollo no puede conectar directamente a la base de datos Supabase Cloud via TCP/5432 (bloqueado por firewall de red). La migración `20260407200700_messages_processed_flag.sql` debe aplicarse manualmente desde el SQL Editor de Supabase Dashboard.

Esta migración agrega el campo `processed` a la tabla `messages`, que es la señal que el AI Orchestrator usa para saber qué mensajes procesar.

### Pasos (dummy-friendly)

**PASO 1 — Abrir el SQL Editor de Supabase**

1. Abre tu navegador y ve a: `https://supabase.com/dashboard`
2. Inicia sesión con tu cuenta.
3. En la lista de proyectos, haz clic en el proyecto **`commerce-ops-dev`** (ref: `xmelwnhhphksbpdjmbbp`).
4. En el menú lateral izquierdo busca el ícono que parece un terminal o código: **"SQL Editor"**. Haz clic en él.
5. Se abrirá una pantalla con un editor de texto. Haz clic en **"+ New query"** (botón arriba a la izquierda).

**PASO 2 — Pegar el SQL**

Copia y pega **exactamente** el siguiente bloque en el editor:

```sql
-- Migración: campo 'processed' para el AI Orchestrator
ALTER TABLE public.messages
  ADD COLUMN IF NOT EXISTS processed BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS processed_at TIMESTAMPTZ;

-- Índice de performance para el poller del Orchestrator
CREATE INDEX IF NOT EXISTS idx_messages_inbound_unprocessed
  ON public.messages (tenant_id, created_at ASC)
  WHERE processed = FALSE AND direction = 'inbound';

COMMENT ON COLUMN public.messages.processed IS
  'Flag que el AI Orchestrator setea a TRUE tras enviar la respuesta de WhatsApp';

COMMENT ON COLUMN public.messages.processed_at IS
  'Timestamp UTC en que el Orchestrator procesó este mensaje';
```

**PASO 3 — Ejecutar**

1. Haz clic en el botón verde **"Run"** (o presiona `Ctrl + Enter`).
2. En la sección inferior verás el resultado. Debe decir algo como: `Success. No rows returned.`
3. Si aparece un error que dice `column "processed" of relation "messages" already exists` → la migración ya fue aplicada antes, esto es OK.

**PASO 4 — Verificar**

Pega esta query para confirmar:

```sql
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'messages'
  AND column_name IN ('processed', 'processed_at')
ORDER BY column_name;
```

Debes ver 2 filas: una para `processed` (tipo `boolean`) y otra para `processed_at` (tipo `timestamp with time zone`).

### Criterio de Éxito

- ✅ La query de verificación retorna 2 filas
- ✅ El campo `processed` existe con tipo `boolean` y default `false`
- ✅ El índice `idx_messages_inbound_unprocessed` fue creado

### Referencia Oficial

- [Supabase SQL Editor Docs](https://supabase.com/docs/guides/database/overview)
- [Supabase Table Editor — Columns](https://supabase.com/docs/guides/database/tables)

---

## [IH-002] Configurar `meta_waba_id` en el tenant de Supabase

**Estado**: ⏳ PENDIENTE  
**Responsable**: Operador con acceso a Supabase Dashboard  
**Fecha identificada**: 2026-04-07

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
