# Framework de Arquitectura: Resolución de Vacíos Operativos

## Objetivo
Documentar **únicamente** la arquitectura definitiva para solventar los cuatro vacíos críticos detectados, junto con la validación de documentación oficial requerida, como se exige en el framework de calidad de salida (`06-output-quality.md`).

---

## 1. Riesgo de Cuotas Concurrentes (Supabase Realtime)

### Arquitectura de Solución
El acceso "Realtime" se limitará estrictamente al dominio de **Conversaciones** (`inbox`, `messages`).
El sistema no expondrá `Postgres Changes` indiscriminadamente para métricas de inventario ni logs.
En el frontend, el cliente React utilizará una reconexión controlada y un fallback a REST (polling controlado de baja frecuencia) si el WebSocket falla o es rechazado por `rate limiting`.

- **DECISION FINAL**: Restringir Supabase Realtime Channels exclusivamente para los eventos de la capa de inbox/bot en el frontend. Toda otra pantalla viva (Dashboard, Pedidos, Logs) se refrescará con REST HTTP vía `SWR / React Query`.
- **VALIDAR EN DOCUMENTACION OFICIAL**: Confirmar en _Supabase Realtime Documentation_ el límite exacto de conexiones concurrentes según tier (Free = 200, Pro = 500) y el channel connection limit for Websockets per project.
- **RIESGO**: Que un tenant con múltiples pestañas abiertas consuma el pool entero de conexiones del sistema causando desconexiones silenciosas al resto de tenants.
- **IMPACTO OPERATIVO**: Degradación de la "Voz al Cliente" y de la rapidez del handoff entre agente y bot. Sin embargo, no hay pérdida de datos transaccionales, es puramente UX.
- **INTERVENCION HUMANA REQUERIDA**: Monitorear en el panel métrico global el uso de Realtime connections; y, si un tenant está abusando, comunicarse y planear un upgrade o limitación estricta de sus suscripciones.

---

## 2. Vacío en Quotas de Storage (Supabase Storage)

### Arquitectura de Solución
Es imperativo aislar el espacio consumido por tenant_id para evitar que uno agote el límite del sistema.
Dado que Supabase Storage no permite imponer RLS por "*tamaño total bytes del tenant*", se resolverá en la **Capa API (FastAPI backend)** usando signed URLs proxy.
1. Se crea la tabla transaccional `storage_usage_stats (tenant_id, bytes_used)`.
2. El API Backend aprueba las subidas. Antes de devolver una presigned URL de upload para el Bucket Privado, verifica contra los bytes usados.
3. Se interceptan los webhooks de storage/pg para actualizar la tabla.

- **DECISION FINAL**: FastAPI será el proxy validador. El frontend nunca sube de manera directa pública a Supabase Storage; sino que FastAPI valida la cuota (`quota_limit`) y emite una `presigned upload URL` temporal y restrictiva, además de restringir a los agentes a descargar usando RLS nativo en Supabase.
- **VALIDAR EN DOCUMENTACION OFICIAL**: En _Supabase Storage_, validar la emisión y las duraciones máximas de los `presigned uploads`, además de corroborar los límites de tamaño en planes Pro o Enterprise. Adicionalmente, revisar en _Meta API_ (WhatsApp) el tamaño máximo de descarga de video/documento para setear la cuota por operación.
- **RIESGO**: Que la tabla `storage_usage_stats` presente divergencias con la ocupación real del bucket si los deletes (borrados masivos) no se reflejan automáticamente.
- **IMPACTO OPERATIVO**: Un tenant con cuotas divergentes podría bloquear la propia empresa durante envíos comerciales.
- **INTERVENCION HUMANA REQUERIDA**: Setup inicial de `quotas_limit` por tenant según el nivel comercial que tenga activo al suscribirse, reajuste por el owner si reportan falso positivo.

---

## 3. Riesgos de Concurrencia de Múltiples Workloads (Sincronización Meli/Orders)

