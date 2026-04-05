# Validated Decisions

## Propósito
Registrar decisiones ya alineadas con la dirección del proyecto y sujetas a confirmación documental final durante el blueprint.

## Decisiones base actuales
1. El producto será una plataforma SaaS multi-tenant de operación conversacional para e-commerce.
2. No se construirá como “bot aislado”.
3. El canal principal hacia cliente final será WhatsApp Cloud API oficial.
4. Telegram se usará para operación interna y alertas.
5. El núcleo de datos será Postgres en Supabase.
6. La autenticación se basará en Supabase Auth.
7. La autorización se diseñará con RBAC + claims + RLS.
8. El storage de media y documentos se manejará en Supabase Storage.
9. El realtime se apoyará en Supabase Realtime.
10. El RAG se apoyará inicialmente en pgvector dentro de Postgres.
11. Los procesos asincrónicos se diseñarán con colas y workers, evitando complejidad innecesaria.
12. El hosting app-side se orienta a Render.
13. La integración inicial obligatoria de marketplace será Mercado Libre.
14. Shopify queda preparado como siguiente conector importante.
15. La tienda personalizada queda preparada como evolución futura del mismo core.
16. El LLM no será fuente de verdad para stock, pedidos, precios ni permisos.

## Nota
Estas decisiones sirven como baseline del blueprint y deben confirmarse con documentación oficial vigente durante el trabajo del agente.