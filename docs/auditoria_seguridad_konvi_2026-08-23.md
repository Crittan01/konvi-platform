# Informe de Auditoría de Seguridad OWASP Top 10

**Proyecto:** Konvi Platform
**Alcance:** Repositorio GitHub `Crittan01/konvi-platform` (rama `develop`, commit `eac46b4`, público) + Proyecto Supabase `konvi-prod` (ref `xmelwnhhphksbpdjmbbp`, PostgreSQL 17.6, us-east-1)
**Fecha:** 2026-08-23
**Metodología:** Checklist OWASP Top 10 (2021) con cobertura completa A01–A10, 0 suposiciones — cada hallazgo fue verificado contra evidencia real: código fuente (lectura íntegra de las 33 API routes de Next.js, 262 archivos Python / ~67.800 LOC en `services/`), escaneos automatizados (`bandit 1.9.4`, `pip-audit 2.10.1`, `osv-scanner v2.2.4`, `pnpm audit`), SQL en vivo contra la base de datos de producción (RLS, grants, definiciones de funciones, storage, cron, vault), advisors de seguridad de Supabase, logs de las últimas 24 h, y verificación independiente de los hallazgos críticos por el auditor principal.

## Resumen ejecutivo

| Severidad | Cantidad |
|---|---|
| 🔴 RED (Alta) | 2 |
| 🟡 YELLOW (Media) | 11 |
| 🟢 GREEN (Baja) | 17 |
| ✅ PASS (sin hallazgos) | varias categorías parciales |

**Veredicto general:** La plataforma presenta una postura de seguridad notablemente madura en código y base de datos (RLS en el 100% de las tablas, RPCs sensibles con guardas de ownership/rol verificadas, webhooks con firma, MFA AAL2, rate limiting distribuido, 0 CVEs en dependencias Python). **El riesgo crítico actual no está en el código sino en la higiene del repositorio público:** credenciales reales de producción persisten accesibles en un commit huérfano y App Secrets de Meta están en claro en el árbol actual. Hasta que se roten esos secretos y se purgue el commit, el perímetro permanece expuesto de forma activa.

## Resumen de riesgo por categoría OWASP

| ID | Categoría | Estado |
|----|-----------|--------|
| A01 | Broken Access Control | 🔴/🟡 (vía A02 expone todo; MeLi webhook YELLOW; defensa en profundidad web) |
| A02 | Cryptographic Failures | 🔴 **2 hallazgos RED** (secretos en repo público) |
| A03 | Injection | 🟢 (interpolación PostgREST `.or_()` intra-tenant) |
| A04 | Insecure Design | 🟡 (MFA fail-open; rate limit delegado) |
| A05 | Security Misconfiguration | 🟡 (35 funciones search_path mutable; OpenAPI público) |
| A06 | Vulnerable Components | 🟡 (xlsx 2 CVE HIGH; transitivas Python sin lock) |
| A07 | Authentication Failures | 🟡 (leaked password protection off; 1/3 usuarios con MFA; password change sin re-auth) |
| A08 | Integrity Failures | 🟡 (CI sin `permissions:`; lock sin hashes) |
| A09 | Logging & Monitoring | 🟢 (IP spoofeable en audit trail; PII en logs) |
| A10 | SSRF | 🟡 (allowlist MeLi sobre header spoofeable) |

---

## Hallazgos (ordenados por severidad descendente)

### 🔴 [RED-1] [A02] — Commit huérfano público conserva `.env` con credenciales REALES de producción

- **Ubicación:** commit `be739a40314943d6c0dc7ef7fca04a750b2e327c` (2026-04-07), accesible vía la URL raw de GitHub para ese SHA + `/.env` (verificado en vivo por el auditor principal el 2026-08-23; re-verificado 2026-08-28, HTTP 200. URL exacta redactada 2026-08-29 — el repo es público y el enlace directo facilita el acceso al leak; reconstruible trivialmente a partir del SHA).
- **Evidencia (valores redactados):**
  ```
  NEXT_PUBLIC_SUPABASE_URL="https://xmel…***"        ← proyecto konvi-prod
  NEXT_PUBLIC_SUPABASE_ANON_KEY="eyJhbGc…***"        ← JWT legacy anon (exp 2036)
  SUPABASE_SERVICE_ROLE_KEY="eyJhbGc…***"            ← bypass TOTAL de RLS
  DATABASE_URL="postgre…***"                         ← password embebido
  SUPABASE_DB_PASSWORD="9Go3e0C…***"
  META_VERIFY_TOKEN="commerc…***"
  META_APP_SECRET="9d6ef4c…***"                      ← 32 hex
  ```
- **Matiz verificado:** la rama `develop` actual ya eliminó/redactó el `.env`, pero el objeto git huérfano sigue servido por GitHub. Estado de rotación verificado por el auditor: la **legacy anon key figura `disabled: true`** en el proyecto (consulta `get_publishable_keys` 2026-08-23) y los docs internos afirman que la service_role legacy fue desactivada y la DB password reseteada (2026-08-19). **Sin evidencia de rotación de `META_APP_SECRET` / `META_VERIFY_TOKEN` ni de purga del commit.**
- **Impacto:** con el App Secret de Meta se falsifica `X-Hub-Signature-256` (inyección de mensajes/pedidos falsos por WhatsApp) y se pueden obtener tokens de app vía Graph API. Las claves Supabase históricas hoy darían 401, pero cualquier credencial no rotada del lote sigue comprometida. Exposición **pública y anónima**.
- **Fix (orden obligatorio):**
  1. **Rotar hoy** en Meta for Developers el App Secret y verify token de la app afectada (invalida el valor filtrado aunque el commit siga existiendo).
  2. Solicitar a GitHub Support el purge del objeto huérfano: https://support.github.com/contact/private-information (un `filter-repo` + force-push NO elimina objetos ya indexados/cacheados por SHA).
  3. Como defensa en profundidad: `git filter-repo --path .env --invert-paths` + force-push coordinado (tarea H8 ya documentada en `.context/01-state.md`).
  4. Confirmar por escrito que la DB password y cualquier secreto de proveedor del lote fueron rotados (Wompi, Telegram, MeLi, Resend, Aveonline aparecen como variables en ese `.env`).

