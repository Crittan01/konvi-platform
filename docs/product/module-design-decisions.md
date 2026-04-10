# Decisiones de Diseño por Módulo — Tenant Console

Última actualización: 2026-04-09 (rev. 1 — sesión de revisión de producto post Fase 11)

Este documento captura las decisiones de producto y visión objetivo por módulo, derivadas de la revisión de realidad de la sesión 2026-04-09. Complementa `admin-ui-modules.md` con intención funcional concreta.

**Principio rector**: Este producto NO es un prototipo, MVP ni experimento. Es una plataforma SaaS real, masiva y vendible, pensada para múltiples clientes reales. Cada módulo debe reflectir esa ambición desde el primer uso.

---

## A.1 — Resumen / Dashboard

### Visión objetivo

El Dashboard no es una página de bienvenida — es el **centro de comando operacional** del tenant. Debe mostrar a la vez urgencia operacional y visión de negocio.

### Estructura propuesta: Tabs

| Tab | Contenido |
|-----|-----------|
| **Operaciones** | Conversaciones activas con bot, conversaciones en takeover humano, pedidos pendientes de confirmar, alertas de stock bajo, cotizaciones de envío pendientes |
| **Negocio** | KPIs con tendencia (conversaciones semana vs anterior, pedidos semana, revenue del mes), gráfica de actividad diaria (línea), distribución de pedidos por estado (pastel), top productos vendidos |

### Detalles de ejecución

- Las cards actuales (email + tenant name) son insuficientes para un SaaS real
- Los KPI deben tener comparativa temporal (vs semana anterior, vs mes anterior)
- Gráficas: recharts o similar vía Client Component (el resto del Dashboard puede ser Server Component)
- Las alertas operacionales son clickables → navegan al módulo correspondiente
- Pequeños detalles que suman: animaciones suaves de entrada de cards, skeleton loading mientras cargan los datos
- Descripción breve del módulo visible al hacer hover o como subtítulo en mobile

### Estado actual

- 4 KPI cards de totales planos (sin tendencia)
- Sin gráficas
- Sin alertas operacionales

### Deuda más urgente

1. Tab de Operaciones con alertas clickables
2. Gráficas de tendencia en Tab Negocio (no estáticas)
3. Comparativa temporal en KPIs

---

## A.2 — Inbox AI

### Visión objetivo

Los agentes deben poder **responder desde el panel** o **desde móvil**. El takeover actual está incompleto porque toma el control de la conversación pero no permite enviar mensajes desde la consola.

### Detalles de ejecución

- Campo de texto + botón enviar al hacer takeover humano → llama a `POST /api/v1/messages/send` (o endpoint equivalente en connector-whatsapp que llame a Meta API)
- El botón de takeover no tiene sentido sin la capacidad de responder
- En mobile: diseño responsive del inbox (lista izquierda colapsa, hilo ocupa pantalla completa)
- Filtros básicos: solo takeover humano, solo bot activo, cerradas
- Búsqueda por número de teléfono
- Notas internas por conversación (no se envían por WhatsApp, solo visibles para el equipo)

### Estado actual

- Takeover implementado (cambia `status` de conversación)
- NO hay campo para enviar mensajes desde la consola
- Sin filtros, sin búsqueda

### Deuda más urgente

1. **Envío de mensajes desde consola al hacer takeover** — sin esto, el módulo está incompleto funcionalmente

---

## A.3 — Catálogo

### Visión objetivo

Un catálogo versátil que soporte múltiples tipos de negocio: ropa (talla/color), tecnología (modelo/capacidad), alimentos (peso/presentación), etc. Debe también poder importar información de producto desde fuentes externas.

### Detalles de ejecución

#### Variantes múltiples
- El formulario de creación debe soportar N variantes con atributos dinámicos (JSONB)
- Interfaz tipo "add variant" con atributos configurables por el tenant
- Precio + stock por cada variante

#### Importación desde MeLi / Internet
- Campo de "MeLi URL o ID" en la ficha de producto → el backend busca y pre-rellena título, descripción, imágenes y variantes
- Requiere endpoint en `services/api` que consulte MeLi API y retorne datos del producto
- Aplicar al formulario de creación como pre-fill (el tenant confirma/edita antes de guardar)
- Futuro: búsqueda por nombre en internet para productos sin MeLi ID

#### Carga masiva por categorías
- CSV upload con schema diferente según categoría (ej: `ropa.csv` con columnas talla/color, `tech.csv` con columnas modelo/capacidad)
- El tenant selecciona la categoría → se le muestra el template CSV correspondiente
- El backend valida el CSV y crea los productos con sus variantes

