# @commerce/ui — DEFERRED

**Estado**: Intencionalmente vacío.

Los 11 componentes UI (shadcn/ui) viven en `apps/web/components/ui/`:
`accordion, badge, button, card, dialog, input, label, select, sheet, tabs, textarea`

**Cuándo poblarlo**: Si un segundo app (ej. `apps/platform/`) necesita compartir componentes con `apps/web`.
Mientras haya una sola app, no hay beneficio de extraer aquí.

**No mover componentes aquí** sin una decisión arquitectónica formal que lo justifique.
