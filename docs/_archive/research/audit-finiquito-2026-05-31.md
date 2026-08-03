> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Auditoría exhaustiva de finiquito — Konvi · 2026-05-31

> Generada por workflow paralelo `exhaustive-konvi-audit-finiquito` (12 agents, 1.5M tokens, 14.7 min).

> Fuente: inspección directa de código + DB schema + migrations + tests. NO basada en docs/reports.


## Índice


1. [Inbox CORE (Orchestrator agentic + state machine + multimodal)](#1-inbox-core)

2. [Productos (Catálogo)](#2-productos)

3. [Ventas (Contactos / Cotizador / Promociones / Reclamos / Pedidos)](#3-ventas)

4. [Compras (Suppliers + POs + WAC)](#4-compras)

5. [Canales (WhatsApp / MeLi / Telegram + Channel Registry)](#5-canales)

6. [IA y Conocimiento (KB + Agentes IA)](#6-ia-y-conocimiento)

7. [Finanzas y Analítica](#7-finanzas-y-analítica)

8. [Configuración (Tenant Console settings)](#8-configuración)

9. [Seguridad cross-cutting (OWASP + Habeas Data + multi-tenant)](#9-seguridad-cross-cutting)

10. [Deuda técnica (monolitos / duplicados / spaghetti)](#10-deuda-técnica)

11. [Cross-module wiring ("TODO debe estar conectado")](#11-cross-module-wiring)

12. [Storefront readiness (back para tienda web pública)](#12-storefront-readiness)


---


## Resumen ejecutivo


| # | Módulo | real_status (resumen) | Bugs total | crit+high | gaps_func | gaps_tech | Prio | Esfuerzo |

|---|---|---|---|---|---|---|---|---|

| 1 | **Inbox CORE** | FUNCIONAL CON BUGS RUNTIME REALES + GAP CRÍTICO DE FUENTES DE VERDAD. El estado descrito e… | 16 | 7 | 9 | 10 | P0 | 10-14 days. Breakdown: (1) Shipping_orig… |

| 2 | **Productos** | PARCIALMENTE FUNCIONAL — Production-ready para tenant KAIU (cosmética artesanal, ~20 produ… | 15 | 6 | 14 | 14 | P1 | 14-18 días (P0 4-5d, P1 6-7d, P2 4-6d)… |

| 3 | **Ventas** |  ═══════════════════════════════════════════════════════════════════════ [1] CONTACTOS — s… | 7 | 3 | 11 | 12 | P0 | 7-10 días totales para llevar VENTAS a p… |

| 4 | **Compras** | EXISTE pero es MVP esquelético — confirmado por código, no por docs. Stack real:  DB (`sup… | 8 | 3 | 17 | 17 | P1 | P0 hardening crítico (atomicidad transac… |

| 5 | **Canales** | El módulo CANALES está fragmentado y NO unificado. Hay 3 canales con niveles de madurez mu… | 13 | 6 | 14 | 15 | P1 | ~14-18 días dev productivos. Desglose: (… |

| 6 | **IA y Conocimiento** | KB (Knowledge Base) — FUNCIONAL nivel MVP, GAPS para producción multi-tenant: UI Tenant Co… | 8 | 4 | 9 | 9 | P1 | 8-12 días… |

| 7 | **Finanzas y Analítica** | PARCIAL — Existen 2 módulos UI independientes con KPIs basicos, NO un dashboard unificado … | 9 | 3 | 15 | 11 | P1 | 14-18 días para alcanzar production-grad… |

| 8 | **Configuración** | Configuración está MAYORMENTE FUNCIONAL en producción. La estructura está modularizada cor… | 9 | 3 | 12 | 14 | P1 | 8-12 días (P0 bloqueantes: validación se… |

| 9 | **Seguridad cross-cutting** | PARCIAL — Hay base sólida (RLS 73/73 tablas, HMAC Meta + Wompi constant-time, JWT validati… | 15 | 7 | 7 | 7 | P0 | P0 (H7 rotación secretos) = 1 día founde… |

| 10 | **Deuda técnica** | Repo en plena migración strangler-fig: `agentic/` (nuevo) coexiste con `orchestrator.py` m… | 7 | 4 | 5 | 15 | P1 | 15-20 días desarrollador senior (no cont… |

| 11 | **Cross-module wiring** | 7 de 14 conexiones OK end-to-end (Inbox→Productos, Inbox→KB RAG, Cart→Pedidos snapshot, Pe… | 10 | 2 | 7 | 9 | P1 | 5-7 días… |

| 12 | **Storefront readiness** | NO LISTO PARA STOREFRONT PÚBLICO — arquitectónicamente preparatorio, funcionalmente bloque… | 9 | 4 | 12 | 12 | P2 | 28-42 días dev (5.5-8.5 semanas, NO <2 s… |


---


## 1. Inbox CORE (Orchestrator agentic + state machine + multimodal)


**Prioridad finiquito**: `P0`  

**Esfuerzo estimado**: 10-14 days. Breakdown: (1) Shipping_origin + business_ops block injection: 0.5d. (2) Address schema reconciliation contact_record line1/street: 0.5d. (3) WhatsApp Flows Phase 1 (CTA URL button + send_interactive helpers): 2-3d. (4) Dispatcher monolito refactor split per-resolver module + pytests cover: 3-4d. (5) Multi-agente tool enforcement BEFORE pre-LLM resolvers: 1d. (6) FakeEscalationInvariant validation + side-effect tests: 0.5d. (7) Philosophy length truncation + coupon visibility filter: 0.5d. (8) consent_intent espontaneo + audit propagation: 1d. (9) State machine race protection + concurrent test: 0.5-1d. (10) E2E UAT live dinámico per founder methodology: 1d.


### Estado real (verificado en código)


FUNCIONAL CON BUGS RUNTIME REALES + GAP CRÍTICO DE FUENTES DE VERDAD. El estado descrito en rev109_uat_exhaustivo_completo.md (19 bugs fixed) es 95% CIERTO al inspeccionar código actual en develop: BUG 1 (migration 20260604000000_conversations_agentic_state aplicada CONFIRMADO), BUG 2 (resolver lee shipping_meta JSONB CONFIRMADO), BUG 3 (purchase_intent_resolver tie return None CONFIRMADO), BUG 4 (document_number CONFIRMADO), BUG 5 (add_to_cart en GREETING+EXPLORING CONFIRMADO en tools_subset.py:65-82), BUG 6 (save_contact_field en PAYMENT subset CONFIRMADO línea 113), BUG 7+17 (Pydantic AliasChoices field/field_name/email/name/phone CONFIRMADO contact.py:705+720), BUG 8 (POST-LLM cod re-mark dispatcher.py:2004 + payment_coherence CASE C invariant CONFIRMADO), BUG 9 (shipping_resolver stop-markers no/y/pero/sino CONFIRMADO línea 80), BUG 10 (_resolve_and_persist_agentic_state helper unificado CONFIRMADO dispatcher.py:2346 + se invoca en 4+ bypass paths), BUG 11 (CanonicalCategoriesInvariant CONFIRMADO + en invariant_set línea 2112), BUG 12 (rename PaymentCoherence CONFIRMADO; PaymentMethodExplicit es solo comentario residual línea 5 doctring), BUG 13 (DECLINED webhook emojis removidos — no verificado pero no es crítico), BUG 14 (singular/plural stemming en _product_matches_category CONFIRMADO catalog.py:140-163), BUG 15+18 (_CART_MODS reutilizable CONFIRMADO tools_subset.py:28-37), BUG 16 (coupon_intent pre-LLM dispatcher.py:915-1035 CONFIRMADO), BUG 19 (PIISaveTruthfulnessInvariant CONFIRMADO invariants/pii_save_truthfulness.py + en pipeline 2100). PERO: encontré bugs runtime NUEVOS no documentados en el reporte (address schema mismatch line1/street, shipping_origin no inyectado, WhatsApp Flows zero infrastructure, multi-agent tool enforcement after pre-LLM resolvers). El founder feedback 'tiene demasiados bugs, disvaría, repite cosas' tiene causa raíz: (a) address mismatch hace que cliente CONOCIDO sea tratado parcial, (b) shipping_origin/store_locations missing impide responder preguntas operacionales básicas, (c) dispatcher 2763 LOC monolítico imposible de testear/depurar. NO production-grade. Necesita 10-14 días refactor + UAT live dinámico antes de declarar done.


### Bugs runtime (16)


- 🟠 **[HIGH]** tenant.shipping_origin (warehouse origin) y tenant.store_locations NO se inyectan al system_prompt agentic. La función build_system_prompt() no acepta esos kwargs ni el dispatcher los lee del row tenants (línea 526 solo select 'name, business_pitch, tono_comunicacion, mision, vision, valores'). Resultado runtime: si cliente pregunta '¿desde dónde despachan?' / '¿tienen tienda física?' / '¿en qué barrio están?', el bot disvaría o escala innecesariamente. El legacy orchestrator V1 sí lo cargaba (orchestrator.py:5880 + 6134) — gap real introducido en la migración agentic.

  - `services/ai-orchestrator/agentic/dispatcher.py:526-544 + services/ai-orchestrator/agentic/system_prompt.py:448-498`

- 🟠 **[HIGH]** system_prompt NO renderiza ningún bloque tipo CONTEXTO_NEGOCIO / DIRECCIÓN BODEGA / SEDES. Solo expone catálogo + carriers + payment_methods + cupones + filosofía + persona. El bot tiene cero awareness de la operación física del tenant — no puede responder preguntas básicas (hora de atención, dirección, redes sociales). La filosofía (mision/vision/valores) sí se inyecta pero es contexto IDENTITARIO, no operacional.

  - `services/ai-orchestrator/agentic/system_prompt.py:_render_philosophy_block solo / no hay _render_business_ops_block`

- 🔴 **[CRITICAL]** El bloque CONTACTO en system_prompt sí inyecta address.line1/city/state del contact CONOCIDO (línea 387-411), pero los keys que lee son line1/city/state mientras que el address persistido por SaveContactFieldTool usa street/city/building_type/apartment/neighborhood/dane_code (cart.py linea 30-55 _build_address_dict). Mismatch silencioso: para clientes que dieron dirección via agentic, addr_parts queda vacío → addr_str='(sin dirección guardada)' → bot vuelve a pedir dirección a cliente CONOCIDO. Bug arquitectónico de schema drift.

  - `services/ai-orchestrator/agentic/system_prompt.py:387-395 vs services/ai-orchestrator/agentic/tools/contact.py:31-55`

- 🟠 **[HIGH]** WhatsApp Flows / interactive outbound: send_whatsapp_message() en whatsapp_sender.py solo soporta type=text|image|template. NO existe función send_interactive_buttons / send_interactive_list / send_flow. Inbound parser sí reconoce button_reply, list_reply, nfm_reply (parser.py:10-26) pero el bot nunca origina esos mensajes — el cliente nunca verá un CTA URL Button ni una lista, todo es texto plano. Plan L Phase 1 (CTA URL button) requiere CERO migration DB, solo agregar send_interactive_button + integrarlo en payment_link_tool/quote_shipping outbound.

  - `services/ai-orchestrator/whatsapp_sender.py:47-139 (solo text/image) + 142+ (solo template). No hay branch type=interactive`

- ⚪ **[LOW]** Multimodal: cuando Gemini procesa audio/imagen, transcribe el texto y lo persiste en messages.content como '🎤 Audio: <texto>' (dispatcher.py:389), pero ese override sobrescribe el placeholder '[Audio recibido]' del parser → Inbox UI muestra emojis decorativos que la regla 'CERO emojis decorativos' del system_prompt prohíbe al bot. Inconsistencia entre Inbox UI policy y system rule.

  - `services/ai-orchestrator/agentic/dispatcher.py:383-393`

- 🟡 **[MEDIUM]** Tenant philosophy se carga del tenant row directamente, pero los campos valores/mision/vision pueden ser muy largos (UI permite textarea libre). NO hay límite de longitud — un tenant con valores=10KB texto satura el system_prompt y baja calidad LLM. No hay truncate ni length-check en _render_philosophy_block.

  - `services/ai-orchestrator/agentic/system_prompt.py:314-352`

- 🟡 **[MEDIUM]** Coupons block (rev. 109 founder 2026-05-28) inyecta hasta 20 cupones activos. Si tenant tiene cupones internos no-cliente-aplicables (ej. afiliados), todos pasan al prompt + el LLM puede mencionarlos al cliente. NO hay flag `customer_visible` ni filtro por tipo de cupón en la query (dispatcher.py:586-606).

  - `services/ai-orchestrator/agentic/dispatcher.py:586-611`

- 🟠 **[HIGH]** Multi-agente: agent_router carga activeAgent.tools_allowed y hace intersección con tools_for_state (dispatcher.py:1974-1985). PERO si tenant tiene 2+ agentes y el agente activo se cambia mid-conversación, los pre-LLM resolvers (coupon, cancel, image_send, purchase_intent, shipping_intent) NO consultan al agente activo. Pueden actuar fuera del scope autorizado. Ej: agente 'Reclamos' configurado sin add_to_cart, pero purchase_intent_resolver hace add_to_cart_tool antes del check.

  - `services/ai-orchestrator/agentic/dispatcher.py:617-624 (router carga DESPUÉS de pre-LLM resolvers) vs 1539-1750`

- 🟡 **[MEDIUM]** consent_intent_resolver es solo regex (ver consent_intent_resolver.py). El detector match solo si el último outbound del bot pidió consent explícito. Si el cliente envía 'sí acepto Habeas Data' espontáneo (sin que el bot preguntó primero), NO se marca consent → bot pregunta de nuevo → loop infinito potencial.

  - `services/ai-orchestrator/agentic/consent_intent_resolver.py + dispatcher.py:1431-1446`

- 🟡 **[MEDIUM]** payment_coherence invariant lee cart en estados [open, checkout, converted] pero CASE A (REWRITE pregunta modo) corre antes del LLM saber que el cliente ya pagó. Si carta=converted (orden hecha) + outbound es post-pago narrativa, el invariant puede reescribir un mensaje válido. Ver línea 366: order desc updated_at limit 1 puede traer cart converted recien convertido en el mismo turn.

  - `services/ai-orchestrator/agentic/invariants/payment_coherence.py:360-372`

- ⚪ **[LOW]** BUG 16 coupon_intent en dispatcher.py:925-1035 detecta cupón pero NO valida que el cliente tenga consent Habeas Data. Si cliente nuevo aplica cupón antes de dar consent, se persiste en cart_events sin auditoría adecuada. cart_events.event_type='coupon_applied' debería estar en consent_audit_log también si el cupón implica tracking PII.

  - `services/ai-orchestrator/agentic/dispatcher.py:1006-1014`

- ⚪ **[LOW]** agent_router get_active_agent puede retornar None silenciosamente (fallback hardcoded a 'Sara Camila'). Si tenant configuró agente con nombre custom (ej. 'Andrea de KAIU') pero la lookup falla por timeout/RLS, el bot se presenta como Sara Camila → confusión cliente. NO hay alerta/log.

  - `services/ai-orchestrator/agentic/dispatcher.py:617-623`

- 🟠 **[HIGH]** FakeEscalationInvariant existe (rev. 109 founder 2026-05-28 'super delicado'). El system_prompt regla técnica obliga llamar escalate_to_human ANTES del texto si promete especialista. Pero la implementación del invariant no se inspeccionó — si no FUERZA el side-effect (notify_escalation_async + conv.status=human_takeover), promete cliente sin notificar operador. Necesita inspección puntual de invariants/fake_escalation.py:213.

  - `services/ai-orchestrator/agentic/invariants/fake_escalation.py`

- ⚪ **[LOW]** purchase_intent_resolver pre-LLM bypasea LLM cuando resuelve productos/qty. Pero NO consulta consent del cliente — add_to_cart funciona sin consent (cart-as-SoT permite items pre-PII), entonces OK. Sin embargo, una vez creado el cart, el state machine va a CART_BUILDING. Si el cliente dijo TODO ('1 jabón coco 100g a Bogotá contraentrega'), shipping_intent_resolver dispara después pero requiere PII para llegar a PAYMENT — termina forzando flow PII_COLLECTION post-bypass. Funciona, pero el bypass NO logea el estado downstream del state machine para auditoría/debugging.

  - `services/ai-orchestrator/agentic/dispatcher.py:1539-1654`

- ⚪ **[LOW]** agentic_state column es nullable + no default en supabase/migrations/20260604000000. El helper _resolve_and_persist_agentic_state best-effort actualiza pero no garantiza consistencia. Si dos turnos concurrentes del mismo conv corren simultaneamente (raro en WhatsApp, pero posible con multi-message), pueden race-condition el agentic_state. NO hay versioning ni optimistic lock.

  - `supabase/migrations/20260604000000_conversations_agentic_state.sql + dispatcher.py:2433`

- 🟠 **[HIGH]** Dispatcher monolítico: 2763 líneas en agentic/dispatcher.py. _run_agentic_full es una sola función de ~1500 LOC con 14 pre-LLM resolvers inline. Imposible testear unitariamente cada resolver path. Bug surface area enorme. Founder reporta 'disvaría y repite' → muy probable que un resolver pre-LLM esté disparando incorrectamente y nadie lo nota porque no hay test cobertura per-resolver-path.

  - `services/ai-orchestrator/agentic/dispatcher.py:322-2218 (single function)`



### Fuentes de verdad (uso real)


- CONTACTS.ADDRESS — USO PARCIAL/ROTO. system_prompt linea 387-395 inyecta line1/city/state pero SaveContactFieldTool persiste street/city/building_type/apartment (cart.py:31-46). Mismatch schema → cliente CONOCIDO que dio dirección via agentic será re-preguntado (regresión Habeas Data + UX).

- CONTACTS.CONSENT/EMAIL/DOC/NAME — USO CORRECTO. _render_contact_block detecta is_known_customer correctamente; tools/contact.py:GetContactInfoTool retorna summary_lines_for_order pre-renderizado (BUG 32 fix). PIICoherence + PIISaveTruthfulness invariants en pipeline.

- PRODUCTS + CATALOG — USO CORRECTO. catalog se inyecta full al system_prompt con product_id + variation_id literales (system_prompt.py:_render_catalog_block:21-63). Regla 'NUNCA inventes productos' explícita. tools/catalog.py:_product_matches_category tiene singular/plural stemming post BUG 14.

- CONVERSATION_CARTS (cart-as-SoT) — USO CORRECTO. State machine resuelve cart_items_count + shipping_meta + payment_method en cada turno (resolver.py:135-207). Cart se lee at state machine + per-state prompt + invariants (cart_render_coherence, summary_coherence). Pre-LLM resolvers (coupon, cancel, image, shipping, purchase) consultan cart.

- SHIPPING_META (carrier, dane_code, city_canonical) — USO PARCIAL. shipping_meta JSONB se lee correcto en resolver (carrier_code/payment_link populated del JSONB). dane_code se persiste en address al save (contact.py:48-53 via lib.dane_resolver). carrier_select_resolver lee shipping_meta.quoted_options. CORRECTO.

- PAYMENTS.STATUS — USO PARCIAL. state machine considera payment_status=approved|declined|pending para POST_PAYMENT/PAYMENT (resolver.py:73-86). PERO la auditoría no encontró que el dispatcher cargue una row activa de payments para inyectar al system_prompt — solo cart.payment_method. Si bot post-Wompi DECLINED, depende del webhook haber actualizado cart + el LLM ver el estado en next turn — no en el mismo turn.

- KB (knowledge_base) via kb_query — TOOL CORRECTO. tools/kb_tool.py soporta RAG semántico + boost categórico canónico (faq/negocio/politicas/productos/envios/pagos). agentic/tools/knowledge.py:KbQueryTool registrado. Está en tools_subset para GREETING, EXPLORING, CART_BUILDING, POST_PAYMENT, etc. system_prompt regla #7 obliga kb_query antes de escalar.

- TENANT.SHIPPING_ORIGIN (warehouse) — NO USADO POR EL BOT. shipping_quote_tool sí lo lee al cotizar (tools/shipping_quote_tool.py:1425), pero el bot NUNCA tiene awareness en su system_prompt. Cliente pregunta '¿desde dónde despachan?' → bot disvaría. Legacy orchestrator.py:5941 lo cargaba en prompt, agentic NO. Bug crítico introducido en migración.

- TENANT.PAYMENT_METHODS ACTIVOS — USO CORRECTO. lib/tenant_payment_methods.get_tenant_payment_methods carga + se inyecta como bloque [MÉTODOS DE PAGO HABILITADOS] (system_prompt.py:_render_payment_methods_block). Reglas críticas por config explícitas. payment_method_availability_resolver pre-LLM short-circuit si tenant disabled lo solicitado.

- TENANT.CARRIERS — USO CORRECTO. lib/carrier_capabilities.get_all_capabilities_for_tenant se inyecta como bloque [CARRIERS] con flags supports_cod, charges_return_fee, cod_min_recaudo. Reglas COD canónicas con warnings.

- TENANT.NAME/PITCH/TONE/PHILOSOPHY — USO CORRECTO post-rev.107. tenant_name + business_pitch + tono_comunicacion + mision/vision/valores se cargan. Riesgo: longitud sin límite puede saturar prompt.

- TENANT.STORE_LOCATIONS / SOCIAL_LINKS / STORE_TYPE — NO USADO POR AGENTIC. Legacy orchestrator.py:6850 las cargaba; agentic no. Bot no puede responder '¿tienen tienda física?' / '¿síganos en Instagram?'.

- COUPONS — USO CORRECTO. Cupones activos se inyectan vía _render_coupons_block (post rev. 109 BUG arquitectónico). Filtro is_active+valid_until+redemptions disponibles. Regla anti-hallu explícita.

- AI_AGENTS (multi-agente per-tenant) — USO PARCIAL. agent_router selecciona agente activo + inyecta role_description + tools_allowed (dispatcher.py:617). PERO los pre-LLM resolvers corren ANTES del agent_router → pueden ejecutar tools fuera del scope del agente.

- ORDERS — USO CORRECTO. tools/orders.py:GetRecentOrdersTool registrado, en tools_subset de POST_PAYMENT + cancel_intent_resolver consulta orders via lib.order_cancellation.



### Gaps funcionales (9)


- WhatsApp Flows / interactive outbound completamente AUSENTE. Plan L Phase 1 (CTA URL button para link Wompi) requiere agregar send_interactive_button() a whatsapp_sender.py + branch en agentic.tools.payment.GeneratePaymentLinkTool para emitir interactive en lugar de texto plano. ~2-3 días.

- Bot no responde preguntas operacionales del negocio físico ('¿dónde están?', '¿tienen tienda?', '¿horario?'). Falta inyectar tenant.shipping_origin + store_locations + business_hours al system_prompt. KB puede cubrir parcialmente vía categoría 'negocio' pero requiere que el tenant haya cargado docs, no es out-of-the-box.

- PII reuse para cliente conocido falla por address schema mismatch (line1 vs street). Founder reporta 'repite cosas que ya debería saber' — probable causa raíz de esta queja específica para clientes que dieron dirección en agentic recientemente.

- Bot puede prometer especialista sin notificar operador (FakeEscalationInvariant existe pero no auditamos si fuerza side-effect real). Necesita inspección + test e2e.

- Stock reservation hybrid (rev. 109 sección D) no implementado — 2 clientes pueden agregar último item simultáneamente.

- Cancelación post-orden + retracto Ley 1480 implementados pero retracto siempre escala a humano (sin auto-resolve cuando producto NO está excluido). El cliente ELEGIBLE espera 5 días vs auto-resolve inmediato.

- Sin proactive engagement (HSM templates approved + worker payment_reminders existe pero requiere intervención humana para configurar templates Meta-approved per tenant).

- Sin reclamos asincrónicos (claims tool existe rev. 109 founder pero falta UI Inbox para que operador procese; tools/claims.py:create_claim + get_claim_status crean filas pero el ciclo de respuesta al cliente queda en limbo).

- Multi-tenant: solo KAIU probado live. Falta UAT 2do tenant para certificar aislación real (orphan_check de Wompi + RLS service_role + supabase_auth).



### Gaps técnicos (10)


- agentic/dispatcher.py 2763 LOC — monolito spaghetti. _run_agentic_full() es UNA sola función de ~1500 LOC con 14 pre-LLM resolvers inline. Refactor obligatorio antes de producción: extraer cada resolver a módulo + middleware pipeline pattern. CRÍTICO para mantenibilidad + test coverage.

- orchestrator.py legacy V1 todavía existe (10,419 LOC). Es path muerto para KAIU (agentic_enabled=true) PERO el agentic_dispatcher importa decenas de helpers de orchestrator.py (_send_outbound_text, _get_conversation_history, _fetch_contact_for_phone, _mark_message_processing, _log_consent_event, build_and_run_orchestration). Coupling fuerte impide eliminar legacy. Plan A.2 strangler-fig declarado pero NO completado.

- Duplicación tools: services/ai-orchestrator/tools/ (legacy, 8 tools) vs services/ai-orchestrator/agentic/tools/ (agentic, 17 tools). agentic.tools reusan legacy.tools como backend (get_cart_with_items, get_tenant_catalog, get_tenant_kb_rag). Confuso, ya que image_send_tool.py legacy se invoca pre-LLM del agentic. Mover legacy → lib/cart_repo.py + lib/catalog_repo.py para clarificar capas.

- Pre-LLM resolvers carecen de test unitario per-resolver. test suite (345 PASS según rev.109) cubre integración pero no cada pre-LLM path × estado × edge case. Bug surface area enorme.

- agentic/tools/contact.py 884 LOC — 5 clases save_X DEAD CODE (líneas 404-668 SaveEmail/SaveName/SaveDocument/SaveAddress/SaveShippingPhone). Mantenidas 'por backwards-compat de imports' pero no se registran. Eliminarlas reduce 400+ LOC del archivo.

- system_prompt.py 754 LOC con múltiples _render_X_block. Cada cambio de un bloque requiere editar el f-string master de ~250 líneas (línea 500-753). Refactor a Template + builder.

- agent.py 750 LOC — sin auditar pero llaman tool dispatcher + cascade. Probable que tenga lógica recovery duplicada con dispatcher.

- Schema drift detectado: contacts.address es JSONB. SaveContactFieldTool persiste keys {street, city, building_type, apartment, ...}. system_prompt.py:387-395 lee {line1, city, state}. Migration legacy expecting line1, agentic moviendo a street. Schema canónico NO documentado — hay que escoger uno + migration de dato existente.

- agentic_state nunca documentado con FSM diagram + transition table en docs. resolver.py tiene comentarios pero los tests del state machine son pocos (no inspeccionados pero típicos < 20 casos vs 9 estados × N transiciones = >50 casos teóricos).

- NO hay observability dashboard para los pre-LLM resolvers. Solo logs INFO. Imposible para founder ver 'cuántas veces purchase_intent bypaseó LLM esta semana / cuándo falló / qué inbound lo disparó'.



---


## 2. Productos (Catálogo)


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: 14-18 días (P0 4-5d, P1 6-7d, P2 4-6d)


### Estado real (verificado en código)


PARCIALMENTE FUNCIONAL — Production-ready para tenant KAIU (cosmética artesanal, ~20 productos, single-vertical, pocas variantes). NO-production-ready para escala multi-vertical / >100 SKUs / variantes complejas (moda 3D matrix). Schema base es sólido (products + product_variations + stock_movements + stock_reservations con TTL pattern Stripe + audit cost_price WAC) y categorías canónicas existen, pero: (1) categorías globales hardcoded cosmética = no escala a otros verticales; (2) bulk import es cliente-side directo a Supabase sin transacción / sin backend / sin imágenes en bulk; (3) tool list_catalog del bot OMITE imágenes y categorías reales (heurística por title-head); (4) variant images existen pero send_product_image solo manda cover producto; (5) MAX_VARIANTS=6 trunca productos complejos silenciosamente; (6) bypass del API: server actions en Next escriben directo a DB rompiendo audit + sync_meli + validaciones. Founder tiene razón: Front (UI variant matrix OK + drawer denso pero funcional), Back (CRUD completo PERO sin bulk + sin search server-side + sin export), DB (schema correcto, categorías rígidas), MW (tooling dual + cache stale), UX (Inventario route vacío, Media route ciego, sin guía atributos por categoría) — TODO necesita trabajo.


### Bugs runtime (15)


- 🟠 **[HIGH]** Variant images NUNCA llegan al cliente vía WhatsApp. send_product_image SOLO usa products.cover_image_url — ignora product_variations.image_url. Si cliente pregunta 'muestrame la versión negra' / 'la talla M', el bot manda la foto genérica del producto. Schema soporta variant images (column existe + UI sube), pero la tool no lee variation_id.

  - `services/ai-orchestrator/agentic/tools/media.py:24-87 (args solo product_id; SELECT ignora variation_id)`

- 🟡 **[MEDIUM]** list_catalog NO expone imágenes al LLM. El tool retorna product_id/title/variants{price} pero omite cover_image_url y variant.image_url — el LLM no sabe qué productos tienen foto disponible y puede ofrecer enviarla cuando no existe.

  - `services/ai-orchestrator/agentic/tools/catalog.py:90-108 (products_out sin image fields); services/ai-orchestrator/tools/catalog_tool.py:53-97 (catalog_cache builder tampoco propaga images)`

- 🟠 **[HIGH]** catalog_tool.get_tenant_catalog NO filtra por platform_category_id ni lo retorna. El LLM no sabe a qué categoría canónica pertenece cada producto — imposible recomendar cross-category o navegar por categoría real. _extract_category_head() suplanta categoría con la primera palabra del título (frágil: 'Aceite Esencial' vs 'Aceite Vegetal' ambos heuristican a 'aceite').

  - `services/ai-orchestrator/tools/catalog_tool.py:53-97 (no select de platform_category_id); services/ai-orchestrator/agentic/tools/catalog.py:129-167 (fallback heurístico)`

- 🟠 **[HIGH]** Categorías NO son multi-tenant. platform_categories es tabla global compartida (DELETE + INSERT en migration 20260427) → cuando entre un tenant de tech/relojes, sus categorías de 'Cuidado Facial' son ruido y faltan 'Relojería/Carcasas/Cables'. business_pitch+product_groups (rev 20260526) fueron parche, pero NO reemplazan FK platform_category_id que sigue apuntando al set hardcoded cosmética/wellness.

  - `supabase/migrations/20260411162042_fase11_3_catalog_enterprise.sql:4-25 (RLS bloquea writes a tenants); 20260427020000_update_categories.sql:10-32 (20 categorías hardcoded)`

- 🟠 **[HIGH]** Bulk importer (mass-importer.tsx) hace inserts cliente-side directos a Supabase con anon key bypasseando RLS por sesión. No valida: SKU duplicado mid-batch (rompe constraint uc_tenant_sku con error feo), filas con precio=0 las upserta como price=1 (data corrupta), no soporta rollback parcial — si la fila 50/100 falla, las 49 anteriores quedan committed. No procesa imágenes (founder lo declara, pero es bloqueante para onboarding de tenant con 200 SKUs).

  - `apps/web/app/dashboard/(products)/catalog/_components/mass-importer.tsx:196-267 (insert sin transacción + price=1 fallback línea 230)`

- 🟠 **[HIGH]** Bulk importer NO tiene endpoint backend correspondiente — toda la lógica es cliente-side via supabase-js. Imposible: validar SKUs vs business rules server-side, auditar (audit_log no se dispara), aplicar dimensiones obligatorias para Aveonline, integrar con marketplace_listings, sync MeLi. Founder dice 'falta back' → confirmado.

  - `services/api/routers/products.py (no hay POST /products/bulk); mass-importer.tsx:259-261 (upsert directo)`

- 🟡 **[MEDIUM]** patch_variation y patch_product NO normalizan keys de attributes JSONB. Tenant puede crear variantes con attrs={'Color': 'Rojo'} y {'color': 'rojo'} para el mismo producto → el bot las trata como 2 SKUs distintos y _normalize_attributes_label devuelve labels diferentes ('Color: Rojo' vs 'color: rojo'). No hay constraint ni trigger DB que normalice.

  - `services/api/routers/products.py:73 (attributes dict sin schema); supabase/migrations/20260406181236_catalog_schema.sql:19 (JSONB libre)`

- 🟡 **[MEDIUM]** DELETE de producto en page.tsx hace cascade manual (vars + marketplace_listings + products), pero NO libera stock_reservations activas (FK ON DELETE CASCADE existe en stock_reservations pero variation_id RESTRICT bloquea delete cuando hay reservas vivas — UI dejará al usuario stuck con 'Error al eliminar' críptico).

  - `apps/web/app/dashboard/(products)/catalog/page.tsx:193-212 (deleteProduct); supabase/migrations/20260502000000_stock_reservations.sql:36 (variation_id ON DELETE CASCADE pero reservas active bloquean stock_quantity update)`

- 🟡 **[MEDIUM]** create_product (POST /products) NO valida que variation.sku sea único antes de insert — depende del CHECK uc_tenant_sku que dispara 500 genérico 'Error al crear producto' en lugar de 422 con mensaje claro 'SKU XYZ ya existe'. Mismo issue en add_variation y mass-importer (que sí lo maneja pero después de tiempo perdido).

  - `services/api/routers/products.py:120-157 (insert sin pre-check); línea 156 (catch genérico)`

- 🟡 **[MEDIUM]** products router list_products tiene N+1 implícito y NO soporta search (nombre/SKU/categoría) ni filter por category — el frontend filtra cliente-side trayendo TODAS las rows. Con tenant >500 productos, página catalog tarda + bloquea SSR. Sin pagination real (limit hardcoded 50 en orchestrator catalog_cache también).

  - `services/api/routers/products.py:83-108 (sin q param, sin category filter); apps/web/app/dashboard/(products)/catalog/page.tsx:33-49 (trae todo activo + todo archivado)`

- 🟡 **[MEDIUM]** platform_categories.id es FK en products.platform_category_id pero la migración 20260427 hace DELETE + INSERT con gen_random_uuid() — cada vez que se re-aplique la migration en un entorno fresco, los UUIDs cambian. Productos creados ANTES de re-deploy quedan con platform_category_id apuntando a UUID inexistente. La migration lo previene con UPDATE ... = NULL (línea 36) pero solo en la misma transacción, no en futuras inconsistencias entre tenants.

  - `supabase/migrations/20260427020000_update_categories.sql:10-37`

- 🟡 **[MEDIUM]** image-upload-box.tsx hace upload a Storage 'tenant-media' SIN límite de tamaño cliente-side. Tenant puede subir 50MB PNG → succeed → cover_image_url referenciable pero WhatsApp Cloud API rechaza >5MB (image type), bot enviará imagen pero Meta dará error 131053. No hay validación size/dimension ni resize automático.

  - `apps/web/app/dashboard/(products)/catalog/_components/image-upload-box.tsx:30-51 (handleFile sin size check)`

- 🟡 **[MEDIUM]** adjustStock (catalog/page.tsx:214) hace UPDATE de stock_quantity + INSERT en stock_movements sin transacción atómica. Si el segundo falla (RLS, network), stock queda updateado sin auditoría. Promise.all permite ambos succeed parcial sin rollback.

  - `apps/web/app/dashboard/(products)/catalog/page.tsx:233-245`

- 🟠 **[HIGH]** MAX_VARIANTS_PER_PRODUCT=6 en catalog_tool.py — productos con >6 variantes (típico en moda: 3 colores × 4 tallas = 12) son silenciosamente truncados en el catálogo que ve el LLM. El bot NO podrá ofrecer la variante 7+ aunque exista en DB. El total_stock SÍ suma todas (línea 100-105) → discrepancia: bot dice 'hay stock' pero no puede vender la variante correcta.

  - `services/ai-orchestrator/tools/catalog_tool.py:6,72,100-105`

- ⚪ **[LOW]** products.status enum es TEXT sin CHECK — campo soft-delete acepta cualquier string. UI usa 'active'/'inactive', pero un INSERT directo SQL podría dejar status='archived' (ambiguo con UI 'Archivar producto'). Sin enum estricto, futuras migraciones de estado (draft, out_of_season, deprecated) generarán deuda.

  - `supabase/migrations/20260406181236_catalog_schema.sql:8 (TEXT DEFAULT 'active')`



### Fuentes de verdad (uso real)


- DB tables consumidas: products, product_variations (catalog), platform_categories (categorías), stock_movements (auditoría), stock_reservations (soft-reserve carrito), tenants.business_pitch/product_groups/show_prices_in_catalog/low_stock_threshold (presentación bot), marketplace_listings (vínculo MeLi)

- Storage: bucket tenant-media para imágenes producto+variante

- El LLM consume catálogo VÍA catalog_cache (preloaded) + list_catalog tool (filtrado por categoría heurística). Imágenes vía send_product_image tool. NO consume platform_categories directamente — solo extrae 'category head' del title (frágil)

- Cart (conversation_carts) → product_variations FK: cart tiene snapshot de precio al add (correcto, evita drift). Stock reservations vinculan variation_id ↔ cart_id ↔ conversation

- Cross-module: marketplace.py sincroniza products↔Meli con campo external_reference_id+platform_category_id; shipping.py usa weight_kg + dimensions para Aveonline cotización; purchases.py actualiza cost_price (WAC) cuando llega OC



### Gaps funcionales (14)


- Bulk import server-side: no existe POST /products/bulk con validación atómica + audit + rollback. Lógica está duplicada en mass-importer.tsx (cliente-side directo a Supabase). Sin progreso/preview/dry-run. Sin import de imágenes (workflow 2-pasos: importar texto → subir fotos individual). Sin export del catálogo a Excel (round-trip imposible).

- Variantes con imagen propia: el campo product_variations.image_url existe y la UI lo soporta editar, pero NO se usa en send_product_image ni en list_catalog. Cliente no puede recibir foto específica de una variante (caso típico moda: 'mostrame el rojo').

- Categorías per-tenant: platform_categories es lista global 20 ítems hardcoded para cosmética/wellness colombiano. Tenant de tech, relojería, alimentos, hogar NO puede crear sus propias categorías (RLS bloquea writes, línea 22-25). business_pitch+product_groups (rev 20260526) son texto libre, NO afectan platform_category_id en products. Cross-tenant es bloqueante.

- Subcategorías reales: platform_categories tiene columna parent_id (línea 7) pero NUNCA se usa — toda la jerarquía es plana. Imposible 'Moda > Mujer > Vestidos > Largos'.

- Búsqueda real: products.title sin GIN/trigram index ni tsvector. Search cliente-side via .includes() escala mal (>500 productos = lag). Sin synonyms ('aceite' vs 'oleo' vs 'esencia'), sin fuzzy match.

- Atributos estructurados: variation.attributes es JSONB libre — no hay schema per categoría (un perfume tiene {Volumen, Fragancia}, una camisa tiene {Talla, Color}, sin guía + sin validación de allowed values). Tenants escriben 'XL' / 'Extra Grande' / 'EG' inconsistente.

- Bundles / combos: no hay tabla product_bundles ni concepto de 'kit' (producto que agrupa N variantes). KAIU vende kits — workaround actual es crear un producto-kit con SKU separado, sin trazabilidad de qué SKUs hijos consume.

- Variantes media: solo image_url (single) — no carousel multiimage, no video, no PDF (ficha técnica). Limitante para vertical electrónica/luxury.

- Stock por bodega: stock_reservations tiene warehouse_id NULL reservado (línea 38), pero NO existe tabla warehouses. Single-warehouse-per-tenant hardcoded. Founder con 2 ubicaciones físicas (caso founder eventual) tendrá data inconsistente.

- Variant lifecycle: no se puede archivar/agotar UNA variante específica sin borrarla — toggling solo a nivel producto (status). Variante out-of-season requiere DELETE (rompe analytics histórico).

- Cross-sell del bot: list_catalog filtra UN producto por title-head; no hay tool 'suggest_complementary' ni metadato related_products. El bot no puede decir 'el sérum X va bien con la crema Y'.

- Pricing rules: no hay precio por canal (WhatsApp vs MeLi), no hay descuentos por cantidad, no hay precios B2B/wholesale. compare_at_price solo soporta 'tachado'.

- SKU autogeneration: cliente-side suggestPrefix() en catalog-form (línea 47) es JS puro — si el founder sube por Excel, no aplica. No hay endpoint /products/sku/next que garantice unicidad pre-insert.

- Importación de proveedor: Meli sí (rev. marketplace.py), pero NO hay Shopify/WooCommerce/CSV de Bsale/Siigo (verticales LATAM comunes en SMB que migran).



### Gaps técnicos (14)


- Tooling duplicado dual: services/ai-orchestrator/tools/catalog_tool.py (legacy monolito, get_tenant_catalog que builds catalog_cache) Y services/ai-orchestrator/agentic/tools/catalog.py (nueva arquitectura agentic, ListCatalogTool que LEE catalog_cache). El primero es la fuente real de datos, el segundo solo filtra. Si se cambia schema sin sincronizar ambos, el bot quedará inconsistente. Founder reporta 'spaghetti' confirmado.

- page.tsx server actions hacen DB writes directos via supabase client en lugar de llamar al router products.py. Bypass total del backend: rompe audit_log decorators, RBAC consistency, sync_meli_stock hook, validaciones Pydantic. 8 server actions duplican lógica del backend.

- mass-importer.tsx: 337 líneas monolito que hace template gen (XLSX styling) + parse + business logic + DB writes en un componente. Imposible testear. La hoja de cálculo soporta atributos hardcoded (attrKey3 max) — no genérico.

- Mass importer no usa el endpoint POST /products/ del backend — duplica TODA la lógica de creación. El backend products.py:111 sí existe pero el UI lo ignora.

- products.py:99 hace nested select de product_variations sin LIMIT a la nested — un producto con 50 variantes se trae completo por cada llamada del Inbox.

- platform_categories migration history: 20260411 crea 16 categorías → 20260427 DELETE+INSERT 20 distintas → ninguna usa parent_id. Si en el futuro se agregan más vía nueva migration, FK rota silenciosamente.

- image-upload-box.tsx hace upload directo a Storage sin pasar por API → sin audit, sin antivirus, sin resize, sin CDN-warming. tenant-media bucket es público (getPublicUrl) → cualquier URL adivinable expone imágenes.

- Tipos TS Product/Variation duplicados en types.ts y catalog-table.tsx (interfaz local). VariantDraft en catalog-form.tsx tampoco extiende Variation. Drift garantizado.

- Inventory route (apps/web/app/dashboard/(products)/inventory/page.tsx) es solo redirect a /catalog. La UX 'inventario' real está embebida en ProductEditDrawer dentro del catalog → NO hay dashboard de inventario standalone (stock value, ABC analysis, slow-movers, near-expiry).

- Media route es file browser plano del bucket — no muestra qué archivos están vinculados a qué producto (esa info SÍ existe en gallery-picker-modal pero no en /media). Inconsistencia UI.

- VariantMatrixGenerator y InlineMatrixBuilder (catalog-form.tsx) duplican el cartesian product builder + suggestPrefix logic. Misma feature, dos implementaciones.

- No hay tests unitarios visibles para products router (validate.sh tests genérico). Sin coverage específica de bulk import, cascade delete, RLS bypass en server actions.

- Sin hooks/triggers que invaliden catalog_cache cuando se modifica el catálogo. orchestrator.py preload catalog en cada turn (cost), sin Redis/edge cache TTL configurable.

- Server actions en page.tsx no manejan errores — silenciosamente fallan si RLS bloquea o validation falla. UI no comunica al usuario.



---


## 3. Ventas (Contactos / Cotizador / Promociones / Reclamos / Pedidos)


**Prioridad finiquito**: `P0`  

**Esfuerzo estimado**: 7-10 días totales para llevar VENTAS a producción confiable:
• 0.5 día: Fix BUG#1 Cotizador (drop campos provider/rates_snapshot del insert OR add migration). DECISIÓN founder: ELIMINAR historial → 0.25 día (drop columnas + skip insert).
• 0.5 día: Fix BUG#2 Claims status mismatch (decidir canonical status set + DB CHECK + Pydantic Literal + UI sync).
• 2 días: Refactor Reclamos para superioridad (assignment, SLA tracking, timeline events, attachments, escalación Telegram > 24h). Diseño + migración + API endpoints + UI redesign.
• 1 día: Refactor Pedidos form manual (payment_method selector, payment_link toggle, address desde contact, generate-guide encadenado).
• 1 día: Resolver drift Contactos (server actions → fetch API + remover writes directos OR alinear shipping_phone en Pydantic).
• 1 día: Plumbing Cotizador (eliminar historial: drop columnas obsoletas + cron purge + remove insert path).
• 1 día: Promociones mejoras (combinables OR sistema básico campaign 'enviar cupón a top X').
• 1 día: QA UAT analítico + smoke tests + ajustes."


### Estado real (verificado en código)



═══════════════════════════════════════════════════════════════════════
[1] CONTACTOS — services/api/routers/contacts.py (804 líneas) + apps/web/app/dashboard/(sales)/contacts/ (3 server actions inline + ContactsManager)
─────────────────────────────────────────────────────────────────────────
Estado REAL: PARCIALMENTE FUNCIONAL CON DRIFT API↔UI severo.

• Backend router robusto: CRUD + consent (Ley 1581) + reactivate-consent + purge cascade + soft-delete + Habeas Data audit log + idempotency + RBAC + rate limit + role/owner gating + SAR (data_subject_request.py).
• UI funcional: alta/edición/eliminación + Habeas Data ledger + consent evidence upload (canal in_person → bucket privado consent-evidence) + SAR JSON/HTML export + reactivar consent (owner-only).
• DRIFT CRÍTICO: La UI (page.tsx server actions `addContact`/`editContact`) usa `sb.from('contacts').insert/update` DIRECTO, **bypaseando router** `POST /api/v1/contacts/`. Consecuencias:
  - NO se aplica idempotencia.
  - NO se ejecuta `@audit_log` decorator → no rastro en audit_log para create/edit (solo para reactivate y purge que sí van por API).
  - NO se valida server-side via Pydantic (validators duplicados en server action JS).
  - El router declara `shipping_phone` cero veces (Pydantic ContactCreate/Patch no lo conoce), pero la UI lo persiste; cualquier cliente API externo no puede setear `shipping_phone`. Asimetría silenciosa.
• Uso real fuentes:
  - Pedidos manuales (orders-new-form): selecciona contacto correctamente.
  - Wompi webhook + Aveonline: lee contacts(shipping_phone, phone, document_type/number, address) → OK.
  - Mercadeo/campañas/Templates Meta: NO USA contactos (no hay módulo campañas).
  - Cart/pasarela: cart-recovery por phone (purge necesita cascade — implementado vía endpoint purge).
• Bug runtime menor: en `record_consent` (línea 401-413), si el contact ya tenía `consent_evidence` con archivos adjuntos (attachment_path/mime), el endpoint los **sobreescribe** completamente con `{"captured_via", "conversation_id", "timestamp"}` perdiendo evidencia previa.

═══════════════════════════════════════════════════════════════════════
[2] COTIZADOR — services/api/routers/shipping.py (655 líneas) + apps/web/app/dashboard/(sales)/shipping/ (page + ShippingQuoteForm)
─────────────────────────────────────────────────────────────────────────
Estado REAL: PROBABLEMENTE ROTO EN PRODUCCIÓN (regresión rev. 109).

• Provider único activo: Aveonline (Envia eliminado, ADR-0019). Endpoint /quote → `_quote_via_aveonline` → AveonlineClient.
• Persistencia en tabla `shipments` para historial.
• **BUG CRÍTICO P0**: `shipping.py:315-323` hace insert con `provider="aveonline"` y `rates_snapshot=rates`. La tabla `shipments` (per schema canonical fixture `tests/fixtures/db_schema_canonical.json:1497-1620`) **NO tiene columnas `provider` ni `rates_snapshot`**. Migración `20260601120000_deprecate_envia_provider.sql` referencia `shipments.provider` en query de verificación pero **nunca ejecuta ALTER ADD COLUMN provider**. Ni rates_snapshot existe. La columna canónica para rates es `quote_response`. Probabilidad: 100% de los inserts fallan con 400 "column not found" tras pivote Envia→Aveonline. Bloquea historial Cotizador + impide consume_rate (necesita shipment_id).
• Historial: la página Cotizador hace `from('shipments').select(...)` lee correctamente (Supabase admite select de columnas existentes y rellena status como `'quoted'`). El historial estará vacío en producción si quote inserts fallan.
• Founder reporta querer ELIMINAR HISTORIAL — coherente con que (a) ya nadie consulta cotizaciones antiguas, (b) los inserts probablemente están fallando, (c) `purge_orphan_quotes` cron de 30 días existe pero igual genera ruido.
• Endpoint `/orphans` (purge huérfanos) existe pero NO se llama desde UI (sin botón ni cron job documentado).

COLUMNAS / TABLAS RECOMENDADAS A ELIMINAR (per requerimiento founder):
  - Tabla `shipments` debe SEPARAR: shipment real (orden confirmada con tracking) vs quote ephemeral.
  - Opciones:
    (A) ELIMINAR tabla `shipments` por completo — convertir Cotizador en "fire & forget" sin historial. Cotización entra al chat / panel, no se guarda.
    (B) Mantener `shipments` SOLO para rows con `tracking_number` (envíos reales post-Wompi/COD). Borrar todas las rows con `status='quoted'` y nunca persistir cotizaciones nuevas en /quote.
    (C) Drop columnas: `quote_response` JSONB (rates raw — solo útil para debug, no para UX), `selected_rate` JSONB (rara vez se confirma rate desde Cotizador — la mayoría va por wompi_webhook auto).
  - Mantener: shipments(id, tenant_id, order_id, status, carrier, service, tracking_number, tracking_url, label_url, pickup_id, estimated_delivery, last_polled_at, created_at, updated_at).
  - Eliminar: `quote_response`, `selected_rate`, `rates_snapshot`(no existe), `provider`(no existe), `envia_shipment_id`(drop pendiente migración 20260601120000 si no se aplicó), `origin_address`, `destination_address` (duplicación con order/contact.address), `parcels` (info ya está en order_items).

═══════════════════════════════════════════════════════════════════════
[3] PROMOCIONES — services/api/lib/coupons.py (628 líneas) + apps/web/app/dashboard/(sales)/promotions/ (page con server actions + PromotionsManager 670 líneas)
─────────────────────────────────────────────────────────────────────────
Estado REAL: FUNCIONAL Y BIEN INTEGRADO (uno de los módulos más sólidos).

• 3 tipos de descuento (percent/fixed_amount/free_shipping) ADR-0015.
• Helpers puros (validate_coupon_applicable + compute_discount) — testables sin DB.
• Apply/revoke/consume con UNIQUE constraint anti-duplicate + RPC coupon_increment_redemption atomic.
• Integración real con cart: orchestrator.py:7124 + dispatcher.py:984 invocan `apply_coupon` via NLU intent (cliente escribe "tengo el cupón XXX" → bot llama helper directo, NO tool registrado). Bien.
• Wompi webhook consume redemption (orders.py:560 `_consume_cart_reservations_if_any` → consume_redemption). Bien.
• UI Tenant Console: create/edit/toggle/delete con guard Habeas Data (no permite delete si tiene redemptions históricos). Bien.
• Mensajes user-friendly enriquecidos rev. 109 BUG 41 ("te faltan $X para activar el cupón"). Bien.
• Posible gap: cupones NO se ofrecen proactivamente al cliente — solo reactivo si menciona código. No hay "trigger marketing" tipo "envía cupón a los X últimos compradores".
• Limitación: NO COMBINABLES (P1, ADR-0015 D6). Si owner quiere "envío gratis + 10% off" no se puede.

═══════════════════════════════════════════════════════════════════════
[4] RECLAMOS — services/api/routers/claims.py (229 líneas) + apps/web/app/dashboard/(sales)/claims/ (page + actions.ts + ClaimsManager 367 líneas)
─────────────────────────────────────────────────────────────────────────
Estado REAL: MUY BÁSICO (confirma reporte founder).

• Backend mínimo: list + create + get + patch + resolve. NO hay assignment (no `assigned_to`), NO hay SLA (no `due_at`, no `priority`), NO hay escalación (no path a humano vía Telegram para claims), NO hay attachments, NO hay timeline/history de cambios.
• **BUG CRÍTICO P0 — MISMATCH STATUS API↔UI↔DB**:
  - DB (`supabase/migrations/20260413150000_claims.sql:9`): documentado `'open', 'investigating', 'resolved', 'rejected'` (sin CHECK constraint, free text).
  - API (`routers/claims.py:37` `VALID_STATUSES`): `{"open", "in_progress", "resolved", "closed", "cancelled"}` ← usa `in_progress`, `closed`, `cancelled`.
  - UI (`claims-manager.tsx:39-45` STATUS_MAP + botones): `'open', 'investigating', 'resolved', 'refunded', 'rejected'`.
  - **CONSECUENCIA**: Cuando el usuario aprieta "Investigando", "Reembolsar" o "Rechazar" → PATCH `/api/v1/claims/{id}` con status `'investigating'` / `'refunded'` / `'rejected'` → API responde **422 Status inválido**. Founder probablemente reporta que "los botones no hacen nada". Esto es la causa raíz del "muy básico". Es bug duro.
• Bot puede crear claim via `agentic/tools/claims.py` (CreateClaimTool + GetClaimStatusTool). Bien integrado con Telegram (severity='info'). Pero el bot escribe `status='open'` que está bien.
• REASON: API usa free-form con length validation, pero UI tiene su propio REASON_MAP `{'defective', 'wrong_item', 'delayed', 'missing_parts', 'other'}` — distintos de COMMON_REASONS de la API (`defective_product`, `wrong_item`, `missing_item`, `shipping_damage`, `delivery_delay`, `refund_request`, `warranty_claim`, `other`). El bot llena reason free-form (descripción cliente). Inconsistencia cosmética.
• Sin SLA: si un claim queda en `open` 7 días no hay alerta. Sin trigger DB de notif. Sin badge de "urgente" para tickets > X horas.

═══════════════════════════════════════════════════════════════════════
[5] PEDIDOS — services/api/routers/orders.py (849 líneas) + apps/web/app/dashboard/(sales)/orders/ (page + OrdersNewForm + OrdersManager)
─────────────────────────────────────────────────────────────────────────
Estado REAL: FUNCIONAL CORE + PARCIAL EN MANUALIDAD.

• CRUD completo + payment_link (Wompi) + generate-shipping-guide (Aveonline) + COD bypass (payment_method='cod' → confirmed immediate).
• Operador SÍ puede crear pedido manual:
  - UI: `orders-new-form.tsx` (NewOrderForm) — selecciona contacto, agrega ítems desde products (con variations), define precio/cantidad manual, shipping_cost manual, notas.
  - Backend: POST /api/v1/orders/ con idempotency + audit_log + plan gating.
  - Flujo Inbox: `order-mini-form.tsx` (otro form) crea con `auto_confirm=true` (confirma + decrementa stock inmediato).
• Integración cross-módulo:
  - Contacts: ✅ (contact_id opcional).
  - Products + variations: ✅ (consulta cost_price del backend, decrementa stock).
  - Cart conversacional: ✅ (consume reservations + emite cart_events `order_confirmed` / `coupon_consumed`).
  - Coupons: ✅ (consume_redemption via webhook OK).
  - Shipping: ✅ (generate-shipping-guide manual para COD, automático para Wompi).
  - Payment: ✅ (Wompi link gen + COD bypass).
  - MeLi: ✅ (sync_meli_stock async).
• GAPS en form manual:
  - NO permite seleccionar `payment_method` (credit/cod) — el form solo crea status pending. Para COD el operador NO tiene vía desde UI (solo via Inbox order-mini-form).
  - NO permite seleccionar `payment_link=true` — operador debe crear pedido y luego apretar otro botón payment-link.
  - NO genera link Wompi en línea — flujo es: crear pedido → ir a `/orders` → encontrar el pedido → ¿botón generate payment link? (no claro en orders-manager.tsx).
  - NO valida stock disponible antes de crear (puede ir a negativo, intencional pero sin warning UI).
  - NO permite aplicar cupón manualmente (cupones solo se aplican via chat WhatsApp).
  - NO selecciona address de envío del contacto — usa shipping_cost manual sin contexto.
• Reconfirmar: la confirmación manual del pedido (PATCH status=confirmed) NO genera guía Aveonline automáticamente — el operador debe luego apretar "Generar guía". Hay disonancia operativa.



### Bugs runtime (7)


- 🔴 **[CRITICAL]** shipping.py:315-323 inserta en tabla `shipments` columnas `provider` y `rates_snapshot` que NO existen en el schema canónico (tests/fixtures/db_schema_canonical.json:1497-1620 confirma columnas reales: id, tenant_id, order_id, status, carrier, service, origin_address, destination_address, parcels, quote_response, selected_rate, label_url, tracking_number, tracking_url, envia_shipment_id, pickup_id, estimated_delivery, created_at, updated_at, last_polled_at). Migración 20260601120000_deprecate_envia_provider.sql REFERENCIA `shipments.provider` en query de verificación pero NUNCA ejecuta ALTER ADD COLUMN provider ni rates_snapshot. Resultado: 100% de los inserts del Cotizador post-rev.109 fallan con 400 'column "provider" does not exist'. Historial Cotizador queda vacío en producción tras pivote Envia→Aveonline. Bloquea también confirmar_rate (necesita shipment_id retornado).

  - `services/api/routers/shipping.py:315-323`

- 🔴 **[CRITICAL]** MISMATCH STATUS RECLAMOS API↔UI: API define VALID_STATUSES={open,in_progress,resolved,closed,cancelled}. UI claims-manager.tsx:39-45 + botones envían {investigating,refunded,rejected}. PATCH /api/v1/claims/{id} con status='investigating' / 'refunded' / 'rejected' responde 422 'Status inválido'. Founder reporta 'reclamos muy básico' — causa raíz: los 3 botones del detalle (Investigando, Reembolsar, Rechazar) NO funcionan. Único status que actualiza OK es resolved vía /resolve. DB no tiene CHECK constraint así que si se hicieran direct writes pasarían, pero el flujo UI va por API.

  - `services/api/routers/claims.py:37 ↔ apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx:39-45,228,234,240`

- 🟠 **[HIGH]** Drift severo CONTACTOS API↔UI: Server actions addContact/editContact en apps/web/app/dashboard/(sales)/contacts/page.tsx:229,511 usan sb.from('contacts').insert/update DIRECTO bypaseando POST /api/v1/contacts/. Consecuencias: (a) decorator @audit_log no se ejecuta — audit_log table sin rastro de creates/edits desde UI; (b) no idempotency; (c) campo shipping_phone no existe en Pydantic ContactCreate/Patch del router pero sí en DB+UI — clientes API externos no pueden setearlo. Reactivate + delete (purge) sí pasan por API.

  - `apps/web/app/dashboard/(sales)/contacts/page.tsx:229,268,279,511 vs services/api/routers/contacts.py:55-110`

- 🟡 **[MEDIUM]** Endpoint /api/v1/contacts/{id}/consent SOBREESCRIBE consent_evidence completo en línea 408-412 sin preservar attachment_path/mime/size que pudieran existir de F10 (in_person). Si un contact tiene evidence con foto adjunta y luego se llama record_consent vía bot (whatsapp), la evidence se reemplaza por {captured_via, conversation_id, timestamp} perdiendo trazabilidad SIC del adjunto físico.

  - `services/api/routers/contacts.py:408-412`

- 🟡 **[MEDIUM]** orders-new-form.tsx no expone payment_method ni payment_link, así que el operador SOLO puede crear pedido en status='pending'. Para COD debe ir al Inbox (order-mini-form). Para link Wompi debe crear pedido y luego buscar UI separada. Backend soporta ambos campos perfectamente — gap es 100% UI.

  - `apps/web/app/dashboard/(sales)/orders/orders-new-form.tsx:125-148`

- ⚪ **[LOW]** shipping.py:651 purge_orphan_quotes elimina cotizaciones con status='quoted' y selected_rate NULL > 30 días. Endpoint expuesto pero NO se llama desde UI ni cron job. Acumulación silenciosa de basura en shipments (si el bug crítico #1 se soluciona). Recomendable convertir en cron.

  - `services/api/routers/shipping.py:631-655`

- ⚪ **[LOW]** Inconsistencia REASON en claims: COMMON_REASONS API={defective_product, wrong_item, missing_item, shipping_damage, delivery_delay, refund_request, warranty_claim, other}. UI REASON_MAP={defective, wrong_item, delayed, missing_parts, other}. Solo wrong_item y other coinciden. Bot escribe free-form. Reportes/analytics por reason son ruido.

  - `services/api/routers/claims.py:41-50 ↔ claims-manager.tsx:47-53`



### Fuentes de verdad (uso real)


- Contactos: fuente única `contacts` table — leída por orders/shipping/payments/wompi_webhook/aveonline/inbox/integrations (MeLi). Usada bien EXCEPTO el drift de escritura UI vs API.

- Products + variations: leída correctamente desde orders.py para cost_price lookup y stock decrement. cart, shipping, wompi flow usan también.

- Cart conversacional: orders.py consume_cart_reservations + cart_events emit. Bien sincronizado con coupons (consume_redemption) y stock_reservations.

- Courier (Aveonline post rev.109): integración consume contacts.shipping_phone, contacts.address, tenant.shipping_origin correctamente vía wompi_webhook + generate-shipping-guide endpoint. Cotizador (/quote) usa la misma client (AveonlineClient) pero PERSISTENCIA en shipments está rota (bug #1).

- Pagos (Wompi): consume contacts(document_type, document_number, name, phone, email) para customer_data prepopulado. orders.payment_method='credit' vs 'cod' diferencia bien.

- Promociones: leídas vía orchestrator NLU intent (apply/revoke). Cart materializa coupon_id/coupon_code/discount_cents. Wompi webhook consume redemption. Bien.

- KB (Knowledge Base): NO se cruza con módulo VENTAS directamente — opera en Inbox/orchestrator.

- Reclamos: lee orders + contacts via FK. Bot inserta via tool create_claim (escritura directa con tenant_scope). UI escritura vía actions.ts → API router (bien). Lectura UI page.tsx usa supabase directo con join — OK porque es read-only.



### Gaps funcionales (11)


- Cotizador: sin botón 'limpiar historial' para founder. Tampoco hay export del histórico ni link de cotización al cliente. Solo lista en UI.

- Promociones: cupones solo se ofrecen REACTIVAMENTE si cliente escribe código. No hay flujo 'enviar cupón a últimos X compradores' / 'reactivar carritos abandonados con cupón' / campañas push. Founder esperaría 'mercadeo'.

- Promociones: NO COMBINABLES (envío gratis + descuento %). ADR-0015 D6 lo marca P1 backlog.

- Reclamos: NO assignment (assigned_to / responsable). NO SLA tracking (due_at, priority, urgency badge). NO timeline/history de cambios de status. NO attachments (cliente no puede subir foto del producto dañado). NO escalación a Telegram cuando reclamo > 24h sin tocar. NO link automático Reclamo→Refund Wompi cuando status='refunded'.

- Reclamos: el bot tool create_claim notifica Telegram severity='info' al crearse, pero no hay re-notify si el ticket queda abierto > 24h. No hay tabla `claim_events` para audit cross-state.

- Pedidos: el form manual no soporta selección de address de envío del contacto (operador debe digitar shipping_cost manualmente sin contexto geográfico).

- Pedidos: no hay opción de aplicar cupón manualmente desde el form (cupones solo via chat).

- Pedidos: confirmar manualmente (PATCH status=confirmed) no dispara generate-shipping-guide automáticamente — operador debe apretar 2 botones secuenciales.

- Contactos: no hay integración con templates Meta para campañas masivas (módulo de mercadeo inexistente).

- Contactos: la búsqueda en lista_contacts:158-161 es client-side post-fetch — para tenants con > 200 contactos no encuentra resultados fuera del primer page de 200.

- Pedidos: no valida stock disponible antes de crear pedido manual (stock puede ir negativo silencioso — diseño explícito, pero sin warning visible al operador en el form).



### Gaps técnicos (12)


- Drift estructural CONTACTOS: dos paths de escritura concurrentes (UI direct vs API router). El router tiene idempotency + audit + validation; la UI no. Solución: refactor server actions para llamar fetch al API router (igual que claims/actions.ts lo hace bien).

- Cotizador: tabla `shipments` mezcla 3 conceptos (quote ephemeral, label fijo, tracking live). Founder pide eliminar historial → separar en: (a) drop quote_response, selected_rate, rates_snapshot, provider columns; (b) eliminar todas las rows status='quoted' viejas; (c) mantener shipments solo para envíos con tracking_number; (d) considerar tabla separada `shipment_tracking_events` (ya existe migración 20260529000000) para historial polling.

- Cotizador: route `_quote_via_aveonline` retorna response_body con shipment_id=NULL si el insert falla (línea 314-329 captura excepción y solo logea warning) — el frontend muestra cotización pero el botón 'Confirmar tarifa' luego falla porque shipment_id es NULL.

- Reclamos router: 229 líneas, simple, sin endpoints para timeline/comments/attachments. No tiene tabla complementaria `claim_events` ni `claim_messages`. Para superioridad funcional necesita rediseño schema, no parche.

- Coupons engine: bien estructurado — pure functions separadas de DB ops. Pero `consume_redemption` tiene fallback con read-then-update no atómico (líneas 570-598) si RPC `coupon_increment_redemption` no existe; race condition posible si dos webhooks llegan concurrentes para el mismo cupón. Verificar que el RPC esté creado en producción.

- Pedidos router orders.py: 849 líneas en un solo archivo. Mezcla CRUD + payment_link + generate_shipping_guide + stock helpers (_decrement_stock_on_confirm, _consume_cart_reservations_if_any). Falla single-responsibility. Sugerencia: extraer `lib/order_stock.py` y `lib/order_actions.py`.

- Pedidos: import circular evitado via from-inside-function (`from routers.wompi_webhook import _generate_shipping_guide_async` línea 783). Es síntoma de que estos helpers deberían estar en `lib/` no en routers.

- Pedidos status string sin Enum: VALID_STATUSES como set literal en línea 36 (orders.py) sin DB CHECK constraint ni Pydantic Literal. Cualquier valor inválido viaja hasta el insert.

- Claims status mismatch causado por 3 fuentes de verdad sin sync: schema SQL comment (sin CHECK), API VALID_STATUSES, UI STATUS_MAP. Necesita CHECK constraint en DB + Literal en Pydantic + share constants UI↔API (vía endpoint /meta o codegen).

- Promotions page.tsx hace doble query: coupons select + coupon_redemptions select luego agrupa client-side (línea 343-354). Para tenants con cientos de cupones está bien (1 query batch), pero el contador `total_historical_redemptions` corre sobre la query separada — no respeta el ordenamiento. Cosmético.

- Contactos: regex E-mail simplificada en Pydantic (línea 65) NO acepta TLDs largos comunes (.museum, .travel) — limitada a [A-Za-z]{2,}. Para SaaS internacional puede rechazar emails legítimos. Cosmético.

- Shipping `_get_active_shipping_provider`: hace try/except amplio (línea 159-173) que default a 'aveonline' incluso si la consulta falla por error de red real. Si en el futuro hay multi-provider este patrón es problemático.



---


## 4. Compras (Suppliers + POs + WAC)


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: P0 hardening crítico (atomicidad transaccional via RPC Postgres + null-guards UI + tests del router con WAC) = 2-3 días. P1 producción mínima (vínculo product↔preferred_supplier + dashboard básico de compras [spend por mes/proveedor, top suppliers, OCs pendientes] + EDIT/DELETE proveedor + recepción parcial + filtros/paginación + factura externa + IVA/retención) = 8-12 días. P2 visión completa (alertas reorder con workflow → sugerencias auto-PO + aprobaciones por monto + landed cost + multi-moneda + attachments + export PDF/CSV + cuentas por pagar + histórico de costos por SKU + dossier WAC vs FIFO + integración con Inbox para que bot avise low-stock al owner) = 18-25 días. Total finiquito producción robusta: ~4-5 semanas-persona.


### Estado real (verificado en código)


EXISTE pero es MVP esquelético — confirmado por código, no por docs. Stack real:

DB (`supabase/migrations/20260413000000_purchases_and_finance.sql` + `20260413000001_finance_polish.sql`):
- `suppliers` (id, tenant_id, name, contact_email, phone, lead_time_days, created_at/updated_at) — 6 campos básicos
- `purchase_orders` (id, tenant_id, supplier_id, status, expected_date, total_amount, timestamps) — CHECK status IN draft|ordered|in_transit|received|cancelled
- `purchase_order_items` (id, tenant_id, po_id, variation_id, quantity, unit_cost)
- `expenses` (tabla aparte, OPEX) — categoría enum fija
- ALTER en `product_variations.cost_price` y `order_items.unit_cost` ya aplicados
- RLS habilitado en las 4 tablas, FKs con ON DELETE SET NULL en supplier_id/variation_id (preserva histórico financiero)

API (`services/api/routers/purchases.py`, 336 líneas, 6 endpoints):
- GET/POST suppliers
- GET/POST/GET-id purchase_orders
- POST cancel + POST receive (con WAC determinístico server-side y guard de idempotencia status='ordered')
- WAC ((max(0, old_stock) * old_cost) + (po_qty * po_cost)) / (max(0, old_stock) + po_qty)
- Al recibir: incrementa stock, recalcula cost_price (WAC), inserta stock_movement con reason='purchase_restock'
- Audit log decorator aplicado en mutations
- RBAC: require_write_role en owner/manager

Frontend (`apps/web/app/dashboard/purchases/`, 520 líneas total):
- 1 página con Tabs (Órdenes + Proveedores)
- Crear OC con items (variation picker, qty, cost), recibir/cancelar
- Sin filtros server-side, sin búsqueda, sin paginación (todo en memoria)
- Visible en sidebar solo para role='owner' (no manager)

Lo que SÍ funciona end-to-end:
- Crear proveedor, crear OC con items, recibir → suma stock + recalcula WAC
- COGS se conecta automáticamente al pipeline financiero: orders.py al crear pedido busca `cost_price` y lo persiste en `order_items.unit_cost` → finance/page.tsx lo lee para "Costo Mercancía (COGS)"
- Cadena costo → margen real está cerrada técnicamente

Lo que NO existe (founder tiene razón: "muy básico"):
- 0 estadísticas, 0 dashboards de compras (no top suppliers, no rotación, no días-de-cobertura, no spend-by-category, no compras por mes)
- 0 reportes / export
- 0 alertas reorder / minimum_stock per variation
- 0 vínculo product↔preferred_supplier (no se sabe a quién comprarle cada SKU)
- 0 multi-moneda (numeric implícito = pesos sin metadato)
- 0 estado intermedio: el código permite 'draft' e 'in_transit' en CHECK pero el router no los expone (crea directo en 'ordered')
- 0 attachments (factura PDF, recibo del proveedor)
- 0 tests unit/integration del router (solo coherence_pact.py valida que campos Pydantic existan en DB)
- Modelo `suppliers` no tiene: NIT/tax_id, dirección, ciudad, contacto principal por nombre, métodos de pago, payment_terms (días de crédito), currency, notes


### Bugs runtime (8)


- 🟠 **[HIGH]** POST /receive ejecuta múltiples UPDATEs (PO status + N x variations + N x stock_movements inserts) SIN transacción atómica. Si falla a mitad de loop, stock queda parcialmente actualizado y PO marcado received → inventario inconsistente con stock_movements. Sin reintento idempotente.

  - `services/api/routers/purchases.py:264-336`

- 🟠 **[HIGH]** POST / (crear PO) inserta `purchase_orders` y luego `purchase_order_items` en operaciones separadas no atómicas. Si el insert de items falla, queda PO huérfana con total_amount=N pero sin items (cancel/receive responderán 404 'OC sin items').

  - `services/api/routers/purchases.py:189-207`

- 🟡 **[MEDIUM]** El loop por item en receive() hace 3 round-trips a Supabase por item (SELECT variation + UPDATE variation + INSERT stock_movement). Para OC con 50 items = 150 calls. Sin batch ni paralelismo → timeout en POs grandes.

  - `services/api/routers/purchases.py:302-334`

- 🟠 **[HIGH]** WAC asume el variation existe; si la variation fue borrada después de crear la OC (ON DELETE SET NULL en purchase_order_items.variation_id), el item queda con variation_id=NULL y el endpoint receive lo skipea con warning, pero el stock NUNCA se incrementa y el operador no recibe alerta clara → mercancía recibida físicamente queda fuera del sistema.

  - `services/api/routers/purchases.py:311-313 + supabase/migrations/20260413000001_finance_polish.sql:14-22`

- ⚪ **[LOW]** Frontend renderiza `o.total_amount.toLocaleString()` y `i.unit_cost.toLocaleString()` sin null-guards; si DB devuelve null (columna nullable con default), explota cliente con TypeError. Histórico permite valores 0 pero un PO creado con expected_date=NULL OK; total_amount tiene DEFAULT 0 → menos riesgo pero unit_cost en pos histórico recibido podría no existir.

  - `apps/web/app/dashboard/purchases/_components/purchase-orders-manager.tsx:158,166`

- 🟡 **[MEDIUM]** Validación phone en SupplierCreate exige exactamente 10 dígitos (`^[0-9]{10}$`). Bloquea NITs colombianos (8-10 dígitos + DV) y números internacionales (+57...). Operadores reales no podrán registrar muchos proveedores legítimos.

  - `services/api/routers/purchases.py:49`

- 🟡 **[MEDIUM]** GET /purchases/ no soporta filtro por fechas, búsqueda por nombre de proveedor, ni paginación cursor — limit=200 hard cap. Tenant con >200 POs verá histórico truncado en UI silenciosamente.

  - `services/api/routers/purchases.py:151-170`

- ⚪ **[LOW]** PurchaseOrderCreate acepta `expected_date: Optional[str]` sin validación de formato ISO 8601 ni rango (puede ser fecha pasada, string arbitrario). Backend pasa el string crudo a Postgres timestamptz — depende del parser de Postgres aceptarlo o rechazar con 500.

  - `services/api/routers/purchases.py:62, 193`



### Fuentes de verdad (uso real)


- product_variations.cost_price — actualizado vía WAC al recibir PO. Usado por orders.py (snapshot a order_items.unit_cost en venta) y por finance/page.tsx (COGS). ✅ Conectado correctamente.

- order_items.unit_cost — snapshot del cost_price al momento de la venta. Lo lee finance-dashboard.tsx para calcular gross margin. ✅ Conectado.

- stock_movements — recibe inserción con reason='purchase_restock' al hacer receive. ✅ Trazable.

- suppliers, purchase_orders, purchase_order_items — RLS activo, FKs con SET NULL preservan histórico. ✅ Integridad multi-tenant correcta.

- expenses — tabla independiente; finance-dashboard.tsx la usa para OPEX. NO está vinculada a purchase_orders (un PO recibido NO crea automáticamente un expense de tipo logistics/inventario) — depende del founder si quiere ese link contable.

- El módulo Compras NO se consume desde Inbox/Orchestrator (el bot WhatsApp no pregunta sobre POs ni recomienda reorders). Es módulo puramente back-office.



### Gaps funcionales (17)


- NO existe dashboard de estadísticas de compras (gasto mensual por proveedor, top 5 proveedores por monto, # POs activas, lead time promedio real vs declarado).

- NO existe vínculo producto↔proveedor preferente. Para cada variation no se sabe a quién recomprarle ni el último costo conocido por proveedor (solo el WAC global).

- NO existe alerta de bajo stock con sugerencia de reorder cuando un SKU baja del threshold (low_stock_threshold existe a nivel tenant pero no genera workflow hacia compras).

- NO existe vista 'Productos que necesito comprar' (cruzar stock_quantity < threshold con preferred_supplier).

- NO hay reporting/export (CSV/PDF) de POs ni de compras del periodo.

- NO hay registro de factura/recibo del proveedor (attachments), ni número de factura externo, ni impuestos (IVA / retención en la fuente — crítico en Colombia para conciliación contable).

- NO hay manejo de cuentas por pagar: no se sabe qué POs están pagadas/pendientes, ni vencimientos según payment_terms.

- NO hay estados intermedios usables: el schema permite 'draft' e 'in_transit' pero el router nunca los emite (crea directo 'ordered'). Operador no puede borradores ni marcar 'en tránsito' al confirmar guía del proveedor.

- NO hay recepción parcial: receive marca TODOS los items como recibidos. Si un item llega corto/dañado, no hay forma de reflejarlo (queda discrepancia entre PO y stock real).

- NO hay devoluciones a proveedor (return-to-vendor) que afecten WAC y reduzcan stock.

- NO hay multi-moneda (USD/CNY para importaciones), ni tipo de cambio histórico.

- NO hay cálculo de landed cost (flete + aduana + impuestos importación distribuidos sobre items).

- NO hay margen real visible por producto (precio venta − WAC) en UI; el dato existe pero no se muestra en catálogo ni en compras.

- NO hay histórico de costos por SKU (sólo el WAC actual, no la evolución) — imposible auditar inflación de proveedor.

- NO hay categorización de compras (insumos, reventa, activos) para reporting tributario.

- NO hay aprobaciones (workflow): cualquier owner/manager crea PO sin límite ni revisión, aunque sea de $50M.

- Modelo supplier sin: NIT/tax_id, dirección, ciudad/país, contacto-persona, banco/cuenta para transferencias, payment_terms (días de crédito), currency default, notas internas, status activo/inactivo.



### Gaps técnicos (17)


- receive_purchase_order tiene riesgo de consistencia: cambios multi-tabla NO transaccionales (supabase-py no expone txn). Si falla mid-loop deja DB inconsistente.

- create_purchase_order también no-transaccional (PO insertada antes que items; insert items puede fallar → PO huérfana).

- 0 tests unit/integration para purchases.py — el archivo tiene 336 líneas de lógica de negocio (WAC, idempotencia, RBAC) sin cobertura. Sólo test_coherence_pact.py valida que campos Pydantic existan como columnas.

- WAC calculado fila por fila en Python con N+1 queries (1 SELECT + 1 UPDATE + 1 INSERT por item). Debería ser un RPC Postgres con un solo round-trip o batch RPC.

- page.tsx (RSC) consulta DB directo con Supabase server-side para listar POs y productos — bypasea el router /api/v1/purchases (que sí tiene RBAC + audit). Solo las MUTATIONS van por router (vía actions.ts). Las LECTURAS no auditadas ni metricadas.

- purchase-orders-manager.tsx usa `any[]` en todas las props (orders/suppliers/products) — sin tipos TypeScript reales, frágil ante cambios de esquema.

- purchases-client.tsx también `any[]` en props.

- Frontend no maneja estados de error de las server actions (solo console.error). Usuario no recibe feedback en UI si createPurchaseOrder/receive falla.

- Frontend mantiene `addItem` permitiendo añadir la MISMA variation varias veces como filas separadas — no deduplica ni suma. Confunde al operador.

- Sin paginación: si tenant tiene 500 POs, la página intenta renderizar todos en una lista lineal (DOM blow-up + render lento).

- Sin búsqueda/filtros en UI (por proveedor, por estado, por rango de fechas).

- Componente suppliers-manager solo CREATE, sin EDIT ni DELETE (no se puede actualizar lead_time si cambia, no se puede desactivar un proveedor).

- Componente purchase-orders-manager solo CREATE/cancel/receive — no se puede EDITAR una OC en estado 'ordered' (ej. corregir cantidad antes de recibir).

- actions.ts duplica patrón apiFetch+getToken igual que otros módulos sin reusar helper común — deuda menor.

- VALID_PO_STATUSES en router es {'ordered','received','cancelled'} pero el CHECK de DB permite también 'draft' e 'in_transit' — desincronización que esconde features schema-listas pero no expuestas.

- No hay ADR ni dossier propio para Compras — falta documentar política WAC vs FIFO/LIFO, política de recepción parcial futura, política contable.

- Migración purchases solo tiene índice PK; falta índice en (tenant_id, status), (tenant_id, supplier_id), (tenant_id, created_at desc) — queries de listing harán seq scan cuando crezca.



---


## 5. Canales (WhatsApp / MeLi / Telegram + Channel Registry)


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: ~14-18 días dev productivos. Desglose: (1) MeLi Q&A topic + handler + POST /answers + KB-grounded LLM reply = 3d. (2) MeLi Messages topic + handler + send_meli_message helper + persist en messages con channel='meli' = 3d. (3) MeLi Order Acknowledgment (feedback + shipments/handle) = 1d. (4) Schema multi-canal real: orders.external_order_id + messages.external_message_id + messages.channel + contact_identities (provider, external_id) + index migrations + backfill = 2d. (5) conversations.channel set por connector-whatsapp + meli inserts + filtro Inbox UI = 1d. (6) Channel Registry activación real: portar whatsapp_sender → WhatsAppAdapter + actualizar _send_outbound_text para usar get_channel_adapter() + meli adapter (parse_inbound/send_outbound stub→real) = 2d. (7) webhook_framework adoption: migrar 1 router pilot (meli) a F.1 (signature/dedup/rate-limit shared) = 1d. (8) Cross-channel contact unification (merge por phone + email + document) = 2d. (9) Inbox UI: channel badge + filter + canonical formatter por canal = 1d. (10) Tests cross-canal + observability tags = 1d. Items P0/P1 si CC quiere centralización REAL: (1)-(5). Items P2 hardening: (6)-(10). Total estimado: 14d para "MeLi production-grade + centralización", 18d incluyendo hardening completo Channel Registry para Messenger/Instagram futuro.


### Estado real (verificado en código)


El módulo CANALES está fragmentado y NO unificado. Hay 3 canales con niveles de madurez muy distintos: (1) WhatsApp Cloud API — production-grade, único canal con loop conversacional completo (inbound → orchestrator LLM → outbound), con HMAC verify, multi-tenant via meta_waba_id + phone_number_id, dedup, template events handler. (2) MercadoLibre — solo backend webhook IPN inbound: 3 topics (orders_v2, items, shipments). Q&A NO implementado. Mensajería NO implementada. Order ack NO implementado. NO escribe en messages/conversations — solo en orders/marketplace_listings/order_tracking. Es 100% one-way data sync, no es canal conversacional. (3) Telegram — solo OPERADORES (no clientes). 2 comandos básicos (/resolver, /estado) sin interactividad real. NO es canal de venta. Channel Registry (`lib/channels/base.py` + `__init__.py`) existe como SKELETON SOLO STUBS: ningún adapter real registrado, ningún caller lo invoca. La migración `conversations.channel TEXT DEFAULT 'whatsapp'` existe (20260609000000) pero NO es seteada por connector-whatsapp ni meli_webhook al insertar — todas las rows tienen el default. La UI de Inbox NO selecciona ni filtra por `channel`. Cero centralización cross-channel: un cliente en WhatsApp y el mismo cliente en MeLi son contactos separados (MeLi busca por phone, WhatsApp por phone, pero no hay merge ni linking explícito). `webhook_framework` (F.1) existe pero NINGÚN webhook lo usa. Centralización founder solicita: NO existe. Valor agregado MeLi solicitado: tarea entera pendiente (dossier H.5 listo, sin código).


### Bugs runtime (13)


- 🟠 **[HIGH]** conversations.channel siempre queda en default 'whatsapp' — connector-whatsapp/services/db_persistence.py::_upsert_conversation NO setea channel='whatsapp' explícito en insert; meli_webhook nunca inserta conversations (solo orders). Resultado: el campo es inútil para distinguir origen real, todas las conversaciones se ven como WhatsApp aunque vinieran de otro canal en futuro. Channel Registry y filtros multi-canal Inbox no funcionan.

  - `services/connector-whatsapp/services/db_persistence.py:154-164 (insert sin channel); supabase/migrations/20260609000000_conversations_channel.sql (columna creada pero huérfana)`

- 🟠 **[HIGH]** MeLi webhook NO acknowledge a MeLi al confirmar/procesar orden. Solo persiste localmente y decrementa stock. MeLi exige feedback de manejo (handling) y rating de servicio influye en Mercado Líder; sin ack el seller score se afecta. Plan H.5.3 listado pero no implementado.

  - `services/api/routers/meli_webhook.py:491-568 (_process_order — sin POST a /orders/{id}/feedback ni /orders/{id}/shipments/handle)`

- 🟠 **[HIGH]** MeLi Q&A (preguntas pre-venta) NO implementado — topic 'questions' no suscrito en webhook handler. El dossier H.5.1 lo identifica como 'pieza de mayor ROI'. Tenants con presencia MeLi pierden Mercado Líder por no responder en <8h. ai-orchestrator + KB ya existen, sólo falta el plumbing.

  - `services/api/routers/meli_webhook.py:686-706 (_process_notification: solo orders_v2/items/shipments, sin 'questions' branch); integrations/meli_client.py (sin POST /answers helper)`

- 🟠 **[HIGH]** MeLi messages topic (post-venta — chat con comprador) NO implementado. Cliente MeLi escribe al seller via MeLi Messages y nunca llega al Inbox de Konvi. Conversación queda invisible para el bot. Dossier H.5.2 documenta endpoint /messages/orders/{order_id} disponible.

  - `services/api/routers/meli_webhook.py (sin _process_messages handler); services/api/integrations/meli_client.py (sin send_meli_message helper)`

- 🟠 **[HIGH]** Cross-channel customer unification NO existe: si el mismo cliente compra en MeLi y luego escribe al WhatsApp del tenant, son contactos separados — diferentes contact_id, no se enlaza histórico de compras MeLi → contexto WhatsApp. _upsert_meli_contact busca por phone y _upsert_conversation por phone, pero MeLi sólo entrega phone si seller tiene billing_info verificado (raro). En la práctica el cliente vive duplicado.

  - `services/api/routers/meli_webhook.py:379-488 (_upsert_meli_contact aislado, sin merge con WA); services/connector-whatsapp/services/db_persistence.py:66-165 (find por phone, sin lookup cross-channel)`

- 🟠 **[HIGH]** ChannelAdapter Protocol + registry son DEAD CODE — solo stubs registrados (_StubAdapter para whatsapp/meli/telegram/web/messenger/instagram/sms). Ningún caller usa get_channel_adapter(). Orchestrator usa directamente whatsapp_sender.send_whatsapp_message sin pasar por registry. Si añade Messenger/Instagram hoy, hay que cablear todo a mano otra vez.

  - `services/api/lib/channels/__init__.py:130-135 (stub_adapter registrations); services/ai-orchestrator/orchestrator.py:15,2155,6984,7179 (import directo de whatsapp_sender)`

- 🟡 **[MEDIUM]** Telegram webhook tiene fallback 'primer tenant activo' legacy que sigue activo cuando identity_registry no tiene chat_id. Causa cross-talk silencioso entre 2+ tenants con Telegram. Comentado para remover post-backfill pero el backfill nunca se documentó ni ejecutó.

  - `services/api/routers/telegram_webhook.py:199-214 (fallback 'primer tenant activo' explícito)`

- 🟡 **[MEDIUM]** MeLi webhook dedup distribuido cae a in-memory si RPC falla — cross-réplica race condition en Render Starter+ con 2+ réplicas: misma webhook procesada N veces (decremento stock duplicado, ack duplicado). Falla silenciosa via warning log.

  - `services/api/routers/meli_webhook.py:126-157 (_is_duplicate_event fallback local)`

- 🟡 **[MEDIUM]** MeLi IPs hardcoded como default (4 IPs) — si MeLi actualiza IPs, TODOS los webhooks rechazados 403 silenciosamente; alerta requiere ≥5 rechazos/300s desde misma IP para emitir warn. En low-traffic tenants nunca dispara — sólo log info en RPC.

  - `services/api/routers/meli_webhook.py:78-83 (_MELI_DEFAULT_NOTIFICATION_IPS), 166-199 (_check_meli_origin_alert threshold)`

- 🟡 **[MEDIUM]** MeLi order lookup en _process_shipment busca orden por substring de notes ('MeLi order #X') usando .like — frágil si notes son editados manualmente por operador. No hay campo dedicado tipo external_order_id en orders. Posible orden huérfana.

  - `services/api/routers/meli_webhook.py:594-603 (.like notes_prefix)`

- 🟡 **[MEDIUM]** WhatsApp tenant lookup duplica lógica: db_persistence.py usa tenants.meta_waba_id, dependencies/meta.py usa tenant_integrations.credentials.phone_number_id. Si un tenant tiene WABA en tenants pero status='disconnected' en tenant_integrations, el connector persiste mensajes pero el orchestrator no puede responder (credenciales no resolvibles). Esquema inconsistente.

  - `services/connector-whatsapp/services/db_persistence.py:26-49 (tenants.meta_waba_id); services/connector-whatsapp/dependencies/meta.py:144-165 (tenant_integrations.credentials.phone_number_id)`

- ⚪ **[LOW]** MeLi webhook puede retornar 500 al persistir tracking si shipment_id no existe en notes pero estimated_delivery_final.date no parseable — try/except amplio engulle errores y solo logea warning. Tracking puede quedar inconsistente sin que tenant vea nada.

  - `services/api/routers/meli_webhook.py:630-669 (catch all en tracking persistence)`

- ⚪ **[LOW]** Telegram bot solo expone 2 comandos (/resolver, /estado). Founder ya posee Channel Registry concept pero Telegram nunca evolucionó a real-time chat operadores ↔ bot (notificaciones unidireccionales). Comando /inbox, /ventas-hoy, /escalaciones-pendientes serían triviales y valiosos.

  - `services/api/routers/telegram_webhook.py:77-94 (_handle_command — solo 3 comandos: resolver/estado/ayuda)`



### Fuentes de verdad (uso real)


- Inbox NO se audita aquí (módulo distinto) — pero canales lo alimentan: connector-whatsapp persiste messages + conversations correctamente con tenant_id. MeLi NO escribe en messages/conversations (gap). Telegram NO escribe en messages/conversations (es solo operadores).

- Contactos: WA crea contact por phone en orchestrator (consent_channel='whatsapp'); MeLi crea contact por phone via _upsert_meli_contact (consent_channel='marketplace_meli'). Si phone es el mismo entre los 2 canales y formato canónico es idéntico (rev. 104 F0-4 unificó digits-only), el upsert con on_conflict=(tenant_id,phone) merge CORRECTAMENTE — pero solo SI MeLi entrega phone (raro: requiere seller con billing_info habilitado). En la práctica MeLi orders sin phone NO crean contact → 0 cross-merge.

- Productos: marketplace_listings vincula product_variations ↔ MeLi external_id correctamente. Stock decrement en MeLi order webhook usa la vinculación. sync_meli_stock empuja Supabase → MeLi vía PUT. Esto SI funciona — pero unidireccional (Konvi es source of truth, MeLi es channel). NO existe Catálogo Konvi → WhatsApp Commerce Catalog sync (paralelo P2 fase futura).

- Carts: conversation_carts es WA-only (no se crean desde MeLi orders). MeLi orders crean orders directo. Si tenant quiere flow unificado 'cliente MeLi pregunta Q&A → conversación con bot → checkout fuera de MeLi', no es posible.

- Couriers: Aveonline funciona independiente del canal (es shipping, no channel). Pero MeLi tiene su propio Mercado Envíos — actualmente NO se separa: order de MeLi se trata como cualquier otra orden Konvi (Aveonline se le asigna). Esto es BUG potencial — order MeLi NO debería ser shipped via Aveonline (cliente espera Mercado Envíos por contrato MeLi).

- Pagos: Wompi funciona en WA flow. MeLi orders ya vienen pagadas dentro de MeLi — NO se enrutan a Wompi. Coherente con el modelo MeLi.

- KB (knowledge_base): el LLM accede al mismo KB del tenant independiente del canal — esto SI escalaría bien a MeLi Q&A cuando se implemente (KB ya está disponible).



### Gaps funcionales (14)


- Centralización cross-channel inexistente — un cliente que compra MeLi + escribe WA aparece como 2 contactos distintos (sin merge por email o documento). Founder pidió 'centralizar' pero schema no tiene contact_identities (provider, external_id) → contact_id 1:N.

- Sin Inbox multi-canal — Inbox UI implícitamente WhatsApp-only: query selecciona solo customer_phone, no channel; conversation-list muestra phone sin badge de canal. Hoy no se diferencia visualmente un mensaje WA de uno hipotético MeLi/Telegram cliente.

- MeLi Q&A (preguntas pre-venta) — NO implementado. Highest-ROI feature según dossier (sec 2.1). Suscripción de topic 'questions' + handler que invoque ai-orchestrator + POST /answers es feasible en ≈3 días (LLM + KB ya existen).

- MeLi Messages post-venta — NO implementado. Cliente MeLi escribe al seller, llega a inbox MeLi nativo (no Konvi), bot no responde, seller score baja.

- MeLi Order Acknowledgment — Konvi confirma orden internamente pero no avisa a MeLi /orders/{id}/feedback ni /shipments/handle. Afecta Mercado Líder.

- Catálogo MeLi management básico — UI marketplace permite link/unlink/import/pause/sync-stock pero falta: bulk pricing rules per canal (MeLi suele requerir +X% por comisión MeLi), publicación nueva desde Konvi (hoy solo vincular existente), edición catálogo MeLi (atributos, fotos) desde UI Konvi.

- Sin canal cliente Telegram público — Telegram solo notifica operadores. Tenants con presencia bot Telegram público (común en CO/AR/MX para nicho) no pueden usar Konvi.

- Sin canales planeados implementados (Messenger, Instagram, TikTok Shop) — Channel Registry skeleton existe pero ningún adapter real. ROI inmediato bajo (founder prioriza WA + MeLi) pero infra para soportarlos NO se construyó (registry sin uso real).

- Sin Storefront web chat — stub 'web' registrado en registry pero sin connector. Plan I.1 difiere UI pero arquitectura backend (channel='web' + adapter) tampoco está.

- WhatsApp UI test no valida send real — sólo hace GET /v22.0/{phoneId} para verificar token (lectura). No envía mensaje de prueba al operador para validar end-to-end.

- No hay panel unificado 'CRM-like' para ver toda interacción cross-canal de un cliente — el Inbox actual es lista de conversaciones WA, no perfil cliente con timeline (compra MeLi #1 → pregunta MeLi #2 → orden WA #3).

- No hay channel preferences per-tenant — si tenant solo vende MeLi (no WA), Konvi no tiene flag activo/inactivo por canal explícito. Estado se infiere de tenant_integrations.status.

- Sin métricas channel-level — analytics no segmenta por canal de origen (cuántas ventas MeLi vs WA, AOV por canal, tiempo respuesta Q&A MeLi vs DM WA).

- Telegram no permite que el cliente (no operador) chatee con el bot. Para canal cliente bidireccional Telegram (público) falta: registro bot tenant, identity_registry chat_id ↔ tenant, handler de mensajes ≠ comandos /, persist en messages + channel='telegram'.



### Gaps técnicos (15)


- Channel Registry (lib/channels) es DEAD SKELETON — Protocol + base.py + __init__.py escritos como infra futura pero zero callers. orchestrator.py importa whatsapp_sender directo (línea 15). Migrar a registry sin breaks requiere refactor de _send_outbound_text + 8+ callsites.

- webhook_framework (F.1) sin consumidores — meli_webhook, telegram_webhook, aveonline_webhook, wompi_webhook, connector-whatsapp/dependencies/meta.py duplican signature verify + dedup + rate-limit ad-hoc. F.1 fue construido (lib/webhook_framework/{base,signature,idempotency,rate_limit}.py) pero ningún router lo extiende. Deuda técnica: 5 implementaciones distintas del mismo patrón.

- Lógica tenant resolution por canal duplicada en 3 lugares con esquemas distintos: tenants.meta_waba_id (WA); tenant_integrations.credentials.phone_number_id (WA forensics); tenant_integrations.meta.user_id (MeLi); tenant_provider_identity (Telegram + roadmap genérico). identity_registry está OK pero connector-whatsapp y meli_webhook NO la usan — quedaron en el patrón viejo.

- connector-whatsapp es servicio Render separado (rootDir distinto) — duplica `lib/phone.py` desde api/ (no shared package). Cada refactor debe replicarse manualmente. Misma deuda en deploy independiente complica cambios cross-service.

- meli_webhook.py monolítico (745 líneas) mezcla: HTTP dependency (verify origin + rate limit + dedup), business logic (process_order, process_shipment, process_item), DB upsert (_upsert_meli_contact), helpers (_resolve_variation_ids, _decrement_stock_for_meli_order). Refactor mínimo: separar a meli/{router, processors, contact, stock}.py.

- integrations.py (1062 líneas) mezcla OAuth MeLi callback, Aveonline carriers/agents/dry-run/webhook, settings UI server actions. Falta partition meli.py vs aveonline.py — son providers distintos sin relación.

- telegram_webhook.py tiene fallback 'primer tenant activo' (línea 199-214) marcado como legacy pre-backfill — bug arquitectónico documentado sin fecha de fix; identity_registry existe pero el migration backfill chat_id → tenant nunca se aplicó.

- MeLi orders lookup por substring en notes (.like 'MeLi order #X%') — falta columna orders.external_order_id + index. Cambio de schema simple bloqueado por falta de owner.

- db_persistence (WA) hardcoded para WhatsApp — el find-or-create de conversation usa customer_phone como única identidad. Si quisieras añadir Telegram cliente, customer_phone no aplica (chat_id es int). Modelo de identidad debe ser (channel, external_id) no customer_phone solo.

- messages table tiene meta_message_id (Meta-specific) — para MeLi/Telegram/web hace falta external_message_id genérico + provider column. Schema no soporta multi-canal correctamente.

- Stub adapters en _StubAdapter retornan compliance_check=False (default-deny) lo cual es correcto pero NO se llaman desde ningún sitio → la garantía es teórica.

- Sin observabilidad channel-aware: logs no taggean channel, sentry tags no incluyen canal — debugging cross-canal opaco.

- Dashboard integrations UI (integrations-manager.tsx) tiene 5 cards hardcoded (whatsapp, aveonline, mercadolibre, wompi, telegram) + COMING_SOON estático. No data-driven sobre Channel Registry — añadir Messenger requiere editar UI manual además del adapter.

- Inbox conversation-list.tsx asume WhatsApp implícitamente — usa formatPhone(customer_phone) sin pre-validar canal. Si llega channel='meli' con sender_id='MELI_USER_123' (no phone), formatPhone falla.

- Sin tests cross-channel — tests existen para WA inbound/outbound y MeLi orders persist, pero ninguno valida 'mismo cliente WA + MeLi → 1 contacto'.



---


## 6. IA y Conocimiento (KB + Agentes IA)


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: 8-12 días


### Estado real (verificado en código)


KB (Knowledge Base) — FUNCIONAL nivel MVP, GAPS para producción multi-tenant: UI Tenant Console completa en /dashboard/knowledge-base (page.tsx 408 líneas: CRUD + filtros + categorías + plantillas + banners RAG-pending + indexing-status). Backend CRUD vive en services/api/routers/knowledge_base.py (POST/GET/PATCH/DELETE/reindex), embedding síncrono server-side via dependencies/embeddings.py + lib/llm_embed.py (cascada gemini-embedding-001 → text-embedding-004 con cache LRU + retries + versionado). Multi-tenant RLS validado (policy tenant_isolation_kb_documents con app_current_tenant()). RAG real con pgvector vector(3072): RPC match_kb_documents en DB + boost determinístico por categoría detectada en query (kb_tool.py:_detect_categories_from_query) + marker anti-alucinación cuando categoría está vacía. kb_query tool agentic (knowledge.py) registrada y disponible en estados GREETING/EXPLORING/CART_BUILDING/PII_COLLECTION/SHIPPING_QUOTE/HUMAN_HANDOFF (7 occurrences en tools_subset). Embedding NO automático del 100%: si Gemini falla, doc se persiste con embedding=NULL y banner UI 'pending'. NO existe upload PDF/MD masivo: cada doc se crea manual con cap 3000 chars + max 30 docs per tenant. STARTER_TEMPLATES tiene 9 plantillas pero usa categorías legacy ('politica', 'general', 'producto') que rompen el CHECK constraint canónico → bug runtime al cargar. Multi-Agentes — INFRAESTRUCTURA COMPLETA, ENFORCEMENT PARCIAL: tabla ai_agents (consolidada post-migration 20260610000000 que absorbió la tabla efímera tenant_agents) con role + role_description + strict_guardrails + is_default + fallback_for_roles JSONB + tools_allowed JSONB + fsm_states_allowed JSONB + persona_block. UI /dashboard/ai-agents (367 líneas page.tsx + 494 líneas agents-list.tsx) con drawer CRUD multi-rol, validación rol único, default protegido. AI-suggest endpoint (/api/v1/ai-agents/suggest) genera role_description draft via Gemini cascade con contexto tenant (filosofía + catálogo top 8) + template skeleton, fallback al skeleton si Gemini saturado. Router pre-LLM (agent_router.py) clasifica inbound por heurística regex (claims/support/marketing/sales) sin costo LLM. select_agent_for_inbound implementa fallback_for_roles explícito con synthetic handoff agent. Templates per-rol con tools_allowed específico (sales=15 tools, support=5, marketing=3, claims=6). Enforcement: tools_allowed SÍ se intersecta en dispatcher.py:1974 con el subset estado, pero fsm_states_allowed NUNCA se enforce y persona_block NUNCA se inyecta al system_prompt. Handoff humano sintético tiene _needs_human_handoff=True pero sin consumer upstream (no marca conversation.status, no notifica operador). Plan I.5 multi-agente: COMPLETADO en schema + router + UI; PENDIENTE enforcement de states + handoff real con estado.


### Bugs runtime (8)


- 🟠 **[HIGH]** kb_documents.embedding_model_version column existe (migration 20260527010000) y get_embedding_model_version() está definido + exportado en services/api/dependencies/embeddings.py, pero NUNCA se escribe en INSERT/UPDATE/reindex en knowledge_base.py. Resultado: la columna queda NULL siempre → imposible detectar drift cuando se swap el modelo (text-embedding-005/voyage) y disparar re-index masivo. La feature de versionado está muerta.

  - `services/api/routers/knowledge_base.py:137-146 (create), :217-218 (patch re-embed), :279-294 (reindex)`

- 🟠 **[HIGH]** STARTER_TEMPLATES referencia categorías legacy 'politica', 'general', 'producto' que NO existen en el CHECK constraint kb_documents_category_check (canónicas: faq, negocio, politicas, productos, envios, pagos). Al hacer 'Cargar plantillas seleccionadas' en UI, el POST al API retorna 422 (Categoría inválida) o 23514 (check constraint) y rompe el bucle serial sin feedback claro al operador.

  - `apps/web/app/dashboard/(ai)/knowledge-base/starter-templates.ts:7,43,95,107 vs supabase/migrations/20260429000001_kb_categories_constraint.sql:43`

- 🟠 **[HIGH]** fsm_states_allowed se define en agent_templates.py (Support/Claims = ['POST_PAYMENT','HUMAN_HANDOFF']) y se selecciona desde DB en tenant_agents.get_active_agent(), pero NINGÚN código en dispatcher ni en state_machine consume este campo para restringir/redirigir. Un agente Support seleccionado por el router en estado CART_BUILDING podrá ejecutar igualmente — el subset declarado es ignorado. Solo tools_allowed se intersecta (dispatcher.py:1974).

  - `services/ai-orchestrator/lib/agent_templates.py:173,198 vs services/ai-orchestrator/agentic/dispatcher.py:1970-1985 (solo tools, no states)`

- 🟡 **[MEDIUM]** persona_block column en ai_agents (migration consolidate_ai_agents) se SELECT en get_active_agent() pero NUNCA se inyecta en system_prompt. El prompt builder solo usa agent_role_description; no hay merge entre role_description y persona_block. Columna = dead data; si un operador la rellena por SQL directo, no afecta al bot.

  - `services/ai-orchestrator/lib/tenant_agents.py:103-106 vs services/ai-orchestrator/agentic/system_prompt.py:273,495,516`

- 🟠 **[HIGH]** _HANDOFF_SYNTHETIC_AGENT.set _needs_human_handoff=True en agent_router.py pero NO existe consumer upstream. grep en services/ confirma: solo aparece definido + comentado, nunca leído. Cuando classify_intent_to_role retorna un rol NO cubierto por default.fallback_for_roles, el bot devuelve un texto de handoff pero NO se notifica al operador, NO se cambia conversation.status a 'human_handoff', NO se crea ticket. El handoff es pura cortina semántica sin estado real.

  - `services/ai-orchestrator/agentic/agent_router.py:99,126 (definido) — sin consumer en dispatcher`

- ⚪ **[LOW]** Sin chunking de docs largos: contenido completo (hasta 3000 chars = ~750 tokens) se concatena con título y se embebe como vector único. Para policies/FAQs largas, similarity score se diluye. Es aceptable hoy (límite 3000) pero queda como gap para upload masivo (PDFs).

  - `services/api/dependencies/embeddings.py:78-82 embed_kb_document`

- ⚪ **[LOW]** Threshold RAG hardcoded a 0.5 (match_threshold). No es configurable per tenant ni por categoría. Cuando un tenant tiene KB pobre en pagos/envíos, el boost determinístico por categoría compensa, pero si la query es ambigua semánticamente, el threshold 0.5 puede retornar docs irrelevantes que el LLM cita como fuente.

  - `services/ai-orchestrator/tools/kb_tool.py:169`

- 🟡 **[MEDIUM]** Path duplicado de inyección KB: legacy orchestrator.py:7610-7615 inyecta KB pre-LLM siempre (get_tenant_kb_rag + format_kb_for_prompt en system_prompt), mientras path agentic (cutover) usa kb_query como TOOL. Tenants en agentic NO reciben KB pre-inyectado, dependen 100% de que el LLM decida invocar kb_query. Si el LLM omite la tool (saturación de prompt + 17 tools), el bot responde sin contexto KB aunque exista doc relevante. Asimetría entre legacy y agentic no documentada al operador.

  - `services/ai-orchestrator/orchestrator.py:7610-7615 vs services/ai-orchestrator/agentic/dispatcher.py:628-640 (system_prompt sin KB)`



### Fuentes de verdad (uso real)


- kb_documents (Supabase, RLS por tenant_isolation_kb_documents) — fuente única para docs/embeddings; consumida por get_tenant_kb_rag (RAG vía RPC match_kb_documents con pgvector cosine + boost categorial determinístico).

- ai_agents (Supabase, RLS via tenant_users; ÚNICA fuente verdad post-migration 20260610000000 que consolidó la legacy 'tenant_agents'). Lee dispatcher en línea 618 via lib.tenant_agents.get_active_agent.

- tenants.business_pitch + tono_comunicacion + mision/vision/valores: fuente verdad de filosofía. Inyectados al system_prompt separado del agent.role_description (correcto, anti-duplicación).

- Modelo Gemini gemini-embedding-001 (3072 dims) con fallback text-embedding-004 via llm_embed.embed_with_cascade — wrapper unificado byte-equal entre services/api/lib y services/ai-orchestrator (test paridad).

- agent_templates.py (código, NO DB) — single source de los 5 templates (sales/support/marketing/claims/custom) con tools_allowed. fsm_states_allowed definido pero no enforced (gap).



### Gaps funcionales (9)


- Sin import masivo (PDF/MD upload): UI solo permite POST/PATCH 1 doc a la vez con max 3000 chars. STARTER_TEMPLATES es el único bulk insert y está roto por mismatch de categorías. Para un tenant con manual de procedimientos de 50 páginas hay que copy-paste manual en 30 cards (límite MAX_DOCS_PER_TENANT=30).

- Sin chunking: docs largos se embeben como bloque único → similarity diluye. Acompañado de cap rígido 30 docs/tenant deja techo bajo para negocios reales (cosmética con 200 SKUs + políticas + envíos).

- Sin re-embedding masivo: tras swap futuro de modelo (voyage/text-embedding-005) NO existe endpoint POST /knowledge-base/reindex-all ni cron job. Solo POST /{id}/reindex doc a doc — operador tendría que clickar 30 botones.

- Handoff entre agentes mid-conversation NO existe: el router clasifica por INBOUND solo (cero costo, cero LLM), pero una vez seleccionado el agente, no hay continuidad de contexto si el cliente cambia tema (ej. iniciar ventas, terminar en reclamo). El dispatcher invoca get_active_agent CADA TURN, así que el agente puede oscilar turno-a-turno sin transferencia explícita ni log al operador.

- Sin métricas de routing: no se persiste qué agente atendió cada turn, ni miss-classification rate, ni handoff_required. agent_router.py comenta '$0.0001/turno si miss-classification > 10%', pero NO existe medición.

- Sin UI per-agente para ver/editar tools_allowed ni fsm_states_allowed. UI solo expone name/role/role_description/strict_guardrails/fallback_for_roles. Los subsets de tools quedan congelados al template del rol.

- persona_block en DB sin UI ni consumer — operador no puede agregar bloque persona extra ('Soy madre, conozco cosmética natural...'). Solo role_description hace ese papel.

- Sin previsualización del prompt final compuesto (filosofía + agent + KB + catalog) que verá el LLM. BotPreview existe en /ai-agents pero solo muestra outbound de un prompt de prueba, no el system_prompt resuelto.

- Sin búsqueda full-text fallback dentro de KB UI: si tenant escribe 'devoluciones' en el buscador, solo filtra in-memory por substring (page.tsx:141). No usa ts_vector ni embeddings para 'document discovery' visual antes de publicar.



### Gaps técnicos (9)


- DUPLICACIÓN llm_embed.py: 2 copias byte-equal (services/api/lib/llm_embed.py + services/ai-orchestrator/llm_embed.py) con test de paridad cross-service. La nota en código menciona 'futuro: extraer a packages/python-shared/' — gap conocido sin owner.

- ASIMETRÍA legacy vs agentic en inyección KB: legacy pre-inyecta (orchestrator.py:7610), agentic depende de tool kb_query (dispatcher). Misma KB pero comportamiento distinto según flag tenant_integrations.meta.agentic_enabled. Operador no tiene visibilidad de cuál path usa su tenant.

- agent_templates.py + tenant_agents.py + ai_agents.py + agent_router.py + system_prompt.py dispersos sin documento maestro de contrato. Cambiar 'persona_block' o 'fsm_states_allowed' requiere edición coordinada en 4 archivos + 1 migration + frontend; alto riesgo de drift.

- Migration 20260608000000_tenant_agents.sql crea tabla que migration siguiente 20260610000000_consolidate_ai_agents.sql destruye (DROP TABLE tenant_agents CASCADE). En un fresh DB las dos corren OK, pero quedó histórico confuso. Comentario explícito 'HONESTIDAD: en la migration anterior creé una tabla nueva sin detectar que ai_agents ya existía' — deuda no compactada.

- knowledge_base.py 297 líneas — manejable, pero mezcla validation + serialization + DB write + business logic en cada endpoint. _embedding_to_pgvector / _strip_embedding helpers privados sin tests dedicados.

- dispatcher.py 2763 líneas (monolito) hace dispatch + agentic full + shadow + multi-agente + COD intent + cart resolver + payment availability + persistence + audit. Plan refactor proyecto ya identificado en memory project_rev109_refactor_plan.md.

- agentic/tools/knowledge.py importa from tools.kb_tool dentro de execute() (lazy) en lugar de a nivel módulo, lo cual sugiere que durante registry init no quería disparar el embed client. Patrón inconsistente con otras tools (catalog/orders/cart importan en top).

- ai_agents router solo expone /suggest y /templates — el CRUD real va via Next.js Server Actions directo a Supabase (RLS). Funciona pero rompe el patrón de los otros módulos (knowledge_base, claims, purchases, contacts) donde el API es el SoT y el frontend solo es presentación. Si en el futuro se necesita lógica server-side (validation cross-row, audit, eventos), habrá que portar a Python.

- Tests cobertura: existe test_kb_tool.py + test_kb_tool_embeddings.py + test_ai_agent.py + test_rev92_enhance_kb_citation.py pero NO test específico de agent_router.select_agent_for_inbound (4 rutas críticas: claims/support/marketing/fallback). Tampoco test integración multi-agente (tenant con 4 agentes routea correctamente).



---


## 7. Finanzas y Analítica


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: 14-18 días para alcanzar production-grade. Desglose: 2d fix bugs runtime (COGS=0 warning, paid-status revenue, paginación metrics, expense UPDATE/DELETE, timezone). 3d agregar P&L mensual + export CSV/PDF + comparativa periodo anterior + AOV/LTV/repeat-rate. 3d cablear cart_events como fuente analytics (funnel conversion + abandonment). 2d desglose ingresos/costos por canal y proveedor. 4-5d Plan I.8 tenant_billing_events (schema + emitters en wompi_webhook/aveonline/whatsapp_sender/orchestrator + UI desglose costos por tenant + founder aggregate). 1d alertas proactivas push + AiInsightPanel para finance module. Critical-path: P&L temporal + funnel desde cart_events + bugs revenue/COGS — esos 3 son los que el founder pide ("visual completa, control, decisiones"). Plan I.8 es prerequisito para pricing-tenant y deberá ir antes de cobrar el primer tenant premium."


### Estado real (verificado en código)


PARCIAL — Existen 2 módulos UI independientes con KPIs basicos, NO un dashboard unificado de "visual completa del negocio".

ANALÍTICA (`/dashboard/metrics` — `(analytics)/metrics/page.tsx`, 346 LOC):
- KPIs: mensajes (inbound/outbound), conversaciones (bot/humano), pedidos, contactos, productos activos, conversión (orders/conversations), ingresos confirmados (delivered), pedidos cancelados, reclamos (open/refunded/refund_rate/by_reason).
- Gráficos: BarChart mensajes/día semana + PieChart pedidos/estado.
- Top 5 productos por unidades vendidas + revenue.
- Filtro periodo: 7/30/90/all (server-side, vía searchParams).
- Panel `AiInsightPanel module="metrics"` (Gemini-powered, on-demand, owner/manager).
- Sin export CSV/PDF — solo visualización.

FINANZAS (`/dashboard/finance` — `finance/page.tsx` + `_components/finance-dashboard.tsx` 178 LOC):
- KPIs unit-economics: Ingresos Netos, COGS (de order_items.unit_cost × qty, excluye cancelled), OPEX (sum expenses), Gross/Net Profit, Margen Bruto/Neto.
- BarChart Ventas Netas vs COGS vs OPEX vs Beneficio.
- ExpensesManager CRUD parcial (solo INSERT — sin UPDATE/DELETE).
- Filtro tiempo: month / last_month / all (client-side useMemo).
- Sin export, sin desglose por canal/marketplace, sin LTV/CAC, sin cohort analysis, sin gráfico de evolución temporal (mes a mes).
- Acceso solo `role === 'owner'` (sidebar-client.tsx:87).

AUDITORÍA (`/dashboard/audit` — 235 LOC):
- Tabla audit_log con filtros (entity/user/from_date/to_date), paginación 25/pág.
- Export CSV vía `/api/audit/export` (route.ts, 62 LOC, limit 5000).
- Solo `role === 'owner'`, capability `analytics.audit.export`.

DATA SOURCING:
- Todo consultas ad-hoc directas a tablas operativas (orders, order_items, messages, conversations, contacts, products, expenses, claims). NO hay materialized views ni snapshots agregados.
- `cart_events` (migración 20260510090000) EXISTE como append-only log con event_types canónicos (item_added, shipping_quoted, carrier_selected, payment_link_created, order_confirmed, etc.) — pensado para analytics conversacional, pero NO consumido por dashboards.
- `tenant_usage_events` y `tenant_usage_counters` (migración 20260420000005 plan_tiering_foundation) EXISTEN — pensados para metering de capabilities por plan. Insertados solo por SQL function `register_capability_usage` (migración línea 359). NO emitido desde código Python/TS aplicacional.

PLAN I.8 / MA-5 (`tenant_billing_aggregator` + `tenant_billing_events`):
- Documentado en `docs/research/meta-analysis-cross-dossier-2026-05-05.md:118`, `docs/refactor/0005-platform-console-pending-items.md:55`, `docs/refactor/0006-roadmap-pending-sessions.md:168`, `.context/04-next-steps.md:79`.
- Schema referencia: `tenant_billing_events(tenant_id, provider, event_type, units, unit_cost_usd, metadata, created_at)`.
- NO existe migración, NO existe tabla, NO existe UI de desglose costos por provider (WhatsApp HSM, Gemini tokens, Aveonline labels, Wompi fees, Storage, etc.).
- ADR-0016 (HSM templates) línea 274 lo cita explícitamente como "futuro Sem 11 MA-5".

MULTI-TENANT/AGGREGATE FOUNDER:
- Cada tenant ve SUS datos via `tenant_id` filter (correcto, RLS-enforced).
- NO existe vista agregada de Platform Console para founder ver KPIs cross-tenant (Phase 12 bloqueada por OQ-P01 según CLAUDE.md).


### Bugs runtime (9)


- 🟠 **[HIGH]** FinanceDashboard.totalCOGS usa SOLO order_items.unit_cost — si producto fue importado de Meli/Shopify SIN cost_price seteado, unit_cost queda en 0.00 (default migración 20260413000000:9) y el COGS reportado es FALSO 0, inflando margen artificialmente. Sin UI ni warning de 'productos sin costo'.

  - `apps/web/app/dashboard/finance/_components/finance-dashboard.tsx:55-62 + supabase/migrations/20260413000000_purchases_and_finance.sql:9`

- 🟠 **[HIGH]** FinanceDashboard.totalRevenue incluye TODOS los pedidos no-cancelled (incluyendo pending/confirmed/processing que pueden caer). MetricsPage hace lo mismo. Si Wompi rechaza el pago tras crear el order, el revenue queda contado. No hay reconciliación con payment_status.

  - `apps/web/app/dashboard/finance/_components/finance-dashboard.tsx:55-58, apps/web/app/dashboard/(analytics)/metrics/page.tsx:85-86`

- 🟠 **[HIGH]** MetricsPage carga todos los conversations, contacts, products del tenant SIN paginación ni gte('created_at'). En tenant con histórico grande (>10k contactos, >100k mensajes), Supabase aplica límite implícito 1000 rows → KPIs subreportados silenciosamente sin warning.

  - `apps/web/app/dashboard/(analytics)/metrics/page.tsx:61-69`

- 🟡 **[MEDIUM]** ExpensesManager solo permite INSERT. No hay UPDATE/DELETE — un gasto mal capturado (typo amount, fecha incorrecta) queda inmutable y distorsiona OPEX para siempre.

  - `apps/web/app/dashboard/finance/actions.ts + apps/web/app/dashboard/finance/_components/expenses-manager.tsx`

- 🟡 **[MEDIUM]** FinanceDashboard filtra expenses client-side por expense_date pero usa new Date(e.expense_date) sin timezone — puede excluir gastos del último día del mes en TZ Bogotá (UTC-5) si la fecha se almacenó como UTC.

  - `apps/web/app/dashboard/finance/_components/finance-dashboard.tsx:46-49`

- 🟡 **[MEDIUM]** MetricsPage.conversionRate = orders/conversations es matemáticamente engañoso: un cliente puede tener 5 conversaciones y 1 pedido (20%) o 1 conversación con 3 pedidos (300%). No es la 'conversión' real que un founder espera.

  - `apps/web/app/dashboard/(analytics)/metrics/page.tsx:89-91`

- 🟡 **[MEDIUM]** /api/audit/export tiene .limit(5000) hardcoded sin warning al usuario. Si auditoría > 5000 eventos el CSV exporta solo 5000 más recientes silenciosamente — compliance issue (Habeas Data: 'derecho a la información completa').

  - `apps/web/app/api/audit/export/route.ts:24`

- ⚪ **[LOW]** FinanceDashboard usa Tailwind shades 500 (text-blue-500, text-amber-500, text-red-500, text-green-500) y bg-*-500/10 — viola feedback_ui_colors.md ('NUNCA usar Tailwind shades 300-500'). Múltiples cards.

  - `apps/web/app/dashboard/finance/_components/finance-dashboard.tsx:97,110,113,120,123,129,130,133,134`

- ⚪ **[LOW]** expenses.amount es numeric(10,2) NOT NULL CHECK (amount > 0) pero el frontend hace parseFloat sin validar overflow (>99,999,999.99 silently fails en insert) y sin currency — todo asumido COP sin columna `currency` ni conversión.

  - `supabase/migrations/20260413000000_purchases_and_finance.sql:67 + apps/web/app/dashboard/finance/actions.ts:17`



### Fuentes de verdad (uso real)


- orders + order_items (revenue + COGS via unit_cost × quantity)

- expenses (OPEX manual, CRUD parcial)

- messages, conversations (mensajería WhatsApp para conversión bot vs humano)

- contacts, products, product_variations (volumen/catálogo)

- claims (reembolsos — NO se descuenta de revenue actualmente)

- audit_log (eventos para módulo Auditoría)

- cart_events — EXISTE pero NO consumido por dashboards (sub-uso crítico)

- tenant_usage_events / tenant_usage_counters — EXISTEN pero sin emitter aplicacional

- tenant_billing_events — DOCUMENTADO pero NO existe (Plan I.8 pendiente)



### Gaps funcionales (15)


- P&L mensual / trimestral con evolución temporal (gráfico de línea por mes) — hoy solo muestra el período activo, sin trend mes-a-mes.

- Export CSV/PDF de finance dashboard — solo audit log tiene export.

- Desglose ingresos por canal (WhatsApp / Meli / Shopify / web) — finance trata todo como bloque único.

- Desglose costos por proveedor (Wompi fees, Aveonline labels, WhatsApp HSM tokens, Gemini tokens, Storage) — el OPEX es manual via expenses table.

- KPIs missing en metrics: AOV (ticket promedio), LTV, CAC, retention rate, repeat-customer rate, ARPU, churn.

- Funnel de conversión sales: cart_created → cart_quoted → payment_link_sent → order_confirmed → delivered. Los `cart_events` ya están loggeados pero ningún dashboard los lee.

- Comparativa vs período anterior (delta % crecimiento) — UI muestra solo absolutos.

- Gestión de gastos: UPDATE/DELETE/edit + adjuntar comprobante PDF + categoría custom + recurrentes (suscripciones mensuales fijas).

- Cohort analysis (retención mensual de clientes nuevos por mes de adquisición).

- Alertas proactivas: 'gasto en marketing creció 40% este mes', 'top producto agotándose', 'margen bajó por debajo de X%'. AiInsightPanel existe pero es on-demand, no push.

- Reportes fiscales (resumen IVA, retenciones, gastos deducibles por categoría DIAN) — Colombia-specific compliance.

- Plan I.8 — sin tabla `tenant_billing_events` el founder NO puede pricing tenant correcto: no hay forma de saber cuánto le costó cada tenant en infra (WhatsApp + Gemini + Storage).

- Sin agregado cross-tenant para founder (Phase 12 Platform Console bloqueada por OQ-P01).

- Sin tracking de devolución/reembolso impactando margen (claims.requested_amount NO se descuenta de revenue en finance dashboard).

- Sin AiInsightPanel para finance module (existe para inventory/orders/contacts/metrics; module 'finance' no está en validModules en /api/insights/route.ts:225).



### Gaps técnicos (11)


- Arquitectura ad-hoc: cada page hace 5-7 queries directas a tablas operativas en cada render (Promise.all). En tenant con volumen alto → N+1 lectura masiva. Sin materialized views ni snapshot diario agregado.

- Falta tabla `finance_summaries` o `analytics_daily_snapshots` (tenant_id, date, revenue, cogs, opex, orders_count, etc.) calculada nightly por cron — hoy todo es runtime.

- `cart_events` (append-only log) DESPERDICIADO para analytics: tabla ya creada y poblada por orchestrator pero ningún dashboard la consulta. Es la mejor fuente para funnel/abandonment/coupon attribution.

- `tenant_usage_events` + `tenant_usage_counters` EXISTEN (migración plan_tiering_foundation) pero NO se emiten desde código aplicacional (solo desde SQL function `register_capability_usage`). Plan tiering metering está mudo.

- Plan I.8 documentado en 4 ADRs/refactor docs pero CERO implementación — tabla `tenant_billing_events(tenant_id, provider, event_type, units, unit_cost_usd, metadata, created_at)` no existe.

- Lógica de cálculo (revenue, COGS, margin) duplicada en finance-dashboard.tsx y metrics/page.tsx con sutiles diferencias de filtrado (status != 'cancelled' vs status == 'delivered') → divergencia silenciosa.

- `/api/insights/route.ts` tiene módulo 'metrics' pero NO 'finance' — inconsistencia de superficie LLM.

- Finance dashboard hace cálculos en client (useMemo) — no es server-rendered → tenants con histórico grande verán lag visible al filtrar.

- Sin tests unitarios sobre cálculo de KPIs (validate.sh corre 1490 tests pero ninguno cubre finance metrics).

- Categories de expenses son ENUM hardcoded (CHECK constraint SQL: payroll/marketing/software/logistics/other) — no extensible sin migración.

- `(analytics)` es route group de Next pero solo tiene 2 leafs (metrics, audit) — UI siente fragmentada (Finanzas vive aparte como `/finance`, sin agrupar con analytics).



---


## 8. Configuración (Tenant Console settings)


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: 8-12 días (P0 bloqueantes: validación server-side + bucket storage 2d; P1 missing UX: onboarding wizard 5-7 pasos 3d + branding paleta 2d + tenant-readiness dashboard 1d; P2 hardening: helpers compartidos validators+vault 1d + invalidate-cache cross-service 1d; P3 nice-to-have: capabilities matrix UI + Resend UI 2d)


### Estado real (verificado en código)


Configuración está MAYORMENTE FUNCIONAL en producción. La estructura está modularizada correctamente con grupo de rutas `(settings-group)` separando /settings (general), /integrations (5 panels dedicados), /team (RBAC). Persistencia OK para: tono_comunicacion/mision/vision/valores/horario/store_presence/shipping_origin/payment_methods/aveonline_carriers/team RBAC/legal_acceptance/retention_policies. CHECK constraints DB para tono_comunicacion + escalation_role. Vault para secrets (WhatsApp token, Wompi keys, Telegram bot_token, Aveonline password). Server actions con RBAC (`getOwnerTenantId` redirect). Settings se consumen por orchestrator (system_prompt.py inyecta filosofía + tono + escalation_role + after_hours_message; payment_methods consumido por carrier_capabilities; ai_agents.role_description inyectado como persona). PERO: NO existe onboarding wizard (Plan I.7 mencionado en prompt no implementado), branding está limitado a logo+nombre (sin paleta/colores), tenant_provider_capabilities table existe backend pero SIN UI tenant-facing, server actions de settings carecen de validación server-side (solo .trim, sin regex email/phone/NIT/maxLength), logo-upload bypassa server action (sube con anon client directo), bucket `tenant-media` no está creado en migraciones (drift o creación manual sin RLS documentada), cache de tenant config es por-request (no TTL, costo DB extra pero consistencia OK), invalidate_cache de payment_methods no se llama desde web actions (cache 30s expira solo). Settings page (605 LOC) está monolítica con 5 forms separados — mantenible pero rozando el límite.


### Bugs runtime (9)


- 🟠 **[HIGH]** logo-upload.tsx hace upload + UPDATE tenants.logo_url usando supabase CLIENT (anon JWT) en lugar de server action. Bypassa el check `role==='owner'` que protege saveTenant — cualquier usuario autenticado con tenant_id en JWT puede sobrescribir el logo del tenant si las storage policies/RLS no lo restringen explícitamente.

  - `apps/web/app/dashboard/(settings-group)/settings/logo-upload.tsx:42-67`

- 🟠 **[HIGH]** El bucket storage `tenant-media` usado por logo-upload.tsx no está creado en ninguna migración (`grep tenant-media supabase/migrations/` retorna 0 resultados; la migration 20260409270000 menciona `tenant-branding` en COMMENT pero nunca crea el bucket). Implica: o el bucket fue creado manualmente sin RLS policies en repo (drift), o el upload falla silenciosamente en prod fresh.

  - `apps/web/app/dashboard/(settings-group)/settings/logo-upload.tsx:48; supabase/migrations/`

- 🟠 **[HIGH]** Server actions saveTenant/saveFilosofia/savePresenciaDigital/saveShippingOrigin solo aplican `.trim()` SIN validación server-side de: email regex, telefono pattern `3[0-9]{9}`, NIT formato, maxLength (100 nombre / 280 misión/visión/valores). HTML5 attributes son bypassables — un POST manipulado escribe garbage en DB. CHECK constraint en DB solo cubre tono_comunicacion.

  - `apps/web/app/dashboard/(settings-group)/settings/actions.ts:33-52`

- 🟡 **[MEDIUM]** savePresenciaDigital NO valida que store_locations[].state sea un departamento DANE válido ni que city pertenezca al dpto. Cliente envía JSON.stringify(locs) con campos libres — un payload manipulado puede inyectar valores irreales que luego rompen shipping_quote_tool al resolver DANE.

  - `apps/web/app/dashboard/(settings-group)/settings/actions.ts:72-109`

- ⚪ **[LOW]** savePaymentMethods no invalida cache server-side de orchestrator (_CACHE en services/ai-orchestrator/lib/tenant_payment_methods.py TTL=30s). Hasta 30s después de deshabilitar COD, el bot puede seguir ofreciéndolo. No es bloqueante pero contradice la promesa UI 'Métodos actualizados'.

  - `apps/web/app/dashboard/(settings-group)/settings/actions.ts:119-157; services/ai-orchestrator/lib/tenant_payment_methods.py:39-40`

- 🟡 **[MEDIUM]** savePresenciaDigital cuando store_type cambia de 'fisica_virtual' a 'virtual' descarta store_locations (línea 237 del form filtra y envía array vacío). Pero el server action NO re-valida que social_links tenga al menos 1 si store_type='virtual'. Cliente bypass dejaría tenant 'virtual' sin canales digitales registrados — incoherente con la validación client.

  - `apps/web/app/dashboard/(settings-group)/settings/actions.ts:72-109; store-presence-form.tsx:223-232`

- ⚪ **[LOW]** saveTelegram persiste el secret en Vault pero el flujo de save no hace test live antes de upsert — guarda credenciales aunque sean inválidas. testTelegram (separado) sí hace el llamado, pero el usuario puede ver 'Conectado' sin haber probado nunca. Inconsistencia con Aveonline que sí valida en connect.

  - `apps/web/app/dashboard/(settings-group)/integrations/page.tsx:99-135`

- 🟡 **[MEDIUM]** saveWompi no valida que la clave coincida con el environment (private_key prefijo `prv_test_` vs `prv_prod_`). Un tenant puede pegar clave de producción con environment=sandbox y al webhook llegará evento que falla en validate_signature.

  - `apps/web/app/dashboard/(settings-group)/integrations/page.tsx:312-362`

- ⚪ **[LOW]** saveTenant escribe `name: undefined` cuando el form llega vacío (línea 36 usa `|| undefined`). Pydantic/PostgREST puede tratar undefined como no-op o como null dependiendo del cliente — comportamiento ambiguo. Si llega payload sin name, debería retornar error explícito.

  - `apps/web/app/dashboard/(settings-group)/settings/actions.ts:36`



### Fuentes de verdad (uso real)


- tenants table (mision/vision/valores/tono_comunicacion/support_schedule/after_hours_message/escalation_role/store_locations/store_type/social_links/shipping_origin/logo_url/nit/email_contacto/telefono_contacto) — leída cada mensaje en orchestrator.py:6848 sin cache

- tenant_payment_methods (cod/online_wompi) — usada con CHECK constraint, lib/tenant_payment_methods.py cache TTL 30s; OK consumido en carrier_capabilities

- tenant_integrations (provider/status/credentials/meta) per WhatsApp/Aveonline/MeLi/Wompi — secrets en Vault via pgsec_*

- notification_settings (channel='telegram'/bot_token_secret_id/chat_id) — Vault para token

- tenant_aveonline_carrier_prefs (tabla per-tenant matrix carriers + supports_cod) — gestionada por panel /integrations/aveonline?tab=carriers

- ai_agents (name/role_description/strict_guardrails/role/is_default/fallback_for_roles) — multi-agente Rev. 109; role_description inyectado en system_prompt _render_agent_persona_block

- kb_documents (title/content/category/is_active/embedding) — UI /knowledge-base, embeddings server-side via /api/v1/knowledge-base

- tenant_legal_acceptance (append-only) — UI /settings/legal con IP+UA capture

- retention_policies (defaults globales + overrides per-tenant) — UI /settings/retention

- tenant_provider_capabilities — backend completo (lib/capabilities_matrix.py + catálogo CAPABILITIES_BY_PROVIDER) pero SIN UI tenant-facing, no expuesto via HTTP

- tenant_users (RBAC roles owner/manager/operator) — RPC get_tenant_team + add_member_to_tenant

- STORAGE bucket tenant-media NO definido en migraciones (drift potencial); bucket consent-evidence + tenant-offboarding SÍ tienen migrations RLS



### Gaps funcionales (12)


- ONBOARDING WIZARD AUSENTE: Plan I.7 mencionado en prompt del founder no existe. No hay flujo `/onboarding` ni `/welcome` que guíe al nuevo tenant en 5-7 pasos (Identidad → Logo → Sedes → Horario → WhatsApp → Wompi/Aveonline → Filosofía). Hoy el nuevo owner aterriza en /dashboard sin guidance — solo el sidebar y la página `/dashboard/settings` con 6 secciones colapsables. Resultado: tenants se quedan en estado parcial (sin filosofía / sin tono / sin payment methods configurados → degradación bot silenciosa).

- BRANDING REDUCIDO A LOGO+NOMBRE: el prompt audita 'branding (logo, colores, paleta)' pero no existe columna ni UI para brand_primary_color / brand_secondary_color. Migration 20260426030000_tenant_brand_and_hours.sql solo añade mision/valores/tono/horario. Si Konvi pretende renderizar emails/cards/payment-links/PDFs con branding tenant, falta scope significativo.

- tenant_provider_capabilities SIN UI tenant-facing: la tabla + lib/capabilities_matrix.py + catálogo CAPABILITIES_BY_PROVIDER (wompi/meta/meli/telegram/resend/aveonline) son backend-only. No hay endpoint API HTTP ni página settings que permita al tenant ver/togglear (ej: tier_unlimited, hsm_templates, refund). Plataforma Console (fase 12 bloqueada) podría exponer, pero hoy es opaco para el tenant.

- RESEND NO TIENE UI: backend tiene Resend client (services/api/lib/integration_client/retry.py) + lib/compliance/errors.py lo nombra, pero no hay card en /dashboard/integrations ni server action. Tenant no puede configurar dominio/API key custom para emails (orden confirmations, invoices, etc.).

- AVEONLINE_IDAGENTE solo se setea via panel dedicado (no en hub): el campo crítico `idagente` para generarGuia2 vive en /dashboard/integrations/aveonline?tab=setup. Onboarding del hub `/dashboard/integrations` permite conectar Aveonline sin definir idagente — luego al primer pedido COD el bot falla con error 999. Falta o validación bloqueante o checklist en hub.

- CARRIERS MATRIX requiere user click 'Sincronizar' manual: AveonlineCarriersSection nunca auto-seedea — un tenant nuevo ve prefs vacía + banner 'usaremos todos por defecto'. Sin lectura proactiva la tab Carriers es UX dead-end.

- FALTA visualización legible del system prompt FINAL inyectado al LLM: bot-preview.tsx existe pero ai-agents/page.tsx no muestra el prompt completo combinado (philosophy + agent.role_description + tone + escalation_role). Tenant no puede auditar qué 've' su bot.

- ESCALATION_ROLE no se refleja en después de cambiar — la copy del select (`...que te ayudará`) usa el valor actual pero la modificación de copy queda solo en string DB; falta UAT visual o ejemplo en preview.

- SETTINGS PAGE no marca 'requerido' para Payment Methods / Filosofía / Aveonline IDagente como pre-requisitos para que el bot opere — Resumen lateral muestra ✗ pero sin priorización clara (qué falta P0 para que el bot venda vs P2 cosmético).

- No existe vista 'salud configuración' a nivel tenant: la sub-página /settings/health solo monitorea integraciones (WhatsApp/Wompi/Aveonline/MeLi/Telegram) — pero NO completitud de tenant_payment_methods, ai_agents, KB coverage, filosofía. Tenant no tiene un único dashboard '¿estoy listo para vender?'.

- Logo upload NO valida dimensiones ni ratio — sube cualquier PNG/JPG/WebP <2MB. Si logo es 50x500px, downstream renders rotos.

- Sin export de configuración (backup): no hay forma de descargar JSON con la configuración del tenant para auditoría o migración entre ambientes.



### Gaps técnicos (14)


- VALIDACIÓN INCONSISTENTE: hay 3 patrones en actions distintos: (a) settings/actions.ts → solo trim, sin regex; (b) integrations/whatsapp/page.tsx createDraftAction → regex completa + return error JSON; (c) integrations/aveonline saveAveonlineIdagente → regex solo el campo. No hay helper compartido `validators.ts`. Cada acción reinventa parsing.

- settings/page.tsx con 605 LOC monolítico: orquesta 6 forms (Identidad/Filosofía/Presencia/Horario/Despacho/PaymentMethods) + Resumen + Más-configuraciones links. Tipos Tenant inline (37-51) deberían vivir en types/tenant.ts; FormSection y ReadOnlyField son re-implementadas (existe shared/Section en otros panels). Refactor a sub-componentes server-rendered.

- integrations/page.tsx con 488 LOC + 9 server actions inline ('use server' anidadas en componente): patrón funciona pero anti-pattern Next.js (server actions deberían vivir en actions.ts separado para testabilidad). Cada save* duplica el patrón leerExistente→pgsec_upsert_secret→upsert.

- DUPLICACIÓN aveonline server actions: connectAveonline existe en 2 sitios — /integrations/page.tsx (saveAveonline wrapper) Y /integrations/aveonline/page.tsx. Ambos llaman lib/aveonline-actions.ts pero los wrappers tienen RBAC checks distintos (owner-only vs owner+manager). Inconsistente.

- SECRET HANDLING duplica patrón pgsec_upsert/update/delete en 4 sitios (saveTelegram/saveWhatsApp/saveWompi + Aveonline lib): no hay `lib/vault-secrets.ts` helper. Manejo de existingSid+rotación de secrets repetido.

- Path traversal mitigado en logo upload (MIME_TO_EXT) pero NO en consent_evidence (otro bucket): inconsistencia de defensa en depth.

- store_locations + shipping_origin NO comparten schema TypeScript — Location en store-presence-form.tsx (12 keys) y ShippingOrigin en shipping-origin-form.tsx (10 keys) divergen. Si añades campo en uno, otro queda desactualizado.

- settings/actions.ts no usa estructura `{ ok, error }` que el resto (paymentMethods, aveonline, whatsapp-templates) sí usa — saveTenant/saveFilosofia/savePresenciaDigital/saveShippingOrigin no retornan resultado al cliente, el form `<form action>` espera void. Sin UX de error explícita al failure.

- Mezcla de paradigmas form action vs onSubmit handler: identidad/filosofía/horario usan `<form action={serverAction}>` (Next.js Server Form). Presencia/Despacho/PaymentMethods usan onSubmit→action(fd) (transición client→server). 2 patrones sin justificación.

- Cache de tenant config: orchestrator.py:6848 lee la tabla `tenants` por cada mensaje (sin cache). 18 columnas × N mensajes/sec = costo DB elevado en escala. Falta `TenantConfigService` con TTL 30s parecido al de tenant_payment_methods.

- InvalidateCache cross-service ausente: cuando el web actualiza settings, no se notifica orchestrator (no hay webhook ni Redis pub/sub). El orchestrator solo refresca cuando expire su _CACHE local. Para changes críticos (payment_methods, after_hours_message) idealmente push-invalidate.

- Falta tests E2E para settings: scripts/uat/scenarios/ tiene tests de bot, pero no tests Playwright/Cypress que ejerciten /dashboard/settings con login + save + verify DB. Cualquier regresión en server actions pasa sin detección hasta UAT manual.

- Drift bucket storage: tenant-media no documentado. Cualquier instalación fresca falla en logo upload. Falta migration `tenant_media_bucket.sql` con bucket creation + RLS policy (`tenant_id` extraído del path).

- Comentario código dice 'tenant-branding' pero código usa 'tenant-media' (logo-upload.tsx:48 vs migration comment 20260409270000:16). Source of truth ambiguo.



---


## 9. Seguridad cross-cutting (OWASP + Habeas Data + multi-tenant)


**Prioridad finiquito**: `P0`  

**Esfuerzo estimado**: P0 (H7 rotación secretos) = 1 día founder + 0.5 día engineer (Render env update + smoke tests). P0 (telegram constant-time + marketplace RBAC + ai_agents auth) = 0.5 día. P1 (wompi IP allowlist + webhook rate-limits) = 1.5 días. P1 (Vault tokenize document_number con read just-in-time Wompi) = 3-5 días (alto riesgo regresión Wompi). P2 (refactor 319 .table() → scoped_table) = 4-6 días. P2 (auth.py ES256 — leer app_metadata del user object autoritativo) = 0.5 día. P3 (data_subject_request HTML escape robusto) = 0.5 día. TOTAL roadmap finiquito: ~12-16 días engineer + 1 día founder coordinación.


### Estado real (verificado en código)


PARCIAL — Hay base sólida (RLS 73/73 tablas, HMAC Meta + Wompi constant-time, JWT validation, MFA TOTP en middleware, consent_audit_log append-only enforced por triggers, retention pg_cron registrado, SAR funcional con PII access log, rate-limit distribuido y headers de seguridad). PERO existen brechas serias de producción que contradicen la frase "siempre con las excelentes prácticas en todo sentido incluyendo seguridad": (1) H7 — secretos Supabase / Meta / Wompi siguen IDÉNTICOS a los expuestos en commit historic ***REDACTED-SHA*** (rotación documentada como P0 pendiente, NO ejecutada, ver .context/04-next-steps.md líneas 443-446 y .env actual versus git show ***REDACTED-SHA***:.env); (2) `TenantScopedClient` existe como `scoped_table()` pero se USA solo en 4 callsites contra 319 .table() raw — defensa-en-profundidad casi nunca activada; (3) routers críticos (marketplace 5 endpoints, ai_agents 2 endpoints, mfa) NO usan require_write_role/require_owner_role; (4) Telegram webhook hace `if x_tg_secret != SECRET:` (NO constant-time, timing attack); (5) Wompi y Aveonline y WhatsApp webhooks no tienen rate-limit (solo MeLi lo tiene); (6) `document_number` plaintext en `contacts` — tokenización es solo hash+last4 aditivos, NO se eliminó el plaintext (comment migration 20260506010000 dice "aditiva" / Wompi sigue consumiendo claro); (7) Wompi webhook NO tiene IP allowlist (single-layer defense vs MeLi que sí); (8) /ai-agents/templates totalmente público sin auth ni tenant; (9) frontend `apps/web/.env.local` y root `.env` contienen secretos reales sin gitignore-trip pero con riesgo alto de exposure por screenshot/leak (ya gitignored, no committed, pero rotación pendiente igual aplica).


### Bugs runtime (15)


- 🔴 **[CRITICAL]** CRITICAL — Secretos Supabase service_role, Meta App Secret, Wompi sandbox keys, DB password y JWT secret quedaron en historia git pushed (commit ***REDACTED-SHA*** .env). El comentario .context/04-next-steps.md L443-446 marca H7 (rotación) como P0 pendiente y H8 (filter-repo) como opcional. Verificación: `git show ***REDACTED-SHA***:.env` muestra los MISMOS secretos que `cat .env` actual (SUPABASE_SERVICE_ROLE_KEY=***SUPABASE_SECRET_REDACTED***, META_APP_SECRET=***META_APP_SECRET_REDACTED***, WOMPI_PRIVATE_KEY_SANDBOX=***WOMPI_PRIVATE_REDACTED***). Founder reporta 'excelentes prácticas en seguridad' pero rotación NO está hecha. Cualquier persona con acceso al repo público (GitHub) puede leer historia y obtener credenciales válidas hoy. Fix: rotar TODAS las credenciales hoy + actualizar Render env + actualizar .env local. Considerar git filter-repo + force-push (destructivo, coordinable).

  - `/home/ansible/workspaces/konvi-platform/.env (vivos hoy) vs git history ***REDACTED-SHA***:.env (committed 2026-04-06); .context/04-next-steps.md:443-446`

- 🟠 **[HIGH]** HIGH — Routers `marketplace.py` con 5 endpoints mutating (POST /link, POST /import, DELETE /link/{id}, PATCH /{id}/status, PATCH /{id}/sync-stock) NO requieren rol owner/manager — cualquier usuario authenticado (incluso operator) puede crear/borrar/desincronizar listings MeLi del tenant. Los demás routers (products, contacts, orders, knowledge_base, conversations, settings, claims, purchases) sí usan require_write_role; marketplace fue olvidado.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/marketplace.py:264,353,377,432,550 — comparar con products.py:194 o contacts.py:266 que sí tienen `_role: str = Depends(require_write_role)``

- 🟠 **[HIGH]** HIGH — `ai_agents` router endpoint POST /api/v1/ai-agents/suggest no requiere role (solo tenant). Genera AI prompts personalizados leyendo contexto del tenant + invoca cascade LLM. Un operator puede consumir presupuesto LLM y extraer info de filosofía/catálogo del tenant. Endpoint GET /templates expuesto sin auth ('endpoint público (no requiere tenant — los templates son globales)' L87) — devuelve estructura interna de templates AI; debería al menos requerir get_current_tenant.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/ai_agents.py:84-97 y 100-105`

- 🟠 **[HIGH]** HIGH — Telegram webhook hace comparación NO constant-time del secret: `if x_telegram_bot_api_secret_token != TELEGRAM_WEBHOOK_SECRET`. Toda otra signature en el codebase usa `hmac.compare_digest` (Meta, Wompi, MeLi). Vulnerable a timing attack sobre el secret. Fix: `if not hmac.compare_digest(x_telegram_bot_api_secret_token.encode(), TELEGRAM_WEBHOOK_SECRET.encode())`.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/telegram_webhook.py:52`

- 🟠 **[HIGH]** HIGH — `scoped_table()` (lib defensa-en-profundidad anti olvido de tenant_id filter) usado solo en 4 callsites vs 319 invocaciones de `supabase.table(...)` directas. La promesa de Plan A.6 (`TenantScopedClient`) no se ejecutó. Aunque inspección manual muestra que la mayoría de queries SÍ aplican .eq('tenant_id', tenant_id) correctamente, no hay protección automática contra olvido futuro. Específicamente preocupa worker.py:455 (update messages by id sin tenant) — si message_id es controlado por externo, riesgo cross-tenant.

  - `/home/ansible/workspaces/konvi-platform/services/api/dependencies/tenant_scope.py (TENANT_SCOPED_TABLES whitelist usado 4 veces); /home/ansible/workspaces/konvi-platform/services/ai-orchestrator/worker.py:439,455 (update por id sin tenant_id filter)`

- 🟠 **[HIGH]** HIGH — Wompi webhook no tiene IP allowlist ni rate-limit. La firma es defensa primaria, pero el handler hace varios SELECTs Supabase y, en caso de huérfano, levanta WARNING + escribe consent/audit logs. Un atacante con payload bien-formado pero secret-equivocado dispara load DB para cada POST (rejected_origin logging, audit insert tentativo, etc.). MeLi tiene `_verify_meli_origin` + `webhook_rate_limit_check`; Wompi y Aveonline y WhatsApp NO. Recomendación: agregar IPAllowlistStrategy (Wompi documentó ranges); para los demás, agregar webhook_rate_limit_check por IP.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/wompi_webhook.py:35-48 (no IP check); aveonline_webhook.py @router.post (no rate-limit); services/connector-whatsapp/routers/webhook.py:95-119 (no rate-limit)`

- 🟠 **[HIGH]** HIGH — `marketplace.py` rollback DELETEs no filtran tenant_id: en `import_meli_item()` los rollbacks tras INSERT fail hacen `supabase.table('products').delete().eq('id', product_id).execute()` sin `.eq('tenant_id', tenant_id)`. Producto recién creado SÍ pertenece al tenant pero el patrón viola defense-in-depth y, si `product_id` fuera referenciable post-rollback (race), un atacante de otro tenant podría aprovechar IDs adivinables. UUID v4 reduce el riesgo pero el patrón debe corregirse por consistencia.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/marketplace.py:648,660,684,685`

- 🟡 **[MEDIUM]** MEDIUM — Habeas Data tokenización PII: `document_number` se almacena PLAINTEXT en `public.contacts.document_number` con columnas aditivas `document_number_hash` y `document_number_last4`. Comentario migration 20260506010000_pii_tokenization.sql L1-8 explícitamente dice 'aditiva' porque 'Wompi consume document_number en claro'. Para Ley 1581 Art. 4 (minimización) la mejor práctica sería tokenizar en Vault + leer just-in-time para Wompi. Estado actual cumple LEGALMENTE pero no es 'excelentes prácticas'. PII tokenize lib (`lib/pii_tokenize.py`) solo expone normalize/hash/last4/mask — NO Vault tokenize. PII en Vault NO implementado para document_number.

  - `/home/ansible/workspaces/konvi-platform/services/api/lib/pii_tokenize.py (solo hash+last4, sin Vault); /home/ansible/workspaces/konvi-platform/supabase/migrations/20260506010000_pii_tokenization.sql:1-8 (aditiva, plaintext intacto)`

- 🟡 **[MEDIUM]** MEDIUM — JWT ES256 fallback (auth.py:60-71): cuando el JWT no es HS256, se delega validación a `sb.auth.get_user(token)` y luego `jwt.decode(token, options={'verify_signature': False})`. La validación es legítima (Supabase confirma firma), pero después se hace decode sin signature verification + se confía en el payload. Si get_user retorna user pero el JWT fue manipulado en claims (ej. tenant_id, app_metadata) tras validación, el decode local no detecta. Supabase get_user retorna el user real basado en sub claim → claims forjados se ignoran efectivamente, pero el código local lee `app_metadata` desde el token decoded UNVERIFIED. Recomendación: leer app_metadata desde el user object retornado por sb.auth.get_user (autoritativo), no del JWT decoded sin verify.

  - `/home/ansible/workspaces/konvi-platform/services/api/dependencies/auth.py:60-71`

- 🟡 **[MEDIUM]** MEDIUM — Wompi webhook BackgroundTask: `_process_wompi_event` corre fuera del request → si lanza excepción tras 200 response, Wompi NO reintenta. La firma se verifica DENTRO del BackgroundTask, no en el endpoint. Esto significa que CUALQUIER atacante puede hacer POST → recibe 200 OK → consume CPU de BackgroundTask. Lo correcto sería verificar firma SÍNCRONA (antes del 200) y solo encolar BackgroundTask si la firma pasó. Hoy el sistema gasta DB lookups + cpu para invalid signatures.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/wompi_webhook.py:36-48 (response 200 antes de verify) vs L123 (verify dentro de BackgroundTask)`

- 🟡 **[MEDIUM]** MEDIUM — `data_subject_request.py` endpoint HTML printable (GET /printable) inyecta `payload` via f-string en HTML. El helper `esc()` (L418-424) escapa &, <, > pero NO escapa `"` ni `'` — un valor como `address` con comilla doble podría romper atributos HTML. Aunque hoy no hay atributos generated-from-payload, el patrón es frágil. Fix: html.escape(s, quote=True).

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/data_subject_request.py:418-424 (función esc local)`

- 🟡 **[MEDIUM]** MEDIUM — CORS configurado con `allow_origins=ALLOWED_ORIGINS` desde env. Si en Render no se configura ALLOWED_ORIGINS, el default es `http://localhost:3000`. En producción si admin olvida setearlo, los browsers de prod no podrán llamar la API → degradado funcional, no de seguridad. PERO: `allow_credentials=True` + posible `allow_origins=['*']` accidental sería brecha. Validar que en Render esté seteado al dominio web real.

  - `/home/ansible/workspaces/konvi-platform/services/api/main.py:70-79`

- ⚪ **[LOW]** LOW — No hay CSRF token protection. FastAPI + JWT Bearer en header mitiga CSRF (cookies SameSite no involucradas en API auth), pero el frontend usa cookies HttpOnly de Supabase para SSR. Server Actions de Next.js dependen del SameSite cookie default — verificar que createServerClient setee cookies con SameSite=Lax/Strict. El admin.ts comment menciona `Secure + SameSite=Strict + HttpOnly` solo en `/api/mfa/recovery-codes/verify` (L14). Cookies de auth principal heredan el default de Supabase SSR — revisar policy.

  - `/home/ansible/workspaces/konvi-platform/apps/web/middleware.ts:11-55 (createServerClient sin set explícito de SameSite); /home/ansible/workspaces/konvi-platform/apps/web/app/api/mfa/recovery-codes/verify/route.ts:14`

- ⚪ **[LOW]** LOW — MeLi webhook usa `_extract_request_ip` que prioriza `x-forwarded-for[0]`. En Render hay LB confiable, pero un cliente externo puede setear ese header → spoofing del IP allowlist es trivial si el server expone esto desde NGINX directo. Validar en Render que el proxy SOBREESCRIBE x-forwarded-for; si no, atacante puede pasar IP allowlist enviando `X-Forwarded-For: 54.88.218.97`.

  - `/home/ansible/workspaces/konvi-platform/services/api/routers/meli_webhook.py:202-211`

- ⚪ **[LOW]** LOW — `reject_if_tenant_deleting` (auth.py:184) skipea GET/HEAD/OPTIONS. Documentado intencional, pero significa que SAR GET printable y EXPORTS pueden hacerse durante grace period. Si tenant en offboarding sigue pudiendo exportar todo el dataset, podría usar grace para data exfil tras revocación de billing. Documentar política comercial explícita o cerrar.

  - `/home/ansible/workspaces/konvi-platform/services/api/dependencies/auth.py:184-186`



### Fuentes de verdad (uso real)


- /home/ansible/workspaces/konvi-platform/.env — secretos vivos hoy (idénticos a git history ***REDACTED-SHA***)

- git show ***REDACTED-SHA***:.env — historia pública GitHub con secretos plaintext

- /home/ansible/workspaces/konvi-platform/.context/04-next-steps.md:443-446 — H7 rotación documentada como P0 pendiente

- /home/ansible/workspaces/konvi-platform/services/api/dependencies/tenant_scope.py — TenantScopedClient implementado pero infra-utilizado

- /home/ansible/workspaces/konvi-platform/services/api/dependencies/auth.py — JWT validation HS256/ES256 + reject_if_tenant_deleting + RUNTIME_ROLES whitelist

- /home/ansible/workspaces/konvi-platform/services/api/lib/webhook_framework/signature.py — strategies HMAC/Wompi/URLToken/IPAllowlist canónicas (subutilizadas)

- /home/ansible/workspaces/konvi-platform/services/api/lib/webhook_secret_manager.py — rotación bcrypt 90d + grace 7d (correcto)

- /home/ansible/workspaces/konvi-platform/supabase/migrations/20260502010000_consent_audit_log.sql — append-only triggers correctos

- /home/ansible/workspaces/konvi-platform/supabase/migrations/20260505010000_retention_policies.sql + 20260605000000 — pg_cron retention OK

- /home/ansible/workspaces/konvi-platform/apps/web/middleware.ts:69-93 — MFA AAL2 enforcement /dashboard/* funcional con fail-open en outage



### Gaps funcionales (7)


- TenantScopedClient existe (Plan A.6) pero adopción real es 4/319 callsites — no es enforcement, es opt-in casi nunca usado

- Rate-limit outbound NO existe (no hay TokenBucket para Meta / Wompi / Aveonline / Resend / Gemini) — solo rate-limit inbound. Una runaway loop en orchestrator podría disparar quotas Meta o Gemini billing spike

- PII tokenization (Vault per-tenant) implementada para credenciales Wompi/Meta tokens pero NO para document_number de contacts (plaintext + hash aditivo)

- Wompi webhook sin IP allowlist (solo signature) — defensa-en-profundidad incompleta vs MeLi que tiene ambos

- Webhook rate-limit aplicado solo a MeLi — Wompi, Aveonline, WhatsApp, Telegram sin rate-limit por IP (DoS amplificación posible)

- Endpoints AI agents (/templates, /suggest) sin RBAC o rate-limit dedicado — riesgo presupuesto LLM

- consent revocation flow: tras `_execute_erase` se anonimiza contact pero `messages.content` y `conversations.customer_phone` mantienen PII histórica (rastreable vía phone_hash en audit) — verificar si retention cron purga messages.content (Ley 1581 Art. 11 finalidad)



### Gaps técnicos (7)


- 319 .table() raw vs 4 scoped_table() — patrón inconsistente. Refactor masivo a `scoped_table` daría mejor postura post-rev109

- Cada router define sus propios queries con .eq('tenant_id', tenant_id) en formato variado — fácil olvidar uno. Caso encontrado: marketplace.py L648,660,684,685 (rollback DELETE sin tenant_id)

- Webhook framework existe (lib/webhook_framework/) pero solo se usa parcialmente — wompi_webhook.py y connector-whatsapp/dependencies/meta.py reimplementan HMAC sin usar HMACSha256Strategy del framework

- telegram_webhook.py:52 — comparación de secret no usa hmac.compare_digest a pesar de que el resto del codebase sí lo usa (5 callsites distintos)

- auth.py:60-71 — ES256 fallback decodifica JWT con verify_signature=False y confía en sb.auth.get_user → comportamiento correcto pero código frágil; mezclar payload no-verificado con tenant_id auth es high-cognitive-load

- compliance/decorators.py describe 8 decoradores Habeas Data pero comentario L29 dice 'NO se aplican a endpoints existentes en este commit' — código existe pero ningún endpoint los usa (gap de aplicación)

- .env y apps/web/.env.local viven en VM local con secretos PROD (no committed pero presentes); cualquier compromiso de la VM lee directamente. Considerar mover a Vault/age/sops



---


## 10. Deuda técnica (monolitos / duplicados / spaghetti)


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: 15-20 días desarrollador senior (no continuos): 3d desbastar monolito orchestrator.py extrayendo helpers a fsm/prompt/outbound/customer (sin tocar lógica); 4d partir agentic/dispatcher.py _run_agentic_full (1901 LOC) en pipeline por estado FSM; 2d crear pact tests para 5 duplicados restantes (observability/tenant_carriers/llm_embed/tenant_payment_methods/carrier_capabilities); 2d refactor wompi_webhook.py por evento; 2d refactor worker.py por job type; 1d limpiar scratch/ + scripts/debug/ + 43 tests test_revNN_* obsoletos (auditar uno a uno); 1d cerrar ruff F821 + reducir baseline 340→250; 2d levantar coverage de dispatcher.py 3.3%→60% + order_cancellation 37%→60% (compliance); 1d política rollback migrations (.down.sql obligatorio o ADR documentando alternativa). NOTA: NO antes del live UAT pendiente de rev. 109 — founder ya tiene gate para merge a main y refactor durante UAT contamina la prueba.


### Estado real (verificado en código)


Repo en plena migración strangler-fig: `agentic/` (nuevo) coexiste con `orchestrator.py` monolito (10,419 LOC, 1 clase, 131 funciones). `tools/` (legacy) y `agentic/tools/` (nuevo) viven en paralelo. Dispatcher nuevo importa el monolito 6+ veces (4 callsites en runtime crítico). Hay 9 módulos duplicados byte-equal cross-services con SOLO 3 pact tests que detectan drift (phone, dane, aveonline_client) — los otros 6 (observability, tenant_carriers, llm_embed, tenant_payment_methods, carrier_capabilities, +__init__ vacíos) NO tienen pact test, drift puede entrar sin detectarse en CI. 150 migraciones SQL, ninguna `.down.sql`, sin política rollback. Coverage 57.9% (debajo del baseline 58.9% declarado en CLAUDE.md). Ruff 340 errores (no 202 como dice CLAUDE.md ni 353 como dice founder) — drift entre baseline y realidad. Tests todos en `tests/` raíz (224 archivos), 43 son `test_revNN_*` históricos potencialmente obsoletos. Suite corre OK (pact phone/dane/aveonline pasan). 10 skips legítimos (bcrypt + golden conversations gated por GEMINI_KEY). Cero archivos .bak/.old/.orig en repo. Único basurero real: `scratch/test_orch.py` (54 LOC, abr-22) + `scripts/debug/` (9 scripts ad-hoc abr-13). 33 archivos con TODO/FIXME/HACK (manejable).


### Bugs runtime (7)


- 🔴 **[CRITICAL]** dispatcher.py reporta solo 3.3% coverage (770 de 796 stmts sin tocar por tests) — _run_agentic_full tiene 1901 LOC y complejidad ciclomática 120. Está en hot path inbound y NO está testeado. Cualquier bug runtime aquí no se detecta en CI.

  - `services/ai-orchestrator/agentic/dispatcher.py:322-2223`

- 🟠 **[HIGH]** orchestrator.observability.py vs api.observability.py byte-equal pero SIN pact test — cambio en uno solo entra a CI verde con servicios divergentes. Mismo patrón para tenant_carriers, llm_embed, tenant_payment_methods, carrier_capabilities (5 archivos sin pact).

  - `services/ai-orchestrator/observability.py + services/api/observability.py (162 LOC c/u)`

- 🟠 **[HIGH]** Ruff baseline declarado en CLAUDE.md=202, env var BASELINE_RUFF_ERRORS=202, pero real=340. CI con --lint falla o no se ejecuta. Hay 2 F821 (undefined-name) — riesgo NameError runtime.

  - `scripts/validate.sh:BASELINE_RUFF_ERRORS=202 vs `ruff check services/` real=340`

- 🟠 **[HIGH]** _handle_optout_if_keyword tiene complejidad 14 — opt-out es compliance Habeas Data. Cualquier branch que falle silenciosamente = violación legal.

  - `services/ai-orchestrator/agentic/dispatcher.py:2605 (~108 LOC)`

- 🟡 **[MEDIUM]** run_agentic_turn complejidad 33 (límite 10) — turn principal del bot agentic. 33 ramas = trampa cognitiva.

  - `services/ai-orchestrator/agentic/agent.py:82`

- 🟡 **[MEDIUM]** Coverage real 57.9% (baseline declarado 58.9% en CLAUDE.md, target J.5=70%) — drift menor pero existe; algunos módulos críticos en zona roja: dispatcher.py 3.3%, observability.py 16%, lib/order_cancellation.py 37%, llm_embed.py 32%, marketplace.py 17.5%, aveonline_webhook.py 25%, wompi_webhook.py 42.5%.

  - `python3.11 -m coverage report (TOTAL 18162 stmts, 7642 miss)`

- 🟡 **[MEDIUM]** 150 migraciones SQL sin .down.sql ni política de rollback documentada — recovery de migración fallida en remote requiere intervención manual riesgosa (memoria del founder ya marca 'feedback_supabase_migrations.md: ledger tiene drift').

  - `supabase/migrations/ (150 archivos, 0 .down.sql)`



### Fuentes de verdad (uso real)


- Inbox depende de orchestrator.py monolito como fuente de verdad de la mayoría de subprocesos (consent, cart recovery, escalation, claims, PII access logging) — pese a que `agentic/state_machine/` se anunció como cierre arquitectónico, el dispatcher nuevo delega al monolito vía 6 import sites distintos.

- Cliente Aveonline duplicado byte-equal en api/ y ai-orchestrator/ — la fuente de verdad real es services/api/integrations/aveonline_client.py (marcado 'master' en pact test); orchestrator copia tras commit. Riesgo bajo HOY (pact test pasa) pero el patrón 'duplicación deliberada' escala mal: cada nuevo módulo compartido necesita pact test manual.

- Wompi como SOT de pago: wompi_webhook.py 1958 LOC concentra verify_signature + handle_approved/declined/voided + generate_shipping_guide — un cambio en cualquier evento toca el archivo entero (acoplamiento).

- Aveonline como SOT de envío: dispersado en services/api/routers/aveonline_webhook.py (25% coverage), services/{api,ai-orchestrator}/integrations/aveonline_client.py (duplicado), tools/shipping_quote_tool.py — sin un domain object centralizador de Shipment con state machine.

- Contactos / consent / habeas-data: lógica dispersa entre orchestrator.py (_record_consent, _log_consent_event, _log_pii_access), api/routers/contacts.py (reactivate_consent 146 LOC) y api/routers/data_subject_request.py (49% coverage) — el founder ya cerró rev. 93-99 Habeas Data pero las funciones siguen en monolito, riesgo de inconsistencia legal.



### Gaps funcionales (5)


- Strangler-fig incompleto: `agentic/dispatcher.py` aún importa `orchestrator.py` en 6 puntos (líneas 175, 224, 336, 474, 2277, 2697) — el monolito sigue siendo dependencia hard. Migración a state machine + per-state agents anunciada como CIERRE ARQUITECTÓNICO pero el dispatcher delega al monolito para casos no triviales.

- Dos sistemas de tools paralelos: `services/ai-orchestrator/tools/` (legacy, 11 archivos, ~6000 LOC) vs `services/ai-orchestrator/agentic/tools/` (nuevo, 12 archivos) — sin plan visible de retirar `tools/` legacy, doble fuente de verdad para catalog/cart/kb/payment/shipping. Riesgo: bug fix en uno no se propaga al otro.

- Pact tests cubren solo 3 de 9 duplicados: faltan pact tests para observability.py (2 copias), tenant_carriers.py (2), llm_embed.py (2), tenant_payment_methods.py (2), carrier_capabilities.py (2). Sin estos, drift silencioso puede entrar — exactamente el patrón que el founder reporta evitar.

- 43 tests `test_revNN_*` (rev71-rev106) en `tests/` raíz, codificando hotfixes/regresiones históricas — algunos pueden ser dead weight si la feature ya tiene test canónico. No hay limpieza programada.

- Sin packaging Python compartido (`packages/python-shared/` planeado en Plan K Sem 12, no creado) — cada nueva utilidad cross-service requiere duplicar archivo + escribir pact test.



### Gaps técnicos (15)


- MONOLITO #1: services/ai-orchestrator/orchestrator.py — 10,419 LOC, 1 clase, 131 funciones, 3767 stmts. Coverage 54.1%. Función _send_outbound_text en línea 1875 (~350 LOC). _build_order_summary_text línea 4638 (~188 LOC). Veredicto: REFACTOR NEEDED — strangler-fig declarado pero detenido; mover por dominio a fsm/, prompt/, outbound/, customer/.

- MONOLITO #2: services/ai-orchestrator/agentic/dispatcher.py — 2,763 LOC. _run_agentic_full línea 322 = 1901 LOC, ciclomática 120 (12x el límite ruff). Es el corazón del bot agentic nuevo y NACIÓ ya como monolito. Coverage 3.3%. Veredicto: REFACTOR NEEDED YA — partir por estado FSM (intent_extraction, slot_filling, tool_dispatch, response_build, persist).

- MONOLITO #3: services/ai-orchestrator/tools/shipping_quote_tool.py — 2,053 LOC. Funciones de 162, 154, 145 LOC. Coverage 75.9% (OK). Veredicto: REFACTOR NEEDED — partir por capability (quote/destination/highlights/rate_compare).

- MONOLITO #4: services/ai-orchestrator/worker.py — 2,026 LOC. Coverage 44.3%. Veredicto: REFACTOR NEEDED — separar por job type (hsm_reminders, processing_attempts, webhook_cleanup, outbound_queue, payment_reminders).

- MONOLITO #5: services/api/routers/wompi_webhook.py — 1,958 LOC con 29 funciones. _generate_shipping_guide_async línea 1226 = 318 LOC. Función inicial en línea 51 = 282 LOC. Coverage 42.5%. Veredicto: REFACTOR NEEDED — separar verify_signature, parse_event, handle_approved, handle_declined, generate_guide en módulos.

- MONOLITO #6: services/api/routers/conversations.py — 1,384 LOC. Función línea 262 = 340 LOC. Coverage 32.3%. Veredicto: REFACTOR NEEDED — partir GET listing / GET detail / takeover / outbound / notes en sub-routers.

- MONOLITO #7: services/api/integrations/aveonline_client.py — 1,158 LOC. Funciones razonables (max 38 LOC). Veredicto: OK POR DOMINIO — cliente HTTP de proveedor justifica tamaño, no spaghetti.

- MONOLITO #8: services/api/routers/integrations.py — 1,062 LOC. Función línea 417 = 202 LOC (aveonline_guide_dry_run). Veredicto: REFACTOR NEEDED MENOR — extraer helpers del endpoint dry-run.

- MONOLITO #9: services/ai-orchestrator/tools/cart_tool.py — 978 LOC. Función línea 67 = 146 LOC. Coverage 68.6%. Veredicto: REFACTOR NEEDED MENOR.

- MONOLITO #10: services/ai-orchestrator/lib/order_cancellation.py — 821 LOC, función línea 218 = 201 LOC. Coverage 37%. Veredicto: REFACTOR NEEDED — flujo cancelación + retracto Ley 1480 merecen módulo dedicado con tests; 37% coverage en compliance es insuficiente.

- DUPLICADOS SIN PACT (drift silencioso posible): observability.py, tenant_carriers.py, llm_embed.py, tenant_payment_methods.py, carrier_capabilities.py — 5 pares byte-equal hoy pero CI no detecta divergencia.

- Basura abandonada: scratch/test_orch.py (54 LOC, sin tocar desde abr-22) + scripts/debug/ (9 scripts ad-hoc: decode_jwt_header.py, find_leaf*.py, test_api*.py, test_meli_token.py, test_shoe_attrs.py — todos abr-13). Recomendación: borrar carpetas enteras (ya están en CLAUDE.md como 'NO leer').

- Sin migrations .down.sql en 150 archivos — recovery requiere intervención humana ad-hoc. Founder ya tiene 'feedback_supabase_migrations.md' por drift de ledger.

- Ruff 340 errores reales vs baseline 202 — drift de 138 errores no contabilizado. Top categorías: 105 B008 (mutable default), 101 B904 (raise sin from), 49 F401 (unused imports), 48 I001 (imports desordenados), 23 C901 (complejidad). Hay 2 F821 (undefined-name) que pueden tronar runtime.

- Coverage real 57.9% vs CLAUDE.md baseline declarado 58.9% — el repo está REGRESANDO en cobertura sin alertar.



---


## 11. Cross-module wiring ("TODO debe estar conectado")


**Prioridad finiquito**: `P1`  

**Esfuerzo estimado**: 5-7 días


### Estado real (verificado en código)


7 de 14 conexiones OK end-to-end (Inbox→Productos, Inbox→KB RAG, Cart→Pedidos snapshot, Pedidos→Wompi correlación, Pedidos→Aveonline guía async, Productos→Stock con reserva Hybrid, Reclamos→Pedidos UI). 6 PARCIALES (Inbox→Cart no es event-sourced verdadero; Inbox→Contactos audit-log solo en reads no en writes; Promociones→Cart sin auto-revoke en mutation; Settings→Runtime con 5min lag; Habeas Data→All sin audit de writes; Analytics→Eventos solo cart_events). 1 ROTA (Canales: solo WhatsApp real; MeLi sin conversation/message inbox; ChannelAdapter registry 100% stubs). Tech debt notable: orchestrator.py 10419L + dispatcher.py 2763L monolitos; aveonline_client.py DUPLICADO byte-idéntico en 2 paths; wompi_client.py con drift; catalog tool wrap del legacy. Producto vendible para WhatsApp B2C single-channel hoy; multi-channel verdadero requiere ~5-7 días.


### Bugs runtime (10)


- 🟠 **[HIGH]** Save-PII tools (_write_contact_update) NO escriben a pii_access_log/consent_audit_log. Habeas Data Ley 1581 exige audit de TODA escritura de PII. Solo get_contact_info y record_consent audit. SaveEmailTool/SaveNameTool/SaveDocumentTool/SaveAddressTool/SaveShippingPhoneTool/SaveContactFieldTool quedan sin trazabilidad legal de WRITES.

  - `services/ai-orchestrator/agentic/tools/contact.py:368-385 (_write_contact_update) — el helper retorna tool_success con audit_metadata pero ese campo NUNCA se consume/persiste en ningún sitio (verificado grep audit_metadata, solo definición en base.py).`

- 🟠 **[HIGH]** Coupons NO se re-validan ni revocan automáticamente cuando el cart muta (remove_item, update_quantity, add_item). Si min_subtotal_cents queda incumplido tras remove_item, el cupón permanece aplicado: total_cents queda incoherente (subtotal nuevo + shipping - descuento viejo). Solo revoke_coupon manual o via intent del cliente.

  - `services/ai-orchestrator/tools/cart_tool.py:467-516 remove_item recompute subtotal pero NO llama revoke_coupon ni validate_coupon_applicable. Mismo gap en update_item_quantity:427-464 y add_item:367-424.`

- 🟡 **[MEDIUM]** ChannelAdapter registry registra TODOS los canales como _StubAdapter (whatsapp, meli, telegram, web, messenger, instagram, sms). send_outbound retorna error STUB_ADAPTER. WhatsApp real funciona vía whatsapp_sender legacy bypassing el registry. No hay cross-channel continuity real — get_channel_adapter('whatsapp').send_outbound() retornaría error.

  - `services/api/lib/channels/__init__.py:130-136 — 7 register_channel(name, _StubAdapter(name)). _StubAdapter.send_outbound línea 103-114 retorna ok=False.`

- 🟡 **[MEDIUM]** MeLi webhook NO crea filas en conversations/messages — solo procesa orders + shipments + upsert contacts. Cliente MeLi no tiene continuidad de chat en Inbox unificado. conversations.channel default 'whatsapp' significa que MeLi solo entra como contact+order pero NO como conversación interactiva.

  - `services/api/routers/meli_webhook.py:491-570 _process_order solo toca tabla orders/order_items/contacts; sin insert en conversations/messages.`

- ⚪ **[LOW]** WhatsApp persist_or_resolve_conversation NO setea channel='whatsapp' explícito al insertar conversation row. Funciona por DEFAULT 'whatsapp' del schema pero rompe principio explícito y bloquea futuro multi-canal sin migración.

  - `services/connector-whatsapp/services/db_persistence.py:154-159 insert solo tenant_id/customer_phone/status; falta channel='whatsapp'.`

- ⚪ **[LOW]** Wompi webhook APPROVED NO emite cart_events.order_confirmed. El evento order_confirmed solo se emite en orders.py:545 (cuando frontend Inbox crea orden) y en payment_link_tool:677 (COD). El path Wompi APPROVED → confirm_order omite el cart_events emit. Inconsistencia: COD emite, Wompi NO.

  - `services/api/routers/wompi_webhook.py:224-230 _confirm_order — sin cart_events.insert con event_type='order_confirmed'.`

- ⚪ **[LOW]** No existe tabla product_categories (founder mencionó en pregunta). Categorías se derivan por heurística title-head-word (catalog.py:_extract_category_head línea 129) con stemming ES simple. No hay taxonomía formal, no hay relación many-to-many product↔category. Si tenant requiere navegación por categoría rica, falta el modelo.

  - `supabase/migrations/20260406181236_catalog_schema.sql — solo tabla products + product_variations. NO product_categories. services/ai-orchestrator/agentic/tools/catalog.py:122-167.`

- ⚪ **[LOW]** No existen tablas order_events ni payment_events (event sourcing para analytics). Solo cart_events (rev. 104 F1-6). Métricas de dashboard leen orders/messages/conversations raw — sin event log per-pedido (status changes, refunds, retries, etc).

  - `Sin migraciones order_events/payment_events en supabase/migrations/. apps/web/app/dashboard/(analytics)/metrics/page.tsx:62-68 consulta tablas materializadas, no event log.`

- 🟡 **[MEDIUM]** aveonline_client.py DUPLICADO byte-idéntico (1158 líneas) en services/api/integrations/ y services/ai-orchestrator/integrations/. Drift risk alto — un fix en una capa no se propaga. Patch dane_resolver reciente (rev109) tuvo que aplicarse en ambos sitios.

  - `services/api/integrations/aveonline_client.py (1158L) y services/ai-orchestrator/integrations/aveonline_client.py (1158L) — diff -q vacío (idénticos).`

- ⚪ **[LOW]** Settings UI (apps/web/app/dashboard/settings/actions.ts) escribe directo a tenant_payment_methods sin invalidar el cache TTL 5min del orchestrator (lib/tenant_payment_methods.py:209 invalidate_cache existe pero NO se invoca desde el web app). Founder cambia método de pago → bot tarda ≤5min en respetarlo.

  - `services/ai-orchestrator/lib/tenant_payment_methods.py:35-118 TTL 5min. apps/web/app/dashboard/(settings-group)/settings/actions.ts:143 escribe sin notificar invalidación.`



### Fuentes de verdad (uso real)


- Inbox → Productos: OK — agentic/tools/catalog.py:64 lee ctx.catalog_cache, ese cache lo precarga dispatcher.py:485 vía tools/catalog_tool.py:get_tenant_catalog que SELECT products + product_variations filtra tenant_id + status=active. Precios al día (read real-time, no LLM). NO usa product_categories (tabla no existe).

- Inbox → Cart: PARCIAL — add_to_cart/remove/update llaman cart_tool con RPC cart_add_item (atomic UPSERT) + emit cart_events append-only. Pero cart_events ES TELEMETRÍA, NO source of truth: estado materializado vive en conversation_carts. NO es event-sourced real (replay desde events no reconstruye estado).

- Inbox → Contactos: OK get_contact_info — agentic/tools/contact.py:80-125 lee + escribe pii_access_log. Save-* tools tienen consent gate (_verify_consent_or_fail:340) ANTES de _write_contact_update. ROTO: writes a PII no auditan habeas data audit log.

- Inbox → KB: OK — agentic/tools/knowledge.py:KbQueryTool registrado vía register_tool, presente en tools_subset (7/9 states). RAG real con pgvector embeddings via tools/kb_tool.py:get_tenant_kb_rag (line 145) + match_kb_documents RPC.

- Cart → Pedidos: OK — services/api/routers/orders.py:122-246 create_order snapshot precios congelados en order_items (unit_price del cart al momento de crear, unit_cost lookup product_variations.cost_price). Idempotente vía request_hash.

- Pedidos → Wompi: OK — payment_link_tool:_find_pending_order idempotencia, POST /api/v1/orders/{id}/payment-link crea link Wompi con order_id. wompi_webhook:_get_order_id_by_link correlaciona via wompi_link_id. APPROVED → _confirm_order + _decrement_stock_on_confirm + notify cliente.

- Pedidos → Aveonline: OK — wompi_webhook:266-318 invoca _generate_shipping_guide → _generate_shipping_guide_async (async/await). Crea shipment row en cualquier caso: si ok='labeled'/'simulated' con tracking; si error='pending_generation' para operador.

- Productos → Stock: OK — _decrement_stock_on_confirm (orders.py:618-708) lee order_items, decrementa product_variations.stock_quantity, registra stock_movements (delta, new_stock, reason='sale', order_id idempotencia). Stock Reservation Hybrid (rev109 D.5) IMPLEMENTADO: agentic/tools/cart.py:350-373 reserve(TTL_CART_SOFT_MINUTES=15) en add_to_cart; consume vía rpc_stock_reservation_consume en confirm.

- Promociones → Cart: PARCIAL — apply_coupon/revoke_coupon en api/lib/coupons.py + pre-LLM coupon_intent detector en dispatcher.py:984. ROTO: cart mutations no re-validan ni revocan automáticamente si subtotal cae bajo min_subtotal_cents.

- Reclamos → Pedidos: OK — claims.order_id FK, router POST /api/v1/claims/ valida order belongs_to_tenant. UI inbox/_components/context-panel.tsx:300-306 muestra open_claims en context lateral.

- Canales → Inbox: ROTO — solo WhatsApp tiene path inbound→conversations/messages real. MeLi webhook crea contacts+orders pero NO conversations. Telegram webhook es operator-only (comandos /resolver /estado). ChannelAdapter Registry todos STUB excepto bypass legacy whatsapp.

- Settings → Runtime: PARCIAL — TTL cache 5min funcional, pero settings UI no notifica invalidación → propagación ≤5min latency.

- Habeas Data → All: PARCIAL — record_consent escribe consent_audit_log. get_contact_info escribe pii_access_log. Save-PII writes NO auditan (gap legal).

- Analytics → Eventos: PARCIAL — solo cart_events existe (telemetría append-only). NO order_events, NO payment_events. Métricas leen tablas materializadas raw (orders/messages/conversations).



### Gaps funcionales (7)


- Coupon auto-revoke en cart mutation: si remove_item baja subtotal_cents bajo coupon.min_subtotal_cents, el cupón queda aplicado de forma incoherente. Necesita hook en remove/update/add que llame validate_coupon_applicable y si no_met → revoke_coupon + emit coupon_revoked + notificar.

- Cross-channel customer chat: MeLi NO se integra con conversations/messages del Inbox. Cliente que pregunta por chat MeLi no aparece en Inbox unificado. Si se promete multi-canal, falta MeLi messages adapter.

- ChannelAdapter pluggable: registry existe pero TODOS los adapters son stubs. WhatsApp real bypassa el registry vía whatsapp_sender legacy. Para que la pluggability sea funcional falta WhatsAppAdapter real que sustituya el stub.

- PII writes audit (Habeas Data): los 6 SaveTool no escriben pii_access_log ni consent_audit_log con event='updated'. Ante auditoría SIC, no hay trazabilidad de cuándo se modificó qué campo PII.

- Cache invalidation desde settings UI: editar métodos de pago en /dashboard/settings tarda ≤5min en propagarse al bot. Falta llamada explícita a invalidate_cache desde la server action de settings o flag de last_modified per tenant.

- Order/Payment event sourcing: para analytics ricos (funnel pagos, tasa retry, SLA Wompi), falta order_events + payment_events. Hoy solo cart_events (que NO es event-sourced verdadero — estado vive en conversation_carts).

- Wompi APPROVED emit cart_events.order_confirmed: inconsistencia con COD que sí lo emite. El ledger queda incompleto si el pago fue por link Wompi.



### Gaps técnicos (9)


- MONOLITO services/ai-orchestrator/orchestrator.py 10419 líneas — legacy pre-agentic, sigue activo en paralelo a dispatcher.py. Drift entre dos paths (orchestrator legacy + agentic dispatcher) es alto.

- MONOLITO services/ai-orchestrator/agentic/dispatcher.py 2763 líneas — handler único con coupon detector + variant detector + state resolver + tool invocation inline. Difícil de testear sin replicar contexto entero.

- DUPLICATE aveonline_client.py byte-idéntico en services/api/integrations/ (1158L) y services/ai-orchestrator/integrations/ (1158L). Patches recientes (rev109 DANE resolver) tuvieron que aplicarse en ambos. Riesgo drift confirmado en HISTORY de commits.

- DRIFT wompi_client.py — versiones distintas (api=760L vs orchestrator=100L). El stub de orchestrator (100L) podría no implementar todas las features del cliente API.

- Catalog_tool DUPLICADO de concepto: services/ai-orchestrator/tools/catalog_tool.py (legacy func get_tenant_catalog) + services/ai-orchestrator/agentic/tools/catalog.py (ListCatalogTool agentic) — ambos siguen activos. Agentic wrap-ea al legacy.

- cart_events ledger NO está siendo usado para reconstruir estado (no es event-sourced verdadero). El nombre induce a error: es telemetría append-only en paralelo a conversation_carts (materialized). Si el founder espera ES real, falta reproyección.

- _write_contact_update retorna tool_success(audit=...) pero `audit_metadata` se descarta en todos los callers (verificado: solo 3 referencias en codebase, 2 en base.py def). Diseño dead-code.

- ChannelAdapter Protocol con TODOS los adapters stubs — la pluggability está documentada pero no implementada. Si no se va a desarrollar pronto, considerar quitar para reducir confusión.

- Settings actions.ts escribe directo a tablas via Supabase client (sin pasar por API gateway). No hay hook de invalidación. Anti-patrón: bypass del API layer rompe single source of truth de business rules.



---


## 12. Storefront readiness (back para tienda web pública)


**Prioridad finiquito**: `P2`  

**Esfuerzo estimado**: 28-42 días dev (5.5-8.5 semanas, NO <2 semanas como hipótesis founder). Desglose por fases:

FASE 0 — Decisiones arquitectónicas + ADRs (3-5 días, BLOQUEANTE):
  • ADR-0024 Storefront público: routing slug vs subdomain, anon_key vs service_role pattern, guest cart strategy (ConversationStub vs cart desacoplado).
  • ADR-0025 Cross-channel identity reconcile: email-based merge contacts.
  • Specs Pydantic + OpenAPI de los 8-10 endpoints public/.

FASE 1 — Schema unblockers (3-4 días):
  • Migration: tenants ADD slug TEXT UNIQUE + storefront_enabled BOOL + storefront_settings JSONB + domain TEXT UNIQUE NULL.
  • Migration: conversations.customer_phone → NULLABLE + sender_id TEXT NOT NULL (backfill phone → sender_id) + CHECK channel-aware.
  • Migration: conversation_carts ADD session_id TEXT NULL para guest carts (idx único parcial).
  • Migration: bucket product-images público + RLS por tenant.
  • cart_events constantes: web_session_started, web_checkout_started, web_payment_initiated, web_payment_completed.

FASE 2 — Public routers core (5-7 días):
  • routers/public/__init__.py con prefix /api/v1/public.
  • routers/public/catalog.py — GET /{slug}/products listing + detail. Rate-limit-by-IP. Resolver slug → tenant_id con cache.
  • routers/public/cart.py — guest cart CRUD con session_id (cookie / localStorage). Rate-limit-by-IP estricto.
  • routers/public/shipping.py — guest quote (Aveonline) con rate-limit + captcha gate.
  • routers/public/checkout.py — POST genera order + payment_link, retorna checkout_url. Reusa lógica orders.py + payment_link_tool.
  • routers/public/orders.py — GET /{slug}/orders/{token} para tracking sin login (token corto firmado).

FASE 3 — Cross-cutting hardening (4-5 días):
  • Captcha gate (hCaptcha/Turnstile) en POST endpoints public/.
  • CORS dinámico por tenant.domain (middleware).
  • IP rate limiting aplicado consistentemente (security.py:webhook_rate_limit_check pattern).
  • Cache de slug→tenant_id resolution (TTL 60s in-memory).

FASE 4 — Channel Registry real wiring (4-5 días, OPCIONAL si web no usa chat):
  • WebChannelAdapter real (parse_inbound desde browser POST, send_outbound vía SSE/WebSocket).
  • Refactor orchestrator._send_outbound_text + agentic/dispatcher → Channel Registry pattern.

FASE 5 — Email notifications + tracking (3-5 días):
  • Resend integration (planeado Sem 11 plan K).
  • Order confirmation + payment receipt + shipping events emails.

FASE 6 — apps/web/app/shop/[tenant-slug] UI (5-7 días, fuera del backend):
  • Páginas Next.js consumiendo backend public/.
  • SEO metadata + sitemap + structured data.

RECOMENDACIÓN: NO arrancar hasta tener (a) ADRs Fase 0 firmados, (b) Lucams >30 órdenes/mes manual validados (prereq founder), (c) decisión clara: tenant-storefront (B2B SaaS feature) VS Konvi-storefront-propio (vende productos founder) — porque cambian estrategia, slug routing, branding y prioridades.

P2 (no P1) porque hoy NO bloquea producción Konvi (WhatsApp + MeLi son los canales activos). Pasa a P1 cuando Lucams piloto o tenant comercial específico pida storefront propio.


### Estado real (verificado en código)


NO LISTO PARA STOREFRONT PÚBLICO — arquitectónicamente preparatorio, funcionalmente bloqueado. Hallazgos verificados leyendo código + migrations:

1. APIs PÚBLICAS: ZERO endpoints public/. Todos los routers usan `Depends(get_current_tenant)` que exige JWT con `app_metadata.tenant_id` (auth.py:97-105). NO existe `/api/v1/public/{tenant_slug}/products`, NO existe `/api/v1/public/{tenant_slug}/cart`, NO existe `/api/v1/public/{tenant_slug}/checkout`. main.py:102-138 incluye 18 routers — ninguno público. apps/web/app/ tiene solo dashboard/auth/login — NO existe `shop/[tenant-slug]/`.

2. TENANTS sin slug público. tenants schema (initial_schema.sql:2-9) = {id, name, status, meta_waba_id, timestamps}. No hay `slug`, `public_handle`, `storefront_enabled`, `domain`. Sin resolver tenant_slug → tenant_id, no hay routing público posible.

3. conversations.channel SÍ permite 'web' (migration 20260609000000) con default 'whatsapp'. PERO conversations.customer_phone TEXT NOT NULL (20260406181237:5) es bloqueante — un shopper web anónimo NO tiene phone. Channel registry es PURE DOCS sin reality check del schema.

4. conversation_carts NO tiene campo channel ni session_id. Schema (20260501000000) ata el cart 1:1 a conversation_id, y conversation requiere customer_phone. NO existe noción de "guest cart" sin phone. cart_events.event_type es TEXT libre (extensible), pero no hay constantes ni emisores para web_checkout_started / web_payment_initiated.

5. Channel Registry pluggable: estructura SÍ existe (services/api/lib/channels/base.py + __init__.py) con Protocol + register_channel + stubs registrados ('whatsapp','meli','telegram','web','messenger','instagram','sms'). PERO TODOS son `_StubAdapter` que retornan `STUB_ADAPTER` 'not implemented'. Crítico: orchestrator.py:15 hardcodea `from whatsapp_sender import send_whatsapp_message` y NUNCA llama `get_channel_adapter()`. El registry es decorativo — el código no lo consume. Lo mismo en agentic/dispatcher.py:1388,2728 y multimodal.py:168.

6. payment_link_tool: 100% channel-agnostic en su lógica core (no menciona 'whatsapp' en payment_link_tool.py). Genera link Wompi a partir de order_id+amount. PERO el flujo de invocación está acoplado a conversation_id (lookup en orders.conversation_id) → para web requeriría crear conversación sintética. orders.py:124 `create_order` requiere JWT tenant — no hay variant pública.

7. Wompi webhook (routers/wompi_webhook.py): es público (sin JWT, validado por HMAC events_key) — funciona para web igual que WhatsApp. checkout_url generado funciona desde cualquier browser. UN punto a favor.

8. Supabase Storage: 2 buckets existentes — `consent-evidence` (privado) y `offboarding-archive` (privado). NO existe bucket `product-images` público para servir assets de catálogo desde CDN. cover_image_url / image_url son TEXT libres (products.py:57,65) sin política de subida ni CDN público.

9. Rate limiting: build_rate_limit_dependency requiere JWT (rate por tenant). `webhook_rate_limit_check` (security.py:220) sí soporta rate-by-IP sin auth — usable para endpoints public, pero NINGÚN endpoint público lo invoca aún. No hay anti-DOS, captcha ni circuit breakers para shoppers anónimos.

10. Cross-channel reconcile: contacts.email index existe (20260424300000) → técnicamente se podría linkear contact_web ↔ contact_whatsapp por email. PERO no hay lógica que lo haga. conversations son por phone canon (lib/phone digits-only), y orchestrator usa phone como sender_id (no email).

11. Plan I.1 ("Storefront base") está explícitamente diferido en .context/04-next-steps.md:126 — "preparación arquitectónica solo (founder pidió diferir UI)". Camino D (Konvi Studio para Lucams) está post-Sem 14+ con prereq comercial: Lucams debe alcanzar >30 órdenes/mes manual ANTES de invertir.

VEREDICTO: el backend está en estado "scaffolded but unwired". Channel Registry vacío, ZERO endpoints públicos, conversations atadas a phone, sin slug en tenants. Un dev nuevo NO puede construir storefront en <2 semanas — necesitaría 4-6 semanas minimum.


### Bugs runtime (9)


- 🔴 **[CRITICAL]** conversations.customer_phone TEXT NOT NULL bloquea canal 'web' — la migration 20260609000000 agregó .channel pero NO relajó customer_phone. Un INSERT con channel='web' y customer_phone=NULL falla. Channel Registry permite 'web' pero el schema lo prohíbe.

  - `supabase/migrations/20260406181237_conversational_schema.sql:5 + 20260609000000_conversations_channel.sql:33`

- 🟠 **[HIGH]** Channel Registry (lib/channels/__init__.py:130-136) registra 7 adapters TODOS como _StubAdapter — todos retornan ok=False con error_code='STUB_ADAPTER'. Si algún caller real invoca get_channel_adapter('whatsapp').send_outbound() asumiendo backwards-compat con whatsapp_sender, falla silenciosamente. El docstring promete 'backward-compat total' pero el stub deniega por defecto.

  - `services/api/lib/channels/__init__.py:87-136`

- 🟠 **[HIGH]** Orchestrator.py:15 + agentic/dispatcher.py:1388,2728 + multimodal.py:168 hardcodean `from whatsapp_sender import send_whatsapp_message` — el Channel Registry diseñado en rev. 109 NO se consume en ningún call-site real. Agregar canal 'web' requiere reescribir ~6 imports + lógica de fanout.

  - `services/ai-orchestrator/orchestrator.py:15 + agentic/dispatcher.py:1388,2728 + agentic/multimodal.py:168`

- 🟠 **[HIGH]** tenants table sin campo slug/public_handle/storefront_enabled. Sin ALTER TABLE tenants ADD COLUMN slug TEXT UNIQUE, no es posible routear /shop/[tenant-slug] → tenant_id. Tampoco existe RPC pública tipo `resolve_tenant_by_slug`.

  - `supabase/migrations/20260406181235_initial_schema.sql:2-9`

- 🟡 **[MEDIUM]** conversation_carts.contact_id es nullable y la única vía a tener cart es vía conversation_id (FK NOT NULL). Para guest checkout (sin contact previo) no hay path — habría que crear contact stub + conversation stub con customer_phone fake. cart_tool.add_item asume conversation viva.

  - `supabase/migrations/20260501000000_conversation_carts.sql:17-67`

- 🟡 **[MEDIUM]** Sin bucket Storage público para imágenes de producto. products.cover_image_url / product_variations.image_url son TEXT libres sin política de subida. Tenant que sube imágenes hoy lo hace contra terceros (?) — no hay flujo documentado y no hay CDN público propio.

  - `supabase/migrations/20260406181236_catalog_schema.sql + products.py:57`

- 🟡 **[MEDIUM]** rate_limit_hit RPC requiere user_id o key derivada de JWT. Para endpoints public (sin JWT) hay que usar `webhook_rate_limit_check` (security.py:220) por IP, pero el patrón NO está aplicado a ningún router público — debería ser invocado en cada handler /public/* antes de procesar request.

  - `services/api/dependencies/security.py:220-247`

- 🟡 **[MEDIUM]** CORS allow_origins viene de env ALLOWED_ORIGINS = 'http://localhost:3000' default. Para storefront público multi-tenant (cada tenant podría tener dominio custom o subdominio), CORS estático rompe. Necesita resolver origen dinámicamente o whitelist por tenant.

  - `services/api/main.py:70-79`

- ⚪ **[LOW]** reject_if_tenant_deleting (auth.py:157) está aplicado vía _OFFBOARDING_GATE a TODOS los routers excepto webhooks. Endpoints public/ deberán heredar el mismo gate (no permitir compras durante offboarding) pero el gate hoy depende de JWT — habría que reescribir variant pública que resuelva tenant_id desde URL slug.

  - `services/api/dependencies/auth.py:157-225 + main.py:22`



### Fuentes de verdad (uso real)


- products + product_variations (SoT catálogo) — listo para exponer público (status='active' filter + ocultar SKU interno).

- conversation_carts + conversation_cart_items + cart_events (SoT cart) — atado a conversation/phone, requiere refactor para guest carts.

- orders + payments (SoT transacción) — POST /orders requiere JWT, payment-link es agnóstico de canal pero requiere order_id + tenant JWT.

- Wompi webhook (public) — único endpoint sin JWT que ya funciona y aplicaría al flujo web sin cambios.

- contacts.email index (20260424300000) — base técnica para cross-channel reconcile, NO aplicado.

- Channel Registry (lib/channels/) — esqueleto pluggable Protocol+register, ZERO adapters reales, NO consumido por orchestrator.

- tenants table — sin slug, sin storefront_settings, sin domain — NO sirve para routing público hoy.

- Aveonline shipping (shipping.py) — disponible solo con JWT, sin variant pública para guest quotes.

- Supabase Storage — 2 buckets privados existentes (consent-evidence, offboarding-archive), CERO bucket público para imágenes de producto/storefront.



### Gaps funcionales (12)


- ZERO endpoints públicos. Hace falta crear router public con al menos: GET /api/v1/public/{slug}/products (listado paginado, filter status='active', sin precio interno), GET /api/v1/public/{slug}/products/{id} (detalle + variations + stock), POST /api/v1/public/{slug}/cart (crear guest cart), POST/PATCH/DELETE /api/v1/public/{slug}/cart/{cart_id}/items, POST /api/v1/public/{slug}/checkout (genera link Wompi, retorna checkout_url), GET /api/v1/public/{slug}/orders/{token} (track pedido con token corto vs JWT).

- Sin Plan A.12 implementado. La doc menciona 'I.1 Storefront base' como diferido — no hay ni ADR ni spec de endpoints, ni Pydantic models, ni schema de tenant.slug ni session/guest token.

- Sin guest checkout flow. Cliente anónimo debería poder: añadir items → entregar email + nombre + dirección → recibir checkout_url Wompi → confirmar. Hoy todo flow asume contact con phone canónico + conversation activa.

- Sin cross-channel reconcile real. Si cliente compra en web con email X y luego escribe por WhatsApp con phone Y, NO existe lógica que linkee contact_web ↔ contact_whatsapp. Requiere: regla 'contact UNIQUE por (tenant_id, email)' opcional + función merge_contacts cuando email coincide.

- Sin notificaciones email transaccionales. WhatsApp es el único canal outbound real. Para web hace falta Resend/SES (planeado Sem 11 plan K) para: order confirmation, payment receipt, shipping tracking. Hoy si compra es por web, cliente no recibe nada después del Wompi success.

- Sin SEO. Routing público requiere: sitemap.xml, robots.txt, OpenGraph meta tags per product, structured data JSON-LD Product schema, canonical URLs. apps/web/app/ no tiene ni layout para /shop ni metadata generators.

- Sin gestión de imágenes producto end-to-end. No hay endpoint POST /products/{id}/image que suba a Supabase Storage bucket público con políticas RLS por tenant, generate signed URL o serve por CDN.

- Sin variantes 'web-only attribute' (color swatches, size charts). El JSONB products.product_variations.attributes existe pero no hay convención canónica para UI render (e.g. attribute schema con type=color con hex, type=size con order).

- Sin inventory hold para checkout web. stock_reservation.py existe en orchestrator pero está ligado a flow WhatsApp+order_acknowledgment. Web checkout debería: lock stock 10min al iniciar checkout, release si abandono → hoy no aplica.

- Sin captcha / antibot en endpoints públicos. POST /cart/items podría ser abusado con bots — falta integrar hCaptcha / Cloudflare Turnstile.

- Sin tenant.storefront_settings (favicon, primary_color, logo_url, contact_email_public, support_phone). Storefront necesita branding básico per tenant.

- Sin envío sin login (guest shipping). shipping.py:5-8 requiere JWT tenant. Para storefront, shopper anónimo debe poder cotizar envío introduciendo ciudad/dirección — necesita variant pública con rate limit por IP.



### Gaps técnicos (12)


- Channel Registry diseñado pero NO consumido. services/api/lib/channels/ tiene Protocol + register + 7 stubs, pero orchestrator + dispatcher importan directamente whatsapp_sender. Para que registry tenga valor, refactor de ~6 callsites en services/ai-orchestrator/*.py para usar `get_channel_adapter(conv.channel).send_outbound(...)` con fallback al sender legacy.

- Estructura services/api/routers/ es flat — 21 routers en un solo directorio. Para storefront público se sumarían más (public_catalog.py, public_cart.py, public_checkout.py, public_orders.py). Sin subdirectorio routers/public/ se vuelve spaghetti. Mejor: routers/public/__init__.py + routers/private/__init__.py.

- conversations table está sobreajustada al modelo WhatsApp: customer_phone NOT NULL, no hay session_id ni external_sender_id genérico. Schema refactor necesario: customer_phone → NULLABLE + agregar sender_id TEXT NOT NULL (alias con check 'if channel=whatsapp then customer_phone IS NOT NULL').

- conversation_carts asume FSM atado a conversation viva con phone. Para web debería: o crear ConversationStub sintética (hack), o desacoplar cart de conversation con cart.session_id alternativo. Decisión arquitectónica pendiente — sin ADR.

- whatsapp_sender.py es monolito multi-purpose (send text + image + template + credential lookup). Para storefront no se requiere reescribir, pero es ejemplo de cómo NO debería ser un Channel Adapter. La promesa 'pluggable' del registry se queda corta si los adapters reales no se modularizan.

- Sin abstracción de outbound notification cross-channel. Orchestrator emite via WhatsApp; para web habría que: refactor _send_outbound_text (orchestrator.py:1875) para ramificar por conv.channel → Channel Registry → adapter.send_outbound. Hoy es 100% WhatsApp.

- Sin tests de Channel Registry. lib/channels/ no tiene tests asociados (verificable por ls). Cualquier refactor pluggable necesita test suite: registro idempotente, lookup, fallback a stub, encadenamiento con orchestrator real.

- tenant_offboarding gate (auth.py:157-225) hace 1 query DB por write request — para storefront con tráfico anónimo alto sería N writes públicas → N queries adicionales. Necesita cache (in-memory TTL 60s) o gate lazy.

- wompi_webhook.py correlaciona tenant via order_id. Para web, igual funciona — PERO no hay test de fl ujo end-to-end web shopper → checkout → webhook → order confirmation → email notification, porque no existe la pieza email.

- ALLOWED_ORIGINS estático en main.py:70. Multi-tenant storefront con dominios custom (e.g. tienda.lucams.co) necesita CORS dinámico vía middleware que lookea tenant_domain en tenants table. Pattern no existe.

- Sin separación service_role vs anon_key en API server. Hoy todos los endpoints usan service_role + filter tenant_id manual. Endpoints public/ deberían idealmente usar anon_key + RLS para defensa en profundidad (si filter falla, RLS aún protege). Refactor non-trivial.

- Plan I.1 (Storefront base) documentado en context pero sin ADR, sin specs ni roadmap detallado. Founder lo difirió, pero la deuda de NO documentarlo hace que el dev nuevo no tenga punto de entrada.



---


# Plan finiquito producción — propuesto


Esta auditoría es la referencia base. El plan se ejecuta por fases A→D.  

Cada fase produce sub-PRs con tests + ADR (cuando aplique). Branch principal: `develop`.  


## Fase A (6 semanas) — Tapar agujeros bloqueantes go-live


| # | Item | Días | Referencia auditoría |
|---|---|---|---|

| A1 | H7 rotación secretos (Supabase + Meta + Wompi sandbox + DB password + JWT secret) + Vault audit | 1 d founder + 2 d dev | §9 SEC-CRITICAL #1 |

| A2 | Schema drift contact.address (line1 vs street) + business_ops block en system_prompt | 1.5 d | §1 #1 + #2 + #3 |

| A3 | Cotizador: drop columnas inexistentes + decisión founder ELIMINAR historial | 0.5 d | §3 BUG#1 |

| A4 | Reclamos: alinear status API↔UI (CHECK + Pydantic + UI) | 0.5 d | §3 BUG#2 |

| A5 | Save-PII Habeas Data audit log (pii_access_log + consent_audit_log) | 2 d | §11 #1 |

| A6 | scoped_table propagation (4/319 → 319/319) | 4-6 d | §9 SEC-HIGH |

| A7 | RBAC marketplace + ai_agents + telegram constant-time comparison | 0.5 d | §9 SEC-HIGH |

| A8 | Multi-agente router orden de carga (antes pre-LLM resolvers) + fsm_states_allowed enforcement | 1.5 d | §1 #8 + §6 |

| A9 | Contactos drift (server actions → fetch API + alinear Pydantic) | 1 d | §3 HIGH |

| A10 | FakeEscalationInvariant side-effects validation | 0.5 d | §1 #13 |

| A11 | UAT live founder analítico (modo NUEVO + CONOCIDO + multimodal + cancelación) | 1.5 h founder | rev109 sec E.1 |


→ Al cierre Fase A: `develop` → `main` autorizado para producción real con KAIU.


## Fase B (8 semanas) — Conectar lo desconectado + visión founder


| # | Item | Días | Referencia |
|---|---|---|---|

| B1 | Productos: variant images + per-tenant categories + bulk importer backend endpoint | 14 d | §2 #1-#4 |

| B2 | WhatsApp Flows Phase 1: CTA URL button + send_interactive helpers + UTM Wompi | 3-5 d | §1 #4 |

| B3 | Canales MeLi: Q&A + messages + order ack + cross-channel unification | 14 d | §5 |

| B4 | Reclamos refactor superior: assignment + SLA + timeline + Telegram escalación | 5-7 d | §3 sub-4 |

| B5 | Promociones: cupones re-validation + UI Settings → Promociones | 3-5 d | §11 #2 |

| B6 | Finanzas P&L mensual + revenue paid-only + COGS fix + paginación | 8-10 d | §7 |

| B7 | Pedidos: form manual con payment_method + payment_link + address desde contact | 1 d | §3 sub-5 |

| B8 | IA/KB: embedding versioning + handoff consumer + multi-agente templates | 6-8 d | §6 |

| B9 | Config: bucket storage + validation server-side + onboarding wizard 5-7 pasos | 5-7 d | §8 |

| B10 | Compras P1: atomicidad RPC + WAC fix + UI completo | 8-10 d | §4 |


→ Al cierre Fase B: módulos conectados E2E, Konvi operable B2B con 2-3 tenants reales.


## Fase C (4 semanas) — Storefront-ready + hardening final


| # | Item | Días |
|---|---|---|

| C1 | Decomponer `dispatcher.py` (1901 LOC) + `orchestrator.py` (10,419 LOC) | 7-10 d |

| C2 | Coverage `dispatcher.py` 3.3% → 60% | 3-4 d |

| C3 | Pact tests para 5 duplicados restantes | 2 d |

| C4 | Storefront FASE 0-2: ADRs + schema unblockers + routers public/ core | 8-10 d |


## Fase D (post-MVP, según demanda real)


- Storefront FASE 3-6 (~20 d)

- WhatsApp Flows Phase 2-5 (PII Flow + checkout review) — requiere Meta Business Verified

- Multi-agente avanzado: handoff inter-agentes + métricas per-agent

- Compras visión completa: alertas reorder + multi-moneda + landed cost + cuentas por pagar


---


## Política de uso


Este documento es referencia viva durante todo el finiquito.  

Cuando se cierre un item de las fases A-C: agregar checkbox `✅` y commit hash al lado. NO eliminar bugs — marcar `RESUELTO en {commit}`.  

Cuando un item se descubra ser inválido o ya cerrado: marcar `~~tachado~~` con motivo.  


**Re-auditar**: cada 3 meses o tras cierre de fase mayor, re-correr el workflow `exhaustive-konvi-audit-finiquito` y comparar deltas.

---

# Adendas (post 2026-05-31)


## A0.1 — Cierre sesión A0 (2026-05-31 → 2026-06-01)


Items audit cerrados o re-alineados:

- ✅ **A1 — Rotación secrets + Vault audit** — RESUELTO en sesión A0 (2026-05-31 → 2026-06-01). Rotadas: Supabase publishable + secret (sistema nuevo `sb_*`), Meta App Secret + Verify Token, Wompi sandbox keys, DB password, JWT secret legacy, INTERNAL_SERVICE_SECRET, ngrok tokens. Refactor adicional NO previsto en audit: `auth.py` migrado a JWKS ES256 asimétrico (Supabase Signing Keys nuevas), service-to-service auth migrado a `X-Internal-Service-Secret` header (no JWT HS256). Rename repo `commerce-ops-platform` → `konvi-platform`, history limpiada con git filter-repo v2 (literals exactos). Stack reorganizado a `/home/ansible/workspaces/konvi-platform/.local/`.


## §13 — Smoke E2E empírico 2026-06-01 (evidencia post-A0)


Smoke conversación dinámica WhatsApp con cliente CONOCIDO (Cristian García + tenant KAIU). Objetivo: validar A0 NO introdujo regresiones.

**Veredicto A0**: ✅ NO introdujo regresiones. Greeting + cart con qty + variantes + agentic state transitions OK.

**4 bugs pre-existentes detectados** (evidencia empírica reforzando hallazgos §1 Inbox CORE del audit):

| ID empírico | Síntoma | Root cause código | Severidad | Mapea a item Fase A |
|---|---|---|---|---|
| BUG-CATALOG-1 | "muéstrame el catálogo completo" → bot envía foto de UN producto en vez de listar | `tools/image_send_tool.py:173` `is_image_request_query` matchea "muestrame" sin negative override "catálogo/listado/completo" | 🔴 ALTA | A8 (Multi-agente router) |
| BUG-CATALOG-2 | Outbound image enviado a Meta (wamid OK) pero NO persistido en `messages` | `whatsapp_sender.py:120-126` `send_whatsapp_message` con image_link NO inserta en DB; asimetría vs `_send_outbound_text` | 🔴 ALTA | A8 + auditar persistencia outbound |
| BUG-CATALOG-3 | `image_send_tool` elige producto al azar cuando query genérica | Falta disambiguation step "¿de cuál producto querés foto?" | 🟡 MEDIA | A8 |
| BUG-CART-1 | LLM hallucina UUIDs en `add_to_cart` (2/2 con UUIDs distintos: `3976a0a9-…` + `b2e7b0c0-…`). Tool valida correctamente y retorna INVALID_PRODUCT_ID. LLM NO auto-recovera vía `list_catalog` | Falta regla post-INVALID_PRODUCT_ID en system prompt + ausencia de fallback estructural en dispatcher | 🔴 ALTA | A8 (refactor dispatcher) + opcional ADR nuevo: tools accept semantic refs |

**Latencias observadas** (target Plan K J.5: P95 ≤3s / mediana ≤4s):
- Turnos texto-only sin tools reales: 15-45s (3.8x–11x sobre target)
- Turnos con tool real (cart_add): 11s (mejor pero alto)
- Acción: registrar como hallazgo separado de observabilidad — investigar pipeline pgmq + LLM inference + outbound send. NO bloqueante go-live; sí mandatorio antes de marketing proactivo de Konvi.

**Decisión 2026-06-01**: NO fixear estos bugs ad-hoc. Caen en Fase A8 finiquito. UAT pose A8 debe re-cubrir estos 4 turnos exactos como regression suite empírica.


## §14 — Adenda Meta App ownership (NUEVO 2026-06-01, REVISADO 2026-06-01 v2 tras verificación docs Meta vigentes)


> ⚠️ **Versión v1 de este §14 (escrita 2026-06-01 temprano) contenía 2 errores corregidos en v2**: (a) afirmaba "Meta NO permite mover App entre BMs" — incorrecto, Meta SÍ documenta el transfer flow; (b) usaba "Tech Provider model" como sinónimo de "1 App + N tenants" — impreciso, Tech Provider es un programa Meta específico requerido sólo para Embedded Signup (no para el modelo arquitectónico básico).

**Estado actual**: Meta App "Commerce Ops App" (ID `819229210624423`) registrada en **cuenta personal Facebook del founder** (NO en un Business Portfolio). El Business Portfolio "Kaiu Natural Living" existe y aloja el **System User commerce-ops** + WABA + phone number de KAIU — pero **NO es owner de la App**. Verificado contra `docs/research/meta-app-architecture-2026-05-08.md` §2.

**Estado objetivo**: Meta App **transferida** a un Business Portfolio nuevo llamado **"Konvi"** (con NIT del founder persona natural, o NIT de entidad jurídica Konvi si se constituye). WABAs per-tenant (KAIU, Lucams, futuros) permanecen bajo sus respectivos BMs, conectadas a la App Konvi via System User access tokens (manual hoy; Embedded Signup futuro si se enrola en Tech Provider Program).

**Por qué crítico**:
1. **Identidad legal correcta**: Business Verification se ejecuta sobre el BM owner de la App. Hoy = cuenta personal = no productizable. Target = BP Konvi = identidad SaaS coherente.
2. **App Review permissions**: `whatsapp_business_messaging` + `whatsapp_business_management` con Advanced access se solicitan bajo el BM owner. Debe ser Konvi.
3. **Multi-tenant escala**: para onboardear Lucams (Sem 14+ per `[[lucams-camino-d]]`) y 3er tenant con onboarding ergonómico, eventualmente Tech Provider + Embedded Signup. Pre-requisito: BM Konvi con BV approved.
4. **System User long-lived tokens**: hoy se emiten desde el BM del tenant (Kaiu Natural Living para KAIU). Correcto — sin cambios.

**Procedimiento migración** (CORREGIDO 2026-06-01 v2 — verificado contra [Meta Transfer Ownership docs](https://developers.facebook.com/docs/development/create-an-app/transfer-an-app/)):

1. Founder crea Business Portfolio nuevo "Konvi" en business.facebook.com (30 min). NIT = personal o entidad según H0.
2. En developers.facebook.com → My Apps → App `819229210624423` → **App Settings → Basic** → sección **"Business Portfolio Ownership"** → click **"+ Business Portfolio"** → seleccionar Konvi del popup.
3. Acción envía **asset claim request** al inbox "Requests/Solicitudes" del BP Konvi.
4. Founder acepta request desde BP Konvi.
5. ⚠️ **Acción irreversible** según doc oficial Meta ("esta acción no se puede deshacer").
6. Rename App: Settings → Basic → App Display Name = "Konvi App". App ID NO cambia.
7. **Smoke test E2E mandatorio**: founder envía mensaje real WhatsApp a KAIU → bot responde → logs sin errores HMAC. Si falla → activar plan contingencia.
8. **Plan contingencia** (App Secret behavior post-transfer NO documentado oficialmente por Meta): si smoke falla, rotar `META_APP_SECRET` + `META_VERIFY_TOKEN` en Render + `.env` + per-tenant `access_token` en Vault. ~1h dev.

**Esfuerzo**: 30 min trámite Meta + smoke test. Total ~1h founder + 1h dev (si smoke pasa) ó 2h dev (si requiere rotación).

**Pre-requisito legal (H0)**: founder decide entre persona natural con NIT personal (cédula+DV) o entidad jurídica (SAS / EU / etc.). Meta acepta ambos. **NO asumir SAS** — corrección 2026-06-01 v2.

**Tech Provider Program — NO incluido en A12**:
- Hoy KAIU funciona en modelo "Direct Provider de facto" (manual System User per tenant). Válido para 1-5 tenants.
- Tech Provider Program es **gating de Embedded Signup automatizado** + 1 App Review única para todos los tenants. Útil cuando pipeline ≥5 tenants self-service.
- **Iniciar paperwork Tech Provider sólo cuando exista pipeline real ≥3 tenants** (no en A12 — diferido a Fase B/C según roadmap).

**Severidad**: 🔴 CRÍTICA BLOQUEANTE multi-tenant productivo. Sin BM Konvi + Business Verification, App Review producción es no-ejecutable bajo identidad Konvi correcta.

**Posicionamiento finiquito**: A12 en Fase A — paralelo a A8/A9/A10 (NO toca código de aplicación; solo config Meta externa + smoke test). Espera Meta BV: 1-3 semanas calendar.


## §14b — Adenda Mode B canonical (REVISADO 2026-06-02 v3 tras ejecución H2.2 + lecciones aprendidas sesión)


### Mode A vs Mode B (clarificación crítica post-H2.2)

| Modelo | Arquitectura | Aplica a Konvi? |
|---|---|---|
| **Mode A — Single-tenant legacy** | Cada tenant tiene su propio App + WABA + System User token autoreferenciados en su propio BP. Funciona para 1 tenant. | NO — es lo que tenía KAIU pre-H2.2. Regresivo respecto al target multi-tenant. |
| **Mode B — Multi-tenant SaaS canónico** | 1 sola App (Konvi App en Konvi BP) + N tenants delegan SUS WABAs vía Embedded Signup. Cada tenant aporta credentials propias en `tenant_integrations.meta`. **Modelo documentado en `meta-app-architecture-2026-05-08.md`**. | SÍ — destino arquitectónico de Konvi. |

### Lecciones aprendidas ejecución H2.2 (sesión 2026-06-02)

Durante la ejecución de H2.2 (transferencia App Kaiu BP → Konvi BP) surgieron caminos transitorios que se evaluaron y descartaron:

1. **Partner business assignment manual (BP Kaiu ↔ BP Konvi sobre WABA)** — intentado, falló con "Unable to assign partner". Hipótesis: Meta requiere BV approved en al menos 1 BP para partner assignment cross-BP. Descartado por bloqueo Meta + por ser Mode A workaround.
2. **Rollback H2.2** (volver App a Kaiu BP) — innecesario; founder argumentó correctamente que la transferencia se ejecutó OK.
3. **Reconfigurar KAIU Chat App (ID `2024793711712790`, en Kaiu BP) como App productiva KAIU** — propuesta evaluada pero descartada. Era regresión a Mode A: configurar Konvi para single-tenant con 1 App por tenant. Opuesto al target Mode B documentado.
4. **Cambiar `META_APP_SECRET` en `.env` a secret de KAIU Chat** — ejecutado pero revertido. Era coherente con Mode A regresivo, incorrecto para Mode B.

**Camino correcto Mode B confirmado**:
1. App `819229210624423` (Konvi App) ya está en Konvi BP ✅ (post-H2.2)
2. `.env META_APP_SECRET` = secret de Konvi App ✅ (revertido a valor original `41eb550c0dad8118ba389fb6822ab2f6`)
3. Pursue **H3 Business Verification** Konvi BP (1-3 sem Meta)
4. Post-BV: **H4 App Review** Konvi App con Advanced Access `whatsapp_business_messaging` + `whatsapp_business_management` (1-2 sem Meta)
5. Post-App Review: **Tech Provider Program enrollment** (1-3 sem Meta)
6. Post-Tech Provider: implementar **Embedded Signup** en Konvi web UI (~5-7d dev)
7. **KAIU se onboardea a Konvi App vía Embedded Signup** — flow self-service desde Konvi web Settings → "Conectar WhatsApp" → popup Meta → autoriza Konvi App a usar WABA KAIU → backend recibe token Business Integration System User → almacena en `tenant_integrations.meta` per tenant
8. **Tenants futuros** (Lucams, etc.) hacen el mismo flow self-service automatizado

### Estado intermedio aceptable (~6-8 sem espera Meta)

- KAIU bot **inactivo** durante la espera Meta. Es aceptable porque KAIU = dev/test environment (founder confirmó 2026-06-02 NO producción real con clientes externos).
- Konvi App + Test Phone Number gratis (Meta asigna automáticamente al agregar producto WhatsApp Cloud API) sirve para development Konvi web Mode B durante este período.
- KAIU Chat App (ID `2024793711712790`) preservada intacta — NO tocar mientras Mode B en curso. Cuando KAIU migre a Konvi App vía Embedded Signup, KAIU Chat queda obsoleta (deferida a delete decision posterior).
- Documentación playbook tenants futuros (`docs/onboarding/tenant-whatsapp-onboarding-konvi.md`) se escribe en paralelo durante la espera Meta.

### Posicionamiento finiquito A12 actualizado

**A12 = MODE B PATH COMPLETO**:
- A12.1 = H3 BV Konvi BP (1-3 sem Meta, paralelo a A2/A6 finiquito)
- A12.2 = H4 App Review Konvi App (1-2 sem Meta, secuencial post-BV)
- A12.3 = Tech Provider Program enrollment (1-3 sem Meta, secuencial post-App Review)
- A12.4 = Konvi web Embedded Signup implementation (5-7d dev, secuencial post-Tech Provider)
- A12.5 = Migrar KAIU a Konvi App + onboard tenants futuros vía Embedded Signup (1d dev + documentación playbook)

**Total esfuerzo A12 v3**: ~6-9 sem calendar Meta + ~6-8d dev. KAIU inactiva durante la espera Meta es aceptable.


## §15 — Reorden Fase A recomendado por dependencias arquitectónicas


El orden A1→A11 del audit es secuencial por número. Por análisis de dependencias reales, se recomienda ejecutar por NIVEL arquitectónico (data → security → compliance → inbox → ui → meta → uat) para evitar refactor doble cuando capa inferior cambia después.

```
NIVEL 0 — FOUNDATION ✅ DONE (A0 2026-05-31 → 2026-06-01)
   A1 Rotación secrets + Konvi rename + JWKS ES256 + S2S auth

NIVEL 1 — DATA LAYER (~1.5d)
   A2 Schema drift contact.address (line1 vs street)

NIVEL 2 — SECURITY CROSS-CUTTING (~5d)
   A6 scoped_table propagation 4/319 → 319/319
   A7 RBAC marketplace/ai_agents + Telegram constant-time

NIVEL 3 — COMPLIANCE LEGAL (~2d)
   A5 Save-PII Habeas Data audit log

NIVEL 4 — INBOX REFACTOR (~3d, incorpora 4 bugs §13)
   A8 Multi-agente router orden carga + fsm_states_allowed
   A10 FakeEscalationInvariant side-effects
   A9 Contactos drift server actions → fetch API

NIVEL 5 — BUSINESS-OPS BUGS (paralelos, ~1d)
   A3 Cotizador drop columns + drop historial
   A4 Reclamos status alignment API↔UI

NIVEL 6 — INFRA META (NUEVO, ~3-4d humano + 1d dev, paralelo con NIVEL 4-5)
   A12 Meta App KAIU BM → Konvi BM + Business Verification (ver §14)

NIVEL 7 — VALIDACIÓN (~1.5h founder)
   A11 UAT live analítico dual-mode (DESPUÉS de A8 — si no, repite §13 bugs)
```

**Total Fase A reordenada**: ~14-17 días-dev + ~5-10 días humanos (Meta + legal V.3-V.5).

**Razón principal**: A6 scoped_table toca 319 archivos. Si se ejecuta tarde, todo refactor previo (A3/A4/A8/A9) se reescribe. Llevarlo a NIVEL 2 (temprano) lo evita.


## §14c — REVISIÓN MAYOR 2026-06-03 — Konvi NO es Partner, Direct Provider per-tenant


**Disparador**: founder identificó que en Meta dashboard la opción elegida fue "Integrate with API" (NO "Become a Partner"). Esto invalida toda la trayectoria Tech Provider que las versiones previas de §14/§14b asumían.


### Decisión arquitectónica definitiva (sesión 2026-06-03)

**Konvi NUNCA será Partner Meta**. Modelo final = **Direct Provider per-tenant**: cada tenant trae su propia Meta App + WABA + Phone Number + System User token. Konvi connector es infraestructura multi-tenant que recibe webhooks de N Meta Apps distintas y enruta por phone_number_id → tenant_id.

Esto es **consistente con cómo Konvi ya maneja Wompi/Aveonline/Telegram**: cada tenant aporta SUS credentials, Konvi backend solo orquesta API calls.


### Tabla A12 reescrita

| # original | Item | Estado bajo nuevo modelo | Acción |
|---|---|---|---|
| A12.1 | H3 BV Konvi BP | ❌ **CANCELADO** — no necesario (Konvi no Partner) | Skip salvo que Konvi quiera su propio Live mode test |
| A12.2 | H4 App Review Konvi App | ❌ **CANCELADO** — solo Konvi Dev test, no para servir tenants | Skip salvo Konvi Live test |
| A12.3 | Tech Provider Program enrollment | ❌ **CANCELADO** — decisión definitiva NO Partner | Skip |
| A12.4 | Konvi web Embedded Signup implementation | ❌ **CANCELADO** — no aplica sin Tech Provider | Skip |
| A12.5 | Migrar KAIU a Konvi App | ❌ **CANCELADO** — KAIU se queda con su KAIU Chat App permanentemente | Skip |
| **A12-NUEVO** | **Refactor connector multi-secret + per-tenant webhook URL** | ✅ NECESARIO | 1-2 días dev |
| **A12-NUEVO** | **Documentar playbook tenant onboarding Direct Provider** (`docs/onboarding/tenant-whatsapp-direct-provider.md`) | ✅ NECESARIO | medio día doc |
| **A12-NUEVO** | **Configurar dominio estable `api.konvi.co` para webhook tenant** | ✅ NECESARIO para producción real | 30 min (Cloudflare DNS + Render Starter reactivación) |


### Plan ejecutable Model B

#### Fase 1 — Restore KAIU tenant_integrations con KAIU Chat creds (yo, ~5 min)
- phone_number_id: `990364080831295`
- waba_id: `2159052118202272`
- app_id: `2024793711712790` (KAIU Chat App)
- app_secret: `1895ac2113e77866574486dbb438e3dd` (KAIU Chat secret, en Vault)
- access_token: regenerar de commerce-ops System User → KAIU Chat App
- verify_token: ej. `konvi-kaiu-direct-2026`
- status: connected

#### Fase 2 — Founder: configurar webhook KAIU Chat (~10 min)
- developers.facebook.com → KAIU Chat → WhatsApp → Configuration → Edit webhook
- Callback URL: ngrok dev (HOY) o `https://api.konvi.co/api/v1/whatsapp/webhook/kaiu` (PROD)
- Verify token: el que se persistió en Fase 1
- Subscribe `messages` field

#### Fase 3 — Founder: regenerar System User token (~5 min)
- BP Kaiu Natural Living → System Users → commerce-ops → Generate Token con KAIU Chat App seleccionada → permisos `whatsapp_business_messaging` + `whatsapp_business_management` → never expires

#### Fase 4 — Refactor connector code multi-secret (yo, ~1-2 días dev)
- `services/connector-whatsapp/dependencies/meta.py`:
  - Eliminar `META_APP_SECRET` global env-var
  - Per-tenant `app_secret_secret_id` lookup en Vault
- `services/connector-whatsapp/routers/webhook.py`:
  - Endpoint path: `/api/v1/whatsapp/webhook/{tenant_id}`
- Tests + smoke E2E
- Consistente con `services/api/integrations/wompi_client.py` pattern

#### Fase 5 — Playbook tenant onboarding (yo, ~medio día)
`docs/onboarding/tenant-whatsapp-direct-provider.md` con 10-12 pasos para tenant nuevo:
1. Crear cuenta Meta Developer
2. Crear Meta App + product WhatsApp Cloud API
3. Configurar webhook URL (Konvi le proporciona)
4. Generar System User token
5. Pasar credentials a Konvi vía Tenant Console UI
6. Smoke test

#### Fase 6 — Pre-producción: dominio estable api.konvi.co (yo + founder, ~30 min)
- Reactivar Render Starter para connector ($7/mes)
- Cloudflare DNS → CNAME `api.konvi.co` → Render endpoint
- Update webhook URLs tenants de ngrok → api.konvi.co/.../webhook/{tenant_id}
- Tenants futuros configuran solo URL permanente


### Trade-offs aceptados (sesión 2026-06-03)

| Pro | Con |
|---|---|
| Konvi NUNCA paperwork Meta extenso | Cada tenant pasa SU OWN BV + App Review (1-3 sem + 1-2 sem Meta) |
| Consistente con patrón Konvi de Wompi/Aveonline/Telegram | Onboarding tenant ~10-12 pasos manual |
| Independencia total tenants | Konvi blind a cambios config tenant en Meta |
| 0 dependencia Tech Provider enrollment | Custodia App Secret tenant requiere DPA |
| No SPOF Tech Provider | Multi-secret HMAC = refactor real (~1-2d dev) |

Founder acepta estos conscientemente.


### Estado dossiers / docs canónicos post-decisión

- `docs/research/meta-app-architecture-2026-05-08.md` — actualizado con §0 Adenda 2026-06-03
- `docs/research/whatsapp-meta-dossier-2026-05-05.md` Refresh 2026-06-01 R.2.3 — outdated en parte (sigue mencionando Tech Provider como destino). Re-leer con lente §14c del audit.
- `memory/project_meta_app_ownership.md` — reescrito 2026-06-03
- `memory/feedback_konvi_not_partner_direct_provider.md` — nuevo, regla operativa


### Referencias

- Workflow profundo 2026-06-03 verificación Model B feasibility (8 agents) — output en `/tmp/claude-1000/.../tasks/wyoyzacnz.output`
- Sesión 2026-06-02/03 documentada en transcript jsonl

**Total esfuerzo §14c Model B**: ~3-4 días dev + ~1h founder + (futuro) reactivación Render. **Ahorra ~6-12 semanas calendar Meta de Tech Provider Program path original**.


## §14d — Plan ejecutable Model B aterrizado (post-audit 9-agent 2026-06-03)

**Trigger**: founder solicitó auditoría exhaustiva pre-refactor. Workflow `wyr6c8f2i` con 7 audits paralelos + adversarial verify + plan synthesis confirmó estado real, identificó hallazgos sorprendentes, produjo plan file-by-file con tiempos realistas. **NO suposición** — cada cambio tiene archivo + línea + evidencia.

**Decisión Q1-Q10 sellada en ADR-0023** (`docs/adr/0023-meta-model-b-direct-provider-per-tenant.md`).

### Hallazgos sorprendentes (verificados live)

| Hallazgo | Evidencia |
|---|---|
| KAIU webhook YA apuntaba a `kaiu-api.onrender.com` (DEAD) — bot KAIU lleva down más de lo pensado | Audit 5 Graph live debug_token |
| Konvi Dev access_token Vault EXPIRADO 2026-06-03 (era temp 24h) | Audit 5 debug_token |
| `saveWhatsApp` server action SOBRESCRIBE credentials (no merge) — destruiría Model B fields si owner KAIU edita | `apps/web/.../integrations/page.tsx:301` |
| `vault_helper.py` NO existe en `services/connector-whatsapp/lib/` (solo `phone.py`) — deploy unit aislado | `ls services/connector-whatsapp/lib/` |
| `status='connected'` filter hace KAIU `pending_token` INVISIBLE al lookup | `dependencies/meta.py:148-149` |
| HMAC validation ocurre ANTES de poder extraer `tenant_id` del path | FastAPI `Depends(verify_meta_signature)` evaluado pre-route handler |
| `tenant_provider_identity` table EXISTE pero está VACÍA (0 filas) | Migration 20260514 nunca poblada |

### Plan de fases (orden estricto)

| Phase | Archivos | Horas dev | Founder | Idempotente | Bloquea |
|---|---|---|---|---|---|
| **0** | `docs/adr/0023-*.md` (Q1-Q10 sellado) | 0.5h | 0.5h review | N/A | TODO downstream |
| **1** | `supabase/migrations/20260622_whatsapp_model_b_backfill_konvi_dev.sql` (NEW) + `scripts/admin/seed_konvi_dev_app_secret_vault.py` (NEW) | 2h | 0 | ✅ Sí (`NOT (credentials ? 'verify_token')`) | Phase 3 |
| **2** | `services/connector-whatsapp/lib/vault_helper.py` (NEW, copy de `services/api/vault_helper.py`) | 0.5h | 0 | ✅ Sí (file copy) | Phase 3 |
| **3** | `services/connector-whatsapp/dependencies/meta.py` (MAJOR REWRITE) + `services/connector-whatsapp/routers/webhook.py` (MAJOR REWRITE) | 28h | 0 | ❌ Atomic deploy | Phase 4-7 |
| **4** | `tests/test_meta_hmac_model_b.py` (NEW reemplaza `test_meta_hmac_per_tenant.py`) | 6h | 0 | N/A | Phase 7 |
| **5** | `scripts/uat/e2e_chat.py` (UPDATE) | 2h | 0 | N/A | Phase 7C/F |
| **6** | `apps/web/.../integrations/page.tsx:297-307` (UPDATE) | 1h | 0 | ✅ Sí (additive) | — |
| **7** | Meta dashboards Konvi App + KAIU Chat (callback URL + tokens + smoke E2E) | 1h asistencia | 5h | ❌ Punto no retorno | Phase 8 |
| **8** | `docs/adr/0023-*.md` (finalizado) + `.context/01-state.md` (rev. 110) + `CLAUDE.md` (referencia ADR) | 4h | 0.5h review | N/A | — |

**Total**: ~44h dev + ~6h founder. Realista: 8-12h sostenidas con paralelización Phases 1+2+6.

### Migrations / scripts a aplicar

```sql
-- supabase/migrations/20260622_whatsapp_model_b_backfill_konvi_dev.sql
BEGIN;
UPDATE public.tenant_integrations
SET credentials = credentials
  || jsonb_build_object(
       'verify_token', 'konvi-dev-direct-2026',
       'integration_role', 'tenant_internal',
       'integration_type', 'direct_provider',
       'webhook_url_path_segment', 'konvi-dev'
     )
WHERE tenant_id = '6115474f-7046-44a8-88ad-182dbf7626a6'
  AND provider = 'whatsapp'
  AND NOT (credentials ? 'verify_token');
COMMIT;
```

Python scripts (one-shot):
1. `scripts/admin/seed_konvi_dev_app_secret_vault.py` — crea Vault secret con `META_APP_SECRET` env + UPDATE `tenant_integrations.credentials.app_secret_secret_id`.
2. `scripts/admin/update_vault_secret.py` — utility rotación tokens.
3. `scripts/admin/seed_kaiu_access_token_vault.py` — Vault create + UPDATE KAIU `access_token_secret_id` + `status='connected'`.

### Compatibility breaks documentados

| Componente | Estado durante refactor | Cuándo se restaura |
|---|---|---|
| KAIU bot | DOWN (ya, webhook stale) | Phase 7E + F |
| Konvi Dev bot | DOWN desde Phase 3 deploy | Phase 7B |
| UAT `e2e_chat.py` | ROTO desde Phase 3 | Phase 5 |
| Tests `test_meta_hmac_per_tenant.py` | FAIL Phase 3 | Phase 4 reemplazo |
| UI `saveWhatsApp` form | sigue funcionando (Phase 6 additive) | — |

**Punto de no retorno**: Phase 3 deploy + Phase 7B (webhook Meta dashboards apuntando a nueva URL).

### Criterios de éxito (definición de DONE)

Ver ADR-0023 §10 "Criterios éxito" — 10 checks específicos verificables.

### Referencias

- ADR-0023: `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md`
- Workflow audit 9-agent: `/tmp/claude-1000/.../tasks/wyr6c8f2i.output`
- Memoria `feedback_konvi_not_partner_direct_provider.md`