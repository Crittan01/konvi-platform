# Commerce Ops Platform — Producto y Árbol Funcional

SaaS multi-tenant de operaciones e-commerce conversacionales. Los tenants venden por WhatsApp. El sistema centraliza catálogo, pedidos, inventario, envíos, KB e integraciones con aislamiento total por tenant (RLS en PostgreSQL).

## 1. El producto NO es un bot
- WhatsApp Cloud API (Meta oficial) es el canal con el cliente final
- El catálogo, pedidos, inventario y reglas viven en el core del sistema
- El LLM (Gemini) es asistencia controlada — **nunca fuente de verdad** de stock, precios, pedidos, shipping ni estados transaccionales
- Las integraciones son módulos desacoplados (MeLi, Envia, Shopify futuro)

## 2. Tree Funcional Completo (Aprobado y Mandatorio)
Esta es la estructura base innegociable de la plataforma. La navegación debe calzar en este árbol sin crear dominios paralelos.

```text
Commerce Ops Platform
├── Tenant Console
│   ├── Inicio (Dashboard, Inbox)
│   ├── Ventas (Pedidos, Contactos, Envíos, Reclamos, Campañas)
│   ├── Productos (Catálogo, Inventario, Media, Precios, Proveedores)
│   ├── Canales (Publicaciones, Conectores, Mapeos, Sincronizaciones)
│   ├── Compras (Órdenes, Proveedores, Recepciones, Abastecimiento)
│   ├── Logística (Cotizaciones, Reglas, Zonas, Transportadoras)
│   ├── Finanzas (Ingresos, Gastos, Costos, Rentabilidad)
│   ├── IA y Conocimiento (Base de conocimiento, Agentes, Automatizaciones, Calidad)
│   ├── Analítica (Métricas, Reportes, Auditoría, Salud operativa)
│   └── Configuración (General, Usuarios, Integraciones, Reglas de negocio, Billing, Seg.)
└── Platform Console
    ├── Tenants
    ├── Soporte interno
    ├── Operación global
    ├── Seguridad global
    └── Observabilidad
```

## 3. Lógica de Lectura del Árbol (Evitar Errores de Diseño)
*   **Inicio:** No es “misc”. Es la capa de operación inmediata: ver qué está pasando, entrar a conversaciones, reaccionar rápido.
*   **Ventas:** Agrupa el flujo comercial transaccional: pedidos, clientes, envíos (despacho), reclamos, campañas.
*   **Productos:** Agrupa el core maestro de producto: catálogo, inventario, media, precios. Las publicaciones externas **NO** son "producto".
*   **Canales:** Proyección del core hacia afuera (MercadoLibre, Shopify, Central Ofertas). *Crítico:* Evita mezclar producto maestro con listing externo.
*   **Configuración:** Setup y gobierno operativo que no ocurre a diario.
*   **Platform Console:** Completamente hermética del Tenant Console. Ni mezclar, ni unificar layout y permisos.

## 4. Qué sí es módulo y qué no
*   **Módulos (Cambian objeto principal y flujo):** Inbox, Pedidos, Contactos, Envíos, Catálogo, Inventario, Publicaciones, Compras, Logística, IA y Conocimiento, Analítica, Configuración.
*   **Submódulos (Siguen el mismo dominio, con tarea y pantalla propia):** Reclamos, Automatizaciones, Auditoría de acceso, Sincronizaciones.
*   **Tabs (Perspectiva de la misma entidad):** Variantes de producto, Pago del pedido, Vista de historial de un contacto.
*   **Acciones secundarias (No deben ser navegación):** duplicar producto, reordenar fotos.

## 5. Tree Interno del Sistema
El codebase también sigue responsabilidades formales separando interfaz de API y workers asíncronos.

```text
commerce-ops-platform
├── apps
│   ├── web
│       ├── tenant-console 
│       └── platform-console
├── api (endpoints funcionales x dominio)
├── worker (sync-jobs, embeddings-jobs...)
├── cron
└── packages (domain-core, domain-commerce, domain-channels...)
```
