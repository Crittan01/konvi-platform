# Runbook — Emails de Auth de Supabase (cierre productivo)

Última actualización: 2026-07-06

> **ESTADO 2026-07-06.** ✅ **IH-EMAIL-01 (Site URL + redirects)**, ✅ **IH-EMAIL-03 (Custom SMTP Resend + rate-limit 2→101)** y ✅ **subjects es-CO** están HECHOS y verificados en producción (`konvi.co` verified, SMTP `smtp.resend.com`/`noreply@konvi.co`, envío real OK). **Falta solo pegar el CONTENIDO de las 13 plantillas en el dashboard** → ver **IH-EMAIL-02** (el Management API bloquea escribir contenido de plantillas, error 1010; el dashboard sí acepta). Fuente de verdad del HTML: `supabase/templates/*.html` (marca verde `#2e5c49`, es-CO). Preview: publicado como Artifact en la sesión de cierre.

Cierra la config productiva de los emails de autenticación (invitación de equipo,
recuperación de contraseña, confirmación, magic link, cambio de correo). Estos emails
**los envía Supabase Auth**, no la app. Este runbook separa lo que controla el código
(versionado, con review) de lo que es **configuración externa en el dashboard de
Supabase** (INTERVENCION HUMANA, fuera de git).

---

## 1. Qué controla el CÓDIGO (ya cerrado en el repo)

| Aspecto | Dónde | Estado |
|---|---|---|
| Destino del link de invitación | `apps/web/.../team/page.tsx` → `redirectTo: ${appUrl}/auth/callback?next=/set-password` | Live (flujo implicit `#access_token`) |
| Destino del link de recuperación | `apps/web/app/forgot-password/forgot-password-form.tsx` → `redirectTo: ${origin}/auth/confirm?next=/set-password` | Live (flujo PKCE `?code=`) |
| Handler del link (PKCE/OTP) | `apps/web/app/auth/confirm/route.ts` | Live |
| Handler del link (implicit) | `apps/web/app/auth/callback/page.tsx` | Live |
| Branding por negocio en el email | `data: { tenant_name, invited_by, invited_role }` en `inviteUserByEmail` → `{{ .Data.tenant_name }}` en la plantilla | Live |
| Contenido/subject versionado (es-CO) | `supabase/templates/*.html` + `supabase/config.toml` | Live (fuente de verdad) |
| Rate-limit aplicativo per-tenant | `inviteRateLimited()` en `team/page.tsx` (5/60s vía `audit_log`) | Live |
| Lookup de usuario existente paginado | `findUserByEmail()` en `team/page.tsx` (perPage 1000, corta en match) | Live |
| Audit trail de invites/reenvíos | `audit_log` (`team.member_invited`, `team.invite_resent`) | Live |

**Regla de acoplamiento (no romper):** el link del email SIEMPRE debe ser
`{{ .ConfirmationURL }}`. Supabase lo construye a partir del `redirectTo` del código. Si
alguien reescribe el link a mano en el dashboard, se desacopla de `/auth/callback` y
`/auth/confirm` y el flujo se rompe **sin que ningún test lo detecte**. Al editar en el
dashboard, copiar el HTML de `supabase/templates/*.html` tal cual.

---

## 2. Qué es CONFIGURACIÓN EXTERNA (INTERVENCION HUMANA)

El proyecto hosted de producción se administra por dashboard de Supabase; estos ajustes
**no viven en git**. Ejecutar antes de habilitar tenants productivos.

### IH-EMAIL-01 — Site URL productivo + allow-list de redirects — ✅ HECHO (2026-07-06)

Site URL = `https://konvi-web.onrender.com`; allow-list = `/auth/callback`, `/auth/confirm`, `/**`. Verificado.

**INTERVENCION HUMANA REQUERIDA:** Sí (COMPLETADA)
**RESPONSABLE:** Owner/DevOps
**MOMENTO:** Antes del primer tenant productivo (bloqueante: sin esto los links salen a `127.0.0.1:3000`).
**PASOS:**
1. Dashboard → Authentication → URL Configuration.
2. `Site URL` = dominio productivo del web (el mismo valor de `APP_URL` en Render).
3. `Redirect URLs` (allow-list, URLs exactas): agregar
   `https://<dominio-web>/auth/callback` y `https://<dominio-web>/auth/confirm`.
   Incluir también la URL de preview/staging si se invita desde allí.
**INSUMOS:** dominio web productivo confirmado (ver `docs/deployment/domains-and-subdomains.md`).
**CRITERIO DE EXITO:** un invite de prueba llega con link al dominio productivo y `/auth/callback` establece sesión sin error de "redirect not allowed".

