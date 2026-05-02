# Próximos Pasos — Estado 2026-05-01 (rev. 100)

## ADRs activos

- [docs/adr/0001-llm-tier-strategy.md](../docs/adr/0001-llm-tier-strategy.md) — Decisión rev. 81: AI Studio paid + cascada `flash → flash-lite → degraded` + model router. **NO** multi-API-key, **NO** Vertex AI por ahora. Contiene **triggers concretos** (§7) para revisitar la decisión cuando: tasa de cascada >10%, degraded >1%, tráfico >500 RPM/tenant, o 5+ tenants productivos. Validar estos umbrales antes de cualquier rev de scaling LLM.
- [docs/adr/0002-meta-business-policy-compliance.md](../docs/adr/0002-meta-business-policy-compliance.md) — rev. 84/85: detectores pre-LLM healthcare + drugs + sensitive payment. Conservador con falsos positivos.
- [docs/adr/0003-habeas-data-compliance-strategy.md](../docs/adr/0003-habeas-data-compliance-strategy.md) — rev. 93–99: cumplimiento Habeas Data Ley 1581/2012 end-to-end. Decisiones D1-D7, alternativas A1-A4, follow-ups F1-F7.

---

## Backlog rev. 102 — Follow-ups Habeas Data (post-iteración UX)

| ID | Tarea | Esfuerzo | Trigger para retomar |
|---|---|---|---|
| **F8** | Flujo de representante legal para venta a menores. Tablas extra: `representative_*`. Sprint dedicado | ~3-5 días | Llega tenant que vende a menores (e.g., uniformes escolares) |
| **F9** | i18n del bot WhatsApp para países no-CO. Adapt prompts + detectores por idioma/país. Hoy el contact se registra OK pero el flujo del bot puede ser limitado para extranjeros | ~1-2 semanas | Llegan tenants con base internacional; contacts con phone non-CO crece >5% |
| **F10** | Upload de evidencia física (PDF/imagen) para canal `in_person`. Hoy se referencia como texto en Evidencia | ~3 días | Tenant lo pide explícitamente (e.g., requisito de auditoría externa) |
| **F11** | Reporte SIC pre-cocinado más rico — incluir `consent_evidence.renewals_after_revocation[]` + cadena completa de eventos | ~1 día | Llegue queja SIC formal o auditoría programada |

## Backlog rev. 100 — ADR-0003 follow-ups (Habeas Data)

| ID | Tarea | Prioridad | Estado |
|---|---|---|---|
| F1 | Generación de PDF para SAR export (WeasyPrint + Meta document upload) | Media | Backlog |
| F2 | Tokenización completa de `document_number` con Vault (rev. 96 dejó hash + last4 aditivo) | Media | Backlog |
| F3 | Migración de `audit_log` legacy a `consent_audit_log` (deduplicar) | Baja | Backlog |
| F4 | UI Tenant Console: configuración retention per-tenant | Media | Backlog |
| F5 | Reporte SIC pre-cocinado (CSV + JSON formal) | Alta si hay queja SIC | Backlog |
| F6 | Detector self-service de **rectificación** vía WhatsApp | Baja | Backlog |
| F7 | UI click-wrap legal acceptance (DPA + privacy + subprocessors). La migración `tenant_legal_acceptance` ya existe; falta el frontend. | Media | Backlog |

## INTERVENCION HUMANA — H7/H8 desde rev. 100

- **H7 (P0)** — Rotar credenciales del proyecto Supabase `***SUPABASE_PROJECT_REF_REDACTED***`: service_role key, anon key, DB password, Meta App Secret, Wompi sandbox keys. Razón: el commit histórico `be739a4` (2026-04-06) tenía un `.env` con plaintext de estos secretos; aunque `488c6c6` ya removió el archivo del tracking, la historia git permanece pushed a GitHub.
- **H8 (opcional)** — `git filter-repo --path .env --invert-paths` para remover el archivo de TODA la historia. Destructivo: reescribe hashes; requiere coordinación con clones locales. Alternativa: solo rotar (H7) y aceptar que los secretos viejos quedan en historia (inutilizables tras rotación).

## Rev. 75 — V2 cancelado (decisión arquitectónica)

