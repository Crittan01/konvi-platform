> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


I now have a complete picture. I have the dossier (Flows = P3-3 "low value"; interactive cta_url = P2-1), the audit ("Plan L Phase 1" = interactive CTA URL button, ~2-3 days, zero migration), the parser (inbound nfm_reply recognized but NOT consumed structurally downstream), the sender (text/image/template only), and the full Inbox health audit. I have everything needed to produce the evaluation.

---

# Evaluación: WhatsApp Flows + In-App Browser en contexto de la salud del Inbox

## TL;DR — Recomendación

**NO ahora.** Cerrar primero los hallazgos Clase A/HIGH del hot-path (FSM, anti-hallucination, idempotencia de envío) y luego abrir Flows **por fases**, empezando NO por Flows sino por su primo barato: `interactive.cta_url` (Plan L Phase 1). Flows propiamente dichos (multi-pantalla cifrados con Data Exchange endpoint) van **al final**, y solo para PII collection — el caso con ROI claro. Carrier selection y payment CTA NO justifican un Flow; se resuelven con `interactive.list` / `interactive.cta_url`, que son 10× más baratos de implementar y operar.

Justificación central: **un Flow introduce un segundo canal de entrada de datos (`nfm_reply`) que hoy el sistema parsea pero NO consume estructuralmente** (parser.py:21-26 extrae `response_json`, pero ningún downstream lo lee — el dispatcher solo ve `[Formulario interactivo recibido]`). Montar Flows sobre la FSM y el guard anti-hallucination actuales —ambos con bugs Clase A confirmados— **propaga la deuda a un canal nuevo y la hace más difícil de auditar**.

---

## 1. Estado real verificado (no asunción)

| Capacidad | Estado en repo | Evidencia |
|---|---|---|
| Inbound `nfm_reply` (respuesta de Flow) | **Parseado pero NO consumido** | `parser.py:21-27` extrae `response_json`; `_extract_message_content` lo colapsa a `"[Formulario interactivo recibido]"` (parser.py:73-74). Grep en `dispatcher.py`/`db_persistence.py`: **0 referencias** a `nfm_reply`/`response_json` downstream. |
| Outbound `interactive.*` (button/list/cta_url/flow) | **AUSENTE** | `whatsapp_sender.py` solo `type=text\|image\|template`. Sin branch `interactive`. |
| "Plan L" | Es el plan del **audit-finiquito**, no un dossier | `audit-finiquito-2026-05-31.md:103,195`: "Plan L Phase 1 (CTA URL button) requiere CERO migration DB". |
| Flows como tal (`interactive.flow`) | Clasificado **P3-3 "bajo valor B2C transaccional"** | `whatsapp-meta-dossier:353`. El dossier mismo lo despioriza. |

**Corrección arquitectónica obligatoria:** el dossier (sec. 3.2, P2-4) describe Flows/onboarding bajo el **modelo Tech Provider + Embedded Signup**. Eso **contradice ADR-0023 y la memoria del proyecto**: Konvi es **Direct Provider per-tenant**, NUNCA Partner Meta. Implicación concreta para Flows: el **Flow asset, el endpoint Data Exchange y la clave pública RSA se registran por-WABA (per-tenant)**, no centralizados en una App Konvi. Esto multiplica el costo de provisioning de Flows por tenant y es un argumento fuerte para diferirlos.

---

## 2. Evaluación por caso de uso

### A) PII collection → **único caso con ROI real para un Flow**
- **Valor:** alto. Hoy la PII se captura en prosa libre vía `save_pii`/`record_consent` (contact.py). Un Flow da: validación de formato client-side (email/documento/dirección), consent checkbox con notice version explícito, y un `response_json` **estructurado** en vez de parsear texto. Ataca directamente dos hallazgos reportados: `has_required_pii` acepta address JSONB parcial (FSM resolver.py:180-188) y el address schema mismatch (`line1` vs `street`) que causa la queja "repite cosas que ya sabe".
- **Pero depende de cerrar antes:** si el Flow entrega `{city: "Bogotá"}` sin línea de dirección, la FSM seguirá saltando PII_COLLECTION→SHIPPING_QUOTE prematuramente. **El Flow no arregla el bug del resolver; lo alimenta más rápido.** Hay que extraer `is_address_shippable(address)` (recomendación del propio audit) ANTES.

