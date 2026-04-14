# Commerce Ops Platform — Árbol Funcional y Reglas Base

**Este archivo es L1 — Autoridad Máxima.**
Ningún agente ni humano puede rediseñar la arquitectura funcional sin actualizar este archivo primero.
Toda decisión de navegación, creación de módulos o dominio debe ser validada aquí antes de ejecutarse.

---

## 1. El Producto

**Commerce Ops Platform** es un SaaS multi-tenant de operaciones e-commerce conversacionales.
Los tenants (empresas B2B2C) venden por WhatsApp. El sistema centraliza catálogo, pedidos, inventario, despachos, KB e integraciones con aislamiento total por tenant (RLS en PostgreSQL).

**Lo que NO es:**
- No es un bot. WhatsApp Cloud API es el canal, no el producto.
- No es un ERP completo. Es operación comercial conversacional.
- La IA (Gemini) es asistencia controlada — **nunca fuente de verdad** de stock, precios, pedidos, shipping ni estados transaccionales.
- Las integraciones (MeLi, Envia, Shopify futuro) son módulos desacoplados.

---

## 2. Tree Funcional Vigente — Tenant Console

Esta es la estructura funcional aprobada (rev. 2, 2026-04-14). La navegación debe calzar en este árbol.

```text
Tenant Console
│
├── INICIO
│   ├── Dashboard          ← visión operativa + negocio del tenant
│   └── Inbox              ← canal conversacional WhatsApp en tiempo real
│
├── VENTAS
│   ├── Pedidos            ← ciclo de vida de la venta: creación, estados, ítems
│   ├── Contactos          ← CRM mínimo: cliente, historial, consent habeas data
│   └── Reclamos           ← post-venta: tickets, devoluciones, disputas MeLi
│
├── PRODUCTOS
│   ├── Catálogo           ← maestro de producto: info, variantes, precios base
│   ├── Inventario         ← stock por variante, ajustes, alertas por umbral
│   └── Media              ← assets del tenant: imágenes, documentos (Supabase Storage)
│
├── CANALES
│   └── Mercado Libre      ← listings, sync catálogo/stock, órdenes MeLi
│
├── DESPACHOS
│   ├── Cotizaciones       ← integración Envia: cotizar envíos por pedido  [✅ live]
│   └── Órdenes de Envío   ← historial despachos, tracking, labels           [🔒 Fase 2]
│
├── COMPRAS
│   └── Órdenes de Compra  ← POs a proveedores, recepciones, WAC
│
├── FINANZAS
│   └── P&L                ← ingresos, OPEX, costos, rentabilidad
│
├── IA Y AUTOMATIZACIÓN
│   ├── Base de Conocimiento ← documentos que alimentan el Orchestrator       [✅ live]
│   └── Agentes IA         ← directrices, roles, parámetros RAG del bot      [✅ live]
│
├── ANALÍTICA
│   ├── Métricas           ← KPIs de negocio: conversación, pedidos, ingresos
│   └── Auditoría          ← log de acceso/cambios, exportación CSV
│
└── CONFIGURACIÓN
    ├── General            ← datos del tenant, logo
    ├── Equipo             ← usuarios, roles RBAC
    ├── WhatsApp           ← WABA, Phone ID, templates aprobados
    ├── Integraciones      ← MeLi OAuth, Envia — estado, connect/disconnect
    └── Notificaciones     ← Telegram, alertas de umbral y operación
```

**Platform Console — Fuera de alcance actual:**
Existe como concepto (tenants, soporte, observabilidad global) pero no tiene implementación.
No debe ser diseñada, expandida ni planificada en esta iniciativa.
Bloqueante: OQ-P01 sin resolver.

---

## 3. Cómo Leer Este Tree Sin Equivocarte

| Dominio | Regla de Lectura |
|---|---|
| **INICIO** | No es "misc". Es la capa de operación inmediata: ver qué pasa, reaccionar, entrar a conversaciones. |
| **VENTAS** | Flujo comercial transaccional. Pedidos + clientes + reclamos. Los *despachos físicos* NO son Ventas. |
| **PRODUCTOS** | Core maestro del producto. Las publicaciones externas (MeLi) **no** son "Productos". |
| **CANALES** | Proyección del catálogo hacia marketplaces externos. Nunca mezclar producto maestro con listing. |
| **DESPACHOS** | Operación logística del envío post-pedido. No "Logística corporativa" — semántica PYME Colombia. |
| **COMPRAS** | Reposición de inventario desde proveedores. Dominio distinto a Ventas. |
| **FINANZAS** | Solo reportería financiera. No incluye operación ni estado transaccional. |
| **IA Y AUTOMATIZACIÓN** | Infraestructura de IA. KB + Agentes. No llamarlo "Contenido" — error semántico. |
| **CONFIGURACIÓN** | Setup y gobierno del tenant. No ocurre a diario. |

---

## 4. Clasificación de Elementos

| Tipo | Criterio | Ejemplos |
|---|---|---|
| **Módulo** | Cambia el objeto principal de trabajo y el flujo operativo | Inbox, Pedidos, Catálogo, Mercado Libre |
| **Submódulo** | Sigue el mismo dominio, tiene tarea y pantalla propia | Reclamos, Auditoría, Órdenes de Envío |
| **Tab** | Misma entidad, distinta perspectiva | Variantes de producto, Historial de un contacto |
| **Acción secundaria** | No merece módulo ni navegación | Duplicar producto, reordenar fotos |

---

## 5. Tree Interno del Sistema (Físico)

```text
commerce-ops-platform/
├── apps/web/                    # Next.js 14.2.35 — Tenant Console
│   └── app/dashboard/
│       ├── (sales)/             # Route Group → /dashboard/{orders,contacts,shipping,claims}
│       ├── (products)/          # Route Group → /dashboard/{catalog,inventory,media}
│       ├── (channels)/          # Route Group → /dashboard/marketplace
│       ├── (ai)/                # Route Group → /dashboard/{knowledge-base,ai-agents}
│       ├── (analytics)/         # Route Group → /dashboard/{metrics,audit}
│       ├── (settings-group)/    # Route Group → /dashboard/{settings,integrations}
│       ├── inbox/               # /dashboard/inbox
│       ├── finance/             # /dashboard/finance
│       └── purchases/           # /dashboard/purchases
├── services/
│   ├── api/                     # FastAPI Core Gateway — 9 routers
│   ├── connector-whatsapp/      # FastAPI Webhook Meta
│   └── ai-orchestrator/         # Polling Gemini — daemon thread en Render Free
├── packages/
│   └── auth/                    # Wrappers Supabase SSR (parcial — 2 archivos)
└── supabase/migrations/         # 20 migraciones — FUENTE CANÓNICA de esquema DB
```

**Nota crítica sobre Route Groups:** Las carpetas `(nombre)` en Next.js no cambian las URLs.
`(sales)/orders/page.tsx` resuelve a `/dashboard/orders` — sin rotura de links ni revalidations.

---

## 6. Política de Actualización de Este Archivo

- Solo puede actualizarse cuando una decisión arquitectónica formal es aprobada.
- No actualizarlo con estados de implementación — eso es `.context/01-state.md`.
- Todo agente debe leer este archivo antes de proponer crear o mover un módulo.
- Si hay contradicción entre este archivo y otro, este archivo tiene prioridad.