**Contexto**: el experimento V2 modular (`core/` + `specialists/` + `tools_v2/` + `llm/` + adapter) nació en commit `b153054` el 2026-04-29 00:42 y vivió 22 horas. En ese tiempo recibió 8 commits de fixes calientes (`fix(orchestrator-v2): runtime fixes contra Gemini real`, `retry+fallback LLM`, `cliente puede continuar comprando tras resumen`, etc.), señalando que estaba en estabilización temprana.

**Datos comparativos:**

| Sistema | Nacimiento | Edad | Commits |
|---|---|---|---|
| V1 `orchestrator.py` | 2026-04-07 | 22 días | 37 (incluye fixes rev. 70-73) |
| V2 modular | 2026-04-29 00:42 | ~22 horas | 8 (1 inicial + 7 fixes calientes) |

**Por qué se canceló:**
1. V2 dependía del monolito V1 (vía adapter + delegaciones inversas: `_maybe_load_cart_recovery`, `_log_bot_sources`, `_record_consent`). No era refactor — era capa adicional.
2. Tener dos sistemas paralelos = duplicación + dos veces el costo de mantenimiento + confusión arquitectural.
3. La instinct del usuario fue correcta: "vamos a tener 150 versiones?".
4. V2 no tenía 24h de soak time. Recomendar "consolidar en V2" era irresponsable.

**Lo que se eliminó (rev. 75):**
- `services/ai-orchestrator/orchestrator_v2_adapter.py`
- `services/ai-orchestrator/core/`
- `services/ai-orchestrator/specialists/`
- `services/ai-orchestrator/tools_v2/`
- `services/ai-orchestrator/llm/`
- `services/ai-orchestrator/persistence/` (carts_repo era V2-only)
- 9 archivos de tests V2 (`test_v2_parity.py`, `test_orchestrator_v2_adapter.py`, `test_carts_repo*.py`, `test_core_*.py`, `test_llm_*.py`, `test_tools_v2_cart.py`)
- `.context/10-v1-v2-parity-audit.md` (auditoría obsoleta)
- `USE_NEW_ORCHESTRATOR=true` → `false` en `.env`

**Lo que queda:**
- `services/ai-orchestrator/orchestrator.py` (4.247 líneas, V1 maduro con todos los fixes rev. 70-73 vigentes).
- `worker.py` llama directo a `orchestrator.build_and_run_orchestration` (sin adapter).
- 599 tests verde · validate.sh 13/13.

**Si en el futuro se prioriza modularidad:**
- Refactor orgánico de `orchestrator.py` a módulos por dominio (`fsm/`, `prompt/`, `outbound/`, etc.) sobre el código que YA funciona en producción.
- Sin segundo path paralelo.
- Sin feature flag.
- Sin adapter.
- Suite rev. 73 (599 tests) sirve de regression.

---

## Rev. 74 — Completar V2 + cutover (CANCELADO en rev. 75 — ver arriba)

> **Estado actual (cierre rev. 74):** Fases A + B + C ejecutadas. Fase D (cutover gradual) y Fase E (decomisar V1) son operacionales — pendientes de activación humana.
>
> **Auditoría completa:** ver `.context/10-v1-v2-parity-audit.md` (matriz V1↔V2). 10 gaps críticos cerrados en V2.
>
> **Lectura previa obligatoria antes de cutover:** `.context/09-bot-flowchart.md` + `.context/10-v1-v2-parity-audit.md`.

### Fase A — Cerrar gaps críticos en V2 ✅ EJECUTADA

Los 10 gaps críticos están cerrados. Los helpers viven en `core/coordinator.py` (módulo + clase), `core/fsm.py` (FsmFacts + determine_state), `core/context.py` (ConversationContext) y `specialists/base.py` (`_augment_system_instruction`):