### 🔴 [RED-2] [A02] — App Secrets de Meta (32-hex) en claro en el ÁRBOL ACTUAL (docs + tests)

- **Ubicación:**
  - `tests/test_meta_hmac_model_b.py:50-51` — etiquetados como `# mock value`:
    ```python
    KONVI_DEV_SECRET = "41eb550c…***"  # mock value
    KAIU_SECRET = "1895ac21…***"      # mock value
    ```
  - `docs/_archive/research/audit-finiquito-2026-05-31.md:2247,2347` — el mismo par de valores descritos en contexto operativo real (rollback de webhooks, restore de `tenant_integrations`).
- **Verificación independiente del auditor principal (2026-08-23):** ambos valores presentes en el árbol actual de `develop`; formato exacto de Meta App Secret (32 hex); el doc los describe en uso productivo real; son **distintos** al `META_APP_SECRET` del `.env` filtrado (lote adicional comprometido).
- **Impacto:** falsificación de firmas de webhooks de WhatsApp (inyección de conversaciones/pedidos) y obtención de app access tokens. Repo público → exposición activa hoy.
- **Fix:**
  1. Rotar ambos App Secrets en Meta for Developers hoy (Konvi Platform App y KAIU Chat).
  2. Reemplazar en tests por valores sintéticos inequívocos:
     ```python
     KONVI_DEV_SECRET = "0" * 32  # sintético — NUNCA un secret real
     KAIU_SECRET = "1" * 32
     ```
  3. Redactar los valores en el doc archivado.
  4. Añadir gate CI (gitleaks/trufflehog o regla en `scripts/validate.sh`) que falle ante `[0-9a-f]{32}` fuera de allowlist.

### 🟡 [YELLOW-3] [A01/A10] — Webhook MercadoLibre: autenticación solo por IP allowlist resuelta desde headers spoofeables

- **Ubicación:** `services/api/api/routers/meli_webhook.py:896` (endpoint), `:79-96` (allowlist), `:206-215`, `:222-228`; `services/api/api/dependencies/security.py:119-145`.
- **Evidencia:**
  ```python
  @router.post("/webhook", dependencies=[Depends(_verify_meli_origin)])
  def _verify_meli_origin(request: Request, supabase=None) -> None:
      ip = _extract_request_ip(request)
      if ip not in _ALLOWED_MELI_IPS:
          raise HTTPException(status_code=403, detail="Origen no autorizado")
  ```
  MeLi no firma sus webhooks (confirmado en comentario `:288`). La IP del cliente se lee de `cf-connecting-ip` o del primer valor de XFF — headers que un atacante puede enviar él mismo si el origen Render (`*.onrender.com`) es alcanzable directamente sin pasar por Cloudflare (topología no verificada, admite el propio código, "T4-01").
- **Impacto:** inyección de eventos webhook MeLi falsos → reprocesamiento de órdenes/stock para un tenant cuyo `user_id` MeLi conozca el atacante. Acotado porque el contenido se re-fetchea de la API real de MeLi (no forjable) y hay regex estricto de `resource` + dedup.
- **Fix:**
  ```python
  # 1) Infra: bloquear tráfico directo al origen Render (Cloudflare Authenticated
  #    Origin Pull / firewall), de modo que cf-connecting-ip solo lo fije CF.
  # 2) Código: fail-closed si el header confiable no está configurado:
  async def _verify_meli_origin(request: Request, supabase=None) -> None:
      ip = _extract_request_ip(request)
      if ip not in _ALLOWED_MELI_IPS:
          _check_meli_origin_alert(ip)
          raise HTTPException(status_code=403, detail="Origen no autorizado")
      if not os.getenv("TRUSTED_CLIENT_IP_HEADER"):
          logger.error("meli_webhook: TRUSTED_CLIENT_IP_HEADER ausente — fail-closed")
          raise HTTPException(status_code=503, detail="Webhook no configurado")
  # 3) Antes de mutar DB, validar que el GET del resource a MeLi retorne el seller esperado.
  ```

### 🟡 [YELLOW-4] [A06] — `xlsx@0.18.5` con 2 CVE HIGH parseando archivos subidos por usuarios

- **Ubicación:** `apps/web/package.json:41`; uso en `apps/web/app/dashboard/(products)/catalog/_components/mass-importer.tsx:134`; allowlist en `osv-scanner.toml:14-21`.
- **Evidencia:** `pnpm audit` y `osv-scanner v2.2.4` confirman:
  - **CVE-2023-30533 / GHSA-4r6h-8v6p-xvw6** — Prototype Pollution SheetJS CE `<0.19.3` (CVSS 7.8)
  - **CVE-2024-22363 / GHSA-5pgg-2g8v-p4x9** — ReDoS SheetJS CE `<0.20.2` (CVSS 7.5)
  `xlsx-js-style@^1.2.0` (package.json:42) es un fork no mantenido sobre la misma línea vulnerable.
- **Impacto:** un XLSX malicioso importado por un operador ejecuta prototype pollution en su sesión autenticada / congela la pestaña. Mitigación parcial: corre client-side y la CSP por-nonce limita escalada a XSS.
- **Fix:**
  ```jsonc
  // apps/web/package.json — SheetJS CE ya no publica fixes en npm; usar el tarball oficial:
  "xlsx": "https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz",
  // eliminar "xlsx-js-style" (o migrar estilos a la API nueva)
  ```
  Alternativa: migrar el importador a `exceljs` (mantenido) parseando en servidor. Después: retirar las 2 entradas de `osv-scanner.toml` y limpiar los 6 ignores obsoletos que el scanner reporta como *unused*.