#### Paginación y búsqueda
- Paginación real (actualmente sin límite)
- Búsqueda por nombre de producto
- Filtro por estado (activo/inactivo)

### Estado actual

- Crea 1 producto + 1 variante "Standard" hardcodeada
- Sin paginación real
- Sin importación desde fuentes externas

### Deuda más urgente

1. Formulario de múltiples variantes
2. Importación desde MeLi ID/URL

---

## A.4 — Media

### Visión objetivo

La Media no debe ser un módulo aislado de "galería de archivos". Su valor real es **estar conectada al catálogo y al inventario** — toda imagen debe poder vincularse a un producto específico.

### Decisión de diseño: integrar, no eliminar

- NO se elimina Media como módulo separado
- El módulo Media funciona como biblioteca centralizada de assets del tenant
- Se añade la capacidad de vincular imágenes a productos/variantes desde el módulo Media O desde el módulo Catálogo
- Desde Catálogo, al editar un producto se puede seleccionar imagen desde la biblioteca Media (en vez de solo upload directo)

### Detalles de ejecución

- Columna `product_id` opcional en la metadata del archivo en Supabase Storage (o tabla `media_assets` futura)
- En la galería Media: badge visual si la imagen está vinculada a un producto (con link al producto)
- Filtros: sin vincular / vinculadas / por tipo de archivo
- Preview de imágenes en la galería (actualmente solo lista de nombres)

### Estado actual

- Upload/delete/copy URL implementados
- Sin asociación a productos
- Sin preview visual de imágenes en galería

### Deuda más urgente

1. Preview visual (thumbnails en la galería)
2. Asociación a productos

---

## A.5 — Inventario

### Visión objetivo

Control granular de stock con alertas configurables, historial auditable y sincronización bidireccional con MeLi.

### Detalles de ejecución

- **Umbral de stock bajo configurable por tenant** — no hardcodeado en 5. Guardarse en `notification_settings` o en `tenants.meta`
- **Historial paginado** de movimientos de stock (actualmente sin paginación)
- **Motivo obligatorio** en ajustes manuales (reason: adjustment/restock/correction)
- **Sincronización con MeLi**: al llegar un webhook de venta en MeLi, decrementar stock de la variante correspondiente (ya hay webhook MeLi — falta el decremento de stock)
- Indicador visual en la variante de si está sincronizada con MeLi o no
- Alerta cuando stock llega a 0 (no solo ≤ umbral)

### Estado actual

- Stock por variante, umbral ≤5 hardcodeado
- Ajustes implementados con movimiento en `stock_movements`
- Sin paginación en historial
- Sin sync con MeLi

### Deuda más urgente

1. Umbral configurable (mover de hardcoded a configuración del tenant)
2. Decremento de stock al procesar webhook MeLi

---

## A.6 — Pedidos

### Visión objetivo

El módulo de Pedidos es el flujo de vida comercial del tenant. Debe soportar pedidos manuales (desde consola), pedidos desde WhatsApp (via Orchestrator), y pedidos desde MeLi (via webhook). La relación con Envíos debe ser clara.

### Relación Pedidos ↔ Envíos (diseño)

```
Pedido (order)
  └─ puede tener 0 o 1 shipment
      └─ el shipment nace desde el módulo Pedidos (no desde Envíos)
      └─ el módulo Envíos muestra historial cross-order de todos los shipments
```

- Desde la vista de un pedido: botón "Crear envío" → abre formulario de cotización Envia con origen, destino y paquetes pre-rellenados desde el pedido
- El módulo Envíos es la vista de gestión de todos los shipments (historial, estados, tracking)
- Los dos módulos se complementan, no se duplican

### Detalles de ejecución

- **Crear pedido manual desde UI**: formulario con búsqueda de contacto, N items (producto + variante + cantidad + precio), cálculo automático de total
- **Multi-item**: el formulario actual solo soporta 1 item — debe soportar N
- **Link a conversación**: el pedido puede vincularse opcionalmente a una conversación de Inbox
- **Actualización de stock**: al confirmar un pedido, decrementar stock de las variantes incluidas (Server Action)
- Filtros: por estado, por fecha, por contacto

### Estado actual

- Listado y cambio de estado implementados
- Creación desde UI: 1 producto, 1 contacto, sin cálculo de total
- Sin vinculación a conversación

### Deuda más urgente

