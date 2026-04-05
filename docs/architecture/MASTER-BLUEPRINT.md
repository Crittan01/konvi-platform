# Architecture Master Blueprint: Commerce Operations Platform SaaS

## 1. RESUMEN EJECUTIVO
- **Objetivo del producto**: Consolidar en un SaaS multi-tenant definitivo la atención (inbox), órdenes, inventario y soporte inteligente (IA) como sistema central de eCommerce para WhatsApp y Marketplaces.
- **Propuesta de valor**: Transformar un "bot conversacional" en un Operation Management System total, evitando que las reglas del negocio las decida una IA no determinista.
- **Selección de Arquitectura Costo/Beneficio**: Un núcleo monolítico modular (FastAPI) junto a Postgres + RLS (Supabase) provee todo el aislamiento multi-tenant robusto necesario sin pagar la factura de latencia o DevOps de microservicios puros y Kubernetes prematuros.
- **Alcance inicial de producción**: Backoffice administrativo, inbox en tiempo real, administración de Catálogo, integración de Mercado Libre masiva vía colas, Telegram como alertador interno y AI Orchestrator con tool calling asertivo.
- **Preparación posterior**: El *Connector Framework* garantizará sumar Shopify y Custom Stores adaptando solo el payload a nuestra estructura in-house.

---

## 2. ARQUITECTURA FUNCIONAL DEL PRODUCTO

1. **Backoffice**: Para Tenant Owner/Staff. Administra usuarios, features, suscripciones. Depende del módulo Core API.
2. **Inbox WhatsApp**: Interfaz de agentes. Consume Supabase Realtime y REST. Emite resoluciones, muta a Humano.
3. **Catálogo y Variantes**: Administrador de SKU, Categorías. Es la fuente de la verdad consumida por bots y connectors.
4. **Media**: Backend proxy a Storage. Los usuarios suben imágenes que AI o WhatsApp usarán luego en plantillas.
5. **Stock, Pedidos y Logística**: Motor transaccional. Mutado por MercadoLibre Connector y ventas de agentes.
6. **Knowledge Base (RAG)**: Gestión de PDFs y FAQ. Transforma documentos en vectores indexados.
7. **AI Orchestrator**: "Cerebro" de parseo de intenciones. Usa *tools* transaccionales en tiempo real respetando permisos de Tenant.
8. **Telegram Interno**: Alertas operativas y de soporte (caída de tokens de ML, handoff urgente).
9. **Módulo Mercado Libre (Channel Connector)**: Agente externo, sync de inventarios. Emite updates crudos a colas durables.
10. **Seguridad y Auditoría**: Cruza a todos. Monitorea accesos y cambios logueados en db (Audit Tables).

---

## 3. ARQUITECTURA TECNICA

- **Frontend App**: SPA en React conectada a API. Workspace Tenant y Platform separados lógicamente por routes.
- **API Service (FastAPI)**: Web Service en Render. Soporta endpoints y valida la capa gruesa del negocio y seguridad Auth.
- **Worker Service**: Background worker de Render sin puertos expuestos, consume de forma segura colas de `pgmq`. No bloquea request de API HTTP.
- **Cron Jobs**: Scripting programado para "retries", chequeos de estados de ML, basureo de logs, vector index updates.
- **Connector Framework**: Abstracción Python (`BaseConnector`) que requiere mapear métodos `map_inventory_in()`, `map_inventory_out()`.
- **Acoplamiento nulo**: Mercado Libre manda data a una tabla de Cola Inbound, luego el Web Service cierra. El Worker procesa.

---

## 4. DECISION FINAL DE STACK TECNOLOGICO

- **React + TS + Tailwind + shadcn/ui**: 
  - *Decisión:* Desarrollo ultrarrápido y tipado robusto. 
  - *Riesgo:* Dependencia continua de hydration overheads. Costo operativo bajo al estar CDN hostings.
- **Python + FastAPI**: 
  - *Decisión:* Velocidad de Python en genAI e integraciones de SDKs nativas de data, async IO concurrente inmejorable.
- **Render**: 
  - *Decisión:* PaaS de 0-DevOps. Background y cron jobs integrados de caja.
  - *Documentación:* Chequear Memory Limits en Background Workers.
