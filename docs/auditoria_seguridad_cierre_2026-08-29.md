# Cierre de Auditoría de Seguridad OWASP 2026-08-23

**Fecha de cierre:** 2026-08-29
**Documento base:** [`auditoria_seguridad_konvi_2026-08-23.md`](./auditoria_seguridad_konvi_2026-08-23.md) (2 RED · 11 YELLOW · 17 GREEN)
**Método:** cada hallazgo fue **re-validado contra el código/DB reales** antes de tocar nada. Los que no se confirmaron se marcan NO CONFIRMADO con la evidencia; los que requieren acción fuera del repo quedan en §3 (checklist externo). Fixes de BD en la migración forward-only `supabase/migrations/20260828120000_owasp_20260823_db_fixes.sql` (aplicada y verificada en STG local; pendiente deploy a PRD).

## 1. Estado por hallazgo

### RED

| ID | Estado | Resolución |
|---|---|---|
| RED-1 (`.env` en commit huérfano público) | **CONFIRMADO — sigue expuesto** (HTTP 200 verificado 2026-08-28) | En repo: `.env` no trackeado (0 ocurrencias); los commits que lo añadieron (`be739a4`, `f6597fbc`) no pertenecen a ninguna rama actual. **El cierre real es externo** → §3 ítems 1-3. Se redactó además el puntero URL directo al leak que contenía el doc de auditoría. |
| RED-2 (App Secrets Meta 32-hex en árbol actual) | **CONFIRMADO + CORREGIDO en repo** | `tests/test_meta_hmac_model_b.py` → valores sintéticos (`"0"*32` / `"1"*32`); `docs/_archive/research/audit-finiquito-2026-05-31.md` → redactado; barrido repo-wide → 0 ocurrencias restantes; **gate anti-secretos nuevo** en `scripts/validate.sh` §4.8 (hex-32 fuera de allowlist por valor, con prueba negativa verificada). **Los valores siguen válidos hasta rotarlos en Meta** → §3 ítem 1. |

### YELLOW

