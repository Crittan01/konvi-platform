# Runbook — Rotación de credenciales (B2 / ritual trimestral)

**Cuándo corre:** (1) cierre del bloqueante **B2** del PLAN (primera rotación — secretos productivos quedaron en historia git el 2026-04-06, commit `be739a4`); (2) ritual trimestral (PLAN §D); (3) tras cualquier incidente de seguridad.
**Owner:** founder (dashboards) + agente (verificación desde el repo). Nada aquí modifica código.
**Fuentes:** documentación oficial citada por sección + `render.yaml` (contrato de env vars por servicio) + `docs/deployment/secrets-and-config.md`.

---

## 1. Matriz de credenciales (verificada 2026-08-13 contra `render.yaml` y código)

### A. Rotación SIN CAÍDA (el proveedor soporta doble credencial activa)

| Credencial | Dónde vive | Mecanismo sin-caída |
|---|---|---|
| `SUPABASE_SECRET_KEY` (`sb_secret_…`) | Render env: **web, connector, api, orchestrator** | Supabase soporta múltiples secret keys activas: crear → desplegar → borrar la vieja ([docs](https://supabase.com/docs/guides/api/api-keys)) |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Render env: **web** | Igual: crear publishable nueva → deploy web → borrar vieja |
| `GEMINI_API_KEY` | Render env: **web, api, orchestrator** | AI Studio soporta múltiples keys por proyecto: crear → desplegar → borrar ([docs](https://ai.google.dev/gemini-api/docs/api-key)). ⚠️ Crear la nueva como **authorized key restringida a Generative Language API** — las standard sin restricción mueren en sept-2026 |
| `RESEND_API_KEY` | Render env: **api, orchestrator** | Resend: "both keys work simultaneously" — crear → desplegar → verificar Logs → borrar ([docs](https://resend.com/docs/knowledge-base/how-to-handle-api-keys)) |
| `INTERNAL_SERVICE_SECRET` | Render env: **api, orchestrator** | **Dual soportado en código desde 2026-08-13**: publicar el saliente en `INTERNAL_SERVICE_SECRET_PREVIOUS` (var efímera, NO está en render.yaml a propósito) junto al nuevo en `INTERNAL_SERVICE_SECRET` en api+orchestrator → verificar → quitar `PREVIOUS`. Test: `tests/test_internal_secret_rotation.py` |
| Meta **System User token** (por tenant) | Vault per-tenant (`tenant_integrations` + `pgsec_*`) | Business Settings → System Users → Generate New Token → actualizar Vault → revocar el viejo. No toca App Secret ni webhooks ([docs](https://developers.facebook.com/blog/post/2022/12/05/auth-tokens/)) |

### B. Rotación CON VENTANA (sin doble credencial nativa — planificar ventana corta)

| Credencial | Dónde vive | Efecto de la rotación y mitigación |
|---|---|---|
| Meta **App Secret** (por tenant) | Vault per-tenant | Reset en App Dashboard → **los webhooks se firman con el nuevo INMEDIATAMENTE y los access tokens de la app quedan invalidados**. Ventana: 403 de HMAC + Graph API caída hasta actualizar Vault + regenerar System User token. Mitigación: hacerlo en horario valle, tener el valor nuevo listo para `pgsec_upsert_secret` antes del reset, ejecutar en ese orden inverso (Vault primero con el valor ya copiado es imposible — el valor nuevo no existe hasta el reset; la secuencia real es: reset en Meta → pegar en Vault → regenerar tokens (A) → smoke). Esperar ~2-5 min de 403 por tenant. Métrica de verificación: `GET /api/v1/whatsapp/health/metrics` (`hmac_ok`) |
| Wompi keys (por tenant): `prv_`, `pub_`, `prod_integrity_`, `prod_events_` | `tenant_integrations` + Vault per-tenant | Una por tipo por ambiente, sin overlap ([docs](https://docs.wompi.co/docs/colombia/ambientes-y-llaves/)). **Orden: events → prv → integrity → pub.** Los eventos en vuelo reintentan (~30 min, 3 h, 24 h) → la ventana queda cubierta ([eventos](https://docs.wompi.co/docs/colombia/eventos/)). Links de pago ya creados no dependen del integrity secret |
| Supabase **DB password** | Solo local/CLI (`SUPABASE_DB_PASSWORD`, scripts, `supabase db query`) | NO afecta runtime Render (PostgREST/Auth/Realtime autentican por API keys, no por esta password). Reset: Dashboard → Database → Settings ([docs](https://supabase.com/docs/guides/troubleshooting/how-do-i-reset-my-supabase-database-password-oTs5sB)). Actualizar `.env` locales |
| `MELI_CLIENT_SECRET` (plataforma) | Render env: **api** | Rotar en MeLi Dev Center invalida tokens OAuth en curso → los tenants MeLi tendrían que reconectar. **Hoy 0 tenants MeLi conectados** (verificado prod 2026-08-03) → rotación trivial ahora; con tenants activos, coordinar reconexión OAuth |
| `MFA_RECOVERY_COOKIE_SECRET` | Render env: **web** | Rotarlo invalida las cookies `mfa_recovery_session` vivas (24h) → usuarios en esa ventana re-verifican TOTP. Sin otro efecto |
| `SENTRY_AUTH_TOKEN` | Render env: **web** (build) | Reemplazar y redeploy. Sin efecto runtime |

### C. NO rotar en este ejercicio

| Credencial | Razón |
|---|---|
| Supabase **JWT secret legacy** (HS256) | Rotarlo **cierra TODAS las sesiones de usuarios** y exige rotar anon+service_role simultáneamente. El código lo usa solo como fallback opcional (JWKS ES256 es la vía primaria, `main.py:85`). Si algún día se requiere: vía [JWT Signing Keys](https://supabase.com/docs/guides/auth/signing-keys) (rotate acepta ambas; nadie se desloguea) — sesión dedicada |
| `SUPABASE_SERVICE_ROLE_KEY` (legacy JWT) | Mismo riesgo. La migración canónica es a `sb_secret_` (A0.2c): si los 4 servicios ya corren con `SUPABASE_SECRET_KEY`, la legacy se **desactiva en el dashboard** como paso final de B2 — verificar antes que ningún servicio dependa del fallback (`grep SUPABASE_SERVICE_ROLE_KEY` en env de Render) |

---

## 2. Orden de ejecución — B2 (primera rotación)

1. **Preparación** (sin efecto): confirmar acceso a dashboards (Supabase, Meta BM de cada tenant, Wompi, AI Studio, Resend, Render). Tener a la mano los comandos de verificación (§3).
2. `INTERNAL_SERVICE_SECRET` (A) — generar `openssl rand -hex 32`; poner nuevo en `INTERNAL_SERVICE_SECRET` y el saliente en `INTERNAL_SERVICE_SECRET_PREVIOUS` en **api y orchestrator**; redeploy automático; verificar §3.3; al final quitar `PREVIOUS`.
3. `SUPABASE_SECRET_KEY` (A) — crear nueva `sb_secret_` en Supabase → actualizar los 4 servicios → verificar §3.1 → borrar la vieja en el dashboard.
4. `GEMINI_API_KEY` (A) — nueva authorized key restringida → actualizar web/api/orchestrator → borrar vieja.
5. `RESEND_API_KEY` (A) — crear → actualizar api/orchestrator → verificar Logs Resend → borrar vieja.
6. Meta **System User tokens** por tenant (A) — generar → actualizar Vault → revocar viejo.
7. Wompi por tenant (B) — orden events → prv → integrity → pub, actualizando Vault tras cada paso.
8. Meta **App Secret** por tenant (B) — ventana corta, horario valle; smoke HMAC inmediato.
9. Supabase **DB password** (B) — reset + actualizar `.env` locales.
10. `MELI_CLIENT_SECRET` + `MFA_RECOVERY_COOKIE_SECRET` + `SENTRY_AUTH_TOKEN` (B, triviales hoy).
11. **M19 (con esto se desbloquea):** rotar el verify_token dev `konvi-dev-direct-2026` (expuesto en `supabase/migrations/20260622_whatsapp_model_b_backfill_konvi_dev.sql:11`): actualizar la fila del tenant dev (`tenant_integrations.credentials.verify_token`) **y** el webhook en la consola Meta del tenant dev en la misma ventana — si se hace solo un lado, el webhook del tenant dev queda roto.
12. **Paso final:** desactivar legacy `anon`/`service_role` JWT keys en Supabase (si ya nada las usa) y confirmar §3.1.
13. Cerrar fila B2 en `docs/PLAN.md` §A con fecha + evidencia; M19 en §B P2.

## 3. Verificación post-rotación

**Atajo ejecutable (recomendado):** `python3.11 scripts/admin/verify_credential_rotation.py [--internal-secret <nuevo> --tenant-id <uuid tenant>]` — corre los checks 3.1/3.3 + salud general de los 4 servicios, imprime tabla con evidencia y sale 0/1. Verificado contra prod 2026-08-13: 6/6 verde. Los pasos manuales de abajo sirven para profundizar si algún check falla.

1. **Supabase keys (3.1):** `curl -s https://konvi-api.onrender.com/health/ready` → 200 (lee DB con la key nueva); igual `konvi-connector` `/health/metrics`; web `/login` 200.
2. **Gemini/LLM:** turno de bot en sandbox o log orchestrator sin `401/403` de Generative Language API.
3. **INTERNAL_SERVICE_SECRET (3.3):** generar un payment-link o shipping-quote desde el bot sandbox (orchestrator→api con el secret nuevo) → 200; `api_security_events` con `internal_auth.ok` reciente.
4. **Meta por tenant:** `GET /api/v1/whatsapp/health/metrics` → `hmac_ok` incrementa tras un mensaje real o `scripts/uat/e2e_chat.py` per-tenant.
5. **Wompi por tenant:** transacción sandbox pequeña o verificar que el webhook de un evento de prueba pasa la firma (log `wompi_webhook` sin 401).
6. **Suite repo:** `python3.11 -m pytest tests/test_internal_secret_rotation.py tests/test_meta_hmac_model_b.py -q` verde.

## 4. Rollback

- Grupo A: el valor viejo sigue activo hasta el paso de borrado → revertir env var en Render y redeploy.
- Grupo B (Meta App Secret, Wompi): **no hay rollback** — el valor viejo muere al regenerar. Por eso la ventana se planifica y los valores nuevos se aplican en minutos. Si algo falla: repetir la rotación completa (generar otro) antes que intentar recuperar el viejo.
- `INTERNAL_SERVICE_SECRET`: mientras `PREVIOUS` esté puesta, el saliente sigue válido → rollback = no hacer nada más y volver `INTERNAL_SERVICE_SECRET` al viejo.

## 5. Evidencia a archivar

Confirmación fechada por credencial rotada (captura o log de verificación §3) referenciada desde la fila B2 del PLAN. **Nunca** pegar valores de secretos en docs ni en git — solo fechas y resultados de verificación.