- **Supabase Postgres + Auth + RLS + Storage + Realtime**: 
  - *Decisión:* Provee Base de datos, autenticación por Claims, isolation a nivel fila gratuito, y storage proxy unificado reduciendo infra costs (No AWS S3/Cognito extras).
  - *Riesgo:* Vendor Lock-In relativo y rate-limits ocultos (PgBouncer connections limit).
- **pgvector**: 
  - *Decisión:* No requiere Pinecone externo extra, RLS de PostgreSQL también filtra búsquedas de embeddings nativamente.
- **Supabase Queues / pgmq**: 
  - *Decisión:* Evita Celery/Redis que suma complejidad DEV. `pgmq` entrega la misma transaccionalidad sin duplicación.
- **WhatsApp Cloud API & Telegram Bot API**: 
  - Oficiales y nativas sin man in the middle.
- **OpenAI / Modelos Small con Tooling**: 
  - Reducen alucinaciones mediante Structured JSON constraints y son económicos.

---

## 5. MODELO MULTI-TENANT

- **Estrategia General**: `tenant_id` obligatorio en TODAS las entidades a nivel tabla (Catálogo, Conversaciones, Embeddings).
- **Separación de Storage**: Storage unificado en el proveedor con un campo o path de la URL del bucket conteniendo al tenant. Middleware de Cuotas impide el Noisy-Neighbor o que un tenant arruine el límite.
- **Separación Ingesta (Colas)**: Los jobs tienen en payload el `tenant_id` para resolver concurrencia prioritaria por cliente en el Worker.
- **Activación y Soft Delete**: `status` in `tenant` table. Todo RLS chequeará la vista de status para denegar a tenants suspendidos. Un tenant eliminado marcará `is_deleted=TRUE` por retención.
- **Subdominios Puros de UX**: Subdominio para ruteos visuales (marca_tenant.com), no confiere mitigación de RLS (evita hack por Host header injectión). La seguridad real vive en JWT claims en PostgreSQL de modo criptográfico.

---

## 6. AUTHENTICATION Y AUTHORIZATION

### Estricto RLS y Roles
- Supabase Auth maneja sesiones JWT mediante Email/Pass, OAuth.
- **Claims JWT**: Tras el Auth hook (sign-in), se inyectan metadata claims como `user_role` (ej: `tenant_admin`, `agent`, o el cross-platform `platform_admin`).
- Toda interacción public/backend exige: `auth.uid() = tenant_members.user_id AND tenant_id = request_tenant`.
- Nunca se emite la *Service Role Key* hacia APIs internas. Se hace bypass únicamente integrando la comprobación `(auth.jwt()->>'user_role' = 'platform_admin')` en RLS y ejecutando *Support Tracking Trigger Logs*.

---

## 7. MODELO DE DATOS

Principales dominios:
- **Core SaaS**: `tenants` (clave primaria id uuid), `tenant_members` (asocia users a tenant + su scope local).
- **Operaciones Product y Catalog**: `products`, `product_variants`. Incluyen campos JSONB para overrides. Siempre `tenant_id`. Indices en `sku` escalado.
- **Canales**: `channels`, `channel_accounts`. Guarda tokens OAuth encriptados o en Vault de Supabase si aplica.
- **Conversacional**: `conversations`, `messages`, `contacts`. Claves con idx para búsquedas temporales. RLS crítico.
- **Jobs**: `sync_runs`, `sync_errors`. Auditoria batch.

---

## 8. STORAGE Y MEDIA

- Rutas de almacenamiento siguen la convención: `{bucket_name}/{tenant_id}/{module}/file.ext`
- **Descargas de Meta / WhatsApp**: El proxy descarga desde FB de forma privada con Headers, guarda local/cloud en `{tenant_id}/whatsapp_media`. 
- **Cuotas Proxy**: Validación de tipo Mime + tamaño de Bytes agregados en `storage_usage_stats` bloqueando de forma segura (FastAPI signed link generation) y limitando excesos comerciales (Evitando que guarden películas ISO).

---

## 9. REALTIME

Postgres Changes solo para vistas "Calientes": `inbox` y `messages`, donde un agente necesita 20 milisegundos de response por chat. 
**Restricción RLS Realtime**: Configurar supabase publication RLS correctas; los cambios se suscriben filtrando via WebSocket context `tenant_id`.
**Fallback REST**: Obligatoriamente el FE utiliza `useSWR/ReactQuery` interval refresh si Supabase agota el quota (ej: Error websocket o desconexión idle). Grillas de stock nunca son realtime websockets.