| ID | Estado | Resolución |
|---|---|---|
| Y3 (webhook MeLi, IP spoofeable) | **CERRADO COMPLETO** (código + evidencia empírica) | Fail-closed en producción sin ancla IP confiable (`client_ip_trust_configured()` + 503; 5 tests). **Residual cerrado por topología (2026-08-30):** canario T4-01 corrido contra prod (`scripts/debug/t4_01_xff_canary.py test`, durable y re-runnable) — 4/4 sondas rechazadas: spoof de `cf-connecting-ip` con IP del allowlist → 403, y los logs de app muestran `rejected_origin ip=<IP REAL del cliente>`. Causa: Render está fronteado por Cloudflare (`server: cloudflare` también en `*.onrender.com`) y el edge **sobrescribe** `cf-connecting-ip`; no hay ruta al origen sin CF. **Edge-proof header DECIDIDO-NO-IMPLEMENTAR** (el residual no existe; añadirlo sería complejidad sin seguridad). |
| Y4 (`xlsx@0.18.5`, 2 CVE HIGH) | CORREGIDO | `xlsx` → tarball oficial SheetJS CE 0.20.3 (`apps/web/package.json`); `xlsx-js-style` (fork vulnerable) eliminado; `mass-importer.tsx`/`import-template.ts` migrados (API compatible, verificado empíricamente: `!cols`/`!rows` se escriben, read-back OK). osv-scanner + pnpm audit limpios; 6 ignores stale retirados. Matices: las 2 entradas de allowlist de xlsx **se conservan** (OSV no registra fixed-version para el paquete npm — razón corregida inline); la plantilla descargable pierde estilos de celda (follow-up `exceljs` documentado en `osv-scanner.toml`). |
| Y5 (`payments_safe` SECURITY DEFINER) | CORREGIDO (con desviación justificada) | REVOKE INSERT/UPDATE/DELETE sobre la vista (authenticated podía escribir `payments` bypaseando RLS vía vista auto-updatable — bypass real cerrado) + `app_current_tenant()` JWT-first (GUC solo sin JWT: workers/harness). `security_invoker=true` **NO aplicado a propósito** (documentado en la migración): la vista es DEFINER deliberada desde Track 9 A7 — con invoker un operator dejaría de ver pagos en `orders/[id]` (policy RESTRICTIVE owner-only en `payments`). |
| Y6 (leaked password protection OFF; 1/3 MFA) | PENDIENTE EXTERNO | Es config del dashboard Supabase Auth + decisión de política MFA → §3 ítems 4-5. En repo: `supabase/config.toml` endurecido (min 12, complejidad, `secure_password_change=true`, `enable_confirmations=true`) para que un `config push` no degrade prod. |
| Y7 (gate MFA AAL2 fail-open) | CORREGIDO | `apps/web/proxy.ts`: fail-open solo para GET/HEAD; métodos mutadores → 503 con mensaje claro. 2 tests nuevos en `proxy.test.ts`. |
| Y8 (cambio password sin re-auth) | CORREGIDO | `settings/security/page.tsx`: exige `current_password` + verificación `signInWithPassword` antes de `updateUser`; input "Contraseña actual" añadido al form (`set-password-form.tsx`, prop opt-in — el flujo de alta/reset no se afecta). |
| Y9 (CI sin `permissions:`) | CORREGIDO | `.github/workflows/ci.yml`: `permissions: contents: read` a nivel raíz. |
| Y10 (deps Python sin lock/hashes) | CORREGIDO | `requirements.lock` con `--generate-hashes` ×3 servicios; `render.yaml` buildCommand → `pip install --require-hashes -r requirements.lock`; `validate.sh` audita los locks; `starlette==0.49.3` pineada (FastAPI 0.139 la deja flotar hasta 1.6.0). Los 5 ignores pip-audit **NO estaban obsoletos** (verificado contra OSV: aplican a 0.49.3, fixed en 1.x) — se conservan con comentario corregido. Follow-up: starlette 1.x → §3 ítem 12. Regeneración documentada en `.context/02-stack.md`. |
| Y11 (35 funciones `search_path` mutable) | CORREGIDO (migración) | DO block sobre `pg_proc` fija `search_path = public, extensions, pg_catalog` en toda función de `public` sin config propia (respeta las que tienen, excluye extensiones). Local: 35 → 0. |
| Y12 (bucket `tenant-media` público) | PARCIAL (justificado) | No se pasa a privado: 4 componentes frontend renderizan vía `getPublicUrl` y `send-image` de WhatsApp exige URL pública (`image_link`). UPDATE queda comentado en la migración → §3 ítem 10. |
| Y13 (`uploadConsentEvidence` sin validar sesión) | CORREGIDO | Tenant derivado SIEMPRE de `auth.getUser()` + `app_metadata.tenant_id`; parámetro `tenantId` del cliente eliminado; 2 callers ajustados (`contacts/page.tsx`). |
| Y14 (grants DML amplios anon/authenticated) | CORREGIDO (migración) | `REVOKE I/U/D ON ALL TABLES FROM anon` + default privileges (causa raíz) + re-grant deliberado `INSERT ON audit_log TO anon`. `authenticated`: revocado solo en las 9 tablas service-only (el frontend SÍ escribe tablas de negocio directo vía PostgREST — verificado por grep; tocarlas rompería la consola). dbharness 316/316. Causa raíz authenticated queda abierta → §4 ítem 3. |

### GREEN