| # | Gap rev. 70-73 | Implementación V2 |
|---|---|---|
| A.1 | `_LIE_PHRASES` anti-alucinación | `core/coordinator._LIE_PHRASES` + `_contains_lie_phrase()` aplicado en `_apply_result` antes de `send_outbound_text` |
| A.2 | Cart-change detection | `core/coordinator._cart_changed_since_last_quote_in_history()` + `FsmFacts.cart_changed_since_last_quote` + branch en `determine_state` |
| A.3 | Skip por data-collection-question | `Coordinator._last_outbound_matched()` con markers de email/nombre/doc/dirección + `ConversationContext.last_outbound_was_data_collection_question` |
| A.4 | Cart recovery (rev. 70) | `Coordinator._maybe_load_cart_recovery()` delega al loader del monolito V1 (`orchestrator._load_cart_recovery_block`) hasta decomisar — `ctx.cart_recovery_block` se inyecta en specialist via `_augment_system_instruction` |
| A.5 | `bot_source_log` insert | `Coordinator._log_bot_sources()` delega al helper del monolito V1 (`orchestrator._log_bot_sources`) con cooldown lazy ya construido en V1 |
| A.6 | Reset 24h | `core/coordinator._is_conversation_window_expired()` + `FsmFacts.is_window_expired` + branch en `determine_state` |
| A.7 | After-hours CONTEXTO TEMPORAL | `BaseSpecialist._augment_system_instruction()` inyecta bloque cuando `ctx.is_outside_business_hours=True`, derivado de `_is_outside_business_hours(support_schedule)` |
| A.8 | Revocación "eliminar mis datos" | `Coordinator._detect_revocation_intent()` GATE 0 antes del specialist; delega al `orchestrator._record_consent` para anonimización Ley 1581 |
| A.9 | MEDIA_WARN | `Coordinator` GATE 1 para `content_type ∈ {image, video, sticker}`. Si ya advertido → escalation; si no → mensaje + processed |
| A.10 | `_humanize_name_in_text` | `core/coordinator._humanize_name_in_text()` aplicado en `_apply_result` antes del format WhatsApp |

### Fase B — Verificación gaps moderados ✅ EJECUTADA

Lectura confirmó:
- Specialists V2 son cortos por diseño; los bloques transversales (anti-alucinación, after-hours, cart-recovery) ahora se inyectan vía `BaseSpecialist._augment_system_instruction()` en cada turno.
- `tools_v2/order_tools.handle_render_summary` reusa la lógica determinística de V1 — verificación visual confirmó CTA correcto.
- Customer context (pedidos activos, reclamos) NO se carga al `ctx` V2 todavía. Esto es deuda menor: el LLM tiene los tools `search_catalog` / `answer_kb` / `order_status` para cubrir on-demand.
- Tono y sedes: V2 reusa `tenant_meta` de V1 loader. Los specialists no inyectan filosofía — deuda menor para post-cutover.

### Fase C — Tests V2 ✅ EJECUTADA

`tests/test_v2_parity.py` — 28 tests cubriendo:
- FSM con flags rev. 73 (cart-change, ventana 24h).
- Detectores: LIE_PHRASES, humanize_name, revocation, MEDIA_WARN.
- `_facts_from_cart_and_contact` propaga nuevos flags.
- `BaseSpecialist._augment_system_instruction` inyecta bloques cuando aplica.
- `tools_for_state` cubre los 10 estados.

Total suite: **709 tests OK** (681 → 709, +28 nuevos rev. 74).

### Fase D — Cutover gradual (PENDIENTE — operacional, INTERVENCION HUMANA)

**Pre-requisitos cumplidos:**
- ✅ Gaps críticos cerrados en V2 (Fase A).
- ✅ Tests V2 verdes (Fase C, 28/28).
- ✅ V1 sigue como red de seguridad (fallback automático en adapter).

**Contexto operacional (rev. 74):**
- **Render está en FREEZE** — no se desplega allá hasta retomar producción comercial.
- **Toda prueba corre en VM local** levantada con `make -C /home/ansible/commerce-ops-local up`.
- **`USE_NEW_ORCHESTRATOR=true` ya está en `.env`** del repo. Toma efecto en el siguiente mensaje del bot — el adapter lee la var en cada llamada (hot-reload, sin restart).
- **Pero** los cambios de código rev. 74 (`core/coordinator.py`, `core/fsm.py`, etc.) requieren reiniciar el orchestrator local para cargarse en memoria. El flag solo enruta al código que ya está cargado.

**Checklist de activación (operador, VM local):**

1. **Confirmar flag en `.env`:**
   ```bash
   grep USE_NEW_ORCHESTRATOR /home/ansible/workspaces/commerce-ops-platform/.env
   # Debe imprimir: USE_NEW_ORCHESTRATOR=true
   ```

