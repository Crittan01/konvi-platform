# Próximos Pasos — Estado 2026-04-28

## Cierre sesión actual (2026-04-28, rev. 66) — CIERRE DE CERTIFICACIÓN REAL

- ✅ Cerrado WS1: humanización end-to-end (system prompt + 5 tonos ampliados +
  salvaguarda con 25 variantes + reescritura humana de mensajes templated:
  cancelación, reactivación, corrección de datos, pago fallido Wompi, tracking,
  ticket de claim).
- ✅ Cerrado WS2: `MAX_PROCESSING_ATTEMPTS=5` unificado (.env.example, worker.py
  default, render.yaml). Local replica producción.
- ✅ Cerrado WS3: MeLi webhook hardening — IP allowlist (4 IPs oficiales como
  default en código, override por env), rate-limit 200 req/min por IP,
  idempotencia in-memory TTL 300s. Sin IH obligatoria.
- ✅ Cerrado WS4: docs sincronizadas — `.context/00-product.md` rev. 6 con
  rutas hidden, `.context/01-state.md` rev. 66, `docs/HANDOFF.md` con 62
  migraciones reales.
- ✅ 74 tests nuevos · 389 tests OK · 13/13 validate.sh OK · sin regresiones.

### Tarea recurrente (anotación)

- **Revisión trimestral de IPs MeLi**: validar
  `https://developers.mercadolibre.com.co/es_ar/notificaciones` sección
  "Historial de notificaciones" cada 3 meses. Si MeLi expande las IPs,
  actualizar `_MELI_DEFAULT_NOTIFICATION_IPS` en
  `services/api/routers/meli_webhook.py` en un PR menor.
- **Próxima revisión**: 2026-07-28.

---

## Cierre sesión anterior (2026-04-26, rev. 65) — Módulo Configuración CERTIFICADO

- ✅ **General**: Filosofía del negocio (misión/visión/valores/tono), Presencia y ubicaciones (DANE + sedes con phone/email), Horario estructurado (asesor + fuera de horario + cut-off), Despacho con selector de sede, Resumen navegable, colores emerald/amber globalmente más claros.
- ✅ **Usuarios y Acceso**: Estados activo/inactivo/pendiente/eliminado, ban_duration nativo Supabase, shouldSoftDelete, ChangeRoleButton con confirmación, InactivateMemberButton con motivo, URL cleanup, redirect para non-owners.
- ✅ **Integraciones**: Vault para credentials, DisconnectIntegrationButton, tests de WhatsApp/Envia/Telegram, badge sandbox/producción, MeLi expired state, pgsec_upsert_secret (fix reconexión), manager en sidebar.
- ✅ **Auth flows**: set-password (show/hide + loading), forgot-password (browser client PKCE), login (show/hide + forgot link), /dashboard/account (cambiar contraseña), dropdown usuario en sidebar.
- ✅ **Seguridad**: ASSIGNABLE_ROLES, MIME_TO_EXT logo, redirects por navegación directa, signOut global en todas las acciones destructivas.
- 13/13 validate.sh OK · 305 tests · TypeScript OK

## Cierre sesión actual (2026-04-25, rev. 57)

- ✅ Cerrado: CxD + FSM hardening completo (ver `.context/01-state.md` rev. 57 para detalle).
- ✅ Cerrado: E2E simulado Inbox→Wompi completo (164 unit tests + UAT script 10/10 checks).
- ✅ Cerrado: humanización de nombre (primer nombre en conversación, completo en resumen).
- ✅ Cerrado: carrier selection sin falsos positivos.
- ✅ Cerrado: totales verificados desde DB antes del link de pago.
- ✅ Cerrado: catálogo condicional (optimización ~30-45% tokens en estados de recolección de datos).
- ✅ Cerrado: cierre correctivo completo rev. 60 (ver 01-state.md).
- ✅ Cerrado: R-01 a R-04, R-05, R-07, R-09, R-10, R-12 (ver rev. 58 y 59).
- ✅ Cerrado rev. 61: migración distributed_rate_limiter aplicada, R-11, R-15, R-18, ANTI_HIBERNATION.
- ✅ Cerrado rev. 62: F1 (Wompi retry), F2 (Tracking bot), F3A (Timeout 24h), F3B (Cancelar), F4 (R-13 product snapshot).
- ✅ Cerrado rev. 63: F5 (Ticket claims automático), F6 (Telegram bidireccional /resolver).
- ⏭️ Pendiente inmediato:
  - INTERVENCION HUMANA: configurar `ANTI_HIBERNATION_PING_URL` en Render Dashboard (URLs /health de api + connector + orchestrator, separadas por coma).
  - Validar con tráfico real de WhatsApp en sandbox con número whitelisted (+573125835649).