> Nota: `supabase/config.toml:site_url = http://127.0.0.1:3000` es SOLO para desarrollo local. No refleja producción y no debe usarse como fuente de verdad del dominio prod.

### IH-EMAIL-02 — Pegar el CONTENIDO de las 13 plantillas en el dashboard

**INTERVENCION HUMANA REQUERIDA:** Sí (obligatorio manual — ver "Por qué" abajo)
**RESPONSABLE:** Owner (founder)
**MOMENTO:** Cuando se quiera reemplazar los defaults en inglés por la marca Konvi es-CO.
**POR QUÉ MANUAL:** el Management API de Supabase **bloquea escribir el contenido** de
plantillas (`mailer_templates_*_content` → HTTP 403 `error code: 1010`), aunque sí permite
los `mailer_subjects_*`. Verificado 2026-07-06 (13/13 content rechazados con presupuesto de
rate-limit fresco). Los **subjects es-CO ya se intentaron por API**; si alguno quedó en inglés,
se pone a mano en la misma pantalla. El **contenido va sí o sí por el dashboard.**

**PASOS (por cada plantilla):**
1. Dashboard → **Authentication → Emails**.
2. Abrir la plantilla (columna izquierda) → en el editor:
   - **Subject (heading):** pegar el asunto es-CO de la tabla.
   - **Message body:** cambiar a **Source/HTML** y pegar el contenido COMPLETO del archivo
     `supabase/templates/<archivo>.html` del repo (tal cual, sin editar).
3. **Save**.
4. Las 7 de **Security** vienen **DESACTIVADAS** (`mailer_notifications_*_enabled=false`).
   Para usarlas: activar el toggle **Enable** de cada una además de pegar el contenido.

**Mapa (nombre en el dashboard → archivo del repo → asunto):**

| Authentication → Emails | Archivo (`supabase/templates/`) | Subject es-CO | Grupo |
|---|---|---|---|
| Invite user | `invite.html` | Te invitaron a un equipo en Konvi | Auth |
| Reset password | `recovery.html` | Restablece tu contraseña de Konvi | Auth |
| Confirm sign up | `confirmation.html` | Confirma tu cuenta en Konvi | Auth |
| Magic link / OTP | `magic_link.html` | Tu enlace de acceso a Konvi | Auth |
| Change email address | `email_change.html` | Confirma tu nuevo correo · Konvi | Auth |
| Reauthentication | `reauthentication.html` | Tu código de verificación · Konvi | Auth |
| Password changed | `password_changed_notification.html` | Tu contraseña de Konvi cambió | Security (off) |
| Email address changed | `email_changed_notification.html` | Tu correo de Konvi cambió | Security (off) |
| Phone number changed | `phone_changed_notification.html` | Tu teléfono de Konvi cambió | Security (off) |
| Sign-in method linked | `identity_linked_notification.html` | Nuevo método de acceso vinculado · Konvi | Security (off) |
| Sign-in method removed | `identity_unlinked_notification.html` | Método de acceso removido · Konvi | Security (off) |
| MFA method added | `mfa_factor_enrolled_notification.html` | Nuevo método de verificación (MFA) · Konvi | Security (off) |
| MFA method removed | `mfa_factor_unenrolled_notification.html` | Método de verificación (MFA) removido · Konvi | Security (off) |

**PRIORIDAD:** las **6 de Auth** primero (son las que se envían hoy: invitación de equipo y
recuperación de contraseña sobre todo). Las **7 de Security** son opcionales y van desactivadas.
**REGLA DE ACOPLAMIENTO:** NO tocar `{{ .ConfirmationURL }}` ni las variables `{{ .Data.* }}` /
`{{ .Token }}` / `{{ .NewEmail }}` del HTML (§1) — Supabase las reemplaza en runtime.
**INSUMOS:** acceso admin al dashboard; archivos del repo como fuente de verdad.
**CRITERIO DE EXITO:** un recovery de prueba llega en es-CO, marca verde Konvi, botón que abre
`/auth/callback|/auth/confirm` y aterriza en `/set-password`.

> Los **subjects** SÍ se pueden automatizar por Management API (`PATCH /v1/projects/{ref}/config/auth`
> con `mailer_subjects_*`), respetando el rate-limit de **120 req/60s**. El **contenido no** (1010).

#### Notificaciones de "Security" — cuáles ACTIVAR (no todas)

La sección **Security** trae 7 notificaciones **desactivadas** (`mailer_notifications_*_enabled=false`).
**No actives todas**: solo las que apliquen a la config real de auth de Konvi (email + MFA; **sin**
teléfono/SMS ni OAuth). Para cada una que actives → **Enable** + pega su `*_notification.html`.