### B) Carrier selection → **NO usar Flow. Usar `interactive.list`**
- Es una selección de 1-de-N (cheapest/fastest). Un Flow multi-pantalla cifrado es sobre-ingeniería. `interactive.list` (≤10 rows) resuelve el caso con UX superior al texto actual y sin endpoint/cifrado.
- **Riesgo crítico si se hace mal:** acoplar la selección a IDs de carrier/rate **agravaría los bugs Cart-as-SoT confirmados** — `set_shipping_meta` nulifica `city` (CART-01) y el cross-binding de cart por `updated_at` sin `conversation_id`. Un `list_reply.id` con `rate_id` stale entra directo al link Wompi con shipping desactualizado. **Bloqueado hasta cerrar CART-01.**

### C) Payment CTA → **NO usar Flow. Usar `interactive.cta_url` (Plan L Phase 1)**
- Mejor relación valor/esfuerzo de todo el conjunto: **0 migraciones DB, ~2-3 días**, reemplaza el link plano por un botón "Pagar". Reduce clicks erróneos.
- **Pero choca con un gate HARD hoy ausente en agentic:** el audit confirma que el path agentic LIVE **NO ejecuta `summary-before-link`** (Ley consumidor — el cliente debe ver el desglose antes del link Wompi). Un botón CTA hace el link **más prominente**, amplificando la violación. **Portar ese invariant al set agentic es prerrequisito duro.**

---

## 3. Prerequisitos técnicos / compliance

**Para `interactive.cta_url` + `interactive.list` (los baratos):**
1. `send_whatsapp_message` debe devolver resultado tipado (hoy colapsa permanente/transitorio en `None` → riesgo doble-envío). El nuevo branch `interactive` heredaría ese defecto.
2. Idempotency key estable en el envío (hoy ausente entre `_send_outbound_text` y mark PROCESSED) — un CTA reenviado por el sweep = doble botón de pago.
3. Portar gate `summary-before-link` al path agentic (compliance, bloqueante para payment CTA).

**Para Flows propiamente (PII):**
4. **Data Exchange endpoint per-tenant** con cifrado RSA (clave pública registrada en cada WABA, descifrado AES-GCM del request) + health-check endpoint Meta. **Verificar en doc oficial vigente** versión de Flows API y el `flow_token` lifecycle — no asumir.
5. **Consumir `nfm_reply.response_json` downstream**: nuevo handler en dispatcher que mapee el JSON a `save_pii`/`record_consent`. Hoy ese camino **no existe** — es trabajo nuevo de hot-path, justo donde están los bugs.
6. Idempotencia del `nfm_reply` vía `webhook_event_check_or_register` (que el connector **hoy no invoca** — WH-02).
7. **Migración Graph API v21→v22** (P0-2 dossier) — Flows API moderna lo exige.
8. Compliance Habeas Data: el consent capturado por Flow debe escribir `consent_audit_log` append-only con `consent_notice_version` y actor — reusar `_record_consent`, no inventar path paralelo (ya hay drift entre las 2 implementaciones de consent).

---

## 4. Riesgos

- **Riesgo arquitectónico (alto):** Flows abre un canal de entrada (`nfm_reply`) que **bypassa el flujo conversacional donde viven los invariants**. Si la PII entra por Flow, hay que re-aplicar consent/PII gates en ese canal o se crea un hueco de compliance. Es la misma clase de drift legacy↔agentic ya documentada.
- **Riesgo Clase A (alto):** montar selección de carrier/payment sobre IDs estructurados materializa los bugs latentes de Cart-as-SoT (city nulificada, cross-binding) en pérdida de dinero real (shipping/total incorrectos en el link).
- **Riesgo per-tenant (medio):** endpoint Flows + RSA por WABA bajo Model B = costo de onboarding y superficie de fallo multiplicados por tenant. No hay tooling para esto hoy.
- **Riesgo de fan-out de tests (medio):** los tests del hot-path mockean Supabase y ya enmascararon ≥3 bugs Clase A. Un canal nuevo sin tests de integración reales repite el patrón.

