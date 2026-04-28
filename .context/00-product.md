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

## 2. Tree Funcional Vigente — Tenant Console (Rev. 5 — 2026-04-17)

Esta es la estructura funcional aprobada y cerrada semánticamente (rev. 5, 2026-04-17).
La navegación visible debe calzar exactamente en este árbol. No agregar nada sin decisión formal.

```text
Tenant Console
│
├── Dashboard          ← visión operativa + negocio del tenant (umbral dinámico)
├── Inbox              ← canal conversacional WhatsApp en tiempo real
│
├── VENTAS
│   ├── Pedidos            ← ciclo de vida de la venta: creación, estados, ítems
│   ├── Contactos          ← CRM mínimo: cliente, historial, consent habeas data
│   ├── Despachos          ← cotizaciones Envia post-pedido (logística comercial)
│   └── Reclamos           ← post-venta: tickets, devoluciones, disputas
│
├── PRODUCTOS              ← hoja directa → /dashboard/catalog
│                            Catálogo + Inventario unificados en una sola pantalla.
│                            KPI bar (total/bajo/sin stock), ajuste delta inline por variante,
│                            historial de movimientos colapsable. Inventario ya NO es módulo separado.
│
├── CANALES
│   └── Mercado Libre      ← listings, sync catálogo/stock/precio, órdenes MeLi
│
├── COMPRAS            ← repositorio de órdenes de compra a proveedores
│
├── FINANZAS           ← P&L, OPEX, rentabilidad operativa
│
├── IA Y CONOCIMIENTO
│   ├── Base de Conocimiento ← documentos que alimentan el Orchestrator
│   └── Agentes IA         ← directrices, roles, parámetros del bot
│
├── ANALÍTICA
│   ├── Métricas           ← KPIs de negocio
│   └── Auditoría          ← log de acceso/cambios, exportación CSV
│
└── CONFIGURACIÓN
    ├── General            ← /settings: nombre, logo, threshold, dirección origen
    ├── Usuarios y Acceso  ← /team: invite email, changeRole, removeMember
    └── Integraciones      ← /integrations: Envia (API key), MeLi (OAuth), Telegram (Bot Token + Chat ID)
```

**Platform Console — Fuera de alcance absoluto en esta iniciativa:**
No tiene implementación. Bloqueante OQ-P01 sin resolver.


---

## 3. Cómo Leer Este Tree Sin Equivocarte

| Dominio | Regla de Lectura | Decisión Rev.4 |
|---|---|---|
| **INICIO** | Capa de operación inmediata. No es "misc". | Sin cambio |
| **VENTAS** | Flujo comercial completo: pedido → despachar → resolver. Despachos es un paso del ciclo, no dominio independiente. | Despachos movido a Ventas |
| **PRODUCTOS** | Core maestro del producto. Catálogo + Inventario fusionados en una sola hoja `/dashboard/catalog`. Media oculta del menú. | Rev.5: Inventario eliminado como módulo separado |
| **CANALES** | Proyección del catálogo hacia marketplaces externos. Aunque hoy solo hay MeLi, el grupo existe para que no flote suelto. | Restaurado como grupo |
| **COMPRAS** | Reposición de inventario. Dominio distinto a Ventas. | Sin cambio |
| **FINANZAS** | Reportería financiera. No incluye operación ni estado transaccional. | Sin cambio |
| **IA Y CONOCIMIENTO** | KB + Agentes. Honesto con lo que existe. No se llama "Automatización" hasta que haya algo real. | Renombrado |
| **ANALÍTICA** | KPIs y auditoría. No ocurre a diario. | Sin cambio |
| **CONFIGURACIÓN** | Setup y gobierno del tenant. Equipo/RBAC in-page. Reglas de Negocio pendiente. | Label corregido |

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
│       ├── (products)/          # Route Group → /dashboard/catalog  (inventory eliminado)
│       │   └── catalog/         # Productos unificado: catálogo + stock + ajustes
│       ├── (channels)/          # Route Group → /dashboard/marketplace
│       ├── (ai)/                # Route Group → /dashboard/{knowledge-base,ai-agents}
│       ├── (analytics)/         # Route Group → /dashboard/{metrics,audit}
│       ├── (settings-group)/    # Route Group → /dashboard/{settings,team,integrations}
│       ├── inbox/               # /dashboard/inbox
│       ├── finance/             # /dashboard/finance
│       └── purchases/           # /dashboard/purchases
├── services/
│   ├── api/                     # FastAPI Core Gateway — 9 routers
│   ├── connector-whatsapp/      # FastAPI Webhook Meta
│   └── ai-orchestrator/         # Polling Gemini — daemon thread en Render Free
├── packages/
│   ├── auth/                    # Wrappers Supabase SSR (parcial)
│   ├── shared-types/            # Contratos TS compartidos (mínimos)
│   └── [otros paquetes deferred]
└── supabase/migrations/         # 42 migraciones — FUENTE CANÓNICA de esquema DB
```

**Nota crítica sobre Route Groups:** Las carpetas `(nombre)` en Next.js no cambian las URLs.
`(sales)/orders/page.tsx` resuelve a `/dashboard/orders` — sin rotura de links ni revalidations.

---

## 5.1 Rutas hidden / pendientes de decisión de producto (Rev. 6 — 2026-04-28)

Estas rutas existen como código funcional pero NO están expuestas en el sidebar
ni forman parte del tree funcional canónico. Se mantienen funcionales hasta
que una decisión formal de producto las integre o las elimine.

| Ruta | Estado | Razón |
|---|---|---|
| `/dashboard/(products)/media` | Funcional, oculta | Gestor de medios (subida y listado de archivos a `tenant-media` en Supabase Storage). Pendiente decisión: ¿se integra al editor de Catálogo o queda como módulo paralelo? Hasta entonces no se enlaza desde el sidebar. |
| `/dashboard/(products)/inventory` | Redirect 301 → `/dashboard/catalog` | Ruta legacy mantenida intencionalmente para compatibilidad con bookmarks y links externos. Definida en rev. 5. |

Política: cualquier ruta hidden debe quedar listada aquí con razón explícita.
Si se decide eliminarla, hacerlo en una sola operación con barrido de
referencias (links, redirects, búsqueda en sidebar, breadcrumbs).

---

## 6. Política de Actualización de Este Archivo

- Solo puede actualizarse cuando una decisión arquitectónica formal es aprobada.
- No actualizarlo con estados de implementación — eso es `.context/01-state.md`.
- Todo agente debe leer este archivo antes de proponer crear o mover un módulo.
- Si hay contradicción entre este archivo y otro, este archivo tiene prioridad.