2. **Reiniciar orchestrator local** para cargar código rev. 74 en memoria:
   ```bash
   make -C /home/ansible/commerce-ops-local stop-orchestrator
   make -C /home/ansible/commerce-ops-local start-orchestrator
   # o equivalente:
   # make -C /home/ansible/commerce-ops-local restart  (reinicia todo)
   ```

3. **Verificar que arrancó sin errores:**
   ```bash
   tail -n 50 /home/ansible/commerce-ops-local/logs/orchestrator.log
   # Buscar líneas: "OrchestratorWorker started" + "[coord]" o "[v2_adapter]"
   ```

4. **Validación inmediata (primer mensaje):**
   - Enviar 1 mensaje de prueba al WhatsApp del tenant dev (`+573125835649`).
   - Tail los logs: `tail -f /home/ansible/commerce-ops-local/logs/orchestrator.log`.
   - Buscar línea `[coord] tenant=... conv=... state=... cart_items=N outside_hours=... window_expired=... cart_changed=...` (V2 corriendo).
   - Si aparece `[v2_adapter] coordinator falló — fallback a monolito`: V2 lanzó excepción → fallback OK al cliente, pero hay bug que investigar.

5. **Validación corrida E2E** (un solo cliente, una sesión completa):
   - Saludo → "¿Qué tienes?" → bot lista catálogo (CATALOG_MODE).
   - "Quiero 1 jabón de coco" → bot agrega (cart-tool).
   - "Cotizar a Bogotá" → bot cotiza (shipping-tool).
   - Elegir Económica → consent → email → name → document → dirección → resumen → confirmar.
   - Verificar link Wompi generado.

6. **Validación corridas anti-alucinación (rev. 73 paridad):**
   - Re-ejecutar caso del log `615a9902`: cliente conocido, agregar producto post-cotización.
   - **Esperado**: bot re-cotiza con peso real. Si dice "Coordinadora $17.730 sigue siendo" sin haber re-cotizado → bug.
   - Decir "ok, gracias" tras resumen → **esperado**: bot pide CTA explícito ("¿Confirmas para generar tu link de pago?"), NO afirma "tu pedido será entregado".

7. **Si todo OK 24h continuas en uso real**: V2 estable en local. Cuando Render se retome, basta con setear `USE_NEW_ORCHESTRATOR=true` en el dashboard de Render (sin redeploy — hot-reload).

8. **Si aparece bug**:
   ```bash
   # Editar .env: USE_NEW_ORCHESTRATOR=false
   # Próximo mensaje cae a V1 monolito (sin restart necesario).
   # Investigar logs, fix V2, restart orchestrator, repetir desde paso 4.
   ```

**Comandos útiles (VM local):**

```bash
# Estado de servicios
make -C /home/ansible/commerce-ops-local status

# Logs en vivo
tail -f /home/ansible/commerce-ops-local/logs/orchestrator.log

# Logs de api / connector
tail -f /home/ansible/commerce-ops-local/logs/api.log
tail -f /home/ansible/commerce-ops-local/logs/connector.log

# URLs de webhooks (ngrok)
make -C /home/ansible/commerce-ops-local print-urls

# Reiniciar todo
make -C /home/ansible/commerce-ops-local restart

# Bajar todo
make -C /home/ansible/commerce-ops-local down
```

### Fase E — Decomisar V1 (PENDIENTE — solo tras Fase D estable)

**NO ejecutar antes de 7 días sin fallback.** El monolito V1 es la red de seguridad.

Pasos cuando se priorice:

1. **Mover loaders compartidos** que V2 reusa (vía adapter):
   - `get_tenant_catalog` → `services/loaders/catalog_loader.py`
   - `get_tenant_kb_rag` → ya está en `tools/kb_tool.py` (sin movimiento)
   - `_get_conversation_history` → `services/loaders/history_loader.py`
   - `_fetch_contact_for_phone` → `services/loaders/contact_loader.py`
   - `_load_cart_recovery_block` → `customer_context/cart_recovery.py` o tool en `tools_v2/`
   - `_log_bot_sources` + `_bot_log_available` → `services/audit_logger.py`
   - `_record_consent` → `services/consent.py`
   - `_send_outbound_text` → ya existe en `whatsapp_sender.py` o equivalente