---

## 10. AI ORCHESTRATOR

- **El LlM NUNCA toma el estado real**: Responde redactando intenciones, determinando la función, pero la ejecución de la "Herramienta" emite la verdad.
- **Herramientas (Tool Contracts)**: 
  - `get_variant_stock(sku: str) -> Int`
  - `create_handoff(reason: str) -> status`
  - `quote_shipping(...)`
- El LLM solo obtiene acceso a RAG con datos no-transaccionales; la comprobación es siempre backend API. Guardrails cancelan prompt inject de un cliente engañando a pedir descuentos libres si no se encuentra pre-programado.

---

## 11. RAG / KNOWLEDGE BASE

- Fragmentación (Chunking) usando `Langchain` u otro loader estándar sobre PDFs. 
- Ingesa Vectorial `pgvector` indexada en una columna flotante con HNSW/IVFFlat index.
- Condicional Obligatorio: `WHERE tenant_id = <requestst_tenant>`. No existe cross-tenant extraction.
- **Versionado y Reindex**: Desactivación soft para "reindexar". Si una FAQ cambia, los chunks viejos pasan a status inactive para retener trazabilidad de tickets RAG anteriores, evitando confusión en auditoría.

---

## 12. WHATSAPP CLOUD API

- **Webhooks Verification y Rate Limits**: Respuesta en <1s forzada (`dumb proxy`) devolviendo Hub Challenge en GET y en POST 200 Inmediato enviando a pgmq.
- **INTERVENCION HUMANA REQUERIDA**: 
  - *Quien:* Admin de Plataforma y Tenant Owner. 
  - *Pasos:* Creación de Meta App, WABA, vinculación a BM, validación final con Número Comercial (OTP sms), creación y revisión (Wait-time de Meta) manual de Messages Templates interactivos.
  - *Resultado:* Token de sistema y WABA ID registrados en tabla base para operación bot.

---

## 13. TELEGRAM INTERNO

Uso para el Staff / Support o Owners del Tenant que requieran alertas VIP. No para consumidores eCommerce.
- Exposición selectiva y anónima: Alerts en formato texto, sin inyección media.
- Limitación a Chat IDs registrados manualmente o verificados con OTP. Rate limits por si Marketplaces throw 10k alerts in seconds (Batch Alerts).

---

## 14. INTEGRACION MERCADO LIBRE

- Obligatorio mapeo exacto de la arquitectura interna de Variantes con `variations/User Products` en Meli.
- Sincronización inyectada a Job Queue. Worker procesa con control de rate limiting oficial de MLib.
- Reconciliación nocturna obligatoria cruzando todos los listings vs tabla productos (Webhook != Garantía Absoluta).
- **INTERVENCION HUMANA REQUERIDA**:
  - *Que:* Autorización de Integración o OAuth. 
  - *Pasos:* Autorizar redirect App Mercado libre en modo offline access. Soporte de tokens expirados (cada 6 hs se regenera asíncrono, si da Error_Auth requiere clic del humano dueño de la cuenta vendedor mercantil nuevamente en Backoffice).

---

## 15. PREPARACION PARA SHOPIFY

El *Connector Framework* recibirá mapeos como `products.json` proveniente de la Admin API de GraphQL de Shopify como si fuese otro channel inhouse, acoplando `Shopify webhook inventory level update` a nuestra cola nativa de inventarios.
- **INTERVENCION HUMANA REQUERIDA**:
  - *Que:* Custom Apps for Shopify. 
  - *Pasos:* Merchant crea App interna (Headless) entregando access Token al platform o vía OAuth App review pública aprobada (Si se plantea como Public Shopify App). Asignación vital de `write_products`, `read_inventory`.

---

## 16. SOPORTE FUTURO PARA TIENDA PERSONALIZADA

Será otro Headless Consumer expuesto al Backend a través de tokens públicos con CORS scope restriction o proxies. Consumará a `api.v1.public.catalog.*` limitados visualmente y disparará carritos que decantarán en `orders`.

---

## 17. LOGISTICA / SHIPPING