| ID | Estado | Resolución |
|---|---|---|
| G15 (`.or_()` phone sin whitelist) | CORREGIDO | Whitelist estricta de dígitos en 7 sitios (los 6 citados + `contact_cleanup._phone_variants`, que incluía el raw literal); +2 tests de inyección. |
| G16 (OpenAPI público ×3) | CORREGIDO | `docs_url`/`redoc_url`/`openapi_url = None` cuando `APP_ENV=production` en api, orchestrator y connector-whatsapp (visibles en dev). |
| G17 (`/status` orchestrator sin auth) | CORREGIDO | Protegido con `_require_internal_secret`. El health check real de Render es `/health` (verificado en `render.yaml`) → sigue público, no se rompen deploys. |
| G18 (errores crudos al cliente) | PARCIAL | Corregidos: `shipping.py` (prefijos estáticos conservados — el orchestrator los matchea), `server.py:214`, `integrations.py:1234,1385`, `categories/actions.ts` (helper `logApiError` + genéricos). NO CONFIRMADOS (ya estaban bien): `marketplace/actions.ts` y `purchases/actions.ts` (tienen `parseApiError`/`apiError`), `tenant_offboarding.py` (excepción de dominio con mensajes controlados), `integrations.py:226` (ValueError de config estático). |
| G19 (IP spoofeable en audit export) | CORREGIDO | Último valor no vacío de XFF (el anexado por el edge) + fallback `x-real-ip`. |
| G20 (PII en logs email) | CORREGIDO | Reuso de `_mask_email_addr` + `subject_hash` (sha256/12) en los 3 logs del sender de compradores. |
| G21 (sin rate limit propio en web) | NO IMPLEMENTADO (riesgo aceptado) | El backend ya rate-limita MFA 5/min distribuido (verificado); un throttle in-memory en el route web aporta poco en multi-instancia. Documentado como delegado. |
| G22 (docstring 256 vs 64 bits) | CORREGIDO | Docstring honesto (64-bit solo con RL_MFA_VERIFY 5/min) + constante muerta `CODE_BYTES` eliminada. |
| G23 (`INTERNAL_SERVICE_SECRET` root) | RIESGO ACEPTADO (evidencia) | El dual-auth cubre ~toda la superficie del API (orders/shipping/conversations/integrations/plans/offboarding) → una allowlist de paths no acotaría nada y rompería pagos/envíos. Mitigaciones vigentes: rotación PREVIOUS, `_audit_internal_call`, MFA dual-aware, RLS. |
| G24 (MD5 no criptográfico) | CORREGIDO | `usedforsecurity=False` + `# nosec B324` ×2. |
| G25 (`except: pass` silenciosos) | CORREGIDO | 19 sitios reales (dispatcher 11, cart 4, order_cancellation 4) → `logger.debug` con tipo de excepción; la degradación deliberada no cambia. |
| G26 (redirect MeLi sin validar) | CORREGIDO | Allowlist de host + `https:` + try/catch antes de `window.location.href`. |
| G27 (`allowedDevOrigins` / remotePatterns) | CORREGIDO | `allowedDevOrigins` solo en development y desde `NEXT_ALLOWED_DEV_ORIGINS` (declarada en `.env.example`). `placehold.co`/`dummyimage.com` retirados (0 usos en repo). **Caveat**: si los 16 productos KAIU con `cover_image_url` placeholder siguen en datos de prod, esas imágenes no cargarán vía next/image → §3 ítem 11. |
| G28 (PII docs + config débil + ref prod) | CORREGIDO | 13 ocurrencias del teléfono real redactadas en 9 archivos (+`.context/01-state.md`); `config.toml` endurecido; `_env_guard.py` fail-closed con `KONVI_PROD_REF` (sin default hardcodeado — **acción**: poner el ref real en los `.env*` gitignored, §3 ítem 8); `client.test.ts` con ref sintético. |
| G29 (`.claude/settings.json` auto-approve) | CORREGIDO | Eliminados `Bash(*)`, `Write(*)`, `Edit(*)`, `git push …develop:production`, `cp .env.prod .env`. Residual: `Bash(psql:*)` sigue auto-aprobado → §4 ítem 6. |
| G30 (7 tablas deny-all sin policies) | CORREGIDO (migración) | `COMMENT ON TABLE` declarándolas service-only ×7. |
| G31 (secreto Vault legacy fuera de convención) | CUBIERTO (migración defensiva) | No existe en local ni referencias en código (consumo por `secret_id`). La migración copia a `<tenant>/whatsapp/app_secret_legacy` solo si el legacy existe (prod, nombre matcheado por prefijo); DELETE pendiente tras verificar lectores → §3 ítem 9. |

## 2. Verificación ejecutada (todo verde al cierre)

- `bash scripts/validate.sh` → **18 OK / 0 ERROR / 0 WARN** (modo default, incluye gate anti-secretos §4.8 nuevo, lint, render.yaml, env contract).
- `bash scripts/validate.sh --ci` → **26 OK / 0 ERROR / 0 WARN — "Listo para despliegue"** (modo completo: suite pytest + py-core + dbharness gates + osv-scanner + ruff 198 ≤ baseline 202).
- pytest completo: **4865+ passed** (la única falla — `test_env_contract_guard` por la var `NEXT_ALLOWED_DEV_ORIGINS` sin declarar — corregida en `.env.example`; 3/3 al re-correr).
- `tests/dbharness/` → **316/316** tras la migración (incl. RLS/tenant/policies y el test de precedencia GUC/JWT).
- Vitest web → **447/447** (incl. 2 tests nuevos del proxy y los 12 del contrato de plantilla xlsx contra CE 0.20.3).
- `tsc --noEmit` limpio (se corrigió además el error pre-existente de `glow-button.tsx:65` que rompía el gate: children tipado `ReactNode` — MotionValue de `motion.button` no es renderizable por el `<span>` interno).
- pip-audit sobre los 3 locks: 0 vulns. osv-scanner sobre `pnpm-lock.yaml`: 0 issues.
- Migración aplicada a STG local 3× (idempotente, exit 0; re-corrida fija 0 objetos).

