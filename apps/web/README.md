# Web App

## Objetivo
Aplicación principal del producto.

## Contendrá
- Tenant Space
- Platform Space

## Tenant Space
Vistas y flujos para operación del cliente:
- dashboard
- catálogo
- variantes
- stock
- pedidos
- inbox
- logística
- knowledge base
- integraciones del tenant

## Platform Space
Vistas y flujos para administración de la plataforma:
- tenants
- estados comerciales
- suspensión/reactivación
- feature flags
- soporte
- salud global
- métricas globales

## Regla
La separación inicial entre tenant y plataforma se hará por:
- auth
- roles
- rutas
- layouts
- permisos
no por apps distintas.