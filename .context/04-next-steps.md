# Próximos Pasos — Estado 2026-04-14

## AHORA — Vuelta 2 de Reestructuración (Pre-Fase 12)

Se realizó una revisión arquitectónica completa (Vuelta 1) el 2026-04-14.
El diagnóstico completo está en `docs/architecture/restructuring-review.md`.

### Cambios de código pendientes (Vuelta 2):
1. `sidebar-client.tsx` — restructurar NAV_ITEMS: sección Inicio sin accordeon, Envíos → Despachos, eliminar Central Ofertas, desbloquear ai-agents, arreglar íconos duplicados
2. `layout.tsx` — breadcrumb en top bar desktop; top bar reducida/eliminada en mobile
3. Crear `components/bottom-nav.tsx` — bottom navigation para mobile (Inbox, Pedidos, Contactos)
4. `dashboard/page.tsx` — usar `tenants.low_stock_threshold` dinámico en lugar del hardcodeado `<= 5`
5. `dashboard-client.tsx` — eliminar trends hardcodeados (`+12%`, `+5%`)

### Limpieza documental pendiente (Vuelta 2):
- `.context/01-state.md` líneas 266-270: remover refs a docs eliminados
- `docs/HANDOFF.md` "Referencias rápidas": actualizar tabla
- Eliminar stubs vacíos en `docs/product/` y `docs/architecture/`
- Mover scripts debug de raíz a `scripts/debug/`

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
