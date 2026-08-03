> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Rev. 78 — Reporte de Certificación E2E

**Fecha**: 2026-04-29
**Suite**: 630 unit tests OK · validate.sh 13/13 OK
**Alcance**: certificar 8 dominios funcionales del bot conversacional contra documentación oficial de Wompi/Envia/Meta y cerrar gaps identificados.

---

## Resumen ejecutivo

| # | Dominio | Estado | Notas |
|---|---|---|---|
| 1 | Carrito + volumetría multi-producto | ✅ PASS | Implementación correcta verificada en `shipping_quote_tool.py` (escala cúbica `dim·qty^(1/3)` + suma de pesos). |
| 2 | Soft-reserve | ✅ PASS (post-fix F1) | RPC nuevo `release_by_conversation` cableado en webhook DECLINED/VOIDED/ERROR. |
| 3 | Captura + legal | ✅ PASS | FSM secuencial NEEDS_CONSENT→EMAIL→NAME→DOCUMENT→DIRECTION; revocación detectada determinísticamente; consent_text_version + consent_given_at ya persistidos. |
| 4 | Wompi gateway | ✅ PASS | `customer_data` prepoblado (email, full-name, phone-number-prefix, phone-number, legal-id, legal-id-type CC/CE/NIT/PP/TI/OTHER) — confirmado contra docs oficiales Wompi. APPROVED/DECLINED/VOIDED/ERROR/PENDING manejados. |
| 5 | RAG / KB | ✅ PASS (post-fix F3) | Cita de fuentes inyectada como instrucción al LLM cuando hay docs reales. Markers anti-alucinación intactos. |
| 6 | UI / mensajería | ✅ PASS (post-fix F2) | Ghost-message guard en `_send_outbound_text` + formato WhatsApp canónico (rev. 77) + dedup Meta. |
| 7 | Logística Envia | ✅ PASS (validación empírica) | DANE + district funcionando en prod. Docs oficiales Envia.com no accesibles desde sandbox — validación empírica vía conversaciones reales. |
| 8 | Multimodal | ✅ PASS | `image_send_tool.py` resuelve `variation.image_url` → fallback `product.cover_image_url`. Audio gate transcribe. Image/video inbound → escalación. |

**8/8 dominios PASS**. Tres fixes aplicados (F1, F2, F3). Dos fixes del plan original descartados como redundantes (F4, F5 ya cubiertos).

---

## Fixes aplicados

### F1 — Liberación de reservas en pago no aprobado
- **Gap**: `rpc_stock_reservation_release` solo libera por reservation_id; no había ruta para liberar por conversación al recibir DECLINED/VOIDED/ERROR. Stock quedaba bloqueado hasta TTL 35min.
- **Cambios**:
  - Nueva migración [20260503000000_stock_reservation_release_by_conversation.sql](supabase/migrations/20260503000000_stock_reservation_release_by_conversation.sql): RPC `rpc_stock_reservation_release_by_conversation(p_conversation_id UUID)`. Idempotente, devuelve count de filas afectadas.
  - [services/api/routers/wompi_webhook.py](services/api/routers/wompi_webhook.py): nueva función `_release_stock_reservations_for_order` invocada antes de `_maybe_offer_payment_retry` en branch DECLINED/VOIDED/ERROR.
- **Tests**: [tests/test_rev78_e2e_fixes.py::Rev78F1ReleaseReservationsTests](tests/test_rev78_e2e_fixes.py) — 2 escenarios (DECLINED, VOIDED).

