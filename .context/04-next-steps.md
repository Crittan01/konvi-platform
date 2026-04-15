# Próximos Pasos — Estado 2026-04-14

## Estado Post-Vuelta 5 (Configuración cerrada semánticamente)

Vuelta 5 completada el 2026-04-14. Configuración ahora tiene 3 entradas reales con rutas separadas.
El árbol visible del tenant está cerrado completamente. No quedan cambios de navegación pendientes.

### Pendientes de código reales (próxima sesión):
1. **Envia Fase 2** — label, tracking, pickup: `shipping.py` ya tiene diseño, falta implementación
2. **Sync bidireccional catálogo ↔ MeLi** — webhook existe, sync de vuelta al catálogo falta
3. **Reglas de Negocio** (Configuración) — pendiente funcional obligatorio:
   - Criterio de activación: definir caso de uso real primero (¿márgenes mínimos?, ¿reglas de precio automático?, ¿horarios de atención WhatsApp?)
   - No crear ruta ni UI hasta tener el caso de uso aprobado
   - Cuando exista, entrará en `/dashboard/rules` dentro del Route Group `(settings-group)/`
4. **Invite de miembros** (`/team`) — hoy es intervención manual vía Supabase Auth. Automatizar con formulario de invite es deuda conocida.

### Deuda técnica residual:

## DESPUÉS — Fase 12 Platform Console (Bloqueada OQ-P01)

Fuera de alcance hasta resolver: ¿misma app Next.js (`/platform/*`) vs app separada?
Ver decisión en `docs/risks/open-questions.md` — OQ-P01.

## Deuda técnica activa

| Deuda | Prioridad |
|-------|-----------|
| Label + tracking + pickup Envia (Fase 2) | Media |
| Reclamos — acciones reales (crear, cambiar estado, vincular pedido) | Alta |
| Sync bidireccional catálogo↔MeLi listings | Media |
| WhatsApp Config centralizada (templates, WABA) | Media |

## Lecciones aprendidas (no repetir)

- `gemini-2.0-flash` no disponible en cuentas nuevas → usar `gemini-2.5-flash`
- `NODE_ENV=production` + `npm install` omite devDeps → fix: `--include=dev`
- `psql` TCP bloqueado por Supavisor → usar `supabase db query --linked`
- `google-generativeai` deprecated → usar `google-genai==1.47.0`
- `getSession()` inseguro en Server Components → siempre `getUser()`
- ESLint v10 incompatible con Next.js 14 → usar `eslint@8`
- Funciones arrow como props RSC no son serializables → props opcionales con default interno