- Base en tablas para `carriers`, zonas postales, peso/volumen.
- Cotización estática para primera iteración, y el proxy FastAPI para enviar en el futuro HTTP posts con dimensiones reales (WxHxD) a FedEx/DHL o carrier local agregador sin modificar la inteligencia del LLM (El Tool local esconde todo).

---

## 18. COLAS, WORKERS Y CRON

- *Que va a Queue:* MLib incoming webhooks, WhatsApp incoming webhooks, Media downloads pesados.
- *Tipos:* Dead-letter para reintentos fijos; Batching jobs limitados a `visibility_timeout` nativo de Postgres (Skip locked).
- Cron jobs inyectarán en la cola (ej `0 3 * * *` de sync final, cleanup y metrics crunch).

---

## 19. DESPLIEGUE FINAL

- Infraestructura: PaaS Moderno nativo. 
- Local (VM ssh / Docker-compose), Staging (Pre-Prod clones en Render).
- **Migraciones de Db**: `Alembic` aplicadas desde pipeline de render antes o en pre-boot phase.
- **INTERVENCION HUMANA REQUERIDA**:
  - Compra de C-Name Domains.
  - Setup de DNS TXT para Emails de Auth.
  - Inyecciòn manual de `SUPABASE_KEY` master y Secrets Meta en Render.

---

## 20. SEGURIDAD EXTENDIDA

- Strict RLS aislando *Row Level*.
- Validation de Mime-types para Subidas (prevención de scripts executables).
- Rate Limiting a nivel API con `slowapi` en FastAPI por IP + API Keys del Tenant.
- Prevención total contra *Prompt Injection* (Los outputs del LLM deben cumplir un parser JSON Pydantic validado, si el bot decide de pronto que de un descuento del 100%, Pydantic validará `assert discount <= rule_max_disc`.)

---

## 21. OBSERVABILIDAD Y SOPORTE

Métricas consolidadas sobre el Backport o PostHog (opcional a futuro). Por defecto log estructurado JSON.
Alerta crítica si *MercadoLibre Token Refresh fallando > 2x* se manda a grupo Telegram staff.

---

## 22. ROADMAP DE IMPLEMENTACION

- **Fase 0**: Fundamentos DB (RLS, Migrations, Storage config RLS, Docker local ready).
- **Fase 1**: Auth total + RLS Base + Catálogo CRUD (Core Transaccional Web).
- **Fase 2**: Integración Whatsapp C-API Inbound Raw / Webhooks Seguros en Queue + Fallback Frontend (inbox crudo Realtime).
- **Fase 3**: Logística Simple, Órdenes Transaccionales internas + Stock Decrement system.
- **Fase 4**: AI Orchestrator sumado al Inbox como Bot proxy, con tools básicos y Knowledge Base vectorial (RAG Ingest).
- **Fase 5**: Sincronizaciones bidireccionales asíncronas con API Oficial de Mercado Libre y Webhooks de la app.
- **Fase 6**: Hardening, Métricas exhaustivas de logs y Support Bypass seguro en Producción total.

---

## 23. CHECKLIST DE IMPLEMENTACION BASADA EN DOCUMENTACION OFICIAL

*(Antes de emitir cualquier código, se fuerza un read/validate oficial en estos rubros)*
- [ ] **Supabase Auth / Policies**: Custom JWT injection methods & RLS Overhead limitations docs.
- [ ] **Supabase Storage**: Quota limits en Tiers gratuitos y PRO, Signed urls caching headers rules.
- [ ] **Supabase Realtime**: Rate limit concurrente, disconnect timeouts of active Websockets channels.
- [ ] **Supabase pgmq**: Implementación correcta en Postgres extension docs 2024+.
- [ ] **Render Web/Background Services**: Zero-downtime deployment behaviour, memory/out of bounds limits, Cron scheduling rules.
- [ ] **Meta WhatsApp API**: Policies comerciales (Opt-ins requeridos), Expiración y Auth tokens permanentes limitados; validación SHA-256 de webhooks.
- [ ] **Telegram Bots API**: Límite de mensajes por segundo (30msg/s max approx for broadcasting or less).
- [ ] **Mercado Libre Developer**: Flujo de autorización OAuth explícito, caducidad del Refresh Token y API Limits por categoría y sincronización masiva offline.

---
*(End of Architecture Blueprint Final)*
