# Regla N-06: Frontend Best Practices y Restricciones (Next.js 14)

Esta regla define el estándar innegociable de uso de componentes y arquitectura frontend, en cumplimiento con el Tree Funcional oficial `.context/00-product.md`.

## 1. Patrones de Diseño (Next.js App Router)
- **Separación de Responsabilidades:** Utiliza *RSC (React Server Components)* por defecto. Convierte a `"use client"` únicamente los componentes hoja que requieran estado (useState), interactividad de eventos (onClick) o hooks (useEffect).
- **Mutaciones:** Cualquier mutación de datos (POST/PUT/DELETE) hacia la API Gateway debe ser delegada idealmente a un **Server Action** tipado o validado internamente para proteger el JWT context_user. Nunca hacer `fetch` pelón directo del lado del cliente sin envolverlo en abort controllers.
- **Ruteo Estricto:** Físicamente, todas las páginas pertenecen a los *Route Groups* de dominio: `(sales)`, `(products)`, `(channels)`, `(ai)`, `(analytics)`, o `(settings-group)`. ¡No añadir rutas físicas raízes como `/dashboard/mimodulo`!

## 2. Reglas de Estilo (Tailwind + Shadcn)
- **No re-inventar la rueda:** Utilizar la carpeta `apps/web/components/ui/` para componentes visuales core.
- **Nombres y Linters:** Seguir la convención `kebab-case` para archivos e importaciones. El formato está custodiado estrictamente por Prettier (`.prettierrc.json`) y `@typescript-eslint`.
- No emplear `any`. Usar types explícitos para cualquier payload transitado hacia/desde API externa.
