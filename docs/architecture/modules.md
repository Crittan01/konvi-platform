# Modules

## Módulos principales

### 1. Web Application
Una sola aplicación principal con dos zonas lógicas:
- Tenant Space
- Platform Space

### 2. Catalog Service
Administra productos, variantes, atributos, imágenes y estado por canal.

### 3. Inventory Service
Administra stock, movimientos, alertas y disponibilidad.

### 4. Orders Service
Administra pedidos, estados, incidencias y trazabilidad.

### 5. Conversation Service
Administra contactos, conversaciones, mensajes, etiquetas, notas internas y handoff.

### 6. Shipping Service
Administra carriers, cobertura, reglas de cotización y auditoría de cotizaciones.

### 7. Knowledge Service
Administra documentos, chunks, embeddings y trazabilidad de contenido usado.

### 8. AI Orchestrator
Interpreta intención, decide tools, apoya respuestas y escala a humano.

### 9. Connector Framework
Provee abstracción común para canales e integraciones externas por tenant.

### 10. WhatsApp Connector
Gestiona webhooks, envío, recepción, templates, media y mapeo con conversaciones internas.

### 11. MercadoLibre Connector
Gestiona autorización, mapeos, sincronización, notificaciones y reconciliación.

### 12. Shopify Connector (preparado)
Reserva el punto de extensión para futuro soporte.

### 13. Custom Store Connector (preparado)
Reserva el punto de extensión para storefront propio.

### 14. Platform Administration
Gestiona tenants, estados comerciales, soporte, métricas globales y operaciones internas.

## Regla
Cada módulo debe documentar:
- responsabilidad
- entidades
- eventos
- APIs
- permisos
- dependencia de documentación oficial