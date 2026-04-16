# Próximos Pasos — Estado 2026-04-15

---

## Plan de Certificación — Tenant Console (Pre Platform Console)

**Criterio:** Solo Configuración está certificada y validada en producción con usuario real.
El resto de los módulos existen como código pero **no han sido auditados, ajustados ni probados** al nivel de certificación.
Este plan establece el orden de trabajo antes de abordar Fase 12 (Platform Console).

### Criterio de certificación por módulo

Un módulo se considera **certificado** cuando:
- Flujo principal funciona end-to-end en Render (producción)
- No hay llamadas inseguras (`getSession()` en Server Components, tokens expuestos en DOM, etc.)
- RLS activo y validado para el dominio
- UX consistente: iconos Lucide, sin emojis, dark warm theme
- Deuda técnica del módulo resuelta o registrada explícitamente

---

### Orden de certificación

| # | Módulo | Ruta | Razón de orden | Estado |
|---|--------|------|----------------|--------|
| 1 | **Dashboard** | `/dashboard` | Primera pantalla post-login. Read-only. Base para validar queries paralelas y umbral dinámico. | ✅ Certificado |
| 2 | **Inbox** | `/dashboard/inbox` | Canal principal del negocio. WhatsApp es el producto. Bloquea toda operación real. | 🔲 Pendiente |
| 3 | **Contactos** | `/dashboard/contacts` | CRM base. Pedidos e Inbox dependen de contactos. Consent Habeas Data crítico. | 🔲 Pendiente |
| 4 | **Pedidos** | `/dashboard/orders` | Transacción central del tenant. Depende de Catálogo + Contactos. | 🔲 Pendiente |
| 5 | **Catálogo** | `/dashboard/catalog` | Maestro de producto. Pedidos, Inventario y MeLi dependen de él. | 🔲 Pendiente |
| 6 | **Inventario** | `/dashboard/inventory` | Depende de Catálogo (variantes). Umbral dinámico ya implementado. | 🔲 Pendiente |
| 7 | **Despachos** | `/dashboard/shipping` | Post-pedido confirmado. Envia API. Fase 2 (label/tracking) pendiente. | 🔲 Pendiente |
| 8 | **Reclamos** | `/dashboard/claims` | Post-venta. Depende de Pedidos. `resolution_notes` editable pendiente. | 🔲 Pendiente |
| 9 | **Mercado Libre** | `/dashboard/marketplace` | Canal externo. Depende de Catálogo. Sync bidireccional pendiente. | 🔲 Pendiente |
| 10 | **Compras** | `/dashboard/purchases` | Reposición de inventario. Depende de que haya stock real. | 🔲 Pendiente |
| 11 | **Finanzas** | `/dashboard/finance` | Reportería P&L. Depende de datos operacionales reales. | 🔲 Pendiente |
| 12 | **Base de Conocimiento** | `/dashboard/knowledge-base` | Soporte al Orchestrator. No bloquea operación comercial. | 🔲 Pendiente |
| 13 | **Agentes IA** | `/dashboard/ai-agents` | Directrices del bot. Depende de KB funcional. | 🔲 Pendiente |
| 14 | **Métricas** | `/dashboard/metrics` | KPIs de negocio. Depende de datos reales acumulados. | 🔲 Pendiente |
| 15 | **Auditoría** | `/dashboard/audit` | Log de accesos y cambios. Última capa analítica. | 🔲 Pendiente |

---

## Módulos certificados

| Módulo | Certificado | Notas |
|--------|-------------|-------|
| Configuración — General | ✅ 2026-04-15 | Identidad, operativa, dirección origen DANE |
| Configuración — Usuarios y Acceso | ✅ 2026-04-15 | Flujo invite validado en Render con usuario real |
| Configuración — Integraciones | ✅ 2026-04-15 | Envia, MeLi OAuth, Telegram. testTelegram desde DB |

**Pendiente solo en Configuración:** IH-SMTP — SMTP custom con Resend (requiere dominio propio).

---

## Intervenciones Humanas Pendientes

**IH-SMTP — SMTP custom con dominio propio**
- Gmail sender bloqueado por DMARC `p=reject`. Free plan: 3 emails/hora.
- Cuando haya dominio propio: Resend.com → verificar dominio → configurar en Supabase Auth SMTP.
- No bloquea operación actual.

---

## DESPUÉS — Fase 12 Platform Console (Bloqueada OQ-P01)

Fuera de alcance hasta completar certificación Tenant Console y resolver:
¿misma app Next.js (`/platform/*`) vs app separada?
Ver decisión en `docs/risks/open-questions.md` — OQ-P01.

---

## Lecciones aprendidas (no repetir)

- `gemini-2.0-flash` no disponible en cuentas nuevas → usar `gemini-2.5-flash`
- `NODE_ENV=production` + `npm install` omite devDeps → fix: `--include=dev`
- `psql` TCP bloqueado por Supavisor → usar `supabase db query --linked`
- `google-generativeai` deprecated → usar `google-genai==1.47.0`
- `getSession()` inseguro en Server Components → siempre `getUser()`
- ESLint v10 incompatible con Next.js 14 → usar `eslint@8`
- Funciones arrow como props RSC no son serializables → props opcionales con default interno
- Gmail como SMTP sender bloqueado por DMARC `p=reject` → usar Resend con dominio propio
- `inviteUserByEmail` usa implicit flow (`#access_token=`) → leer hash ANTES de `createClient()`
- JWT stale claims tras cambio de rol → invalidar con `admin.signOut(userId, 'global')`
