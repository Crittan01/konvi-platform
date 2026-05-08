# Bot Flowchart Canónico — Konvi Platform

**Estado:** rev. 73 (post-fixes del log UAT 2026-04-29 conv `615a9902`).
**Fuente de verdad visual:** este documento. Si el código diverge, este archivo deja de servir como contrato del refactor rev. 74.

> ## Implementación canónica (rev. 75)
>
> Este flowchart describe el **comportamiento canónico del bot**, implementado en el orquestador único `services/ai-orchestrator/orchestrator.py` (V1 monolito, 4.247 líneas, 22 días de madurez + 37 commits + fixes rev. 70-73).
>
> **Decisión rev. 75**: el experimento V2 modular (commit `b153054`, 22 horas de vida) se canceló. Razón: V2 dependía del monolito V1 vía adapter + delegaciones cruzadas, y mantener ambos sumaba deuda incremental. Cuando se priorice modularidad real, se refactoriza V1 orgánicamente sobre código probado en producción, sin segundo path paralelo.

---

## 1. Flowchart Mermaid

```mermaid
flowchart TD
    %% Leyenda
    classDef msg fill:#e1f5fe,stroke:#03a9f4,stroke-width:2px,color:#000
    classDef sys fill:#f5f5f5,stroke:#9e9e9e,stroke-width:1px,color:#000
    classDef alert fill:#fff3e0,stroke:#ff9800,stroke-width:2px,color:#000
    classDef async fill:#e8f5e9,stroke:#4caf50,stroke-width:2px,color:#000
    classDef tool fill:#ede7f6,stroke:#673ab7,stroke-width:2px,color:#000
    classDef guard fill:#ffebee,stroke:#f44336,stroke-width:2px,color:#000

    %% ═══ ENTRY + GATES DE SEGURIDAD ═══
    IN([Mensaje entrante WhatsApp Cloud API]):::msg --> META_DEDUP{meta_message_id<br/>ya procesado?}:::sys
    META_DEDUP -->|Sí| DROP_DUP[Silencio: ignorar duplicado]:::sys
    META_DEDUP -->|No| WIN24{Ventana 24h Meta<br/>activa?}:::sys

    WIN24 -->|Expirada| RESET_FSM[Resetear contexto<br/>buying_intent=False]:::sys --> SESSION_GATE
    WIN24 -->|OK| SESSION_GATE{conversation.status}:::sys

    SESSION_GATE -->|closed| DROP_CLOSED[Silencio]:::sys
    SESSION_GATE -->|human_takeover| SILENCE[Silencio: agente humano activo]:::alert
    SESSION_GATE -->|bot_active| AFTER_HOURS{Fuera de horario<br/>configurado?}:::sys

    AFTER_HOURS -->|Sí| INJECT_TIME[Inyectar CONTEXTO TEMPORAL<br/>al system prompt<br/>rev. 71]:::sys --> CMD_GLOBAL
    AFTER_HOURS -->|No| CMD_GLOBAL{Comando global?}:::sys

    %% ═══ COMANDOS GLOBALES ═══
    CMD_GLOBAL -->|asesor / humano / ayuda| ESCALATE_HUMAN[Cambiar a human_takeover<br/>+ alerta Telegram]:::alert
    CMD_GLOBAL -->|cancelar| CANCEL_FLOW[release_pending_payment_order<br/>liberar stock_reservations]:::sys --> OUT_CANCEL([Listo, cancelado.<br/>¿En qué más te ayudo?]):::msg
    CMD_GLOBAL -->|eliminar mis datos| ANON[Anonimizar contact:<br/>name/email/address NULL<br/>Ley 1581 Art.15]:::sys --> OUT_DEL([Tus datos fueron eliminados.]):::msg
    CMD_GLOBAL -->|cambia el envío a X| RESET_SHIP[shipping_quoted=False<br/>reabrir cotización]:::sys --> CONTENT_GATE
    CMD_GLOBAL -->|Mensaje normal| CONTENT_GATE{content_type?}:::sys

    %% ═══ MULTIMODAL ═══
    CONTENT_GATE -->|audio| AUDIO_TOOL[meta_media + Gemini<br/>multimodal: transcribir<br/>rev. 67]:::tool --> CONTENT_GATE
    CONTENT_GATE -->|image / video / sticker| MEDIA_WARN{Ya advertido<br/>en últimas 4h?}:::sys
    MEDIA_WARN -->|No| OUT_MEDIA([Solo manejo texto.<br/>Si es urgente escribe 'asesor']):::msg
    MEDIA_WARN -->|Sí| ESCALATE_HUMAN
    CONTENT_GATE -->|text| RESOLVE_CTX[Cargar tenant + contact + history<br/>+ catalog + KB pre-RAG<br/>+ customer_context lazy<br/>+ cart_recovery rev. 70]:::sys

    %% ═══ DETERMINACIÓN DE FSM STATE ═══
    RESOLVE_CTX --> FSM_DETERMINE{Determinar<br/>display_state}:::sys

    %% Reglas FSM (rev. 73)
    FSM_DETERMINE -->|buying_intent=False| CATALOG_MODE[CATALOG_MODE]:::sys
    FSM_DETERMINE -->|buying_intent=True<br/>+ shipping_quoted=False<br/>O cart_changed_since_quote<br/>rev. 73| NEEDS_CITY[NEEDS_SHIPPING_CITY]:::sys
    FSM_DETERMINE -->|shipping_quoted=True<br/>+ carrier_NO_seleccionado<br/>per-pedido rev. 73| AWAITING_CARRIER[AWAITING_CARRIER_SELECTION]:::sys
    FSM_DETERMINE -->|carrier OK<br/>+ datos personales faltan| TX_STATE{Cuál falta?}:::sys
    FSM_DETERMINE -->|todos los datos<br/>+ shipping_cost extraído >0<br/>rev. 73 guard| READY_SUM[READY_FOR_SUMMARY]:::sys
    FSM_DETERMINE -->|último outbound fue<br/>'¿confirmas?' + inbound afirma| AWAIT_ORDER[AWAITING_ORDER_CONFIRMATION]:::sys

    %% Guard rev. 73
    READY_SUM --> SHIP_GUARD{shipping_cost<br/>extraído >0?<br/>rev. 73}:::guard
    SHIP_GUARD -->|No| AWAITING_CARRIER
    SHIP_GUARD -->|Sí| BUILD_SUMMARY[_build_verified_order_context<br/>+ dirección de contact_record]:::sys

    %% ═══ CATALOG_MODE ═══
    CATALOG_MODE --> KB_RAG[KB pre-RAG con boost<br/>por categoría rev. 71<br/>+ marker missing-cat]:::tool --> LLM_CATALOG[LLM responde<br/>con catálogo + KB]:::sys --> ANTI_HALLU
    CATALOG_MODE -.->|consulta status pedido| ORDER_STATUS_TOOL[order_status_tool]:::tool --> OUT_TRACK([Estado del pedido + tracking]):::msg

    %% ═══ NEEDS_SHIPPING_CITY ═══
    NEEDS_CITY --> SHIP_SKIP_GUARD{último outbound fue<br/>consent_question O<br/>data_collection_question?<br/>rev. 73}:::guard
    SHIP_SKIP_GUARD -->|Sí| LLM_DATA[LLM no recota<br/>continúa recolección]:::sys
    SHIP_SKIP_GUARD -->|No| SHIP_QUOTE[shipping_quote_tool<br/>peso real multi-producto<br/>desde product_variations]:::tool
    SHIP_QUOTE -->|sin ciudad| OUT_ASK_CITY([¿A qué ciudad enviamos?]):::msg
    SHIP_QUOTE -->|con ciudad + DANE| OUT_QUOTE([Envío a Bogotá:<br/>• Económica $X Coordinadora<br/>• Rápida $Y Servientrega<br/>¿Con cuál continuamos?]):::msg

    %% ═══ AWAITING_CARRIER_SELECTION ═══
    AWAITING_CARRIER --> CARRIER_DETECT{Inbound contiene<br/>token de carrier<br/>(económica/rápida/Coord/etc)?}:::sys
    CARRIER_DETECT -->|Sí| FSM_DETERMINE
    CARRIER_DETECT -->|No| OUT_ASK_CARRIER([¿Económica o Rápida?]):::msg

    %% ═══ FSM RECOLECCIÓN DE DATOS ═══
    TX_STATE -->|consent_given=False| NEEDS_CONS[NEEDS_CONSENT]:::sys --> OUT_CONSENT([Para procesar tu pedido<br/>necesito tu autorización<br/>Ley 1581...]):::msg
    TX_STATE -->|email vacío| NEEDS_EM[NEEDS_EMAIL]:::sys --> OUT_EMAIL([¿Cuál es tu correo?]):::msg
    TX_STATE -->|name vacío| NEEDS_NM[NEEDS_NAME]:::sys --> OUT_NAME([¿Cuál es tu nombre completo?]):::msg
    TX_STATE -->|document vacío| NEEDS_DOC[NEEDS_DOCUMENT]:::sys --> OUT_DOC([Tipo y número de documento.<br/>CC, CE, NIT, PP, TI]):::msg
    TX_STATE -->|address vacía| NEEDS_DIR[NEEDS_DIRECTION]:::sys --> OUT_DIR([Dirección + tipo vivienda<br/>casa/edificio/conjunto<br/>+ apto/torre si aplica]):::msg

    %% Cada respuesta del cliente vuelve al FSM
    OUT_CONSENT -.-> FSM_DETERMINE
    OUT_EMAIL -.-> FSM_DETERMINE
    OUT_NAME -.-> FSM_DETERMINE
    OUT_DOC -.-> FSM_DETERMINE
    OUT_DIR -.-> FSM_DETERMINE

    %% ═══ READY_FOR_SUMMARY ═══
    BUILD_SUMMARY --> OUT_SUM([RESUMEN COMPLETO:<br/>• Productos + cantidad + precio<br/>• Subtotal<br/>• Envío con carrier + ETA<br/>• Dirección de entrega literal<br/>• TOTAL<br/>¿Confirmas para generar<br/>tu link de pago?]):::msg

    OUT_SUM -.->|Inbound del cliente| CONFIRM_PARSE{Respuesta del<br/>cliente}:::sys
    CONFIRM_PARSE -->|Sí / Confirmo / Pago / OK pago| AWAIT_ORDER
    CONFIRM_PARSE -->|Corregir nombre/dir/email| FSM_DETERMINE
    CONFIRM_PARSE -->|Cancelar| CANCEL_FLOW
    CONFIRM_PARSE -->|Ok / gracias / vale<br/>(ambiguo, NO es pago)| OUT_CTA([¿Confirmas para<br/>generar tu link de pago?]):::msg

    %% ═══ AWAITING_ORDER_CONFIRMATION ═══
    AWAIT_ORDER --> PAYMENT_TOOL[payment_link_tool<br/>1- crear order pending_payment<br/>2- reservar stock<br/>3- generar link Wompi]:::tool
    PAYMENT_TOOL -->|OK| OUT_LINK([Perfecto, te genero tu link:<br/>{wompi_url}<br/>Vence en 30 min]):::msg
    PAYMENT_TOOL -->|Falla| OUT_PAY_FAIL([No pude generar el link.<br/>Intentemos de nuevo?]):::msg

    %% ═══ ANTI-ALUCINACIÓN POST-PROCESS rev. 73 ═══
    LLM_CATALOG --> ANTI_HALLU{Respuesta contiene<br/>frase prohibida<br/>'tu pedido fue entregado'<br/>'ya seleccioné Coord'?<br/>+ payment_link_result=None}:::guard
    LLM_DATA --> ANTI_HALLU
    ANTI_HALLU -->|Sí| LIE_REPLACE[Reemplazar texto<br/>por CTA seguro<br/>+ log warning]:::guard
    ANTI_HALLU -->|No| FORMAT_WA[Formato WhatsApp<br/>+ humanize_name]:::sys
    LIE_REPLACE --> FORMAT_WA
    FORMAT_WA --> SEND_OUTBOUND[_send_outbound_text<br/>+ ack_pending retry<br/>+ bot_source_log rev. 71]:::sys

    %% ═══ ASYNC: WEBHOOKS ═══
    OUT_LINK -.-> WOMPI_HOOK{Webhook Wompi<br/>POST /api/v1/wompi}:::async
    WOMPI_HOOK -.->|APPROVED| ORDER_OK[order.status=confirmed<br/>decrementar stock_quantity<br/>liberar reservation]:::async --> OUT_OK([¡Pago recibido!<br/>Tu pedido está confirmado.<br/>ETA: 2 días hábiles]):::async
    WOMPI_HOOK -.->|DECLINED / VOIDED| OUT_FAIL([Hubo un problema con el pago.<br/>¿Quieres que generemos otro link?]):::async
    WOMPI_HOOK -.->|Sin pago en 30 min| WORKER_RELEASE[worker._release_expired<br/>order.status=cancelled<br/>liberar stock]:::async

    %% ═══ ASYNC: CART RECOVERY rev. 70 ═══
    WORKER_RELEASE -.-> CART_LATER{Cliente vuelve<br/>en próximos 7 días?}:::async
    CART_LATER -.->|Sí + token léxico<br/>(carrito/retomar/etc)| CART_BLOCK[_load_cart_recovery_block<br/>inyecta carrito previo<br/>con re-validación stock+precio]:::async --> OUT_RECOVER([Vi que dejaste un pedido pendiente:<br/>• items con precio actual<br/>¿Lo retomamos?]):::msg
    CART_LATER -.->|No / token no presente| END_FLOW([Conversación archivada<br/>tras 90 días sin actividad]):::sys

    %% ═══ ASYNC: ENVIA TRACKING ═══
    ORDER_OK -.-> ENVIA_TRACK{Tracking Envia<br/>actualizado?}:::async
    ENVIA_TRACK -.->|status change| OUT_TRACKING_UPDATE([Tu pedido fue actualizado.<br/>Guía disponible en seguimiento]):::async

    %% ═══ AUDIT TRAIL TRANSVERSAL ═══
    SEND_OUTBOUND -.-> AUDIT[bot_source_log INSERT<br/>fsm_state, injected_*<br/>kb_categories_used<br/>missing_categories<br/>rev. 71]:::async
    PAYMENT_TOOL -.-> AUDIT_LOG_API[audit_log INSERT<br/>via @audit_log decorator<br/>rev. 72]:::async
    CANCEL_FLOW -.-> AUDIT_LOG_API
    ANON -.-> AUDIT_LOG_API
```