- ⏭️ Backlog (plan de trabajo productivo):
  - ✅ F5: Ticket automático en claims — implementado (rev. 63).
  - ✅ F6: Telegram `/resolver` bidireccional — implementado (rev. 63). IH pendiente: setWebhook + TELEGRAM_WEBHOOK_SECRET en Render.
  - F7: Cart abandonment cron — BLOQUEADO por plantilla Meta aprobada (IH: Meta Business Manager).
  - F8: Audio/imagen via Gemini Vision (multimodal nativo — después de estabilidad F1-F5).
  - R-08: Email alertas takeover (SMTP Resend.com — IH cuenta SMTP).
  - R-14: Consentimiento LGPD en primer contacto — decisión de producto.
  - R-16: Refresh automático tokens MeLi — flujo OAuth complejo.
  - R-17: DANE dinámico desde Envia API.

## Pendientes reales

0. **Inbox - certificacion funcional por intents**

   ### Fase A ✅ CERTIFICADA
   - Catálogo con variantes, precio/stock real, fallback técnico UAT aprobado.

   ### Fase B ✅ COMPLETADA (2026-04-22, rev. 53)
   - `order_status_tool` determinístico.
   - `shipping_quote_tool` con cotización real Envia (cheapest+fastest, sin LLM para precios).
   - Panel contextual UI: contacto, pedidos, catálogo+stock, mini-form crear pedido.
   - Realtime Supabase (`REPLICA IDENTITY FULL`).
   - Normalización de teléfono (+57 con/sin espacio) para asociar contactos.
   - Formato conversacional WhatsApp: párrafos `\n\n`, bullets `•`, negritas `*`.
   - Escalación automática: stall ≥2 rondas, reclamos, garantías, frustración.
   - Prefijos de ambiente `[TEST]` eliminados en todas las capas de respuesta al cliente.
   - TZ Colombia (`America/Bogota`) en frontend y en ETA de envío.
   - Deduplicación de nombre carrier/servicio ("Deprisa Deprisa" → "Deprisa Estandar").

   ### Fase C ✅ IMPLEMENTADA Y CERTIFICADA E2E (2026-04-25, rev. 57)
   - Gate no-texto con advertencia antes de escalamiento.
   - Saludo inicial personalizado por nombre.
   - Carrier selection sin falsos positivos.
   - READY_FOR_SUMMARY con contexto verificado (totales desde DB).
   - Payment link bounds-validated.
   - E2E simulado 10/10 checks OK.

   ### Fase C — Pendiente formal (NO abrir hasta gate explícito)

   **Objetivo**: Cierre transaccional completo desde WhatsApp — crear pedido + cobrar.

   **Flujo conversacional objetivo:**
   ```
   Cliente confirma producto + cantidad + transportista
   → Bot: resume pedido con total (productos + envío)
   → Bot solicita: nombre + dirección de entrega
   → Sistema: crea Order en DB (status=pending_payment, stock reservado)
   → Sistema: genera link de pago Wompi (sandbox → producción)
   → Bot: envía link de pago al cliente vía WhatsApp
   → Webhook Wompi: notifica pago exitoso → Order status=confirmed
   → Sistema: descuenta stock definitivamente
   → Bot: confirma pago y da número de pedido al cliente
   → Sistema: solicita guía de envío a Envia (pickup scheduling)
   ```

   **Componentes a construir:**
   - `create_order_tool`: herramienta determinística en orquestador (no LLM).
     - Input: tenant_id, contact_id, items[], shipping_option, address.
     - Output: order_id, total, reservation_id.
     - Stock: reserva (no descuenta definitivo hasta pago confirmado).
   - `payment_link_tool`: genera link de cobro en Wompi sandbox.
     - Requiere: `WOMPI_PUBLIC_KEY`, `WOMPI_PRIVATE_KEY` por tenant.
     - Contrato: `POST https://sandbox.wompi.co/v1/payment_links` (validar en docs).
   - Webhook `POST /api/v1/webhooks/wompi`: recibe evento `transaction.updated`.
     - Valida signature Wompi (header `x-event-checksum`).
     - Confirma order + descuenta stock + notifica WhatsApp al cliente.
   - `release_order_tool`: libera reserva de stock si pago no llega en N minutos (TTL).

   **Gate de entrada Fase C:**
   - [ ] Fase B certificada con UAT ≥ 95% en flujo conversacional completo.
   - [ ] Validar política Wompi sandbox para Colombia (moneda COP, montos mínimos, fees).
   - [ ] Tenant tiene cuenta Wompi activa (o acceso sandbox).
   - [ ] Definir TTL de reserva de stock (propuesta: 30 minutos).
   - [ ] Revisión legal de términos de compra enviados via WhatsApp.

   **Documentación a crear antes de implementar:**
   - `docs/integrations/wompi.md` — endpoints, eventos, firma, sandbox vs prod.
   - `docs/operations/order-flow-conversational.md` — diagrama de estados completo.

   **Restricción**: No abrir Fase C sin gate formal aprobado.

   **Gate de entrada Fase C — Estado actual:**
   - [ ] Fase B certificada con UAT ≥ 95% en flujo conversacional completo (pendiente ejecución formal).
   - [ ] Validar política Wompi sandbox para Colombia (moneda COP, montos mínimos, fees) — INTERVENCION HUMANA.
   - [ ] Tenant tiene cuenta Wompi activa o acceso sandbox — INTERVENCION HUMANA.
   - [ ] Definir TTL de reserva de stock (propuesta: 30 minutos).
   - [ ] Revisión legal de términos de compra enviados via WhatsApp.
   - [ ] `docs/integrations/wompi.md` y `docs/operations/order-flow-conversational.md` creados antes de implementar.

