# Realtime Architecture

## Objetivo
Definir qué partes del sistema necesitan actualizaciones en tiempo real y qué mecanismo usar.

## Casos de uso principales
- inbox de conversaciones
- cambios de asignación de agente
- handoff a humano
- alertas de stock
- cambios de estado de pedido visibles en panel
- panel de operación con métricas vivas mínimas

## Estrategia
### Inicio
Usar Supabase Realtime con enfoque conservador.

### Preferencia inicial
- Postgres Changes para simplicidad en pantallas de operación
- Broadcast solo si ciertas vistas se vuelven muy calientes o si la arquitectura lo exige

## Qué debe ir en realtime
- nuevas conversaciones
- nuevos mensajes
- cambios de estado de conversación
- asignación/reasignación de agente
- handoff abierto/cerrado
- cambios visibles de pedidos relevantes para atención
- alertas operativas

## Qué NO debe depender exclusivamente de realtime
- persistencia del dato
- lógica crítica de negocio
- sincronización marketplace
- auditoría
- reconciliaciones
- cálculo de stock

## Reglas
- realtime es para UX y operación, no para fuente de verdad
- todo evento visible debe existir primero en DB
- la UI debe soportar fallback por refresh/polling controlado
- no diseñar lógica crítica que falle si realtime se interrumpe

## Riesgos a vigilar
- suscripciones excesivas por tenant
- eventos duplicados
- pantallas con demasiadas fuentes de actualización
- errores de autorización sobre canales en vivo

## Pendientes
- definir exactamente qué vistas usarán Postgres Changes
- evaluar más adelante si alguna vista requiere Broadcast
EOF

cat > docs/architecture/async-processing.md <<'EOF'
# Async Processing Architecture

## Objetivo
Separar correctamente las operaciones rápidas del request path y los procesos pesados o lentos.

## Principio
Toda tarea que:
- dependa de terceros,
- pueda tardar,
- requiera retry,
- procese media,
- procese documentos,
- genere embeddings,
- sincronice marketplaces,
debe salir del request path principal.

## Base tecnológica
- Supabase Queues / pgmq para colas durables
- Render Background Workers para consumo de jobs
- Render Cron Jobs para tareas programadas
- Postgres como fuente de estado de jobs y auditoría

## Tipos de trabajo asíncrono
### 1. Media processing
- descarga de media de WhatsApp
- validación
- persistencia en Storage
- extracción de metadatos

### 2. Knowledge processing
- carga de documentos
- parsing
- chunking
- embeddings
- reindexación

### 3. Marketplace sync
- sync de productos
- sync de variantes
- sync de stock
- reconciliación
- reintentos

### 4. Operación
- alertas
- follow-ups
- resúmenes
- notificaciones internas

## Reglas de diseño
- jobs idempotentes
- payload mínimo y trazable
- estado auditable
- retries controlados
- separar errores recuperables de no recuperables
- registrar tenant_id en todo trabajo que corresponda

## Jobs sugeridos
- whatsapp_media_download
- document_ingest
- embeddings_generate
- ml_product_sync
- ml_stock_sync
- ml_reconciliation
- notification_dispatch
- audit_compaction

## Qué debe quedar en request
- validación básica
- persistencia mínima
- respuesta rápida al usuario o proveedor
- encolado del trabajo pesado

## Qué debe salir del request
- procesamiento pesado
- llamadas largas a terceros
- reconciliaciones
- importaciones masivas
- generación de embeddings
EOF

cat > docs/deployment/local-dev.md <<'EOF'
# Local Development Environment

## Definición
El entorno local de este proyecto es una VM dedicada al proyecto, accesible por Remote SSH.

## Decisión actual
- Host: Fedora 43
- Virtualización: KVM
- Guest recomendado: Fedora Server o equivalente Linux orientado a desarrollo
- Workspace del proyecto: repo aislado dentro de la VM

## Objetivos del local
- aislamiento del proyecto
- reglas del agente específicas sin contaminar otros proyectos
- secretos separados
- tooling consistente
- desarrollo backend/frontend/documentación
- pruebas locales controladas

## Reglas
- desarrollar dentro del filesystem Linux de la VM
- no mezclar tooling del proyecto con otros repos
- no exponer secrets en el repo
- mantener el workspace autocontenido

## Herramientas mínimas esperadas
- git
- python
- node
- package manager del monorepo
- editor con Remote SSH
- Antigravity apuntando al workspace del repo

## Consideraciones
- webhooks externos pueden requerir túneles o staging más adelante
- el entorno local no reemplaza producción
- staging se añadirá cuando entren integraciones reales sensibles

## Estado de ambientes
- local: VM dedicada
- prod: Render + Supabase
- staging: diferido hasta necesidad real