---

## 2. Leyenda de colores

| Clase | Color | Significado |
|---|---|---|
| `msg` | 🔵 Azul | Mensaje al cliente (outbound texto WhatsApp) |
| `sys` | ⚪ Gris | Lógica del sistema sin output al cliente |
| `alert` | 🟠 Naranja | Alerta / escalación a humano |
| `async` | 🟢 Verde | Trigger asíncrono (webhook / cron / worker) |
| `tool` | 🟣 Morado | Tool determinístico (no-LLM) |
| `guard` | 🔴 Rojo | Guard / anti-alucinación (rev. 73) |

---

## 3. Mapeo cluster → módulo destino rev. 74

Esta tabla es el **acceptance criteria** del refactor estructural. Cada cluster
del flowchart determina el archivo donde deben vivir las funciones que hoy
están en `services/ai-orchestrator/orchestrator.py` (4.247 líneas).

| Cluster del flowchart | Archivo destino rev. 74 |
|---|---|
| Gates de seguridad iniciales (META_DEDUP, WIN24, SESSION_GATE, AFTER_HOURS) | `services/ai-orchestrator/fsm/guards.py` |
| Comandos globales (asesor / cancelar / eliminar / cambia envío) | `services/ai-orchestrator/commands/global_commands.py` (NUEVO) |
| Multimodal (audio gate, MEDIA_WARN) | `services/ai-orchestrator/tools/multimodal.py` (extender) |
| FSM_DETERMINE + transitions + cart-change detection (`_cart_changed_since_last_quote`) | `services/ai-orchestrator/fsm/states.py` + `fsm/transitions.py` |
| Skip guards rev. 73 (`_last_outbound_was_consent_question`, `_last_outbound_was_data_collection_question`) | `services/ai-orchestrator/fsm/guards.py` |
| Build summary + verified context (Fix-4 rev. 73 con dirección literal) | `services/ai-orchestrator/prompt/verified_context.py` |
| Tools morados (catalog/kb/shipping/order_status/payment_link) | `services/ai-orchestrator/tools/*.py` (ya separados — sin cambio) |
| Anti-alucinación post-process (Fix-5 rev. 73 `_LIE_PHRASES`) | `services/ai-orchestrator/outbound/post_process.py` |
| Audit trail (`bot_source_log` + `@audit_log`) | `services/ai-orchestrator/customer_context/audit_logger.py` |
| Cart recovery async (rev. 70 `_load_cart_recovery_block`) | `services/ai-orchestrator/customer_context/cart_recovery.py` |