### 🟡 [YELLOW-5] [A01] — Vista `payments_safe` es SECURITY DEFINER (advisor ERROR, verificado)

- **Ubicación (BD viva):** vista `public.payments_safe` — confirmada por advisor de seguridad de Supabase (lint 0010, nivel ERROR) y por `pg_get_viewdef`:
  ```sql
  SELECT id, tenant_id, order_id, provider, checkout_url, amount_in_cents,
         currency, status, wompi_status, created_at, updated_at
  FROM payments
  WHERE tenant_id = app_current_tenant();
  ```
  Tiene `security_barrier=true` y filtra por tenant, pero se evalúa con los permisos del **creador** de la vista, no del consultante; y `app_current_tenant()` da prioridad a `current_setting('app.current_tenant_id', true)` (GUC de sesión) sobre el JWT.
- **Impacto:** patrón frágil: si alguna vía futura permite fijar el GUC `app.current_tenant_id` (RPC mal escrita, worker compartiendo sesión), la vista devuelve pagos de otro tenant. Los grants a `authenticated` incluyen DELETE/INSERT/SELECT/UPDATE sobre la vista (`information_schema.role_table_grants`, verificado).
- **Fix:**
  ```sql
  ALTER VIEW public.payments_safe SET (security_invoker = true);
  REVOKE INSERT, UPDATE, DELETE ON public.payments_safe FROM authenticated;
  ```
  Y endurecer `app_current_tenant()` para contextos de API: preferir el claim JWT y usar el GUC solo cuando `auth.uid() IS NULL` (workers):
  ```sql
  CREATE OR REPLACE FUNCTION public.app_current_tenant() RETURNS uuid
  LANGUAGE sql STABLE AS $$
    SELECT CASE
      WHEN auth.uid() IS NOT NULL
        THEN (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid
      ELSE NULLIF(current_setting('app.current_tenant_id', true), '')::uuid
    END
  $$;
  ```

### 🟡 [YELLOW-6] [A07] — Protección contra contraseñas filtradas desactivada + MFA solo en 1/3 usuarios

