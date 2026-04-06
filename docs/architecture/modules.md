# Módulos del Monorepo

## 1. Aplicaciones (`apps/*`)
### `apps/web`
- **Responsabilidad:** Panel de administración Backoffice (Dashboard) donde los dueños o agentes loguean y manejan la operación de e-commerce.
- **Pila Técnica:** Next.js (App Router), React, TailwindCSS, shadcn/ui.
- **Relaciones:** Consume `@commerce/auth` para SSR Security y consume vistas parciales desde `@commerce/db`. Afrontará a la API principal del Backend para transacciones persistentes. Su capa de red perimetral está protegida por `middleware.ts`.

## 2. Servicios Backend (`services/*`)
- **`ai-orchestrator`:** Procesado profundo y filtrado de intenciones mediante herramientas NLP y JSON Schemas. (Worker Render asíncrono).
- **`connector-whatsapp`:** Boundary gateway para Meta. Convierte eventos webhook a JSONs limpios encolados, devolviendo OK_200 síncrono ultra-rápido.
- **`api`:** (Planeado) El cerebro sincrónico para atender a la página web (CRUD de catálogos, configuraciones WABA).

## 3. Paquetes Compartidos (`packages/*`)
- **`@commerce/auth`:** Contiene los wrappers SSR oficiales y los JWT logic claims.
- **`@commerce/db`:** Esquema atómico SQL y directrices de Row-Level Security (RLS) mandatorio por tenant.