---

## 4. Cómo usar este diagrama

### Onboarding (5 minutos)
Un dev nuevo lee el flowchart de arriba a abajo y entiende los 6 estados del FSM, los 4 gates de seguridad y los 5 tools determinísticos. Ningún concepto del bot vive solo en código — todo tiene su nodo aquí.

### Debugging
Cuando un cliente reporta comportamiento inesperado:
1. Ubicar en qué nodo del flowchart ocurrió.
2. Mapear ese nodo al cluster → archivo destino rev. 74.
3. Buscar la función específica en el archivo correspondiente.

Ejemplo: cliente dice "el bot me confirmó pedido sin pagar" → nodo `LIE_REPLACE` → cluster anti-alucinación → `outbound/post_process.py` (post rev. 74) → revisar `_LIE_PHRASES` y `payment_link_result`.

### QA y tests
Cada path completo del flowchart es una test case. La suite rev. 73 cubre las ramas críticas:
- `tests/test_rev73_flow_coherence.py` — carrier per-pedido, cart-change, skip per data-question, anti-alucinación.
- `tests/test_orchestrator_catalog_prompt.py` — guard READY_FOR_SUMMARY sin shipping verificado.

### Refactor rev. 74 (driver del refactor)
Antes de mover una función desde `orchestrator.py` a un archivo nuevo:
1. Identificar a qué cluster del flowchart pertenece esa función.
2. Mapear ese cluster en la tabla de la sección 3 → archivo destino.
3. Mover.
4. Verificar suite tests verde después de cada commit.

