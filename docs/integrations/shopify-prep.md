# Shopify Preparation

## Objetivo
Preparar la arquitectura para una futura integración con Shopify sin reescribir el núcleo del sistema.

## Principios
- usar un conector desacoplado
- mapear productos, variantes e inventario al modelo interno
- usar webhooks para sincronización de cambios
- mantener Supabase como núcleo operativo interno

## Áreas a validar documentalmente
- Admin GraphQL API
- products
- variants
- inventory
- webhooks
- scopes
- modelo de app

## Intervención humana esperada
- partner account
- configuración de app
- scopes
- instalación de la app en la tienda del cliente