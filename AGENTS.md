# AGENTS.md

## Proyecto
Commerce Operations Platform

## Objetivo
Construir una plataforma SaaS multi-tenant para operación conversacional de e-commerce, con:
- backoffice web
- inbox WhatsApp
- catálogo
- variantes
- media
- stock
- pedidos
- logística
- knowledge base
- AI orchestrator
- Telegram interno
- integración inicial con Mercado Libre
- diseño preparado para Shopify y tienda personalizada

## Regla principal
No asumir nada sensible sin documentación oficial vigente.

## Documentación de contexto
Leer primero:
- docs/product/overview.md
- docs/product/scope.md
- docs/architecture/overview.md
- docs/architecture/modules.md
- docs/architecture/multi-tenant-security.md
- docs/data/schema.md
- docs/data/rls-policies.md
- docs/integrations/whatsapp.md
- docs/integrations/mercadolibre.md
- docs/deployment/environments.md
- docs/research/official-doc-checklist.md

## Forma de trabajo
- usar Planning mode para tareas complejas
- dividir trabajo en task groups
- generar artifacts
- marcar intervención humana
- no desplegar ni ejecutar cambios destructivos sin confirmación

## Restricciones
- nada no oficial para WhatsApp
- no usar el LLM como fuente de verdad transaccional
- no simplificar a MVP
- no omitir seguridad multi-tenant