Si una función NO calza con ningún cluster del flowchart, hay 2 posibilidades:
- El flowchart está incompleto — actualizar primero el flowchart.
- La función es muerta / redundante — candidatos a eliminar en rev. 74.

---

## 5. Cobertura y limitaciones

### Qué SÍ refleja
- Estado real post-rev. 73 (681 tests verde).
- Flujo de cliente nuevo y conocido (sin shortcuts por consent histórico).
- Anti-alucinación transaccional (no afirmar pedido sin tool verificado).
- Cart recovery (rev. 70) con re-validación stock+precio actual.
- Audit trail dual: `bot_source_log` (rev. 71) + `audit_log` (rev. 72).

### Qué NO está (intencional)
- **F7-full** (templates Meta proactivos) — bloqueado por aprobación Meta del template.
- **F7-email** (recovery dual-channel WhatsApp + email) — bloqueado por SMTP propio (Resend con dominio).
- **F8 multimodal imagen** — postpuesto tras audio (rev. 67).
- **AI Agents router** — drift moderado M3 rev. 72, postpuesto.
- **Insights / preview Gemini SSR** — deuda técnica, viven en Next.js Server Routes.

---

## 6. Política de actualización

**Regla única:** cualquier cambio en FSM, tools, guards o transiciones DEBE actualizar este flowchart en la misma rev. del repo.

Si el flowchart y el código divergen:
1. Deja de ser fuente de verdad.
2. El refactor rev. 74 queda sin contrato verificable.
3. Onboarding con dev nuevo se rompe (lee algo que no existe).

**Checklist al cerrar cualquier rev. que toque `orchestrator.py`:**
- [ ] ¿Modifiqué un FSM state o transition? → actualizar nodos del flowchart.
- [ ] ¿Agregué un tool determinístico nuevo? → agregar nodo morado.
- [ ] ¿Agregué un guard nuevo? → agregar nodo rojo.
- [ ] ¿Agregué un async branch? → agregar nodo verde.
- [ ] ¿Cambió la jerarquía de gates? → reordenar las flechas.

Si tu rev. no tocó FSM/tools/guards, **el flowchart no necesita cambio**.