## 3. Acciones EXTERNAS pendientes (no realizables desde el repo — checklist de cierre real)

1. ~~**[RED-1/RED-2] Rotar HOY en Meta for Developers**: App Secret de *Konvi Platform App* y de *KAIU Chat* + verify token~~ **✅ VALIDADO ya rotado (2026-08-29)** — el founder rotó este mes. Evidencia activa: sonda contra nuestro propio webhook de prod (`scratch/validate_secret_rotation_20260829.py`, reusable) — los 3 secretos filtrados (2 del árbol + el del `.env` huérfano) y el verify_token filtrado son **rechazados 403** por el verificador HMAC per-tenant actual; y como el bot de prod opera, Meta firma hoy con el valor nuevo. Evidencia pasiva: `0fb0777e…/whatsapp/app_secret` en Vault prod tiene `updated_at = 2026-08-15`.
2. ~~**[RED-1] Confirmar rotación del resto del lote `.env`**~~ **✅ CERRADO con corrección de alcance (2026-08-29):** el `.env` huérfano contiene SOLO 9 variables (Supabase URL/anon/service_role/DB password/ref + Meta app_secret/verify_token + DATABASE_URL) — la auditoría **sobreestimó** el lote (Wompi/Telegram/MeLi/Resend/Aveonline NO están en ese archivo). De las presentes: legacy anon/service_role desactivadas 2026-08-19 (verificado 401), DB password reseteada 2026-08-19, Meta rechazado por la sonda. **Nada queda por rotar del lote `.env`.** (En Vault, Wompi rotó 2026-08-21 y Aveonline 2026-08-21; el bot_token de Telegram no está en el `.env` filtrado.)
3. **[RED-1] Purga del commit huérfano `be739a4`** — **DECIDIDO: SE OMITE (founder, 2026-08-29).** Justificación: la sonda del 2026-08-29 demostró que el objeto solo expone credenciales **ya muertas** (todas rotadas/desactivadas, verificado activamente) + metadatos de infra que ya son públicos en los docs. Riesgo residual: solo informativo. **Cierre definitivo planificado: eliminar el repo de GitHub y recrearlo de 0 al final** (destruye todos los objetos dangling sin Support). Checklist para el recreate (integraciones que se pierden): 4 secrets GH del nightly CI (registrados 2026-08-27) · Render auto-deploy apuntando al repo · branch protection · Dependabot. Alternativa de 1-clic si se quiere cerrar antes: pasar el repo a **privado** (mata el acceso anónimo al huérfano sin tocar nada más).
4. **[Y6] Supabase Dashboard → Auth**: ~~activar *Leaked password protection* + `minimum_password_length ≥ 12`~~ **✅ HECHO por founder 2026-08-29** (2A).
5. **[Y6] MFA**: ~~decisión founder~~ **✅ founder activó MFA en su cuenta 2026-08-29** (2/2 usuarios humanos con factor verificado; la cuenta huérfana `MJB37hupsNE0…` fue eliminada — sin tenant, sin uso desde 2026-06). Abierto aún: enforcement por código para owner/manager (opcional).
6. ~~**[Y3] Infra**: bloquear tráfico directo al origen Render + canario T4-01~~ **CERRADO POR EVIDENCIA (2026-08-30):** el canario T4-01 corrido contra prod demuestra que el origen Render también va por Cloudflare y el edge sobrescribe `cf-connecting-ip` (4/4 sondas rechazadas, app loguea la IP real). No hay residual que cerrar; edge-proof no se implementa. Canario durable: `scripts/debug/t4_01_xff_canary.py test`.
7. ~~**[Deploy] Aplicar `supabase/migrations/20260828120000_owasp_20260823_db_fixes.sql` a PRD**~~ **✅ APLICADA 2026-08-29** (smoke BEGIN/ROLLBACK → apply → repair → verificación post: 35→0 funciones sin search_path · anon DML → solo INSERT audit_log · payments_safe → solo SELECT · 9 service-only sin DML · copia GREEN-31 creada en Vault · 7 comments · `app_current_tenant` JWT-first · ledger 270=270 · health ×5 200). El smoke detectó y se corrigió: INSERT directo a `vault.secrets` no permitido en cloud → `vault.create_secret`. **Follow-up manual en dashboard:** re-correr advisors (el ERROR lint 0010 y los WARN de grants/search_path deben haber desaparecido; queda como aceptado-justificado el lint de vista secdef de `payments_safe`).
8. **[_env_guard] Poner `KONVI_PROD_REF=<ref real>` en `.env.prd-backup`** (gitignored). Sin ella, TODO script que apunte a un destino cloud no-local aborta (fail-closed deliberado).
9. ~~**[G31] Tras el deploy**: verificar que nada lee el secreto Vault legacy y ejecutar el `DELETE`~~ **✅ EJECUTADO 2026-08-29** (`DELETE FROM vault.secrets WHERE name='whatsapp_app_secret_kaiu_0fb0777e'` — verificado: 8 secretos, todos con naming convencional).
10. **[Y12] Migrar frontend a signed URLs** (4 componentes + send-image) y entonces `UPDATE storage.buckets SET public=false WHERE name='tenant-media'`.
11. **[G27] Limpiar datos de prod**: productos con `cover_image_url` de placehold.co/dummyimage.com (si siguen), pues los hosts salieron de `remotePatterns`.
12. **[Y10 follow-up] Subir a starlette 1.x** (elimina las 5 PYSEC allowlisteadas) con regresión completa previa.