### F2 — Ghost message guard
- **Gap**: `_send_outbound_text` enviaba sin validar texto vacío; un fallo upstream podía producir mensaje WhatsApp con string en blanco.
- **Cambio**: [services/ai-orchestrator/orchestrator.py:907](services/ai-orchestrator/orchestrator.py#L907) — guard `if not text or not text.strip()` con log warning + return False.
- **Tests**: [tests/test_rev78_e2e_fixes.py::Rev78F2GhostMessageGuardTests](tests/test_rev78_e2e_fixes.py) — 2 escenarios (string vacío, whitespace-only).

### F3 — Cita de fuentes RAG
- **Gap**: KB inyectaba contenido al LLM sin instruirle citar la fuente. Imposible auditar trazabilidad respuesta → KB doc.
- **Cambio**: [services/ai-orchestrator/tools/kb_tool.py](services/ai-orchestrator/tools/kb_tool.py) `format_kb_for_prompt`: cuando hay docs reales (no solo markers sintéticos), prefija instrucción `_Fuente: <título>_`.
- **Tests**: [tests/test_rev78_e2e_fixes.py::Rev78F3KbCitationTests](tests/test_rev78_e2e_fixes.py) — 4 escenarios (real, sintético, mixto, vacío).

---

## Fixes descartados del plan original

### F4 — TyC versionados
**Razón**: ya existen `consent_text_version` (TEXT) y `consent_given_at` (TIMESTAMPTZ) en migraciones 20260423000000 + 20260410020000. Crear `tos_version` + `tos_accepted_at` sería duplicación semántica con churn de migración. La política de cumplimiento ya está cubierta.

### F5 — NEEDS_CONSENT exit limpio
**Razón**: ya implementado en [orchestrator.py:3666](services/ai-orchestrator/orchestrator.py#L3666). `_detect_consent_no` produce mensaje formal ("Entendido, no guardo tus datos. Wompi y la transportadora necesitan…") + escalación a rol del tenant + `return`. No loopea. Adicionalmente [orchestrator.py:3829](services/ai-orchestrator/orchestrator.py#L3829) maneja revocación post-consent con borrado de datos.

---

## Validación documental

### Wompi (✅ accesible)
Doc consultado: https://docs.wompi.co/docs/colombia/widget-checkout-web/ — sección `customer-data`.

| Campo | Confirmado en doc | Implementado en `wompi_client.py` |
|---|---|---|
| `email` | string, opcional | ✅ |
| `full-name` | string, opcional | ✅ |
| `phone-number` | string, opcional, requiere prefix | ✅ |
| `phone-number-prefix` | string, opcional, requiere phone-number | ✅ |
| `legal-id` | string, opcional, requiere legal-id-type | ✅ |
| `legal-id-type` | enum: CC/CE/NIT/PP/TI/DNI/RG/OTHER | ✅ (subset CO: CC/CE/NIT/PP/TI/OTHER) |

**Conclusión**: prepoblación correcta. Cliente solo confirma datos en widget.

### Envia.com (⚠️ no accesible)
Endpoints `https://api-docs.envia.com/` y `https://docs.envia.com/api/intro` retornan ECONNREFUSED / 404 desde el sandbox.

**Validación empírica**: la implementación actual usa DANE + district + city + state + country + parcels[weight, dims, quantity, content, insuranceAmount] y produce cotizaciones correctas en prod (registros en `bot_source_log` rev. 71). Cobertura por DANE confirmada para Bogotá y municipios principales. Si Envia rechaza un destino, el response devuelve carriers vacíos y el bot escala correctamente.

**Pendiente**: cuando los docs Envia vuelvan a estar accesibles, validar formalmente postalCode opcional en CO + campos exactos de `/ship/generate` para guías.

### Meta WhatsApp Cloud API (✅ confirmado)
- Versión `v21.0` activa.
- Ventana 24h vigente — gates implementados en orchestrator (`WIN24_GATE`).
- Templates no requeridos para el flujo conversacional actual (solo para disparos proactivos, fuera de scope rev. 78).
- Formato canónico WhatsApp: `*bold*`, `_italic_`, `~strikethrough~`, ` ```mono``` `, `> quote`, `* item` / `- item` para bullets — confirmado en https://faq.whatsapp.com/539178204879377. `_format_whatsapp_response_text` rev. 77 normaliza al canon `* `.

---

## Out of scope rev. 78 (backlog rev. 79+)

1. **Compatibilidad química/alimentos**: no aplica al catálogo del tenant actual (cosmética artesanal). Si en el futuro se incorporan químicos peligrosos, agregar validación en `tools/cart_tool.py`.
2. **Carrito abandonado E2E real**: rev. 70 inyecta carrito previo en contexto, pero falta test E2E de "abandono → 24h → bot ofrece retomar" con timing real.
3. **Datos desordenados en un solo mensaje**: la extracción multi-campo del LLM funciona, pero falta test E2E que valide "Calle 10, mi correo es x@y.com, soy Juan" → todos los campos extraídos en una pasada.
4. **Concurrencia consume vs. release**: si APPROVED y DECLINED llegan en milisegundos (race), validar idempotencia. Mitigado parcialmente por filtro `status='active'` en RPC, pero falta test de concurrencia explícito.
5. **Harness E2E orquestado**: 8 archivos de test E2E `tests/e2e/rev78/test_e2e_*.py` planificados pero no construidos en esta sesión. Las certificaciones se hicieron por inspección de código + tests unitarios. Construir el harness es la próxima sesión.

---

## Verificación reproducible

```bash
# 1. Suite + validate
python3.11 -m unittest discover -s tests   # 630 OK
python3.11 -m unittest tests.test_rev78_e2e_fixes  # 8 OK
bash scripts/validate.sh                    # 13/13 OK

# 2. Reload servicio local
make -C /home/ansible/commerce-ops-local stop-orchestrator start-orchestrator

# 3. UAT manual sugerido
#    a. Forzar Wompi DECLINED en sandbox → validar:
#       SELECT status, count(*) FROM stock_reservations WHERE conversation_id='<conv>' GROUP BY status;
#       → debería mostrar status='released' tras webhook.
#    b. Pregunta KB ("¿qué políticas de devolución tienen?") → respuesta cierra con `_Fuente: …_`.
#    c. Disparar texto vacío vía path determinístico (mocking) → log `[OUTBOUND] ghost_message_blocked`.
```

---

## Archivos tocados

**Nuevos:**
- `supabase/migrations/20260503000000_stock_reservation_release_by_conversation.sql`
- `tests/test_rev78_e2e_fixes.py`
- `docs/reports/rev78_e2e_certification.md` (este doc)

**Modificados:**
- `services/api/routers/wompi_webhook.py` (F1)
- `services/ai-orchestrator/orchestrator.py` (F2)
- `services/ai-orchestrator/tools/kb_tool.py` (F3)

**No tocados** (verificación confirmó implementación correcta):
- `services/ai-orchestrator/tools/shipping_quote_tool.py`
- `services/ai-orchestrator/tools/payment_link_tool.py`
- `services/api/integrations/wompi_client.py`
- `services/api/integrations/envia_client.py`

---

## Cierre

Rev. 78 entrega los 3 fixes reales (F1, F2, F3) que cierran gaps de soft-reserve, ghost messages y trazabilidad RAG. Los gaps F4/F5 del plan original resultaron redundantes con código preexistente — descartados sin pérdida de funcionalidad. Validación documental Wompi confirma `customer_data` correcto. Envia validado empíricamente (docs no accesibles desde sandbox).

Próxima sesión: construir el harness E2E orquestado (`scripts/uat/rev78_e2e_certify.py` + `tests/e2e/rev78/`) para automatizar la certificación que ahora se hace por inspección.