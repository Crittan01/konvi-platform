# ADR-0031 — Identidad de remitente de email: remitente único compartido (por ahora)

**Status**: Accepted (2026-07-04)
**Deciders**: Founder + AI Architect
**Context**: Fase 0 completeness audit — decisión `impl_auth` (business_call, group F7)

---

## Contexto

Los emails transaccionales de identidad (invitación de equipo, reenvío, recuperación) se
envían vía **Supabase Auth** (`auth.admin.inviteUserByEmail`), cuyo SMTP y dirección de
remitente (`from`) se configuran a **nivel de proyecto/ENV en Render**, NO por-tenant en DB.
El branding por-negocio hoy se logra inyectando `tenant_name` en `user_metadata`, que la
plantilla de email renderiza como `{{ .Data.tenant_name }}`.

Opción evaluada: **(a)** custom domains en Resend + `from` por marca/logo + quota guard
per-tenant; **(b)** mantener remitente genérico único compartido.

## Decisión

**Mantener remitente único compartido (opción b).** El aislamiento per-tenant del remitente
es configuración externa (Resend custom domains, verificación DNS por marca, cuotas) — costosa
y **sin demanda actual**: el único tenant productivo es KAIU y no hay tenants externos exigiendo
su propia identidad de correo. El branding textual vía `tenant_name` en la plantilla cubre la
necesidad de reconocimiento del invitado.

**No hay cambio de código.** El envío actual (Supabase Auth SMTP) permanece intacto. Se
documenta la decisión para trazabilidad y se define el disparador de reversión.

## Disparador de reversión (cuándo mover a opción a)

Cuando exista **al menos un tenant externo en producción exigiendo su propia marca de correo**
(dominio/`from`/logo propios). Ese trabajo es infra + business, no code-first:

- Provisionar Resend (o proveedor equivalente) con custom domains verificados por tenant (DNS: SPF/DKIM/DMARC).
- `from` por marca resuelto desde config per-tenant (nueva tabla/campo).
- Quota guard per-tenant (evitar que un tenant agote la cuota compartida).
- Migrar el envío de invitaciones fuera de Supabase Auth SMTP (o SMTP custom per-tenant si Supabase lo permite).

## INTERVENCION HUMANA REQUERIDA (sólo al reversar)

- **RESPONSABLE**: Founder (decisión de negocio) + Infra.
- **INSUMOS**: cuenta Resend, dominios verificados por tenant, presupuesto.
- **CRITERIO DE EXITO**: cada tenant externo envía invitaciones desde su propio dominio
  verificado sin degradar el envío de los demás.
