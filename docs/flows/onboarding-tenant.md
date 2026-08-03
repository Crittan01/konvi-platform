# Flujo — Onboarding de Tenant (qué configura un negocio nuevo)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Todo lo que un tenant configura para operar, verificado en las páginas de Settings/Integraciones (`apps/web/app/dashboard/(settings-group)/`) y los routers (`services/api/routers/`). Los secretos se cifran en **Vault** (server-side); la consola nunca los muestra en claro tras guardarlos.

Orden recomendado (derivado de las dependencias reales: WhatsApp habilita el Inbox; shipping habilita el Cotizador; Wompi habilita cobros):

## 1. General del negocio — `/dashboard/settings` (owner)

- Nombre, **logo** (`logo-upload.tsx` — aparece en el sidebar), umbral de bajo stock (KPI bar del catálogo), dirección de origen de envíos (`shipping-origin-form.tsx` + `domicilio-selector.tsx` — origen para cotizar Aveonline), métodos de pago aceptados (`payment-methods-form.tsx`), presencia de tienda (`store-presence-form.tsx`).
- Router: `services/api/routers/settings.py`.

## 2. WhatsApp — Model B "Direct Provider" (app propia de Meta)

`/dashboard/integrations/whatsapp` — **ADR-0023**: cada tenant conecta **SU PROPIA Meta App**. NO es Embedded Signup (comentario verificado en `whatsapp-setup.tsx:30`: "cada tenant trae SU PROPIA Meta App. NO Embedded Signup").

- **6 credenciales** (`whatsapp-credentials-form.tsx:14-19`):
  1. `app_id` — Meta App → Configuración → Básica
  2. `app_secret` — se cifra en Vault
  3. `verify_token` — string que el tenant elige; el mismo va en el webhook de Meta
  4. `phone_number_id`
  5. `waba_id`
  6. `access_token` (System User) — se cifra en Vault
- Tras guardar, los secretos no se retienen en estado del cliente (61).
- Tabs del panel (`whatsapp-tabs.tsx`): **Plantillas HSM** (`whatsapp-templates.tsx` — la URL legacy `/dashboard/whatsapp-templates` redirige aquí con `?tab=plantillas`), **Opt-outs** (`whatsapp-optouts.tsx`), **Calidad** (`whatsapp-quality.tsx`).
- Efecto: la integración `whatsapp` `connected` habilita el Inbox en la navegación (`sidebar-client.tsx:56`); sin ella el Inbox muestra el estado vacío con CTA de configuración (`inbox-manager.tsx:328-346`).

## 3. Wompi (pagos)

`/dashboard/integrations/wompi` (`wompi-setup.tsx`):

- Solo **2 llaves**: `private_key` y `events_key` (ambas a Vault). Los campos `public_key`/`integrity_key` fueron **retirados** (Fase 0 F6): el backend tiene 0 readers de ellas y confundían la configuración (11-16).
- La `events_key` es la que verifica la firma SHA256 de los webhooks (ver [`pago-wompi.md`](pago-wompi.md) §2.2).

## 4. Aveonline (envíos)

`/dashboard/integrations/aveonline` (`aveonline-setup.tsx`):

- Campos: **usuario** (ej. `mi-empresa-ecommerce`), **password** (secreto), `auth_version`, `tiempo_token`; el panel muestra **Empresa ID** y usuario tras conectar (156-301).
- Sub-paneles: carriers disponibles (`aveonline-carriers.tsx`) y guía de funcionamiento (`aveonline-how-it-works.tsx`).
- Efecto: `aveonline` `connected` habilita el Cotizador (`/dashboard/shipping`) vía la abstracción `shipping` (`layout.tsx:80-83,106`).
- Guías reales: además requiere el flip operativo `AVEONLINE_GENERATE_REAL_GUIDES=true` (bloqueante B1 — ver [`despacho-aveonline.md`](despacho-aveonline.md) §2.1).

## 5. Telegram (notificaciones del operador)

`/dashboard/integrations/telegram` (`telegram-setup.tsx`):

- **Bot Token** (Vault) + **Chat ID operador**; webhook `secret_token` activo; comandos disponibles `/resolver` · `/estado` (46-84).
- **Gap M17**: el `setWebhook` es **manual por tenant** — paso operativo documentado, no auto-provisionado.
- Es el canal de alertas de escalación human_takeover (ver [`human-takeover.md`](human-takeover.md) §2).

## 6. Mercado Libre (opcional, Canales)

`/dashboard/integrations/mercadolibre` (`meli-setup.tsx`): OAuth. Habilita el módulo Mercado Libre en Canales (integración + capability `integrations.mercadolibre`, `sidebar-client.tsx:80`). Gap M17: refresh de tokens es lazy (token >6 meses sin uso expira).

## 7. Equipo y roles — `/dashboard/team` (owner only)

- Roles verificados (`team/page.tsx:39-57` + `sidebar-client.tsx:146-150`):
  - `owner` — **Administrador**: todo, incl. Compras, Finanzas, Cerrar cuenta.
  - `manager` — **Supervisor**: operación + catálogo + integraciones + métricas.
  - `operator` — **Gestor**: Inbox, pedidos, contactos, reclamos, seguridad propia.
- Acciones: invitar por email, `changeRole`, `removeMember`/`inactivate` (componentes `change-role-button.tsx`, `remove-member-button.tsx`, `inactivate-member-button.tsx`). La página está protegida para owner incluso por navegación directa (207).

## 8. MFA y seguridad de la cuenta — `/dashboard/settings/security` (todos los roles)

`security-form.tsx`:

- **Enroll TOTP**: QR + verificación de código de 6 dígitos.
- **Recovery codes**: se muestran **una sola vez** con descarga `.txt`.
- **Recovery session** (Rev. 109 J.2.4.3): si el usuario entró con recovery code, banner urgente en el dashboard para regenerar MFA (`layout.tsx:160-174`); cookie `mfa_recovery_session` firmada HMAC ligada al user + expiry, se borra al logout.
- **Gap A1**: `MFA_MANDATORY_ENABLED=false` en prod — los write-roles operan hoy sin MFA obligatorio (`render.yaml`, hallazgo de auditoría).

## 9. Gobierno de datos (post-onboarding recomendado)

- `/dashboard/settings/legal` — aceptación legal + reporte SIC.
- `/dashboard/settings/retention` — políticas de retención per-tenant (ver [`opt-out-habeas-data.md`](opt-out-habeas-data.md) §4).
- `/dashboard/settings/health` — salud de integraciones con refresh manual.
- `/dashboard/settings/account-closure` — cierre de cuenta (owner, destructivo con confirm).

---

### Checklist resumido (verificado)

```text
① Settings: identidad + logo + umbral + origen envío + métodos pago
② WhatsApp Model B: 6 credenciales Meta App propia (2 a Vault) → Inbox ON
③ Wompi: private_key + events_key (Vault) → cobros ON
④ Aveonline: usuario/password (+flip flag para guías reales) → Cotizador ON
⑤ Telegram: bot token + chat ID (+ setWebhook manual) → alertas takeover ON
⑥ MeLi (opcional): OAuth → Canales ON
⑦ Team: invitar operadores con rol mínimo necesario
⑧ Seguridad: MFA TOTP + recovery codes por usuario (obligatoriedad: flag OFF hoy — A1)
⑨ Legal/retención: aceptación + políticas per-tenant
```
