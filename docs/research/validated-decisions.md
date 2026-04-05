# Validated Decisions

## Decisiones base actuales del proyecto
1. El producto será una plataforma SaaS multi-tenant, no un bot aislado.
2. El canal cliente principal será WhatsApp Cloud API oficial.
3. Telegram se usará para operación interna, alertas y soporte de staff.
4. La base de datos principal será Postgres en Supabase.
5. La autenticación base será Supabase Auth.
6. La autorización se apoyará en RBAC + custom claims + RLS.
7. El almacenamiento de media y documentos será Supabase Storage.
8. El realtime se resolverá inicialmente con Supabase Realtime.
9. La búsqueda vectorial/RAG se resolverá inicialmente con pgvector en Postgres.
10. Las colas se resolverán inicialmente con Supabase Queues / pgmq.
11. Los workers y cron correrán en Render.
12. El backend principal se diseñará en Python + FastAPI.
13. El frontend principal se diseñará en React + TypeScript + Tailwind + shadcn/ui.
14. Mercado Libre entra desde el diseño inicial como conector prioritario.
15. Shopify y tienda personalizada quedan preparados como extensiones futuras.
16. El entorno local del proyecto será una VM dedicada.

## Estado
Estas decisiones son base de diseño.
Cada una debe seguir contrastándose con documentación oficial en la fase de blueprint e implementación.