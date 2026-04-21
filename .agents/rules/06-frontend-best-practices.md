# Regla N-06: Frontend Best Practices y Restricciones (Next.js 14)

Esta regla debe respetar el tree funcional oficial en `.context/00-product.md`.

## 1. Patrones de diseño (App Router)

- Usar RSC por defecto y `"use client"` solo cuando haya estado/interacción real.
- Mutaciones hacia API deben ir por Server Actions o route handlers server-side.
- Si se usa `fetch` client-side para acciones críticas, incluir timeout/control de errores explícito.
- Los Route Groups son organizativos y no cambian URL. También existen módulos directos de `/dashboard/*` aprobados por L1 (ej. `inbox`, `finance`, `purchases`).

## 2. Reglas de estilo y tipado

- Reusar `apps/web/components/ui/` para componentes base.
- Mantener convenciones de lint/TS del repo.
- Evitar `any` en código nuevo salvo justificación puntual.