- **Ubicación (BD viva / config Auth):** advisor `auth_leaked_password_protection` (WARN, verificado 2026-08-23): *"Leaked password protection is currently disabled"*. Además, consulta directa sobre `auth.users` + `auth.mfa_factors`: **3 usuarios totales, solo 1 con factor TOTP verificado**.
- **Impacto:** contraseñas comprometidas en breaches públicos (HaveIBeenPwned) pueden registrarse/reusarse; los 2 usuarios sin MFA (posiblemente owners) dependen solo de contraseña. Combinado con YELLOW-8 (cambio de password sin re-auth), una credencial robada basta para tomar la cuenta.
- **Fix:**
  1. Activar en Supabase Dashboard → Authentication → Password Protection: *Leaked password protection* (https://supabase.com/docs/guides/auth/password-security#password-strength-and-leaked-password-protection).
  2. Elevar `minimum_password_length` a ≥ 12 y exigir complejidad.
  3. Exigir enrollment MFA a todo owner/manager (el gate AAL2 ya existe en el proxy web — `apps/web/proxy.ts` — pero el enrollment es opcional; hacerlo obligatorio por política o por flag `mfa_required` en `tenant_users`).

### 🟡 [YELLOW-7] [A04/A07] — Gate MFA AAL2 del proxy web es fail-open ante fallo del check

- **Ubicación:** `apps/web/proxy.ts:148-160`.
- **Evidencia:**
  ```ts
  } catch (e) {
    // Decisión FAIL-OPEN (NO cambiar a fail-closed): si el check de AAL falla
    // (network/timeout/outage de Supabase Auth) se deja pasar el request...
    console.error('[proxy] AAL2 check falló — fail-open ...', ...)
  }
  ```
- **Impacto:** durante un outage de Supabase Auth, **todo** el enforcement MFA queda desactivado de facto para `/dashboard/*` y `/api/*` (sesiones AAL1 operan sin TOTP). Decisión documentada como deliberada; se recomienda acotarla.
- **Fix (sin cambiar la decisión de disponibilidad):** degradar a solo-lectura durante el fail-open:
  ```ts
  } catch (e) {
    console.error('[proxy] AAL2 check falló — fail-open:', e instanceof Error ? e.message : e)
    if (request.method !== 'GET' && request.method !== 'HEAD') {
      return NextResponse.json(
        { detail: 'Verificación MFA temporalmente no disponible. Reintenta.' },
        { status: 503 })
    }
    // + alerta/métrica si el fallo persiste > N requests
  }
  ```

### 🟡 [YELLOW-8] [A07] — Cambio de contraseña sin re-autenticación

- **Ubicación:** `apps/web/app/dashboard/(settings-group)/settings/security/page.tsx:106-126`.
- **Evidencia:**
  ```ts
  async function changePassword(formData: FormData) {
    'use server'
    const sb = await createClient()
    const { data: { user: u } } = await sb.auth.getUser()
    if (!u) redirect('/login')
    ...
    const { error } = await sb.auth.updateUser({ password })  // sin pedir password actual
  ```
- **Impacto:** con una sesión secuestrada (cookie robada / equipo desatendido) un atacante cambia la contraseña y toma la cuenta sin conocer la credencial actual. Para usuarios sin MFA (2 de 3 hoy) no hay segunda barrera.
- **Fix:**
  ```ts
  const current = (formData.get('current_password') as string)?.trim()
  if (!current) redirect('/dashboard/settings/security?pwd_error=' +
    encodeURIComponent('Ingresa tu contraseña actual.'))
  const { error: reauthErr } = await sb.auth.signInWithPassword({
    email: u.email!, password: current })
  if (reauthErr) redirect('/dashboard/settings/security?pwd_error=' +
    encodeURIComponent('La contraseña actual no es correcta.'))
  const { error } = await sb.auth.updateUser({ password })
  ```
  (o `supabase.auth.reauthenticate()` si la versión GoTrue lo soporta). Alinear también `supabase/config.toml:218` (`secure_password_change = true`) para que un `config push` no degrade prod.

### 🟡 [YELLOW-9] [A08] — Workflow CI sin bloque `permissions:` (GITHUB_TOKEN con default del repo)

- **Ubicación:** `.github/workflows/ci.yml` (todo el archivo).
- **Evidencia:** los 5 jobs (`changes`, `validate`, `py-core`, `db-harness`, `build-web`) heredan los permisos por defecto del token; el repo es **público** y el trigger `pull_request` ejecuta código de forks. Positivos verificados: acciones pineadas por SHA, sin `pull_request_target`, sin `secrets.*` en logs. Branch protection no verificable vía API (401 sin auth).
- **Impacto:** si el default es read-write, un PR malicioso obtiene token con escritura sobre contents/PRs.
- **Fix:**
  ```yaml
  # nivel raíz de .github/workflows/ci.yml
  permissions:
    contents: read
  ```
  Y en Settings → Actions → *Workflow permissions* → read-only.

### 🟡 [YELLOW-10] [A06/A08] — Dependencias Python: solo directas pineadas; transitivas flotan sin hashes

- **Ubicación:** `services/{api,ai-orchestrator,connector-whatsapp}/requirements.txt`; build en `render.yaml:138` (`pip install -r requirements.txt`); `scripts/validate.sh:381` (allowlist pip-audit con 5 PYSEC de starlette ya obsoletas).
- **Evidencia:** instalación en venv limpio resolvió hoy `starlette 1.6.0` para `fastapi==0.139.0` — el build no es reproducible y un release transitivo malicioso entra sin gate. Resultado del escaneo: **0 CVEs** en directas y en el árbol completo resuelto (pip-audit 2.10.1, verificado).
- **Impacto:** riesgo supply-chain: paquete transitivo comprometido se instala en prod sin cambio en el repo.
- **Fix:**
  ```bash
  pip-compile --generate-hashes services/api/requirements.txt -o services/api/requirements.lock
  # render.yaml buildCommand:
  pip install --require-hashes -r services/api/requirements.lock
  ```
  Auditar el lock (no solo el `.txt`) en `validate.sh` y borrar los 5 `--ignore-vuln` obsoletos.

### 🟡 [YELLOW-11] [A05] — 35 funciones con `search_path` mutable (advisor WARN, verificado)

- **Ubicación (BD viva):** advisor `function_search_path_mutable` ×35, incl. `match_kb_documents`, `fn_variation_available_stock`, `app_current_tenant` (implícito), `touch_updated_at`, `fn_document_hash`, etc.
- **Evidencia:** consulta `pg_proc` — las funciones SECURITY DEFINER sí tienen `proconfig` con `search_path` fijado (verificado), pero ~35 funciones SECURITY INVOKER (triggers y helpers) no lo tienen.
- **Impacto:** bajo-medio: un objeto malicioso con nombre colisionante en un schema precedente del `search_path` del rol ejecutante podría ser invocado (schema injection). Las SECURITY DEFINER están cubiertas; las INVOKER heredan el path del caller.
- **Fix (patrón, aplicar en una migración de hardening):**
  ```sql
  ALTER FUNCTION public.match_kb_documents(vector, double precision, integer, uuid, text)
    SET search_path = 'public', 'extensions', 'pg_catalog';
  -- repetir para las 35; script generador:
  SELECT format('ALTER FUNCTION %s(%s) SET search_path = ''public'', ''pg_catalog'';',
                p.proname, pg_get_function_identity_arguments(p.oid))
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
  WHERE n.nspname = 'public' AND p.proconfig IS NULL;
  ```

### 🟡 [YELLOW-12] [A01] — Bucket de Storage `tenant-media` es público

- **Ubicación (BD viva):** `storage.buckets`: `tenant-media` con `public = true` (verificado). Los otros 3 buckets (`consent-evidence`, `offboarding-archive`, `tenant-inbox-media`) son privados con policies por tenant correctas (incl. `with_check` de escritura, verificado).
- **Impacto:** cualquier objeto de `tenant-media` es legible por URL pública sin autenticación, incluido el prefijo `inbox-attachments/` si se usa ahí (adjuntos de clientes → PII). Los nombres con UUID reducen enumerabilidad, pero no hay control de acceso.
- **Fix:**
  ```sql
  UPDATE storage.buckets SET public = false WHERE name = 'tenant-media';
  ```
  Migrar la entrega de imágenes a URLs firmadas (el frontend ya usa signed URLs para otros buckets) o mover adjuntos de inbox a `tenant-inbox-media` (privado, ya existente).

### 🟡 [YELLOW-13] [A01] — Server action `uploadConsentEvidence` no valida sesión ni tenant del caller

- **Ubicación:** `apps/web/app/dashboard/(sales)/contacts/_components/helpers/upload-evidence.ts:43-87`.
- **Evidencia:** `'use server'` → endpoint invocable con argumentos arbitrarios; `tenantId` llega del cliente y **no** se contrasta con la sesión (sin `getUser()`). La única barrera cross-tenant es la policy de Storage — **verificada por el auditor principal como correcta** (`consent_evidence_tenant_write` con `with_check` por tenant activo + owner/manager). Se mantiene como YELLOW de defensa en profundidad: una regresión de esa policy abriría escritura cross-tenant de evidencia Habeas Data.
- **Fix:**
  ```ts
  export async function uploadConsentEvidence(
    formData: FormData, contactId: string, _tenantId: string,
  ): Promise<UploadEvidenceResult> {
    const sb = await createClient()
    const { data: { user } } = await sb.auth.getUser()
    const m = (user?.app_metadata ?? {}) as { tenant_id?: string }
    if (!user || !m.tenant_id) return { status: 'error', message: 'No autenticado' }
    const tenantId = m.tenant_id  // SIEMPRE derivado de sesión, ignorar el del cliente
    // ... resto igual
  }
  ```

### 🟡 [YELLOW-14] [A05] — Grants DML completos a `anon`/`authenticated` en casi todas las tablas

- **Ubicación (BD viva):** `information_schema.role_table_grants` — `anon` y `authenticated` tienen `DELETE,INSERT,SELECT,UPDATE` en ~70 tablas de `public` (solo `audit_log` limitado a `INSERT,SELECT`; `order_receipts`/`payment_reversal_requests`/`pii_access_log` a `SELECT`).
- **Matiz:** RLS está habilitado en el 100% de las tablas (0 sin RLS, verificado con `pg_class.relrowsecurity`) y las políticas son coherentes por tenant — la barrera real existe. Pero el patrón "grant todo + confiar 100% en RLS" hace que **cualquier migración que rompa una policy** sea un incidente inmediato (como muestra la historia del repo: 7 migraciones de `fix_*_rls`).
- **Impacto:** defensa en profundidad: la capa de grants no aporta nada hoy; recomendado restringir `anon` a lo estrictamente necesario.
- **Fix:**
  ```sql
  -- El frontend autenticado solo necesita SELECT + RPCs; los writes van por API:
  REVOKE INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM anon;
  -- y para authenticated, revocar DML en tablas service-only (webhook dedup, inbox,
  -- idempotency, usage_events, security_events, shadow_log, etc.):
  REVOKE INSERT, UPDATE, DELETE ON public.wompi_webhook_inbox,
    public.whatsapp_webhook_inbox, public.meli_webhook_dedup,
    public.webhook_events_seen, public.rate_limit_windows,
    public.tenant_usage_events, public.api_security_events,
    public.agentic_shadow_log, public.outbound_idempotency_cache
  FROM anon, authenticated;
  ```

---

## Hallazgos GREEN (bajos / defensa en profundidad)

### 🟢 [GREEN-15] [A03] — Interpolación de teléfono en filtros PostgREST `.or_()` sin whitelist de dígitos
- **Ubicación:** `services/ai-orchestrator/agentic/deterministic_gates.py:37`, `orchestrator.py:591,841`, `tools/shipping_quote_tool.py:1020,1048`, `services/api/api/routers/conversations.py:422`.
- **Evidencia:** `.or_(f"phone.eq.{phone},phone.eq.+{phone}")` con normalización `re.sub(r"[\s+]", "", phone)` que NO elimina `, ( ) *` → rompe la gramática del filtro `or=(...)` e inyecta condiciones OR intra-tenant (el escape cross-tenant lo bloquea el `.eq("tenant_id", …)` externo, verificado).
- **Fix:** `def normalize_phone(p): return re.sub(r"\D", "", str(p or ""))` (whitelist estricta de dígitos) y rechazar si `not phone_norm.isdigit()`.

### 🟢 [GREEN-16] [A05] — Esquema OpenAPI público en los 3 servicios Python
- **Ubicación:** `services/api/api/main.py:106`, `services/ai-orchestrator/server.py:68`, `services/connector-whatsapp/main.py:59` — FastAPI sin `docs_url=None` → `/docs`, `/redoc`, `/openapi.json` públicos sin auth.
- **Fix:**
  ```python
  _prod = os.getenv("APP_ENV") == "production"
  app = FastAPI(title="Konvi Core API",
                docs_url=None if _prod else "/docs",
                redoc_url=None if _prod else "/redoc",
                openapi_url=None if _prod else "/openapi.json", lifespan=lifespan)
  ```

### 🟢 [GREEN-17] [A05] — `/status` del orchestrator público y sin autenticación
- **Ubicación:** `services/ai-orchestrator/server.py:142-152` — expone estado del worker, métricas y posible `str(exc)` interno; sin `_require_internal_secret` (a diferencia de `/agentic/metrics`, `:195`).
- **Fix:** añadir `_require_internal_secret(request)` como primer paso del handler.

### 🟢 [GREEN-18] [A05] — Errores internos devueltos crudos al cliente
- **Ubicación:** `services/api/api/routers/integrations.py:226`, `tenant_offboarding.py:145,170,254,301`, `shipping.py:248-268`, `ai-orchestrator/server.py:218`; en web: `apps/web/app/dashboard/(products)/categories/actions.ts:38-40`, `marketplace/actions.ts:28-30`, `purchases/actions.ts:46`.
- **Fix:** patrón ya existente en el repo (`readApiError` de `claims/actions.ts:21-38`): loguear el detalle interno y devolver mensaje genérico traducido; en FastAPI, `raise HTTPException(503, detail="…genérico…")` con `logger.error(..., e)` server-side.

### 🟢 [GREEN-19] [A09] — IP spoofeable en `pii_access_log` (audit trail con valor probatorio)
- **Ubicación:** `apps/web/app/api/audit/export/route.ts:72-73` — toma el **primer** valor de `x-forwarded-for` (controlado por el cliente).
- **Fix:**
  ```ts
  const parts = (request.headers.get('x-forwarded-for') ?? '')
    .split(',').map(s => s.trim()).filter(Boolean)
  const ip = parts.length ? parts[parts.length - 1]
    : (request.headers.get('x-real-ip')?.trim() ?? null)
  ```

### 🟢 [GREEN-20] [A09] — PII en logs: email completo + asunto en notificaciones
- **Ubicación:** `services/ai-orchestrator/notifications.py:307` — `logger.info("[EMAIL][SENT] to=%s subject=%r", to, subject)` (email del comprador + asunto con nombre y nº de pedido) en logs de Render. Ley 1581.
- **Fix:**
  ```python
  def _mask_email(e: str) -> str:
      local, _, dom = (e or "").partition("@")
      return f"{local[:2]}***@{dom}" if dom else "***"
  logger.info("[EMAIL][SENT] to=%s subject_hash=%s",
              _mask_email(to), hashlib.sha256(subject.encode()).hexdigest()[:12])
  ```

### 🟢 [GREEN-21] [A04] — Sin rate limiting propio en la capa web (delegado al backend)
- **Ubicación:** `apps/web/app/api/mfa/recovery-codes/verify/route.ts:28-58` y proxies `/api/*`. El backend Python SÍ implementa rate limit distribuido (RPC `rate_limit_hit`, bucket MFA 5/min verificado en `services/api/api/dependencies/security.py:288-291`) — riesgo residual bajo, defensa en profundidad.
- **Fix (opcional):** throttle por usuario en el route handler de verify (429 tras 5 intentos / 300 s).

### 🟢 [GREEN-22] [A04] — Recovery codes MFA de 64 bits con docstring contradictorio (afirma 256)
- **Ubicación:** `services/api/api/lib/mfa_recovery_codes.py:17` vs `:57` (`secrets.token_hex(8)` = 64 bits reales).
- **Evaluación:** 64 bits single-use + bcrypt + rate-limit 5/min hace brute-force inviable; el riesgo es que alguien relaje el rate-limit confiando en "256-bit".
- **Fix:** corregir el docstring: *"Entropía 64-bit; suficiente SOLO en combinación con RL_MFA_VERIFY (5/min). NO reducir ese rate-limit sin subir a 128-bit."*

### 🟢 [GREEN-23] [A01] — Credencial interna "root cross-tenant" (`INTERNAL_SERVICE_SECRET`)
- **Ubicación:** `services/api/api/dependencies/internal_auth.py:140-160,172-173` — quien posee el secreto actúa como cualquier tenant con rol `owner` (tenant autodeclarado por header `X-Tenant-Id`). Diseño deliberado con audit trail (`_audit_internal_call`) — observación de superficie.
- **Fix (defensa en profundidad):** allowlist de paths alcanzables con internal-secret:
  ```python
  _INTERNAL_ALLOWED_PREFIXES = ("/api/v1/orders", "/api/v1/shipping", "/api/v1/internal/")
  if _verify_internal_secret(request):
      if not any(request.url.path.startswith(p) for p in _INTERNAL_ALLOWED_PREFIXES):
          raise HTTPException(403, detail={"code": "INTERNAL_PATH_NOT_ALLOWED"})
  ```

### 🟢 [GREEN-24] [A02] — MD5 en selección de mensajes (Bandit B324, no-criptográfico)
- **Ubicación:** `services/api/api/routers/wompi_webhook.py:961`, `services/ai-orchestrator/tools/order_status_tool.py:222` — selección determinista de variante de copy, no seguridad.
- **Fix:** `hashlib.md5(..., usedforsecurity=False)` + comentario `# nosec B324`.

### 🟢 [GREEN-25] [A09] — ~70 `try/except: pass` silenciosos (Bandit B110)
- **Ubicación representativa:** `services/ai-orchestrator/agentic/dispatcher.py` (18 sitios), `agentic/tools/cart.py:284,560,589,698`, `lib/order_cancellation.py:315,328,621,816`.
- **Fix:** `except Exception as _exc: logger.debug("ctx swallow: %s", type(_exc).__name__)` — visibilidad sin cambiar la degradación segura deliberada.

### 🟢 [GREEN-26] [A01] — Redirect a `auth_url` de MeLi sin validación de destino
- **Ubicación:** `apps/web/app/dashboard/(settings-group)/integrations/_components/integrations-manager.tsx:169-179`.
- **Fix:**
  ```ts
  const u = new URL(body.auth_url)
  if (u.protocol !== 'https:' ||
      !['auth.mercadolibre.com.co', 'auth.mercadolibre.com'].includes(u.host)) {
    setMeliStartError('URL de autorización inesperada.'); return
  }
  window.location.href = u.toString()
  ```

### 🟢 [GREEN-27] [A05] — `allowedDevOrigins: ['192.168.20.5']` y `dangerouslyAllowSVG` con hosts de terceros
- **Ubicación:** `apps/web/next.config.js:99,131-133`.
- **Fix:** `allowedDevOrigins` desde env solo en development; retirar `placehold.co`/`dummyimage.com` de `remotePatterns` cuando el catálogo no use placeholders.

### 🟢 [GREEN-28] [A05] — PII real (teléfono del tenant) en docs públicos + config auth local débil + ref de prod hardcodeado
- **Ubicación:** `docs/adr/0027-*.md:5`, `docs/_archive/**` (`+57312…649` real de conversaciones KAIU); `supabase/config.toml:175,178,209,218` (`minimum_password_length = 6`, `password_requirements = ""`, `enable_confirmations = false`, `secure_password_change = false` — riesgo solo ante `config push` accidental); `scripts/_env_guard.py:51`, `apps/web/utils/supabase/client.test.ts:27` (ref de prod).
- **Fix:** redactar teléfonos a `+57312XXXX649`; endurecer config.toml (`minimum_password_length = 12`, `password_requirements = "lower_upper_letters_digits"`, `secure_password_change = true`); `PROD_REF = os.environ["KONVI_PROD_REF"]` (fail-closed).

### 🟢 [GREEN-29] [A08] — `.claude/settings.json` auto-aprueba operaciones de alto impacto
- **Ubicación:** `.claude/settings.json:1-16` — `Bash(*)`, `Write(*)`, `Edit(*)` auto-allow + `git push … develop:production` y `cp .env.prod .env` pre-aprobados.
- **Fix:** deny-by-default en el repo y mover allowlists sensibles a `.claude/settings.local.json` (gitignored).

### 🟢 [GREEN-30] [A05/A01] — 7 tablas con RLS habilitado sin políticas (deny-all) + grants residuales
- **Ubicación (BD viva, advisor lint 0008 INFO, verificado):** `bot_source_log`, `meli_webhook_dedup`, `mfa_recovery_codes`, `provider_health_alert_dedup`, `rate_limit_windows`, `whatsapp_webhook_inbox`, `wompi_webhook_inbox`.
- **Evaluación:** RLS sin policy = **deny-all para anon/authenticated** (service_role bypasa) — postura segura para tablas service-only. Riesgo: confusión operativa, no exposición.
- **Fix (higiene):** comentario en migración declarándolas service-only + aplicar YELLOW-14 (revocar DML):
  ```sql
  COMMENT ON TABLE public.wompi_webhook_inbox IS
    'service-only: RLS sin políticas a propósito (deny-all a API). Acceso vía service_role.';
  ```

### 🟢 [GREEN-31] [A02] — Secreto legacy de Vault fuera de la convención de naming por tenant
- **Ubicación (BD viva):** `vault.secrets` contiene `whatsapp_app_secret_kaiu_0fb0777e` (2026-06-22) que NO sigue el patrón `<tenant_uuid>/<provider>/<key>` del resto (8 secretos, todos del tenant `0fb0777e-…`).
- **Evaluación:** fail-closed verificado: las RPC `pgsec_*` extraen el owner de `split_part(name,'/',1)::uuid`; para este nombre la conversión falla → `v_owner NULL` → acceso denegado para `authenticated`. Solo `service_role` lo usa. Sin exposición práctica.
- **Fix (higiene):** renombrar a la convención y borrar el legacy tras migrar el consumo:
  ```sql
  SELECT vault.create_secret((SELECT decrypted_secret FROM vault.decrypted_secrets
     WHERE name='whatsapp_app_secret_kaiu_0fb0777e'),
     '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9/whatsapp/app_secret_legacy', 'migrado');
  -- actualizar el lector en services/ y luego:
  DELETE FROM vault.secrets WHERE name='whatsapp_app_secret_kaiu_0fb0777e';
  ```

---

## Cobertura completa A01–A10 (estado por categoría)

| ID | Categoría | Estado | Evidencia clave |
|----|-----------|--------|-----------------|
| A01 | Broken Access Control | 🟡 | RLS en 100% de tablas `public` (0 sin RLS, verificado `pg_class`); políticas tenant-isolation coherentes (`tenant_id = app_current_tenant()` muestreado en tenants/orders/payments/contacts/audit_log); 33/33 API routes web con verificación de sesión (3 públicas justificadas); RBAC owner/manager/operator consistente. Hallazgos: MeLi webhook (Y3), payments_safe secdef (Y5), tenant-media público (Y12), uploadConsentEvidence (Y13), grants amplios (Y14). |
| A02 | Cryptographic Failures | 🔴 | RED-1/RED-2 (secretos en repo público). En código y BD: JWT ES256 JWKS + audience, bcrypt en recovery codes y webhook secrets, `hmac.compare_digest` en comparaciones, credenciales de proveedores en Supabase Vault (8 secretos, nunca en tablas), HTTPS/TLS en todos los servicios, 0 secretos hardcodeados en código (15+ greps). |
| A03 | Injection | 🟢 | 0 SQL de concatenación (100% PostgREST/RPC parametrizado en Python y supabase-js en web); 0 `subprocess`/`os.system`/`shell=True`/`eval`/`exec`/`pickle` (Bandit limpio en esas reglas); XSS: 2 `dangerouslySetInnerHTML` seguros (escape previo + whitelist de URLs); CSV export con neutralización de fórmulas; media proxy con allowlist MIME + `nosniff`. Hallazgo: `.or_()` intra-tenant (G15). |
| A04 | Insecure Design | 🟡 | Positivo: rate limiting distribuido (RPC `rate_limit_hit` + buckets MFA 5/min, offboarding 1/día), idempotency en money-movement (Wompi/MeLi/Resend dedup verificado), validación monto/moneda pre-confirmación, confirmación `ELIMINAR <tenant>` en cierre, caps en batch. Hallazgos: MFA fail-open (Y7), rate limit web delegado (G21), docstring entropía (G22). |
| A05 | Security Misconfiguration | 🟡 | Positivo: security headers + CSP por-nonce `'strict-dynamic'` (web y API), HSTS, CORS con orígenes explícitos, body-cap 2MB, errores sin stack traces, `render.yaml` 100% `sync: false` para secretos, `.env.example` ejemplar (100% placeholders). Hallazgos: 35 search_path mutables (Y11), OpenAPI público (G16), `/status` sin auth (G17), errores crudos (G18), config.toml débil (G28). |
| A06 | Vulnerable Components | 🟡 | pip-audit: **0 CVEs** (3 servicios, directas + árbol transitivo resuelto); pnpm audit / osv-scanner: **2 HIGH** ambas en `xlsx@0.18.5` (Y4); Dependabot activo con cooldown; lockfiles bajo VCS. Deuda: transitivas Python sin lock/hashes (Y10), ignores obsoletos en osv-scanner.toml. |
| A07 | Authentication Failures | 🟡 | Positivo: MFA TOTP con gate AAL2 en `/dashboard` y `/api/*`, recovery codes bcrypt single-use con consumo atómico, state OAuth MeLi firmado HMAC + nonce single-use + TTL, sin enumeración de usuarios en errores, revocación de sesiones al remover miembros. Hallazgos: leaked password protection OFF (Y6), 1/3 usuarios con MFA (Y6), password change sin re-auth (Y8), MFA fail-open (Y7). |
| A08 | Integrity Failures | 🟡 | Positivo: webhooks con firma verificada en todos los proveedores (Meta HMAC per-tenant, Wompi checksum SHA256 + compare_digest, Resend svix anti-replay, Telegram secret-token, Aveonline bcrypt con rotación), acciones CI pineadas por SHA, `--frozen-lockfile`, sin assets CDN sin SRI. Hallazgos: CI sin `permissions:` (Y9), lock Python sin hashes (Y10), `.claude/settings.json` (G29). |
| A09 | Logging & Monitoring | 🟢 | Positivo: audit trail extenso (`audit_log`, `pii_access_log`, `consent_audit_log`, `api_security_events`, `credential_access_log`, `compliance_enforcement_log` — append-only con triggers que bloquean UPDATE/DELETE, verificado en BD), pg_cron de retención activo (7 jobs), logs 24h sin patrones de ataque (133 auth logs, solo `/user` 200; 0 ráfagas de 401). Hallazgos: IP spoofeable (G19), email en logs (G20), except-pass silenciosos (G25). |
| A10 | SSRF | 🟡 | Positivo: 0 fetch de URLs arbitrarias de usuario (hosts fijos env/config verificados en web y Python); `media_id`/resource MeLi con regex anti path-traversal; descargas Meta solo desde `META_BASE_URL`. Hallazgo: allowlist MeLi bypassable si el origen Render acepta tráfico directo (Y3). |

---

## Verificaciones ejecutadas (trazabilidad de la auditoría)

**GitHub (código):** clon local de `develop` (`eac46b4`); lectura íntegra de las 33 route handlers de `apps/web` y de los 262 `.py` de `services/`; Bandit 1.9.4 (2 High, ambos FP documentados); pip-audit 2.10.1 ×3 requirements + árbol transitivo en venv limpio (0 CVEs); osv-scanner v2.2.4 sobre pnpm-lock (2 vulns xlsx, resto limpio); pnpm audit workspace (684 deps); 15+ greps de patrones de secretos; fetch en vivo del commit huérfano `be739a4` y grep de secretos Meta — **re-verificados por el auditor principal**.

**Supabase (BD viva `konvi-prod`):** advisors de seguridad (44 lints: 1 ERROR, 36 WARN, 7 INFO — todos revisados); `pg_policies` completo (166 políticas); `pg_class.relrowsecurity` (0 tablas sin RLS); `role_table_grants` para anon/authenticated; definición íntegra de las 12 RPC SECURITY DEFINER expuestas a `authenticated` (`pgsec_*`, `get_aveonline_credentials`, `metrics_*`, `get_tenant_team`, `app_current_role`, `log_audit_export`, `rls_auto_enable`) — guardas de ownership/rol verificadas; `pg_proc.proconfig` (search_path); vistas `payments_safe`/`vw_consent_events_unified`; storage buckets + policies (incl. `with_check`); cron jobs; `vault.secrets` (nombres, nunca valores); `auth.users`/`auth.mfa_factors` (conteos); publishable keys (legacy anon `disabled: true`); logs unificados 24h (auth/postgrest/edge).

**Limitaciones declaradas (sin suposiciones):** no se ejecutaron exploits activos (auditoría estática + lectura de BD); la validez actual de los Meta App Secrets no se probó (implicaría usarlos); branch protection de GitHub no verificable vía API sin permisos (401); la configuración de Supabase Auth (GoTrue) se evaluó vía advisors, no vía API de management.

---

## Prioridad de remediación

1. **Rotar HOY los Meta App Secrets** (Konvi Platform App + KAIU Chat) y el verify token [RED-1, RED-2] — invalida la exposición aunque el repo siga público. Es la única acción que cierra el riesgo activo de falsificación de webhooks WhatsApp.
2. **Purgar el commit huérfano `be739a4` vía GitHub Support** y confirmar rotación del resto del lote `.env` (Wompi/Telegram/MeLi/Resend/Aveonline/DB password) [RED-1].
3. **Reemplazar secretos en tests/docs por sintéticos** y añadir gate CI de detección de secretos (`[0-9a-f]{32}`, JWTs) [RED-2].
4. **Blindar el webhook MeLi**: restringir tráfico directo al origen Render + fail-closed si falta `TRUSTED_CLIENT_IP_HEADER` [YELLOW-3].
5. **Activar leaked password protection + MFA obligatorio para owner/manager** [YELLOW-6] y exigir password actual en el cambio de contraseña [YELLOW-8].
6. **`payments_safe` → `security_invoker=true`** + endurecer `app_current_tenant()` (JWT primero para usuarios) [YELLOW-5].
7. **`permissions: contents: read` en ci.yml** [YELLOW-9] y lock Python con hashes [YELLOW-10].
8. **Migrar `xlsx`** a tarball SheetJS 0.20.3 o `exceljs`; limpiar ignores obsoletos [YELLOW-4].
9. **Storage `tenant-media` → privado** + signed URLs [YELLOW-12]; `uploadConsentEvidence` derivando tenant de sesión [YELLOW-13].
10. **Migración de hardening DB:** fijar `search_path` en las 35 funciones [YELLOW-11] y revocar DML innecesario de `anon`/`authenticated` en tablas service-only [YELLOW-14, GREEN-30].
11. Higiene continua: `/docs` y `/status` protegidos, errores genéricos, enmascarar emails en logs, whitelist de dígitos en `normalize_phone`, IP no spoofeable en audit trail [GREEN-15…31].

---

*Nota metodológica: esta auditoría aplica el checklist OWASP Top 10 como herramienta de revisión sistemática. No sustituye un pentest profesional. Para un sistema con dinero en movimiento (Wompi) y PII bajo Ley 1581, se recomienda complementar con pentest dinámico anual.*