---

## 5. ¿Antes o después de cerrar los hallazgos?

**Después — con una excepción quirúrgica.** Secuencia recomendada:

1. **Cerrar primero (bloqueantes duros):** FSM-1 (`human_takeover` literal) + POST_PAYMENT reachability + PLLM-01/INV-01 (guard UUID lee `variants`) + CART-01 (city nulificada) + portar gates `summary-before-link`/`no-pii-pre-consent` al path agentic + idempotency-key de envío. Todos son S/M y ya tienen rec del audit.
2. **Fase L1 (en paralelo, bajo riesgo):** `interactive.cta_url` para payment — **solo después** del gate summary-before-link. ~2-3 días, 0 migración. Quick win UX real.
3. **Fase L2:** `interactive.list` para carrier — **solo después** de CART-01. UX > Flow, sin cifrado.
4. **Fase L3 (último, opcional):** Flow real para PII collection — solo si la fricción de captura PII en prosa demuestra ser cuello de botella medido, y solo tras `is_address_shippable` + consumo estructurado de `nfm_reply` + endpoint RSA per-tenant. Tratarlo como proyecto propio, no como extensión.

---

## DECISIÓN FINAL
Diferir Flows. Priorizar el cierre de hallazgos HIGH/Clase A del hot-path. Luego entrar por `interactive.cta_url` (payment) e `interactive.list` (carrier) — NO por Flows. Reservar Flow multi-pantalla exclusivamente para PII collection, como F3, tras evidencia de fricción medida.

## VALIDAR EN DOCUMENTACIÓN OFICIAL
- Flows API: versión vigente, `flow_token` lifecycle, cifrado del Data Exchange endpoint (RSA/AES-GCM), health-check requirement. (No asumido.)
- Registro de Flow asset + clave pública **per-WABA** bajo Direct Provider (compatibilidad con ADR-0023 Model B — el dossier asume Tech Provider, que NO aplica).
- `interactive.cta_url`: confirmación de "1 botón URL por mensaje".
- Corte Graph API <v22.0.

## RIESGO
Propagar deuda Clase A a un canal nuevo (nfm_reply) sin invariants; pérdida de dinero por carrier/payment sobre Cart-as-SoT con bugs; hueco de compliance Habeas Data si la PII entra por Flow sin re-aplicar consent gates.

## IMPACTO OPERATIVO
Bajo si se hace por fases tras cerrar hallazgos. Alto y negativo si se monta Flows ahora sobre FSM + guard anti-hallucination defectuosos.

## INTERVENCIÓN HUMANA REQUERIDA
- **RESPONSABLE:** Founder — decidir si la captura PII es cuello de botella real que justifique F3 (Flow), o si `interactive.*` cubre el 90% del valor.
- **INSUMOS:** métrica de fricción en PII collection actual; pipeline de tenants (>1 WABA cambia el costo del endpoint per-tenant).
- **CRITERIO DE ÉXITO:** decisión explícita L1/L2 sí, L3 (Flow) condicionado a evidencia.

**Archivos relevantes:**
- `/home/ansible/workspaces/konvi-platform/services/connector-whatsapp/services/parser.py` (inbound `nfm_reply` parseado, no consumido)
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/whatsapp_sender.py` (outbound solo text/image/template)
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/tools/contact.py` (PII collection actual)
- `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/agentic/tools/payment.py` (payment link, sin interactive)
- `/home/ansible/workspaces/konvi-platform/docs/research/whatsapp-meta-dossier-2026-05-05.md` (sec. 2.3, 5, 6; Flows = P3-3)
- `/home/ansible/workspaces/konvi-platform/docs/research/audit-finiquito-2026-05-31.md:103,195` (Plan L Phase 1)
- `/home/ansible/workspaces/konvi-platform/docs/adr/0023-meta-model-b-direct-provider-per-tenant.md` (Model B — invalida el supuesto Tech Provider del dossier)