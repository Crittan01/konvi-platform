# Functional Requirements

## Objetivo
Definir los requerimientos funcionales mínimos de producción para la plataforma.

## 1. Gestión de tenants
El sistema debe permitir:
- crear tenants
- activar tenants
- suspender tenants
- configurar subdominios por tenant
- administrar estado operativo del tenant
- administrar estado comercial del tenant
- restringir acceso por suspensión o falta de pago
- registrar auditoría de estos cambios

## 2. Gestión de usuarios y roles
El sistema debe permitir:
- crear usuarios
- invitar usuarios
- asignar membresía a uno o varios tenants
- asignar roles por tenant
- distinguir roles de plataforma y roles de tenant
- revocar acceso
- auditar cambios de permisos

## 3. Gestión de catálogo
El sistema debe permitir:
- crear productos
- editar productos
- activar o desactivar productos
- definir SKU
- definir categorías o colecciones
- definir marca
- definir estado de publicación por canal

## 4. Gestión de variantes
El sistema debe permitir:
- crear variantes
- definir atributos como color, talla, material, presentación
- asignar SKU por variante
- asignar precio por variante si aplica
- asignar stock por variante

## 5. Gestión de imágenes y media
El sistema debe permitir:
- subir imágenes de producto
- subir imágenes de variante
- definir imagen principal
- reordenar imágenes
- eliminar imágenes
- almacenar documentos de soporte y conocimiento
- almacenar media relevante recibida desde canales externos

## 6. Gestión de stock
El sistema debe permitir:
- consultar stock por producto y variante
- ajustar stock manualmente
- registrar movimientos
- manejar stock por bodega si aplica
- definir stock mínimo
- generar alertas de stock

## 7. Gestión de pedidos
El sistema debe permitir:
- consultar pedidos
- ver detalle de pedido
- actualizar estado
- registrar incidencias
- asociar contacto y conversación
- asociar información logística

## 8. Gestión de logística
El sistema debe permitir:
- definir carriers
- definir cobertura
- definir reglas de cotización
- calcular cotización por peso, volumen, zona o reglas propias
- registrar auditoría de cada cotización

## 9. Inbox conversacional
El sistema debe permitir:
- recibir mensajes del canal soportado
- responder desde el panel
- ver historial de conversación
- asignar agente
- pausar automatización
- reactivar automatización
- escalar a humano
- etiquetar y dejar notas internas

## 10. Asistente IA
El sistema debe permitir:
- interpretar intención
- consultar tools internas
- responder con contexto real
- generar borradores
- usar RAG sobre conocimiento
- escalar a humano cuando corresponda

## 11. Knowledge Base
El sistema debe permitir:
- subir PDFs y documentos
- crear FAQs
- activar o desactivar fuentes
- reindexar contenido
- filtrar por tenant
- versionar o reemplazar contenido

## 12. Integraciones
El sistema debe permitir:
- conectar canales por tenant
- conectar Mercado Libre por tenant
- almacenar estado de integración
- registrar ejecuciones de sincronización
- registrar errores de sincronización
- desactivar o reactivar integraciones

## 13. Administración de plataforma
El sistema debe permitir a roles de plataforma:
- ver tenants
- suspender tenants
- reactivar tenants
- ver estado de integraciones
- ver errores operativos
- gestionar feature flags
- restringir uso por estado comercial
- auditar acciones de soporte y administración