### Arquitectura de Solución
El ciclo de notificaciones y la sincronización se desagregan. El Webhook de FastAPI es un recolector crudo (`dumb receiver`):
1. El webhook inbound recibe la payload y de inmediato registra un job en la tabla nativa persistente usando **`pgmq` / Supabase Queues**, devolviendo HTTP 200 OK en ms.
2. Un Worker dedicado en **Render (Background Worker)** lee la cola por `tenant_id` y procesa seriamente limitando la concurrencia (`max_retries`, `visibility_timeout`).
3. El update transaccional hacia las tablas de inventario en Postgres siempre tiene un Order By en la transacción explícita a evitar bloqueos circulares (`deadlocks`).

- **DECISION FINAL**: Desacoplar obligatoriamente el request-path del heavy-processing garantizando idempotencia. Se implementará Supabase Queues o una solución nativa basada en Postgres Row Lock `FOR UPDATE SKIP LOCKED`.
- **VALIDAR EN DOCUMENTACION OFICIAL**: 
  - En _MercadoLibre Webhook Notification Guidelines_: Validar Rate Limit y políticas de IP Safelisting (necesario si Render rota de IP) y Retry Policy del lado del marketplace en caso de timeout.
  - En _Render Background Workers documentation_: Confirmar las limitaciones de memoria de Worker y el timeout real de desconexión idle respecto de la base de DB proxy externa (Supervisor/pgbouncer/Supabase).
- **RIESGO**: Acumulación exponencial del backlog en la cola ("Queuing Delay") en las horas pico del eCommerce, provocando fallas masivas de consistencia final (*Eventual Consistency failure*).
- **IMPACTO OPERATIVO**: Sobreventa del stock por la latencia en la confirmación al canal opuesto, resultando en incidentes comerciales serios logísticos.
- **INTERVENCION HUMANA REQUERIDA**: Habilitación/Rotación segura del Access Token de Mercado Libre. Resolución asíncrona de reconciliaciones del Dashboard si fallaron N veces (`Dead Letter Queue management`).

---

## 4. Mantenimiento de Roles de Plataforma & Bypass RLS

### Arquitectura de Solución
Para resolver la imposición de roles administrativos respetando la seguridad intrínseca del sistema:
1. No usar `anon key` o `service_role` de forma indiscriminada en frontend ni backend que maneje peticiones.
2. Todo acceso en backend (FastAPI) de soporte usarán llamadas con `tenant_id` explícitamente forzado en las DB queries y audit logs forzosos por trigger.
3. Se adoptarán **Custom Claims in JWT**. Un super-admin obtiene el token JWT en el sign-in con el custom claim estructurado: `{"user_role": "platform_admin"}` usando Supabase Hooks de autenticación, o un endpoint seguro en el login que actualice los _user_metadata_.
4. Las `RLS policies` por defecto incluirán el check seguro, ej: `(auth.jwt()->>'user_role' = 'platform_admin')`.

- **DECISION FINAL**: Modelar los Roles administrativos de sistema inyectando roles temporales y validados en JWT Claims en el backend, los cuales persisten por la duración de sesión temporal y se evalúan nativamente por políticas de seguridad de Row Level nativo, y en FastAPI backend validados como Pydantic Security Dependecies.
- **VALIDAR EN DOCUMENTACION OFICIAL**: En _Supabase Auth Custom Claims & Hooks_, validar la propagación de metadata/claims de auth y la repercusión de latencia o performance impactante en las sentencias generadas internamente por la DB en una alta masiva de requests (Policy performance rules).
- **RIESGO**: Abuso voluntario o involuntario del flag de plataforma para ignorar fallas transaccionales; inyección o alteración de metadata de usuario desde una mala implementación.
- **IMPACTO OPERATIVO**: Completa y catastrófica violación al tenant_isolation perdiendo fiabilidad ISO y comercial respecto de la plataforma central y filtraciones.
- **INTERVENCION HUMANA REQUERIDA**: El "grant" de SuperAdmin role a un partner humano no se realiza desde la interfaz central, solo via Base de datos o script central de despliegue controlado. Todo acceso temporal deberá ser trazado en `support_access_logs`.
