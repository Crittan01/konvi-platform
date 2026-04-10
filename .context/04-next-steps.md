# Próximos Pasos — Fase 12 y Deuda Técnica

## Fase 12 — Platform Console (bloqueada por OQ-P01)

**Prerequisito humano**: Decidir OQ-P01 — ¿misma app Next.js (`/platform/*`) vs app separada?

Una vez decidido:
1. Crear tabla `platform_users` (roles: `platform_superadmin`, `platform_support`, `platform_ops`)
2. Actualizar `middleware.ts` para auth diferenciada en `/platform/*` vs `/dashboard/*`
3. Layout de Platform Console separado del Tenant Console
4. Endpoints platform-only en `services/api`
5. Módulos por prioridad: Overview → Tenants → Health → Jobs → Auditoría Global

## Deuda técnica pre-Fase 12

| Deuda | Prioridad |
|-------|-----------|
| Variantes múltiples en catálogo (UI solo crea "Standard") | Media |
| Label + tracking + pickup Envia (Fase 2) | Media |
| RBAC granular completo por endpoint | Media |
| `packages/db/migrations/` desincronizado con `supabase/migrations/` | Baja |
| Python 3.9.25 EOL → actualizar a 3.11+ antes de Beta | Alta (pre-prod) |

## Lecciones aprendidas (no repetir)

- `gemini-2.0-flash` no disponible en cuentas nuevas → usar `gemini-2.5-flash`
- `NODE_ENV=production` + `npm install` omite devDeps → fix: `--include=dev`
- `psql` TCP bloqueado por Supavisor → usar `supabase db query --linked`
- `google-generativeai` deprecated → usar `google-genai==1.47.0`
- `getSession()` inseguro en Server Components → siempre `getUser()`
- ESLint v10 incompatible con Next.js 14 → usar `eslint@8`
- Funciones arrow como props RSC no son serializables → props opcionales con default interno
