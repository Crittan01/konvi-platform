# Próximos Pasos — Estado 2026-04-16

---

## Plan de Certificación v2 — Tenant Console (Arquitectura Funcional)

**Criterio v2:** Primera pasada cubrió seguridad/UX. Esta pasada cubre **corrección funcional y coherencia arquitectónica**:
- Flujos end-to-end funcionan con datos reales
- Módulos conectados entre sí correctamente (dependencias de datos respetadas)
- Configuración modular: cada tenant puede operar de forma independiente
- Integraciones expuestas donde corresponde arquitectónicamente
- No hay gaps entre lo que el UI promete y lo que el backend entrega

### Criterio de certificación por módulo (v2)

| # | Módulo | Ruta | Estado |
|---|--------|------|--------|
| 1 | **Dashboard** | `/dashboard` | 🔄 En validación |
| 2 | **Inbox** | `/dashboard/inbox` | 🔄 En validación |
| 3 | **Contactos** | `/dashboard/contacts` | 🔄 En validación |
| 4 | **Pedidos** | `/dashboard/orders` | 🔄 En validación |
| 5 | **Catálogo** | `/dashboard/catalog` | 🔄 En validación |
| 6 | **Inventario** | `/dashboard/inventory` | 🔄 En validación |
| 7 | **Despachos** | `/dashboard/shipping` | 🔄 En validación |
| 8 | **Reclamos** | `/dashboard/claims` | 🔄 En validación |
| 9 | **Mercado Libre** | `/dashboard/marketplace` | 🔄 En validación |
| 10 | **Compras** | `/dashboard/purchases` | 🔄 En validación |
| 11 | **Finanzas** | `/dashboard/finance` | 🔄 En validación |
| 12 | **Base de Conocimiento** | `/dashboard/knowledge-base` | 🔄 En validación |
| 13 | **Agentes IA** | `/dashboard/ai-agents` | 🔄 En validación |
| 14 | **Métricas** | `/dashboard/metrics` | 🔄 En validación |
| 15 | **Auditoría** | `/dashboard/audit` | 🔄 En validación |
| C1 | **Config — General** | `/dashboard/settings` | 🔄 En validación |
| C2 | **Config — Integraciones** | `/dashboard/integrations` | 🔄 En validación |
| C3 | **Config — Equipo** | `/dashboard/team` | 🔄 En validación |

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