1. Creación manual multi-item con cálculo de total
2. Decremento de stock al confirmar
3. Botón "Crear envío" desde detalle de pedido

---

## A.7 — Contactos

### Visión objetivo

Base de clientes del tenant con historial cruzado (pedidos + conversaciones) y gestión de datos conforme a Habeas Data Colombia.

### Habeas Data Colombia — Análisis completo

**Ley aplicable**: Ley 1581 de 2012 (Habeas Data, Colombia) + Decreto 1377 de 2013.

**Roles en este sistema**:

| Actor | Rol legal |
|-------|-----------|
| Commerce Ops Platform (nosotros) | **Encargado del tratamiento** (procesa datos por encargo del responsable) |
| Tenant (cliente del SaaS) | **Responsable del tratamiento** (dueño de los datos de sus clientes) |
| Contacto de WhatsApp | **Titular de los datos** |

**Consecuencia práctica**:

1. La plataforma **NO es responsable directa** ante el titular — el tenant sí lo es
2. La plataforma debe firmar un **Contrato de Encargo de Tratamiento (DPA)** con cada tenant
3. El tenant debe obtener consentimiento de sus clientes para tratar sus datos personales
4. La plataforma debe proveer mecanismos técnicos para que el tenant pueda:
   - Ver qué datos tiene de cada contacto
   - Eliminar los datos de un contacto (derecho al olvido)
   - Exportar los datos de un contacto (portabilidad)

**¿Bloquea el desarrollo actual?** NO — pero impone requisitos futuros concretos.

**Cambios técnicos requeridos (no urgentes pero planificados)**:

| Cambio | Tabla | Prioridad |
|--------|-------|-----------|
| Campo `consent_given` BOOLEAN | `contacts` | Media (antes de Beta real) |
| Campo `consent_timestamp` TIMESTAMPTZ | `contacts` | Media |
| Endpoint DELETE contact (cascada a pedidos anónimos) | `contacts` | Media |
| Endpoint export contact data JSON | `contacts` | Baja |
| Cláusula DPA en contrato con tenants | Legal/comercial | Alta (antes de onboarding) |

**Responsabilidad del tenant**: El tenant debe mostrar aviso de privacidad y obtener consentimiento **antes** de la primera interacción por WhatsApp. Esto es responsabilidad del tenant, no de la plataforma técnicamente — pero la plataforma puede facilitar el mecanismo.

### Detalles de ejecución

- Auto-creación de contacto al iniciar conversación WhatsApp (actualmente manual)
- Vista de perfil con historial de conversaciones + pedidos vinculados
- Edición inline (básica)
- Búsqueda por nombre o teléfono

### Estado actual

- Listado y creación manual implementados
- Sin historial cruzado (pedidos + conversaciones)
- Sin auto-creación desde WhatsApp

### Deuda más urgente

1. Auto-creación de contacto al iniciar conversación en WhatsApp (Orchestrator)
2. Vista de perfil con historial de pedidos + conversaciones
3. Campo `consent_given` antes del onboarding a Beta real

---

## A.8 — Knowledge Base

### Visión objetivo — "El Giro"

Refactorizar la KB para implementar RAG real con embeddings + pgvector. La KB de texto plano es un primer paso funcional pero limitante a medida que crecen los documentos.

### Diseño RAG objetivo

```
Tenant crea documento KB
  → Backend genera embedding (Google Embeddings API o similar)
  → Almacena embedding en pgvector (columna `embedding vector(768)` en kb_documents)

Orchestrator recibe mensaje de usuario
  → Genera embedding del mensaje
  → Consulta kb_documents ORDER BY embedding <-> query_embedding LIMIT 5
  → Inyecta solo los documentos relevantes en el system prompt (no todos)
```

### Beneficios respecto al estado actual

| Aspecto | Texto plano (actual) | RAG (objetivo) |
|---------|---------------------|----------------|
| Escalabilidad | El prompt crece con cada documento | Solo los N más relevantes |
| Relevancia | Todos los documentos siempre | Solo los pertinentes a la consulta |
| Token cost | Alto (lleva toda la KB siempre) | Bajo (solo fragmentos relevantes) |
| Administración | Texto libre | Igual + mejor curación por categoría |

### Interfaz de gestión objetivo

- Vista previa de cómo quedará el contenido inyectado en el prompt (debug para el tenant)
- Indicador de "última vez que este documento fue recuperado en una conversación"
- Importación de documentos desde texto, PDF (futuro), URL (futuro)
- Tags además de categorías (más flexibilidad)
- Ordenamiento por relevancia, categoría, fecha de actualización

