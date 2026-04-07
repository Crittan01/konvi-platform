# Guía de Setup — Entorno de Desarrollo

## Sobre Esta Máquina

Esta VM es **100% dedicada** al proyecto Commerce Ops Platform (ambiente de pruebas/desarrollo).  
No se usa `venv` — los paquetes Python se instalan **a nivel de sistema** con `sudo pip3`.

---

## Prerequisitos del Sistema (DNF)

```bash
# Instalar herramientas de sistema requeridas
sudo dnf install -y postgresql     # Cliente psql para debug de DB
sudo dnf install -y python3-devel  # Headers Python para paquetes compilados
sudo dnf install -y libpq-devel    # Headers libpq para psycopg2
sudo dnf install -y gcc            # Compilador C para extensiones nativas
sudo dnf install -y git            # Control de versiones
sudo dnf install -y nodejs npm     # Runtime de Node.js (para pnpm / Next.js)
```

## Dependencias Python del Proyecto (Sistema)

Los servicios backend usan Python 3.9+ instalado en el sistema.  
Instalar una única vez:

```bash
sudo pip3 install \
  supabase==2.28.3 \
  psycopg2-binary \
  google-generativeai \
  httpx \
  pydantic \
  python-dotenv \
  fastapi \
  uvicorn[standard] \
  python-multipart
```

> **Nota**: No se usa `venv` en esta máquina. Si en el futuro el proyecto se mueve a otra máquina
> (staging/producción), usar `venv` o contenedores Docker por aislamiento.

## pnpm (Gestor de Paquetes Node)

```bash
# Instalar pnpm globalmente
npm install -g pnpm

# Instalar dependencias del monorepo (una sola vez desde raíz)
cd /home/ansible/workspaces/commerce-ops-platform
pnpm install
```

## Variables de Entorno

El archivo `.env` está en la raíz del proyecto y NO se versiona en git.

```bash
# Verificar que .env existe y tiene las variables requeridas
cat .env.example  # Ver qué variables se necesitan
```

Variables requeridas para desarrollo local:

| Variable | Descripción |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | URL del proyecto Supabase |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Anon key para el Frontend |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key para los workers backend |
| `META_APP_SECRET` | App Secret de Meta (HMAC signing) |
| `META_VERIFY_TOKEN` | Token propio para verificación del webhook |
| `META_ACCESS_TOKEN` | Token de acceso a la Graph API de Meta |
| `WHATSAPP_PHONE_ID` | Phone Number ID del número de prueba Meta |
| `GEMINI_API_KEY` | API Key de Google Gemini |
| `DATABASE_URL` | Connection string PostgreSQL de Supabase |
| `SUPABASE_PROJECT_REF` | Referencia del proyecto Supabase |
| `SUPABASE_DB_PASSWORD` | Password de la base de datos |
| `ALLOWED_ORIGINS` | Dominios permitidos para CORS (ej: `http://localhost:3000`) |
| `POLL_INTERVAL_SECONDS` | Intervalo del worker en segundos (default: `3`) |
| `GEMINI_MODEL` | Modelo de Gemini a usar (default: `gemini-1.5-flash`) |

---

## Comandos de Desarrollo

### Frontend (Next.js)

```bash
# Desde la raíz del monorepo
pnpm --filter web dev

# Accesible en: http://localhost:3000
```

### WhatsApp Connector (FastAPI)

```bash
cd services/connector-whatsapp
uvicorn main:app --reload --port 8000

# Health check: http://localhost:8000/health
# Webhook: http://localhost:8000/api/v1/whatsapp/webhook
```

### AI Orchestrator (Worker)

```bash
cd services/ai-orchestrator
# Asegúrate de que el .env está cargado
export $(grep -v '^#' ../../.env | xargs)
python3 main.py
```

### Core API (FastAPI)

```bash
cd services/api
uvicorn main:app --reload --port 8001

# Health check: http://localhost:8001/health
```

---

## Conectar Meta Webhook Localmente (Tunnel SSH a Internet)

Para que Meta pueda enviar webhooks a tu máquina local, necesitas un túnel HTTPS público.
Usamos **Pinggy** (sin registro requerido, nativo SSH):

```bash
# Terminal 1: Iniciar el conector de WhatsApp
cd services/connector-whatsapp
uvicorn main:app --port 8000

# Terminal 2: Crear el túnel público
ssh -p 443 -R0:localhost:8000 a.pinggy.io
# Copiará en pantalla una URL tipo: https://abcd1234.auto.pinggy.link
```

Luego ir a Meta Developers → Tu App → WhatsApp → Configuration → Edit Webhook:
- **Callback URL**: `https://abcd1234.auto.pinggy.link/api/v1/whatsapp/webhook`
- **Verify Token**: El valor de `META_VERIFY_TOKEN` en tu `.env`

Ver pasos detallados: `docs/setup/meta_whatsapp_manual_setup.md`

---

## Aplicar Migraciones SQL a Supabase

> ⚠️ **RESTRICCIÓN DE RED**: Esta VM no puede conectar directamente a la base de datos
> Supabase Cloud via TCP (firewall de salida). Las migraciones SQL deben aplicarse 
> **manualmente** via el SQL Editor del Dashboard de Supabase.

Ver procedimiento completo en: `docs/operations/HUMAN_INTERVENTIONS.md` → [IH-001]

**Migraciones aplicadas:**
- `20260406181235_initial_schema.sql` ✅
- `20260406181236_catalog_schema.sql` ✅
- `20260406181237_conversational_schema.sql` ✅
- `20260406181238_rls_policies.sql` ✅
- `20260406181239_custom_claims_trigger.sql` ✅
- `20260407200700_messages_processed_flag.sql` ⏳ **Pendiente — [IH-001]**

---

## Notas de Conectividad con Supabase (Verificado)

| Conexión | Estado | Notas |
|---|---|---|
| VM → Supabase REST API (`https://...supabase.co/rest/v1`) | ✅ Funciona | Usado por todos los servicios |
| VM → Meta Graph API | ✅ Funciona | WhatsApp sender OK |
| VM → Google Gemini API | ✅ Funciona | Orchestrator OK |
| VM → Supabase DB TCP (Supavisor puerto 5432/6543) | ❌ Rechazado | Error: `Tenant or user not found` — el Supavisor rechaza psql desde esta IP |
| VM → Supabase DB TCP directo (port 5432, IPv6) | ❌ Bloqueado | Esta VM no tiene IPv6 habilitado |
| Meta → VM (webhook) | ❌ Sin IP pública | Usar Pinggy SSH tunnel |

### Por qué el Supavisor rechaza psql

Según la [documentación oficial de Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres#direct-connection):
- La conexión directa a Postgres usa **IPv6** por defecto
- El pooler Supavisor sí acepta IPv4, pero **requiere que el proyecto esté accesible desde esa IP**
- El error `"Tenant or user not found"` en el Supavisor indica que el proyecto no es enrutable desde esta IP via TCP

### Solución para migraciones DDL

La **REST API funciona perfectamente** para DML (INSERT, SELECT, UPDATE). Para DDL (ALTER TABLE, CREATE INDEX), usar el **SQL Editor del Dashboard de Supabase**.

Ver procedimiento completo en: `docs/operations/HUMAN_INTERVENTIONS.md` → [IH-001]
