# Runbook — Emails de Auth de Supabase (cierre productivo)

Última actualización: 2026-07-04

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

### IH-EMAIL-01 — Site URL productivo + allow-list de redirects

**INTERVENCION HUMANA REQUERIDA:** Sí
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

### IH-EMAIL-02 — Aplicar plantillas es-CO + branding en el dashboard

**INTERVENCION HUMANA REQUERIDA:** Sí
**RESPONSABLE:** Owner/DevOps
**MOMENTO:** Antes del primer invite productivo (si no, salen los defaults de Supabase en inglés).
**PASOS:**
1. Dashboard → Authentication → Emails (Templates).
2. Para cada plantilla (Invite, Reset Password, Confirm signup, Magic Link, Change Email
   Address): pegar el `subject` y el HTML desde `supabase/templates/*.html` y
   `supabase/config.toml`. Mapa: `invite.html`→Invite, `recovery.html`→Reset Password,
   `confirmation.html`→Confirm signup, `magic_link.html`→Magic Link,
   `email_change.html`→Change Email Address.
3. Verificar que el link siga siendo `{{ .ConfirmationURL }}` (ver regla de acoplamiento §1).
**INSUMOS:** acceso admin al dashboard; archivos del repo como fuente de verdad.
**CRITERIO DE EXITO:** invite de prueba llega en es-CO, con "Konvi" y el nombre del negocio (`{{ .Data.tenant_name }}`) visible; el botón lleva a `/auth/callback`.

> Alternativa CLI: si el proyecto se gestiona con `supabase config push`, los bloques
> `[auth.email.template.*]` de `config.toml` aplican las plantillas sin tocar el dashboard.
> Verificar con el founder cuál es el modo de gestión del proyecto hosted (dashboard vs CLI)
> antes de asumir. **VALIDAR EN DOCUMENTACION OFICIAL:** disponibilidad de `{{ .Data.* }}`
> (user_metadata) en plantillas de invite del proyecto hosted — el HTML incluye fallback si
> viene vacío, por lo que no rompe aunque la variable no resuelva.

### IH-EMAIL-03 — Custom SMTP (deliverability + rate-limit)

**INTERVENCION HUMANA REQUERIDA:** Sí
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