## 4. Hallazgos ADICIONALES identificados durante el cierre (nuevos, no estaban en la auditoría)

1. **PII real adicional en el repo público**: nombre completo + email + CC + dirección física en `docs/_archive/reports/rev79_conversation_run.{json,md}`; otra CC en `rev109_uat_wompi_end_to_end_checklist.md`; email personal en 5 docs (incl. `docs/research/aveonline-dossier.md`, NO archivado); **logs UAT con conversaciones reales commiteados** (`scripts/uat/logs/conversation_*`); el teléfono real del founder como default/fixture en ~40 archivos de código/tests/scripts (incl. `test_hash_phone_parity.py` que lo hashea) — remediarlo es un refactor aparte (pact tests de hash parity) que requiere decisión founder. **Recomendación: tratar como candidato a GREEN futuro o subir a YELLOW dado que el repo es público.**
2. **Bucket `g8a-bucket` también público** en `storage.buckets` local — verificar si existe en prod y para qué se usa.
3. **Causa raíz YELLOW-14 para `authenticated` sigue abierta**: los default privileges otorgan I/U/D a `authenticated` en tablas FUTURAS (solo se cerró `anon`). Regla operativa: toda migración nueva con tabla service-only debe revocar explícito.
4. La URL cruda al `.env` huérfano estaba dentro del doc de auditoría (repo público) → redactada en este cierre.
5. **Fragilidad de aislamiento de tests (pre-existente)**: paquetes homónimos entre servicios + `sys.path.insert` en tests → ImportError si ciertos archivos se coleccionan en orden no alfabético (la suite en orden estándar pasa).
6. `Bash(psql:*)` sigue auto-aprobado en `.claude/settings.json` (permite SQL arbitrario contra la DB configurada) — decisión de comodidad del operador; candidato a quitar.
7. `service_role` conserva DML sobre la vista `payments_safe` (inofensivo — bypass total de todos modos; limpiable en una migración futura).
8. Ref de prod en texto plano en `docs/PLAN.md:232` y `docs/infra/environment-segregation.md` (no es credencial, pero es información de infra en repo público).
9. Docstring de `test_guc_tenant_gana_al_jwt` quedó semánticamente desactualizado tras el cambio JWT-first (describe solo el caso sin `sub`).

## 5. Notas de alcance

- ~~La migración se aplicó a STG local vía psql directo (no queda registrada en `supabase_migrations.schema_migrations` local; en PRD la registrará el flujo normal de migraciones y al ser idempotente no hay conflicto)~~ **Migración aplicada a PRD el 2026-08-29** (smoke→apply→repair; ledger 270=270; verificación post completa en §3-7). En STG local quedó aplicada vía psql directo sin registro en el ledger local (al ser idempotente, un `supabase migration up` posterior no falla).
- **Código desplegado 2026-08-29**: commit `199f4108` → push develop→production (FF) → autoDeploy ×4 live. Post-deploy verificado: health ×5 200 · API reporta version `199f4108` · OpenAPI/docs 404 en los 3 servicios (G16 live) · `/status` 401 sin secret (G17 live) · webhook MeLi 403 allowlist intacto (Y3 fail-closed operativo sin romper: `TRUSTED_CLIENT_IP_HEADER=cf-connecting-ip` ya estaba seteada en Render).
- Los secretos de Meta comprometidos fueron **validados como rotados el 2026-08-29** (sonda activa + timestamps de Vault — §3-1). La única ventana que permanece abierta es la disponibilidad del objeto git huérfano (§3-3), que ya no contiene credenciales vivas verificables.
