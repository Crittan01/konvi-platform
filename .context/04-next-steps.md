# Próximos Pasos — Estado 2026-04-14

## AHORA — Estado Post-Vuelta 4 (Cierre Semántico del Tenant)

Vuelta 4 completada el 2026-04-14. Árbol funcional cerrado semánticamente.
Navegación Rev.4 aplicada. No quedan cambios de navegación pendientes para esta etapa.

### Pendientes de código reales (próxima sesión):
1. **Envia Fase 2** — label, tracking, pickup: endpoints en `shipping.py` ya diseñados, no implementados
2. **Sync bidireccional catálogo ↔ MeLi** — webhook existe, sync de vuelta al catálogo falta
3. **Reglas de Negocio** — pendiente funcional de Configuración (no inventar pantalla hasta definir el caso de uso real: ¿márgenes?, ¿reglas de precio?, ¿horarios de atención?)
4. **Media** — ahora invisible en menú. Pendiente: agregar link/acceso rápido desde `Catálogo` si el tenant lo necesita

### Pendientes documentales NO urgentes:
- `docs/architecture/restructuring-review.md` — registrar decisiones de Vuelta 4 al final del documento

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