### Prerequisito técnico

- Verificar que pgvector está habilitado en el proyecto Supabase actual (OQ-T03 — pendiente de validar)
- Si no: pgvector se activa desde el Dashboard de Supabase en `Database > Extensions`

### Estado actual

- CRUD completo con categorías y toggle activo/inactivo
- Texto plano inyectado en el system prompt del Orchestrator
- Sin embeddings, sin RAG

### Deuda más urgente

1. Verificar pgvector disponibilidad (OQ-T03) — humano
2. Diseñar migración para `embedding vector(768)` en `kb_documents`
3. Integrar generación de embeddings en el pipeline de creación/edición

---

## A.9 — Integraciones

### Visión objetivo

Panel claro de estado de conectores por tenant, con capacidad de conectar/desconectar y diagnóstico básico de errores.

### Gap crítico confirmado: botón de desconexión MeLi

- El botón de **desconectar MeLi** NO existe en la UI actual
- El usuario actualmente no puede desconectar su cuenta MeLi una vez conectada via OAuth
- Esto debe resolverse antes del primer tenant real (riesgo operacional y de confianza)
- Endpoint backend necesario: `DELETE /api/v1/integrations/mercadolibre` → elimina/limpia `tenant_integrations` row para MeLi

### Detalles de ejecución

- Botón "Desconectar" en la card de MeLi (igual que Envia)
- Estado de sincronización en tiempo real: última sincronización exitosa, errores recientes
- Log básico de errores por integración (últimas 10 entradas de error)
- Futura integración de Telegram (canal interno de notificaciones — OQ pendiente)

### Estado actual

- MeLi: solo botón "Conectar" vía OAuth
- Envia: conectar/desconectar con API key
- Sin logs de errores

### Deuda más urgente

1. **Botón "Desconectar MeLi"** — backend + UI

---

## A.10 — Envíos / Shipping

### Visión objetivo

Ver sección A.6 para la relación Pedidos ↔ Envíos.

El módulo Envíos es la **vista operacional de todos los shipments** del tenant: historial, estados, tracking. El flujo de creación de un envío nace desde un pedido.

### Detalles de ejecución

- Formulario interactivo de cotización (el backend POST /shipping/quote existe, la UI no lo expone)
- El formulario debe rellenar: origen (dirección del tenant en Configuración), destino (dirección del contacto del pedido), dimensiones/peso del paquete
- Al cotizar: mostrar tabla de opciones de carrier/servicio/precio (la API Envia devuelve varias)
- Al seleccionar una opción: persistir `selected_rate` en `shipments`
- Fases 2-3 (label, tracking, pickup): planificadas, no implementadas

### Relación con Pedidos

- El envío se **crea desde un pedido** (no desde el módulo Envíos directamente)
- El módulo Envíos muestra el historial cross-order
- Esto evita la duplicación percibida

### Estado actual

- Historial de shipments implementado
- Backend de cotización operativo (POST /shipping/quote)
- Sin formulario interactivo en UI
- Sin selección de carrier/servicio en UI

### Deuda más urgente

1. Formulario interactivo de cotización (Client Component)
2. Tabla de selección de carrier después de cotizar
3. Botón "Crear envío" en vista de pedido individual

---

## A.11 — Métricas

### Visión objetivo

El módulo Métricas es **distinto** del Tab de Negocio del Dashboard. El Dashboard muestra urgencia operacional + resumen ejecutivo. Métricas es el módulo analítico profundo con filtros temporales.

### Detalles de ejecución

- Filtro de período: hoy / esta semana / este mes / 3 meses / personalizado
- Gráficas de tendencia: conversaciones por día (línea), pedidos por día (barras), revenue por semana (área)
- Métricas de IA: tiempo promedio de respuesta del Orchestrator, % de conversaciones resueltas por bot vs takeover humano
- Tasa de conversión: conversaciones → pedidos
- Pedidos por estado (pastel)
- Top productos: por cantidad vendida Y por revenue generado (ya existe, falta gráfica)
- Exportación de datos (CSV al menos para pedidos + métricas de período)

### Estado actual

- 4 KPI cards + 2 listas (pedidos por estado + top productos)
- Todo estático, período fijo 30 días
- Sin gráficas, sin filtros de período

### Deuda más urgente

1. Filtro de período (client-side o con query params)
2. Gráficas de tendencia (recharts o chart.js)
3. Métrica de conversación → pedido

