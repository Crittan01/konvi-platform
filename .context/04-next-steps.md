# Próximos Pasos — Estado 2026-04-14

## Estado Post-Vuelta 5 — Configuración 100% Cerrada (2026-04-15)

El dominio **Configuración** está completamente cerrado funcional y semánticamente.
No quedan cambios de navegación ni de código pendientes para este dominio.

### Intervenciones Humanas Pendientes (para que el invite funcione en producción):

**IH-001 — Variables de entorno en Render (web service)**
- Agregar `NEXT_PUBLIC_APP_URL=https://[dominio-real].onrender.com`
- Verificar que `SUPABASE_SERVICE_ROLE_KEY` esté configurado
- Ver detalle completo: `docs/architecture/settings-domain.md` → IH-001

**IH-002 — ALLOWED_ORIGINS en FastAPI (api service)**
- Variable `ALLOWED_ORIGINS` debe incluir el dominio de producción del frontend
- Ver detalle completo: `docs/architecture/settings-domain.md` → IH-002

### Pendientes de código para próxima sesión (otros dominios):
1. **Reclamos — `resolution_notes` editables**: Server Action `updateResolutionNotes` faltante
2. **Envia Fase 2** — label, tracking, pickup (`shipping.py` tiene el diseño, falta implementación)
3. **Sync bidireccional catálogo ↔ MeLi** — webhook recibe, sync al catálogo falta
4. **Reglas de Negocio** — definir caso de uso antes de implementar (→ `/dashboard/rules`)


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