| Notificación (Security) | ¿Activar? | Por qué (config real) |
|---|---|---|
| Password changed | ✅ **SÍ** | Auth por contraseña — señal de seguridad clave |
| Email address changed | ✅ **SÍ** | Un miembro puede cambiar su correo |
| MFA method added | ✅ **SÍ** | MFA TOTP habilitado (`mfa_totp_enroll_enabled=true`) |
| MFA method removed | ✅ **SÍ** | Quitar un factor MFA es sensible |
| Phone number changed | ❌ NO | No hay auth por teléfono/SMS (`sms_provider=null`, `external_phone_enabled=false`) |
| Sign-in method linked | ❌ NO | Solo email; sin proveedores OAuth (`external_*_enabled=false`) |
| Sign-in method removed | ❌ NO | Igual — sin OAuth |

> Si en el futuro se habilita OAuth (Google, etc.) o phone/SMS, activar también las
> correspondientes — sus plantillas ya están listas en el repo con las variables específicas
> (`{{ .Provider }}`, `{{ .FactorType }}`, `{{ .OldEmail }}`/`{{ .Email }}`, `{{ .OldPhone }}`/`{{ .Phone }}`).

### IH-EMAIL-03 — Custom SMTP (deliverability + rate-limit) — ✅ HECHO (2026-07-06)

**COMPLETADO:** Resend con dominio `konvi.co` verified (región `sa-east-1`, SPF+DKIM+DMARC en
Cloudflare vía Auto configure). Supabase Custom SMTP: host `smtp.resend.com`, port `465`, user
`resend`, pass = API key `re_*`, `admin_email = noreply@konvi.co`, `sender_name = Konvi`.
`rate_limit_email_sent` subido de **2 → 101**. `RESEND_FROM_EMAIL = "Konvi <noreply@konvi.co>"`
en `render.yaml` (api + orchestrator); `RESEND_API_KEY` como secreto en Render (ambos servicios).
Envío real a Gmail verificado (Resend message id devuelto).

**INTERVENCION HUMANA REQUERIDA:** Sí (COMPLETADA)
**RESPONSABLE:** Owner/DevOps + acceso al registrar DNS
**MOMENTO:** Antes de producción (bloqueante legal + funcional).
**CONTEXTO:** sin SMTP propio, Supabase usa un remitente compartido con **~2-4 emails/hora**
(`supabase/config.toml:[auth.rate_limit] email_sent = 2`) y dominio `mail.app.supabase.io`
(no production-ready, alto riesgo de spam). Un owner que invita a 3+ personas en minutos
choca el límite. El rate-limit aplicativo per-tenant NO sustituye esto: el cuello de botella
es el remitente compartido de Supabase.
**PASOS:**
1. Elegir proveedor. Recomendación del dossier: **Resend** (`smtp.resend.com:587`, user
   `resend`, pass = API key `re_*`). Ver `docs/research/sender-email-dossier-2026-05-05.md`.
2. Verificar dominio en el proveedor: agregar SPF + DKIM + DMARC al DNS (ver dossier §9).
3. Dashboard → Authentication → SMTP Settings → habilitar Custom SMTP con host/puerto/user/pass
   y `sender_name = "Konvi"`, `admin_email = noreply@<dominio>`.
4. Dashboard → Authentication → Rate Limits → subir el límite de emails/hora acorde al plan.
**INSUMOS:** cuenta del proveedor SMTP, acceso al DNS del dominio.
**CRITERIO DE EXITO:** envío de prueba a Gmail llega a **inbox** (no spam); invitar a 3+
miembros seguidos no choca rate-limit.

> Decisión de proveedor/plan/dominio = founder. Ver bloques "INTERVENCION HUMANA" del
> dossier (desambiguación "sender", volumen, política de dominio multi-tenant, DNS).

---

## 3. Verificación de cierre (smoke productivo)

1. Invitar a un correo propio desde `/dashboard/team`. El email llega en es-CO, marca Konvi
   y nombre del negocio; el botón abre `/auth/callback` y aterriza en `/set-password`.
2. Solicitar recuperación en `/forgot-password`. El email llega; el botón abre `/auth/confirm`
   (PKCE `?code=`) y aterriza en `/set-password`.
3. Invitar 3+ correos seguidos: no aparece `?error=rate-limit` (requiere IH-EMAIL-03).
4. Revisar `audit_log`: hay filas `team.member_invited` / `team.invite_resent`.

---

## 4. Residual conocido (fuera de este cierre)

- **Deliverability observable (bounce/spam/entregado):** hoy `inviteUserByEmail` sin error
  solo significa "aceptado para envío", no "entregado". Un webhook de eventos del proveedor
  + tabla `email_delivery_events` está propuesto en el dossier (§8) pero **no construido**;
  requiere decisión de proveedor (IH-EMAIL-03) y una migración DB → founder.