1. **Envia Fase 2**
   - Completar validaciones payload carrier-específicas para label/pickup/cancel por país.
   - Webhooks de estado Envia (fase async) para reconciliación automática de tracking.
   - Reemplazar catálogo DANE estático del frontend por source dinámico desde Envia Queries (`/state`, `/city`) para no depender de snapshot local.
   - Agregar observabilidad específica al mapeo CO `DANE5 -> DANE8` y errores de cobertura por carrier/tenant.
   - Definir estrategia de resiliencia por carrier ante timeouts upstream (reintentos por carrier + budget de timeout por ambiente).

2. **Mercado Libre — pendientes menores**
   - Exponer tracking de `order_tracking` en detalle de pedido (UI Pedidos)
   - Paginación completa en `GET /marketplace/listings` (actualmente máx 100)

3. **Operación/Infra**
  - SMTP propio en Supabase (cuando exista dominio propio)
  - Monitoreo operativo (alertas centralizadas por fallos de integración)
  - Completar canal Email real para alertas de takeover (hoy está preparado como placeholder en worker)
  - Agregar observabilidad operativa de cola outbound WhatsApp (lag, retries, failed por tenant)
  - Ejecutar scorecard del gate formal Free->Pago y cerrar `OQ-INFRA-01` con evidencia (`docs/deployment/production-readiness-gate.md`)
  - Complementar evidencia operativa desde entorno con salida a internet (smoke directo a endpoints Render + métricas de latencia/disponibilidad por 14 días)

4. **Cierre producción — hallazgos transversales de sesión (2026-04-20)**
   - Extender capacidades transaccionales del Orchestrator con herramientas backend seguras (cotización/envío, estado de pedido, generación de links de pago) sin delegar verdad al LLM.
   - Unificar patrón UX de estados de integración (desconectado vs error upstream vs reconexión requerida) en todos los módulos dependientes.
   - Completar endurecimiento operacional del hardening API:
     - limiter distribuido (Redis/Upstash) para escenarios con múltiples réplicas
     - observabilidad de `429/409` por tenant y endpoint
   - Cerrar gobierno legal en Contactos:
     - política de retención/anonimización tras revocatoria
     - exportabilidad de evidencia para auditoría SIC
     - versión canónica de aviso de privacidad por tenant

5. **Modelo por planes (Basic / Pro / Enterprise)**
   - Alinear decisión comercial final de límites y exclusividades por plan (IH necesaria).
   - Extender enforcement por plan al resto de operaciones write (ej. compras/finanzas/claims) según catálogo final.
   - Definir política de grace period y overage (bloqueo duro vs degradación controlada).
   - Conectar prompts/contexto de upgrade en UX de módulos bloqueados.
   - Ver estado y plan en `docs/tech/tiering-validation-plan.md`.

6. **Arquitectura de paquetes compartidos (cierre gradual)**
   - Definir momento para consumo real de `@commerce/shared-types` y `@commerce/config` desde apps.
   - Validar estrategia de build/deploy que permita `workspace:*` sin romper Render.
   - Mantener `@commerce/ui` y `@commerce/test-utils` en estado deferred hasta trigger real.

7. **Higiene final de entorno**
   - Retirar fallback legacy `NEXT_PUBLIC_API_URL` del código server-side cuando se cierre refactor de rutas restantes.
   - Mantener una sola vía canónica (`API_URL`) para evitar ambigüedad de configuración.

## Migraciones pendientes de aplicar en Supabase

- Ninguna del bloque 2026-04-20 en entorno linked (`xmelwnhhphksbpdjmbbp`), incluyendo:
  - `20260420000005_plan_tiering_foundation.sql` ✅ aplicada
  - `20260420000006_api_security_observability.sql` ✅ aplicada
- Ninguna del bloque 2026-04-22 en entorno linked, incluyendo:
  - `20260422150000_conversations_last_interaction_sync.sql` ✅ aplicada
- Nota: `20260420000001_order_tracking.sql` ya estaba aplicada previamente en DB;
  su ejecución directa devolvió `relation "order_tracking" already exists`.

---

> Historial de trabajo completado (sesiones 2026-04-18 al 2026-04-23) archivado en `.context/01-state-archive.md`.