---

## A.12 — Auditoría

### Visión objetivo

Trazabilidad completa de todas las acciones del equipo del tenant, con filtros eficientes y exportación.

### Detalles de ejecución

- Filtro por **usuario** (user_email del equipo)
- Filtro por **rango de fechas** (date picker)
- Filtro por entity_type (ya existe)
- Exportación CSV del log filtrado
- Descripción legible de la acción (actualmente código como `product.create`) → texto como "Producto 'Camiseta verde' creado por ana@empresa.com"

### Estado actual

- Filtro por entity_type, paginación 25/página, expandible con `<details>`
- Sin filtro por usuario, sin filtro por fecha, sin exportación

### Deuda más urgente

1. Filtro por rango de fechas + usuario
2. Exportación CSV

---

## A.13 — Configuración

### Visión objetivo

La configuración del tenant incluye la identidad visual de su espacio en la plataforma. Los pequeños detalles de branding suman mucho a la percepción de valor del SaaS.

### Branding del tenant

- **Logo del tenant**: el tenant sube su logo → se muestra en el sidebar de la Tenant Console (en vez del logo genérico de la plataforma)
- **Color primario del tenant** (opcional): permite personalizar el accent color del sidebar/cards
- El logo se almacena en Supabase Storage (bucket `tenant-branding` o en `tenant-media`)
- `tenants` table: añadir columnas `logo_url TEXT` y `brand_color TEXT` (hex)

### Impacto visual

```
Sidebar actual: logo genérico "Commerce Ops"
Sidebar con branding: logo del tenant (ej: "Tienda Boutique XYZ")
```

Este nivel de personalización hace que el tenant sienta que la plataforma es "suya", no genérica.

### Detalles de ejecución adicionales

- **Cambio de contraseña** desde la UI (actualmente no existe)
- **Gestión de invitaciones** al equipo por email (actualmente se añaden manualmente)
- **Dirección de origen** para envíos (campo en Configuración → usado como default en cotizaciones Envia)
- **Zona horaria del tenant** (para métricas y reportes en hora local)

### Estado actual

- Perfil de empresa + WABA, gestión del equipo con RBAC, notificaciones Telegram
- Sin branding, sin cambio de contraseña, sin dirección de origen

### Deuda más urgente

1. Logo del tenant (Supabase Storage + campo `logo_url` en `tenants`)
2. Dirección de origen de envíos (necesaria para formulario de cotización Envia)
3. Cambio de contraseña

---

## Resumen de deudas técnicas por impacto

| Prioridad | Módulo | Deuda | Tipo |
|-----------|--------|-------|------|
| 🔴 CRÍTICO | Inbox AI | Envío de mensajes en takeover | Backend + UI |
| 🔴 CRÍTICO | Integraciones | Botón desconectar MeLi | Backend + UI |
| 🟠 ALTA | Dashboard | Tab operaciones + gráficas básicas | UI |
| 🟠 ALTA | Pedidos | Creación multi-item + decremento stock | Backend + UI |
| 🟠 ALTA | Configuración | Dirección de origen (necesaria para Envíos) | DB + UI |
| 🟠 ALTA | Envíos | Formulario interactivo de cotización | UI (backend listo) |
| 🟡 MEDIA | Catálogo | Múltiples variantes en formulario | UI |
| 🟡 MEDIA | Configuración | Logo del tenant (branding) | DB + Storage + UI |
| 🟡 MEDIA | Contactos | Auto-creación desde WhatsApp | Orchestrator |
| 🟡 MEDIA | Inventario | Umbral configurable | DB + UI |
| 🟡 MEDIA | Knowledge Base | Verificar pgvector + planificar RAG | Técnico (investigación) |
| 🟡 MEDIA | Métricas | Filtro de período + gráficas | UI |
| 🟢 BAJA | Media | Preview thumbnails + vinculación a productos | UI |
| 🟢 BAJA | Auditoría | Filtros por fecha/usuario + exportación | UI |
| 🟢 BAJA | Contactos | Campo `consent_given` (Habeas Data) | DB + UI |

---

## Documentos relacionados

- `docs/product/admin-ui-modules.md` — Evidencia en código y estado actual por módulo
- `docs/architecture/front-back-separation.md` — Mapeo UI ↔ Backend
- `docs/integrations/courier-envia.md` — Diseño completo del módulo Envíos
- `docs/risks/open-questions.md` — OQ-T03 (pgvector) pendiente