2. **Actualizar `orchestrator_v2_adapter.py` _run_v2()`** para importar de los nuevos módulos en vez de `import orchestrator as monolith`.

3. **Eliminar `orchestrator.py`** (4.247 líneas).

4. **Simplificar `worker.py`**: importar Coordinator directo, eliminar el adapter (ya no hay path V1).

5. **Eliminar `orchestrator_v2_adapter.py`**.

6. **Validar**: suite tests verde, validate.sh 13/13.

### Estimación total ejecutada

- Fase A (gaps críticos): ✅ ~3h reales (estimado 6h).
- Fase B (verificación): ✅ ~1h.
- Fase C (tests): ✅ ~1h (28 tests deterministas, sin mocks de Gemini).
- Fase D (cutover): pendiente, 2-7 días monitoring.
- Fase E (decomisar): pendiente, ~3h tras Fase D.

---

# Próximos Pasos — Estado 2026-04-30

## Cierre sesión actual (2026-04-30, rev. 70) — F7-LITE CART RECOVERY

- ✅ **F7-lite cart recovery reactivo**: `_load_cart_recovery_block` inyecta carrito previo cancelado (TTL `CART_RECOVERY_LOOKBACK_DAYS` default 7d) al system prompt con re-validación stock+precio actual por variante. Marca "disponible" / "precio cambió" / "SIN STOCK" / "variante removida". Total recalculado al precio actual.
- ✅ Tokens léxicos extendidos (`carrito`, `retomar`, `antes`, `ayer`, `pagar`, etc.) activan lazy mode con frases naturales.
- ✅ Env vars: `CART_RECOVERY_ENABLED`, `CART_RECOVERY_LOOKBACK_DAYS` (`.env.example` + `render.yaml` + `.env`).
- ✅ Script utilitario `scripts/wipe_conversation.py` para vaciar conversación de teléfono específico (multi-tenant aware, modo full-delete o keep-conversation).
- ✅ 18 tests nuevos · 496 total · validate.sh 13/13 OK.

### Variantes F7 restantes (postpuestas)

- **F7-email** (recovery dual-channel): bloqueado por SMTP propio. Trivial tras tener Resend con dominio.
- **F7-full** (templates Meta proactivos): solo cuando un tenant Pro/Enterprise tenga plantilla aprobada Y volumen que justifique el costo Meta pass-through.

---

## Cierre sesión anterior (2026-04-30, rev. 69) — RIESGOS ABIERTOS CERRADOS

- ✅ **A2 DV NIT**: validación módulo-11 oficial DIAN para NITs con DV.
- ✅ **A4 Customer context lazy**: feature flag + 3 modos (always/lazy/disabled). Default lazy reduce 70-80% de tokens del contexto.
- ✅ **A3 KB migration banner**: banner one-time dismissible con tabla `user_dismissed_alerts` + RLS.
- ✅ **B3 MeLi rejected_origin alert**: contador in-memory + log warning estructurado al exceder umbral.
- ✅ **B6 Tenants tono backfill**: NULL → `'amigable'` + SET NOT NULL guard.
- ✅ **C1 Rate-limit user-aware**: `RL_SEND_MESSAGE` con `include_user_id=True`. Key `bucket:tenant:user:ip`. Previene abuse cross-IP.
- ✅ **C2 MeLi dedup distribuido**: tabla + RPC `meli_webhook_seen` atómica cross-réplica + cleanup en worker. Fallback in-memory.
- ✅ **A1 Frontend Contacts UI**: validators TS + AddressSelector con building_type + form con document_type/number + tabla muestra Doc y Barrio.
- ✅ 23 tests nuevos · 478 total · validate.sh 13/13 OK.

### Riesgos restantes (postpuestos a producción)

- **B4 Anti-hibernation Render**: aplica al pasar a Render Starter+ (HOY en Free + VM local).
- **B5 Wompi producción**: aplica cuando Kaiu (o cualquier tenant) pase a operativo.
- **C3 DR Supabase**: aplica en producción.
- **F7 cart abandonment**: bloqueado por templates Meta (IH del tenant). Detalle ejecutable abajo en `Backlog detallado — F7`.
- **F8 multimodal imagen**: aplazado tras audio (rev. 67).

---

## Backlog detallado — F7 Cart abandonment (3 variantes)

3 variantes documentadas con costos y prerequisitos diferenciados. Listo para ejecutar cuando se priorice.

### F7-lite — Cart recovery reactivo (variante accesible, prioridad alta)

**Hipótesis comercial**: pequeños e-commerce no pueden costear templates Meta. El bot debe recordar el carrito previo cuando el cliente vuelve a escribir, sin proactividad costosa.

**Costo tenant**: $0. Todo dentro de la ventana 24h (gratis Meta) o reactivado por el cliente (la ventana 24h se reabre al primer mensaje del cliente).

**Por qué hoy NO funciona**: `_release_expired_pending_payment_orders` ([worker.py:477](services/ai-orchestrator/worker.py#L477)) cambia status a `cancelled` pero NO borra la orden. Los `order_items` quedan asociados. Sin embargo, `_load_customer_context_block` ([orchestrator.py:232](services/ai-orchestrator/orchestrator.py#L232)) excluye `cancelled` del contexto cargado al system prompt, por eso el bot HOY no recupera carritos cuando el cliente reescribe.

**Cambios concretos:**

| Item | Detalle | Tiempo |
|---|---|---|
| Extender `_load_customer_context_block` | Query a `orders` con `status='cancelled'` + JOIN `order_items` con TTL configurable. Variable env `CART_RECOVERY_LOOKBACK_DAYS` (default 7). | 45 min |
| Bloque system prompt | Sección "CARRITO PREVIO (cancelado hace N días)" con items, totales y INSTRUCCIÓN: ofrecer retomar SOLO si el cliente expresa intención de compra (no proactivo, no intrusivo). | 20 min |
| Tokens léxicos lazy mode | Agregar `"carrito"`, `"retomar"`, `"ese pedido"`, `"lo de antes"`, `"el otro dia"`, `"el de ayer"` a `_CUSTOMER_CONTEXT_LAZY_TOKENS`. | 10 min |
| Tool `recreate_order_from_cancelled(order_id)` | Determinístico, en orchestrator. Copia items, **re-valida stock actual** por variante, **re-calcula precio actual**. Output: `{ new_order_id, stock_diffs[], price_diffs[] }`. | 60 min |
| UX bot — branching | Si stock=0 en alguna variante: ofrecer reemplazo desde catálogo activo. Si precio cambió: advertir antes de generar nuevo link Wompi. | 30 min |
| Tests | (a) carrito cancelled <7d aparece en contexto; (b) cancelled >7d NO aparece; (c) cliente conocido sin token léxico → no se carga; (d) stock=0 dispara branch reemplazo; (e) diff precio se reporta al cliente. | 45 min |

**Total: ~3.5 horas.**

**Reusos:**
- `_load_customer_context_block` y `_customer_context_should_load` (rev. 69) — extender, no reescribir.
- Lazy mode + feature flag `CUSTOMER_CONTEXT_ENABLED/MODE` (rev. 69) cubren el on/off global.
- Wompi `payment_link` y `_build_customer_data` (rev. 68) reusables tal cual al regenerar el link.

### F7-email — Recovery dual-channel (postpuesto hasta SMTP propio)

**Bloqueado por**: IH-SMTP (Resend con dominio propio del operador SaaS, identificado en `docs/HANDOFF.md` como bloqueante operativo conocido).

**Cuando se desbloquee** (~45 min adicionales tras F7-lite):
- Al generar link Wompi en `READY_FOR_SUMMARY`, el bot ofrece: *"¿Te lo mando también por correo?"* — si el cliente acepta, se envía vía Resend con el mismo `payment_link.id`.
- El cliente paga desde cualquier canal; el webhook Wompi llega igual y notifica vía WhatsApp si todavía está dentro de 24h, o vía email si ya cerró.
- No requiere cambios en webhook Wompi ni en orchestrator más allá de un branch en el envío.

### F7-full — Templates Meta proactivos (upgrade Pro/Enterprise)

**Hipótesis comercial**: tenants con volumen alto que quieran capturar el segmento de "fantasmas" (clientes que abandonan y nunca vuelven a escribir). Templates Meta se justifica solo a escala.

**Modelo de costos**: **Pass-through**. Tenant paga Meta directo vía su WABA (`tenant_integrations.whatsapp_credentials`). Plataforma SaaS NO factura el extra. Coherente con cómo opera Wompi y Envia hoy.

**Migración futura a Modelo 3 (gated por plan)**: trivial — agregar gate en `consume_tenant_capability` y condicionar UI/endpoint. Sin cambio en flujo de envío.

**Pre-requisitos (INTERVENCION HUMANA del tenant):**
- Tenant registra plantilla en Meta Business Manager (categoría `MARKETING`) con placeholders `{{nombre}}` y/o `{{link}}`.
- Tenant espera aprobación Meta (24-48h típico).
- Operador del SaaS configura `template_name` aprobado en UI Settings.

**Cambios concretos cuando se priorice (~2.5 h):**

| Item | Detalle | Tiempo |
|---|---|---|
| Migración | `tenants.cart_abandonment_template_name TEXT NULL` + `cart_abandonment_enabled BOOLEAN NOT NULL DEFAULT FALSE`. | 5 min |
| UI Settings | Sección "Plantillas Meta aprobadas" con input + toggle. Validación frontend: `enabled=true` exige `template_name` non-empty. | 30 min |
| Endpoint envío | Extender `POST /conversations/{id}/send` con `{ template_name, template_variables }`. Reusa `ack_pending` + retries (rev. 67 WS-B). | 30 min |
| Worker hook | En `_release_expired_pending_payment_orders`: ANTES de cancelar, si `cart_abandonment_enabled` para el tenant, enviar template vía cliente WhatsApp existente. | 45 min |
| Tests | Unit cubren: `template_name` vacío + `enabled=true` → 422; envío exitoso → message persisted con `template_name=...`; ack flow reusa el existente. | 30 min |

**Reusos:**
- Cliente WhatsApp ya soporta `messages.template` (Meta API v21.0).
- ACK transaccional + retries (rev. 67) cubren el outbound del template.
- `messages` — verificar al implementar si ya existe columna `template_name`; si no, una columna más en la migración.

### Coherencia transversal

- El cron del worker ya existe — F7-lite y F7-full se inyectan en el mismo loop, no requieren cron separado.
- `MAX_PROCESSING_ATTEMPTS=5` (rev. 66) aplica también al outbound de templates.
- La ventana 24h Meta NO aplica a templates — Meta los acepta fuera de ventana, ese es justo el caso de uso de F7-full.
- F7-lite + F7-full son **complementarias, no excluyentes**. Un tenant Pro puede usar ambas: cart recovery captura los que vuelven (gratis) + templates capturan los fantasmas (paga).

### Cuándo priorizar cada variante

- **F7-lite**: cuando un tenant pida cart recovery O cuando se detecte abandono >5% en métricas. Implementable HOY sin prerequisitos.
- **F7-email**: cuando IH-SMTP esté resuelto. Trivial tras F7-lite.
- **F7-full**: solo cuando un tenant Pro/Enterprise concreto tenga plantilla Meta aprobada Y volumen que justifique el costo. NO antes — sin tenant target con plantilla aprobada, el código queda muerto.

---

## Cierre sesión anterior (2026-04-29, rev. 68) — COHERENCIA CORE DEL BOT

- ✅ Eliminada duplicación de misión en system prompt (D1).
- ✅ Placeholders humanos en `after_hours_message` UI Settings.
- ✅ `tenants.escalation_role` configurable + UI dropdown + bot lo usa en escalaciones.
- ✅ KB: 6 categorías canónicas (faq, negocio, politicas, productos, envios, pagos) con CHECK constraint, migración bulk legacy → faq, guía colapsable por categoría en UI.
- ✅ Estado del bot ampliado: 4 → 8 checks (Identidad, Tono, Sedes, Catálogo, KB, Indexación, Agente IA, Pasarela+Courier) con tooltips.
- ✅ Contactos: `document_type` + `document_number` con CHECK Wompi-CO + index parcial; schema canónico `address` JSONB documentado; validators Python (length por tipo, normalización); endpoints API + anonimización Ley 1581 actualizadas.
- ✅ FSM aterrizado rev. 68: orden CONSENT → EMAIL → NAME → DOCUMENT → DIRECTION → READY_FOR_SUMMARY. `extracted_document_type/number` en `OrchestratorOutput`. `_clear_contact_field('document')` limpia ambos. Categoría `document` en flujo de corrección.
- ✅ Cart summary pre-shipping: instrucción en NEEDS_SHIPPING_CITY al LLM para resumir + ofrecer agregar más antes de cotizar.
- ✅ Contexto cliente conocido: `_load_customer_context_block()` carga pedidos activos + reclamos abiertos al system prompt.
- ✅ Wompi `customer_data` completo: `_build_customer_data()` arma email/full_name/phone(+57)/legal_id+type. Call sites actualizados (orders, wompi_webhook retry).
- ✅ Envia `district`: mapeado desde `address.neighborhood` en `_coerce_origin/_coerce_destination`.
- ✅ 41 tests nuevos · 452 total · validate.sh 13/13 OK.

### Riesgos abiertos / pendientes (rev. 68)

- **Frontend Contacts UI** (no bloqueante): el form `/dashboard/contacts` no muestra aún `document_type/number` ni dirección estructurada con `building_type`. El bot conversacional ya los captura por WhatsApp; la UI manual es backlog para sesión futura. Cuando se aborde, ya está el schema canónico documentado y los validators TS quedan pendientes (`apps/web/lib/validators/document.ts`, `address.ts`).
- **F7 cart abandonment** (BLOQUEADO): requiere plantilla Meta aprobada. INTERVENCION HUMANA al priorizar.
- **F8 multimodal imagen**: aplazado tras audio (rev. 67).

---

## Cierre sesión anterior (2026-04-28, rev. 67) — INBOX CERTIFICADO

- ✅ WS-A Frontend Inbox: timestamp lateral fix, badge unread, banner ventana 24h, tooltips estados, Idempotency-Key end-to-end, dedupe realtime, render emojis WhatsApp.
- ✅ WS-B Compliance Meta: ventana 24h enforced backend (422 + códigos accionables), ACK transaccional outbound (retry + ack_pending status).
- ✅ WS-C Multi-tenant runtime: tests `test_tenant_isolation_inbox.py` (5 tests) cubren todos los endpoints Inbox.
- ✅ WS-D Multimodal audio: bot entiende y responde mensajes de voz vía Gemini 2.5 Flash. `meta_media.py` + transcripción + caché. Feature flag `MULTIMODAL_AUDIO_ENABLED`.
- ✅ WS-E Limpieza: role/misión ortogonales (UI + system prompt), sender legacy eliminado, roles `agent` legacy barridos.
- ✅ WS-F Conversaciones archivadas + scroll histórico cursor-based.
- ✅ WS-G Docs: `06-contracts.md` ampliado (secciones 14, 15), `01-state.md` rev. 67.
- ✅ 4 migraciones Supabase aplicadas (66 total).
- ✅ 411 tests · validate.sh 13/13 · sin regresiones.

### Pendientes operativos (rev. 67)

- **F7 cart abandonment** (BLOQUEADO): requiere plantilla Meta aprobada en Meta Business Manager. INTERVENCION HUMANA: registrar plantilla cuando se priorice campañas de recuperación.
- **F8 multimodal imagen**: aplazado tras audio. Reusará la base `meta_media.py` + agregará rama de procesamiento de imagen al orchestrator.
- **Templates Meta**: cuando llegue F7, extender `POST /conversations/{id}/send` para aceptar `template_name` + variables.

### Tarea recurrente (anotación)

- **Revisión trimestral de IPs MeLi**: validar `https://developers.mercadolibre.com.co/es_ar/notificaciones` cada 3 meses. Próxima 2026-07-28.

---

## Cierre sesión anterior (2026-04-28, rev. 66) — CIERRE DE CERTIFICACIÓN REAL

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

- Ninguna del bloque 2026-04-20 en entorno linked (`***SUPABASE_PROJECT_REF_REDACTED***`), incluyendo:
  - `20260420000005_plan_tiering_foundation.sql` ✅ aplicada
  - `20260420000006_api_security_observability.sql` ✅ aplicada
- Ninguna del bloque 2026-04-22 en entorno linked, incluyendo:
  - `20260422150000_conversations_last_interaction_sync.sql` ✅ aplicada
- Nota: `20260420000001_order_tracking.sql` ya estaba aplicada previamente en DB;
  su ejecución directa devolvió `relation "order_tracking" already exists`.

---

> Historial de trabajo completado (sesiones 2026-04-18 al 2026-04-23) archivado en `.context/01-state-archive.md`.
