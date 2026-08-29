> **⚠️ ARCHIVADO — 2026-08-02.** Contenido histórico superado, conservado solo como registro de decisiones. No usar como referencia operativa. Estado vigente: `.context/01-state.md` y `docs/PLAN.md`.

---


# Auditoría fullstack exhaustiva — Konvi Platform · 2026-07-03

> Generada por workflow multi-agente `konvi-fullstack-review` (16 buscadores especializados por capa × dimensión → dedup → verificación adversarial por lotes contra el código real → re-verificación individual de criticals → triage vs auditoría finiquito 2026-05-31 y backlog).
> Fuente: inspección directa de código en `develop` + `supabase/migrations/` + validación contra documentación oficial vigente. **Nada asumido: cada hallazgo incluye evidencia textual del código y sobrevivió a un verificador adversarial cuyo default era refutarlo.** 148 hallazgos crudos → 133 únicos → **122 confirmados** / 11 refutados (descartados, listados al final).

## Resumen ejecutivo

| Capa | 🔴 Critical | 🟠 High | 🟡 Medium | ⚪ Low | Total |
|---|---|---|---|---|---|
| 1. Base de datos y modelo de datos | 1 | 8 | 11 | 3 | 23 |
| 2. Backend (API · Orchestrator · Connector) | 2 | 13 | 24 | 13 | 52 |
| 3. Frontend (Tenant Console) | 1 | 11 | 19 | 9 | 40 |
| 4. Configuración y buenas prácticas | 0 | 0 | 4 | 3 | 7 |
| **Total** | **4** | **32** | **58** | **28** | **122** |

- **106 hallazgos nuevos** (no rastreados en `docs/research/audit-finiquito-2026-05-31.md` ni en `.context/04-next-steps.md`); 16 ya estaban rastreados en el backlog (marcados 📌).
- 14 hallazgos tienen fix propuesto que el verificador ajustó/observó (marcados ⚠️ FIX con la corrección en "Notas del verificador").
- Convención de severidad: critical = corrupción de datos / fuga cross-tenant / dinero / seguridad explotable · high = bug funcional real o riesgo con precondición · medium = deuda que causará bugs / mantenibilidad seria · low = higiene.

## Índice rápido (critical + high)

- **F42** [CRITICAL] `services/ai-orchestrator/tools/payment_link_tool.py:416` — Un cupón aplicado (o cambio de carrier) tras generar el link Wompi no invalida la orden pending_payment y el bot reutiliza el link con el monto viejo — el cliente paga un monto distinto al total acordado
- **F16** [CRITICAL] `services/api/routers/wompi_webhook.py:692` — El guard de validación de monto del webhook Wompi está muerto y el retry de pago nunca genera link: _get_order_by_id no selecciona total_amount
- **F10** [CRITICAL] `supabase/migrations/20260419000001_rbac_operator_runtime_only.sql:32` — add_member_to_tenant es SECURITY DEFINER, expuesto a authenticated/anon (sin REVOKE) y sin validar la identidad del caller → escalada de privilegios cross-tenant a 'owner'
- **F82** [CRITICAL] `apps/web/app/dashboard/(settings-group)/team/page.tsx:264` — removeMember/inactivateMember ejecutan deleteUser/ban con service_role sobre un user_id arbitrario sin verificar que pertenezca al tenant del caller (destrucción cross-tenant de cuentas)
- **F32** [HIGH] `services/ai-orchestrator/agentic/system_prompt.py:666` — Cinco renderizadores de dirección divergentes: el path agentic muestra al cliente direcciones sin Torre/Apto/Piso/Casa#/Empresa que el path legacy sí renderiza
- **F31** [HIGH] `services/ai-orchestrator/agentic/tools/contact.py:38` — Normalización DIAN de dirección solo existe en el path legacy: el path agentic (primario) persiste street/city crudos → formato divergente en contacts.address según qué path atendió el turno
- **F43** [HIGH] `services/ai-orchestrator/tools/cart_tool.py:1072` — invalidate_shipping y set_shipping_city borran shipping_meta.recipient — el destinatario alterno (envío a tercero, fix Habeas Data BUG 37) se pierde silenciosamente al agregar/quitar cualquier item
- **F44** [HIGH] `services/ai-orchestrator/worker.py:1531` — El cron de carritos abandonados está funcionalmente muerto: consulta columnas inexistentes (contacts.first_name/full_name, conversation_cart_items.product_title) → consent_ok siempre False → skipea TODO y quema el flag de idempotencia
- **F45** [HIGH] `services/ai-orchestrator/worker.py:304` — Durante un outage sostenido de Gemini el worker se auto-mata: el heartbeat solo se actualiza al tope del loop y la cascada LLM puede dormir ~63s por llamada → /health 503 a los 120s → Render reinicia en mitad del batch (riesgo de respuestas duplicadas)
- **F17** [HIGH] `services/api/main.py:177` — El webhook de Telegram está montado con _OFFBOARDING_GATE que exige JWT → todo POST de Telegram recibe 401 y los comandos /resolver y /estado están rotos
- **F30** [HIGH] `services/api/routers/ai_agents.py:37` — sys.path.insert(0) hacia ai-orchestrator en la API hace que imports lazy de lib.* resuelvan a las copias del orchestrator (namespace packages sin __init__.py)
- **F18** [HIGH] `services/api/routers/knowledge_base.py:151` — Los 4 endpoints de escritura de knowledge_base encadenan .select()/.single() tras .insert()/.update() — métodos inexistentes en postgrest 2.28.3 → AttributeError y 500 en TODA llamada
- **F19** [HIGH] `services/api/routers/orders.py:296` — Uso sistémico de .single() con check muerto 'if not res.data' — los casos not-found devuelven 500 en vez de 404, y en purchases/receive deja estado parcial (PO received sin stock aplicado)
- **F27** [HIGH] `services/api/routers/orders.py:189` — create_order acepta contact_id/conversation_id del body sin validar que pertenezcan al tenant; el JOIN embebido en get_order/create_payment_link fuga PII cross-tenant (nombre, teléfono, cédula)
- **F105** [HIGH] `services/api/routers/orders.py:398` — La generación de link de pago Wompi en producción NO usa los wrappers de resiliencia: create_payment_link_*_with_resilience tiene cero callers y el 'riesgo P0' del dossier sigue abierto
- **F53** [HIGH] `services/connector-whatsapp/routers/webhook.py:68` — I/O bloqueante síncrona (Supabase/Vault HTTP) ejecutada directamente en el event loop de asyncio: serializa TODOS los webhooks y arriesga exceder el timeout de ACK de Meta
- **F52** [HIGH] `services/connector-whatsapp/services/template_events.py:94` — Eventos de template/phone-quality se persisten SIN autoridad de tenant: reintroduce el patrón WH-01 y permite escritura cross-tenant a cualquier tenant con HMAC válido
- **F2** [HIGH] `services/ai-orchestrator/agentic/dispatcher.py:402` — Habeas Data F6 self-service (Art. 14) muerto al nacer: _resolve_contact_id consulta conversations.contact_id, columna que no existe
- **F1** [HIGH] `services/ai-orchestrator/orchestrator.py:7673` — Escalación por crisis de salud mental nunca marca human_takeover: el UPDATE incluye la columna inexistente conversations.human_takeover_reason y falla completo
- **F119** [HIGH] `services/api/lib/tenant_carriers.py:173` — COD por carrier duplicado en columna deprecada viva: UI/API escriben tenant_carriers.supports_cod pero el runtime resuelve por cod_override (que NADIE escribe) → el toggle COD del tenant no tiene ningún efecto
- **F116** [HIGH] `services/api/routers/contacts.py:336` — Consent duplicado en dos generaciones de columnas (consent_date v1 vs consent_given_at v2) sin sync: el export Habeas Data muestra 'Otorgado en' NULL para contactos creados/editados desde el dashboard y desde MeLi
- **F117** [HIGH] `services/api/routers/integrations.py:134` — WABA ID vive en dos tablas (tenants.meta_waba_id y tenant_integrations.credentials.waba_id) con escritores independientes y sin sync: el onboarding self-service F3 deja los eventos de template/phone-quality sin resolver tenant 📌
- **F4** [HIGH] `services/api/routers/sic_report.py:55` — Endpoint de reporte SIC (Ley 1581) responde 503 SIEMPRE: selecciona tenants.document_number, columna inexistente (la real es nit)
- **F11** [HIGH] `supabase/migrations/20260420000004_whatsapp_outbound_queue.sql:25` — enqueue_whatsapp_outbound_message (SECURITY DEFINER, sin REVOKE) es invocable por authenticated/anon y el worker envía el payload sin validar contra DB → inyección de mensajes WhatsApp salientes suplantando a CUALQUIER tenant
- **F12** [HIGH] `supabase/migrations/20260430000000_meli_webhook_dedup.sql:12` — meli_webhook_dedup es la ÚNICA tabla del schema public sin RLS habilitado → lectura/escritura/borrado directo por anon/authenticated vía PostgREST (envenenamiento de idempotencia / DoS del sync de stock MeLi)
- **F127** [HIGH] `apps/web/app/dashboard/(analytics)/metrics/page.tsx:67` — La página de Métricas trae tablas enteras (order_items sin filtro de fecha, conversations, contacts, products, messages fila-a-fila) para contar en JS — KPIs silenciosamente truncados a 1000 filas 📌
- **F68** [HIGH] `apps/web/app/dashboard/(sales)/contacts/page.tsx:259` — Server actions de Contactos usan `throw new Error(msg)` para errores esperados; en producción Next.js enmascara el mensaje y el operador nunca ve la causa (duplicado 409, guard Wompi, validación consent)
- **F62** [HIGH] `apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:45` — Estado de orden 'pending_payment' existe en el backend (7 estados) pero falta en las 5 copias TypeScript del enum: el operador no puede filtrar ni avanzar esos pedidos
- **F139** [HIGH] `apps/web/app/dashboard/(sales)/orders/page.tsx:109` — Cambio/cancelación de estado de pedido falla en silencio: fetch sin check de res.ok, catch vacío y action Promise<void> sin feedback al usuario
- **F104** [HIGH] `apps/web/app/dashboard/(settings-group)/integrations/page.tsx:88` — El botón 'Desconectar' de MercadoLibre usa un server action que NO revoca el token ni borra los secretos de Vault; el endpoint completo DELETE /api/v1/integrations/meli queda muerto
- **F93** [HIGH] `apps/web/app/dashboard/(settings-group)/integrations/wompi/_components/wompi-setup.tsx:97` — El dashboard muestra a los tenants URLs de webhook ERRÓNEAS para Wompi y Telegram — los eventos de pago registrados según la UI caerían en 404
- **F128** [HIGH] `apps/web/app/dashboard/finance/page.tsx:27` — Analítica Financiera carga TODAS las órdenes históricas con order_items anidados y todos los expenses sin límite ni ventana temporal — unit economics erróneos al superar 1000 filas 📌
- **F126** [HIGH] `apps/web/app/dashboard/inbox/_hooks/use-conversations.ts:103` — El Inbox descarga el historial COMPLETO de mensajes de las 50 conversaciones cada 20 segundos solo para mostrar el preview del último mensaje
- **F69** [HIGH] `apps/web/app/dashboard/inbox/_hooks/use-messages.ts:143` — Polling fallback de useMessages descarta el historial paginado cada 5s: reemplaza el estado con los últimos 100 mensajes aunque el operador haya cargado más con loadMore
- **F140** [HIGH] `apps/web/components/ui/submit-button.tsx:31` — SubmitButton muestra 'Guardado ✓' aunque la mutación haya fallado — y las actions que lo usan (settings, purchases, team) tragan los errores del backend
- **F83** [HIGH] `apps/web/middleware.ts:80` — Bypass total del enforcement MFA: la cookie mfa_recovery_session es un literal '1' sin firma que cualquier cliente puede fabricar

## 1. Base de datos y modelo de datos

### F10 · 🔴 CRITICAL — add_member_to_tenant es SECURITY DEFINER, expuesto a authenticated/anon (sin REVOKE) y sin validar la identidad del caller → escalada de privilegios cross-tenant a 'owner'

**Ubicación**: `supabase/migrations/20260419000001_rbac_operator_runtime_only.sql:32` · **Detectado por**: db-indexes-rls · 🆕 nuevo

**Causa**: La función corre con permisos del owner (postgres) y salta RLS. No hay REVOKE en ninguna migración (verificado: grep REVOKE sólo lista offboarding/mfa/provider_health/provision_tenant/vault; NUNCA add_member_to_tenant), y ninguna migración aplica ALTER DEFAULT PRIVILEGES revocando EXECUTE. Por defecto Postgres concede EXECUTE a PUBLIC y PostgREST expone las funciones del schema public a los roles anon/authenticated. La función sólo valida que p_role ∈ (owner,manager,operator) — NO valida que p_user_id = auth.uid() ni que el caller pertenezca a p_tenant_id. tenant_users.status tiene DEFAULT 'active' (20260426060000_tenant_users_status.sql:5) y custom_access_token_hook inyecta tenant_id+role del membership activo en el JWT. El único caller legítimo usa el admin client service_role (apps/web/.../team/page.tsx:184,196), luego authenticated no necesita EXECUTE.

**Evidencia (código real)**:
```
CREATE OR REPLACE FUNCTION public.add_member_to_tenant(p_user_id uuid, p_tenant_id uuid, p_role text) ... SECURITY DEFINER AS $$ BEGIN IF p_role NOT IN ('owner', 'manager', 'operator') THEN RAISE EXCEPTION 'Rol inválido: %', p_role; END IF; INSERT INTO public.tenant_users (user_id, tenant_id, role) VALUES (p_user_id, p_tenant_id, p_role) ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role; END; $$;  -- (sin REVOKE en el repo)
```

**Corrección propuesta**:
```
Nueva migración que revoca la exposición y fija search_path (el caller real es service_role): 
```sql
REVOKE ALL ON FUNCTION public.add_member_to_tenant(uuid, uuid, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.add_member_to_tenant(uuid, uuid, text) TO service_role;
ALTER FUNCTION public.add_member_to_tenant(uuid, uuid, text) SET search_path = public;
```
Defensa en profundidad opcional dentro del cuerpo: `IF p_user_id <> auth.uid() AND auth.role() <> 'service_role' THEN RAISE EXCEPTION 'forbidden'; END IF;`
```

**Notas del verificador sobre el fix**: REVOKE ...FROM PUBLIC,anon,authenticated + GRANT ...TO service_role cierra la exposicion sin romper el caller real (usa adminSb/service_role). El guard opcional en cuerpo es coherente: con service_role auth.uid()=NULL pero auth.role()='service_role' pasa. SET search_path=public tambien correcto (la funcion solo referencia objetos public). Completo y no rompe nada. | El fix es correcto y no rompe nada. REVOKE ALL ... FROM PUBLIC, anon, authenticated elimina la exposición PostgREST; GRANT EXECUTE ... TO service_role preserva el único caller legítimo (createAdminClient=service_role, confirmado en team/page.tsx:184,196); ALTER FUNCTION ... SET search_path=public es hardening estándar para SECURITY DEFINER. La firma usada (uuid,uuid,text) coincide con la real. Sigue exactamente el patrón ya presente en las 5 migraciones hermanas. El guard opcional en el cuerpo (p_user_id<>auth.uid() AND auth.role()<>'service_role') es defensa en profundidad válida: las llamadas service_role devuelven auth.role()='service_role' y pasan. Recomendable emitir la migración con timestamp posterior a 20260419000001 para que el REVOKE aplique tras el último CREATE OR REPLACE.

**Referencia oficial**: https://supabase.com/docs/guides/database/functions#security-definer-vs-invoker

<details><summary>Verificación adversarial</summary>

Confirmado en 20260419000001_rbac_operator_runtime_only.sql:32-51: add_member_to_tenant es SECURITY DEFINER (corre como owner postgres, bypass RLS) y su unica validacion es p_role IN (owner,manager,operator) — NO valida auth.uid() ni membership del caller en p_tenant_id. grep REVOKE sobre TODAS las migraciones: no existe REVOKE para esta funcion (si existen para provision_tenant, fn_hard_delete_tenant, MFA, provider_health, offboarding — patron que prueba que anon/authenticated tienen acceso por defecto y hay que revocarlo). config.toml expone schema public via PostgREST (schemas=[public,graphql_public]). Por default PostgreSQL concede EXECUTE a PUBLIC y Supabase concede default privileges a […]

</details>

---

### F2 · 🟠 HIGH — Habeas Data F6 self-service (Art. 14) muerto al nacer: _resolve_contact_id consulta conversations.contact_id, columna que no existe

**Ubicación**: `services/ai-orchestrator/agentic/dispatcher.py:402` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: conversations no tiene contact_id en ninguna migración (el vínculo canónico es customer_phone → contacts.phone). El .single().execute() lanza APIError, el except retorna None SIEMPRE → en _handle_data_rights_if_intent (kind=='access', dispatcher.py:477) el flujo self-service recién shippeado en commit 185943fd nunca se ejecuta y todo cae a escalación; además _log_habeas_event (dispatcher.py:419-423) usa la misma query y registra TODOS los eventos en consent_audit_log con contact_id NULL, degradando el paper-trail SIC. El mismo bug-class ya fue corregido en rev. 104: orchestrator.py:1937-1941 documenta «la tabla conversations NO tiene columna contact_id — el lookup correcto es vía customer_phone → contacts.phone. La query previa devolvía HTTP 400 silenciado por el try/except».

**Evidencia (código real)**:
```
supabase.table("conversations").select("contact_id")
.eq("id", conversation_id).eq("tenant_id", tenant_id).single().execute()
```

**Corrección propuesta**:
```
Reimplementar _resolve_contact_id con el patrón canónico rev. 104 (orchestrator.py:1942-1962) y reutilizarlo en _log_habeas_event:

def _resolve_contact_id(supabase: Any, tenant_id: str, conversation_id: str):
    try:
        conv = (
            supabase.table("conversations").select("customer_phone")
            .eq("id", conversation_id).eq("tenant_id", tenant_id)
            .limit(1).execute()
        )
        phone = ((conv.data or [{}])[0].get("customer_phone") or "").lstrip("+")
        if not phone:
            return None
        ctc = (
            supabase.table("contacts").select("id")
            .eq("tenant_id", tenant_id)
            .or_(f"phone.eq.{phone},phone.eq.+{phone}")
            .limit(1).execute()
        )
        return (ctc.data or [{}])[0].get("id")
    except Exception:
        return None
```

**Notas del verificador sobre el fix**: Correcto: replica el patrón canónico rev. 104 (orchestrator.py:1942-1962) incluyendo el or_ phone/+phone que cubre contactos legacy con '+'. contacts.phone se almacena digits-only canónico (connector via lib/phone.to_canonical), así que el match funciona. Completar el fix reutilizando el mismo helper dentro de _log_habeas_event (dispatcher.py:419-423 tiene la query rota duplicada inline) — el snippet propuesto solo muestra _resolve_contact_id; el finding sí lo menciona, verificar que se aplique en ambos sitios.

**Referencia oficial**: https://docs.postgrest.org/en/v12/references/errors.html

<details><summary>Verificación adversarial</summary>

CONFIRMADO. dispatcher.py:402 y 419-423 hacen select('contact_id') sobre conversations — columna inexistente en el schema (verificado: CREATE TABLE 20260406181237 + todos los ALTER TABLE conversations; ningún ADD COLUMN contact_id). PostgREST responde 400 (42703) → APIError → except retorna None SIEMPRE. Consecuencia verificada en dispatcher.py:476-513: kind=='access' con contact_id=None salta el bloque self-service (commit 185943fd) y cae al fallthrough de escalación (515+), y _log_habeas_event inserta consent_audit_log con contact_id NULL (columna nullable per 20260502010000, así que el insert sí ocurre pero sin vínculo al titular). El bug-class idéntico fue corregido en rev. 104 y está do […]

</details>

---

### F1 · 🟠 HIGH — Escalación por crisis de salud mental nunca marca human_takeover: el UPDATE incluye la columna inexistente conversations.human_takeover_reason y falla completo

**Ubicación**: `services/ai-orchestrator/orchestrator.py:7673` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: conversations solo tiene (id, tenant_id, customer_phone, status, last_interaction_at, created_at, archived_at, processing/agentic_state, channel, human_takeover_at) — ninguna migración de supabase/migrations/ crea human_takeover_reason. PostgREST responde 400 (42703 undefined_column) y el UPDATE entero (incluido status='human_takeover') se descarta; el except lo silencia. Consecuencia: el bot le dice al usuario en crisis 'Te conecto también con un asesor humano', pero la conversación queda en bot_active, el trigger DB de human_takeover_notifications_queue nunca dispara y ningún humano es notificado. El propio repo documenta el patrón correcto en agentic/tools/escalation.py:53-55: «conversations schema NO tiene columna escalation_reason — solo status. La razón se persiste en messages.payload».

**Evidencia (código real)**:
```
supabase.table("conversations").update({
    "status": "human_takeover",
    "human_takeover_reason": "mental_health_crisis",
}).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()  # A6.2.7
```

**Corrección propuesta**:
```
Quitar la columna fantasma y persistir la razón como audit append-only en messages (patrón canónico de escalation.py):

supabase.table("conversations").update({
    "status": "human_takeover",
}).eq("id", conversation_id).eq("tenant_id", tenant_id).execute()
supabase.table("messages").insert({
    "conversation_id": conversation_id,
    "tenant_id": tenant_id,
    "direction": "outbound",
    "content_type": "escalation_audit",
    "content": "",
    "payload": {"reason": "mental_health_crisis", "source": "crisis_detector"},
    "processed": True,
    "processing_status": "processed",
}).execute()

(human_takeover_at lo estampa el trigger DB stamp_human_takeover_at — no setearlo a mano.)
```

**Notas del verificador sobre el fix**: Correcto y alineado al patrón canónico de escalation.py (update solo status + insert messages content_type='escalation_audit' con payload.reason; ese insert exacto ya corre en producción, schema probado). Acertado NO setear human_takeover_at a mano (lo estampa el trigger BEFORE UPDATE). Alternativa más simple: reutilizar el helper existente _set_conversation_status(supabase, tenant_id, conversation_id, CONVERSATION_STATUS_HUMAN_TAKEOVER) que ya se usa en la línea 7626 del mismo archivo. Mantener el try/except alrededor de ambas operaciones para no romper el flujo del mensaje de seguridad ya enviado.

**Referencia oficial**: https://docs.postgrest.org/en/v12/references/errors.html

<details><summary>Verificación adversarial</summary>

CONFIRMADO. orchestrator.py:7671-7674 envía UPDATE con 'human_takeover_reason' y ninguna migración crea esa columna: schema base 20260406181237 (id, tenant_id, customer_phone, status, last_interaction_at, created_at) + ALTERs solo añaden archived_at, agentic_state, channel, processing_*, human_takeover_at (20260702180000). El único hit de 'human_takeover_reason' en TODO el repo es la línea buggy. PostgREST rechaza el UPDATE completo (PGRST204 columna desconocida) → status nunca pasa a human_takeover → el trigger enqueue_human_takeover_notification (20260420000003, dispara en la transición de status) nunca encola y stamp_human_takeover_at tampoco corre; el except (7675-7676) lo reduce a logge […]

</details>

---

### F119 · 🟠 HIGH — COD por carrier duplicado en columna deprecada viva: UI/API escriben tenant_carriers.supports_cod pero el runtime resuelve por cod_override (que NADIE escribe) → el toggle COD del tenant no tiene ningún efecto

**Ubicación**: `services/api/lib/tenant_carriers.py:173` · **Detectado por**: db-overlap · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: La migración 20260602010000 deprecó tenant_carriers.supports_cod a favor de cod_override 3-estado + aveonline_carrier_capabilities canónica, sin droparla 'por backwards-compat'. Pero el write-path nunca migró: la UI (aveonline-carriers.tsx:389-390) y el bulk PUT (integrations.py:1007) siguen persistiendo SOLO supports_cod, y ningún código del repo escribe cod_override. El read-path del bot (carrier_capabilities.py:168) selecciona `enabled, display_label, cod_override` e ignora la columna legacy → COALESCE cae siempre al default canónico. El código contradice la decisión documentada: la columna vieja quedó viva Y siendo la única escrita.

**Evidencia (código real)**:
```
tenant_carriers.py:173 `"supports_cod": bool(supports_cod),` (upsert_preference) vs services/ai-orchestrator/lib/carrier_capabilities.py:168 `.select("enabled, display_label, cod_override")` y la migración 20260602010000: 'La columna existente tenant_carriers.supports_cod ... queda como **deprecated** — usar cod_override'
```

**Corrección propuesta**:
```
Mapear el toggle al override en el write-path. En lib/tenant_carriers.py upsert_preference (línea 173):
```python
"supports_cod": bool(supports_cod),  # legacy: mantener hasta contract
"cod_override": "force_enable" if supports_cod else "force_disable",
```
y backfill one-shot en migración:
```sql
UPDATE public.tenant_carriers
   SET cod_override = CASE WHEN supports_cod THEN 'force_enable' ELSE 'force_disable' END
 WHERE provider = 'aveonline' AND cod_override IS NULL;
```
Fase contract posterior: dropear supports_cod y exponer el 3-estado real (heredar canónico / forzar on / forzar off) en la UI.
```

**Notas del verificador sobre el fix**: Dirección correcta (mapear toggle → override) pero incompleto y con regresión live: (1) el backfill supports_cod=false → force_disable convierte el default de seed (integrations.py:1132, 'opt-in explícito post-onboarding', NO decisión del tenant) en force_disable, apagando COD para carriers donde canonical=true y el runtime hoy lo ofrece — cambio de comportamiento en producción (KAIU) que requiere decisión founder; más seguro: backfill solo true→force_enable y dejar false→NULL (hereda canonical); (2) el seed endpoint inserta directo (integrations.py:1124-1133) sin pasar por upsert_preference — quedaría inconsistente con la nueva semántica toggle=verdad; (3) un checkbox 2-estado no puede expresar el 3-estado — la fase contract con UI 3-estado es la solución real y debería decidirse antes del write-path parche.

<details><summary>Verificación adversarial</summary>

Confirmado en código: (1) NINGÚN código del repo escribe cod_override — grep exhaustivo solo encuentra lecturas (carrier_capabilities.py en api y ai-orchestrator, línea 167/168 .select("enabled, display_label, cod_override")) y la migración 20260602010000 que la crea; (2) los tres write-paths escriben solo supports_cod legacy: upsert_preference (tenant_carriers.py:173), bulk PUT (integrations.py:1007), seed (integrations.py:1132 supports_cod=False); (3) la resolución runtime de COD (_resolve_cod, carrier_capabilities.py:103-126) usa exclusivamente cod_override + canonical, ignorando supports_cod — el comentario en aveonline.py:328-330 confirma que 'reemplaza el filter legacy que solo miraba  […]

</details>

---

### F116 · 🟠 HIGH — Consent duplicado en dos generaciones de columnas (consent_date v1 vs consent_given_at v2) sin sync: el export Habeas Data muestra 'Otorgado en' NULL para contactos creados/editados desde el dashboard y desde MeLi

**Ubicación**: `services/api/routers/contacts.py:336` · **Detectado por**: db-overlap · 🆕 nuevo

**Causa**: La migración 20260423000000_contacts_consent_v2.sql añadió consent_given_at/consent_channel sin eliminar ni sincronizar consent_date/consent_source de 20260410020000 (solo backfill one-shot). Quedaron dos sets de columnas para el mismo hecho con escritores inconsistentes: create_contact (contacts.py:335-338) y _apply_consent_patch (contacts.py:258-262) escriben SOLO consent_date; meli_webhook.py:422-425 igual; en cambio record_consent (contacts.py:568-572) y el dispatcher agentic (dispatcher.py:2050-2051) escriben ambas. El lector legal (data_subject_request.py:208,440) lee SOLO consent_given_at. El propio código ya documentó esta clase de bug (dispatcher.py:2042 'A11 UAT fix') pero los paths del dashboard/MeLi nunca se corrigieron.

**Evidencia (código real)**:
```
contacts.py:335-336 `"consent_given": contact.consent_given, "consent_date": now_iso if contact.consent_given else None,` (sin consent_given_at) vs data_subject_request.py:440 `field_row("Otorgado en", subject.get("consent_given_at"))` y meli_webhook.py:424 `"consent_date": now_iso,` (sin consent_given_at)
```

**Corrección propuesta**:
```
1) Escribir ambas columnas en los 3 writers que faltan. En create_contact (contacts.py:336): `"consent_date": now_iso if contact.consent_given else None, "consent_given_at": now_iso if contact.consent_given else None,`. En _apply_consent_patch (return dict, línea 260): añadir `"consent_given_at": effective_date,`. En meli_webhook.py:424: añadir `"consent_given_at": now_iso,`. 2) Backfill: nueva migración `UPDATE public.contacts SET consent_given_at = COALESCE(consent_given_at, consent_date) WHERE consent_given = true AND consent_given_at IS NULL;`. 3) Follow-up expand-contract: consolidar en una sola columna (dropear consent_date tras migrar la UI que la lee).
```

**Notas del verificador sobre el fix**: Los 3 writers identificados son exactamente los que faltan y las líneas citadas son correctas. En _apply_consent_patch, añadir consent_given_at=effective_date incondicionalmente es aceptable (en revocación preserva el valor histórico, semánticamente correcto). Backfill idempotente correcto (WHERE consent_given=true AND consent_given_at IS NULL). El follow-up expand-contract es coherente con la memoria del proyecto (patrón para drops de columnas SELECTeadas). Considerar en el mismo cambio el gap de consent_audit_log en create_contact/_apply_consent_patch (hallazgo hermano, no bloqueante para este fix).

<details><summary>Verificación adversarial</summary>

Confirmado en los 3 writers y el lector: create_contact (contacts.py:335-344) escribe consent_date sin consent_given_at; _apply_consent_patch (return dict :258-271) ídem; meli_webhook.py:418-433 ídem. El lector legal data_subject_request.py:208 y :440 ('Otorgado en') lee SOLO consent_given_at sin fallback a consent_date (verificado: únicos 2 hits en el archivo). Migración 20260423000000_contacts_consent_v2.sql hizo backfill one-shot (COALESCE consent_date, created_at) — todo contacto creado/consentido después vía dashboard o MeLi tiene consent_given=true con consent_given_at NULL. Sin trigger de sync (grep migraciones). Escenario runtime real: web crea contactos vía POST /api/v1/contacts/ (c […]

</details>

---

### F117 · 🟠 HIGH — WABA ID vive en dos tablas (tenants.meta_waba_id y tenant_integrations.credentials.waba_id) con escritores independientes y sin sync: el onboarding self-service F3 deja los eventos de template/phone-quality sin resolver tenant

**Ubicación**: `services/api/routers/integrations.py:134` · **Detectado por**: db-overlap · 📌 ya rastreado (audit finiquito §5 Canales — bug MEDIUM 'WhatsApp tenant lookup duplica lógica: tenants.meta_waba_id vs tenant_integrations.credentials... Esquema inconsistente' + gap técnico 'Lógica tenant resolution por canal duplicada en 3 lugares con esquemas distintos')

**Causa**: upsert_whatsapp_credentials (F3, ADR-0023 Model B) persiste waba_id SOLO en tenant_integrations.credentials JSONB; tenants.meta_waba_id solo se escribe vía PATCH /settings (settings.py:73,150), un endpoint distinto que el tenant puede no tocar o llenar con otro valor. El connector resuelve tenant para template_status_update y phone_number_quality_update por tenants.meta_waba_id (_resolve_tenant_by_waba, db_persistence.py:45; template_events.py:214). Mismo dato, dos stores, cero mecanismo de sincronización — pueden divergir desde el día 1 del onboarding.

**Evidencia (código real)**:
```
integrations.py:134 `"waba_id": payload.waba_id,` (upsert a tenant_integrations.credentials, nunca toca tenants) vs db_persistence.py:45 `res = supabase.table("tenants").select("id").eq("meta_waba_id", meta_waba_id).eq("status", "active").execute()`
```

**Corrección propuesta**:
```
Sincronizar en el mismo endpoint (el índice UNIQUE parcial uniq_tenants_meta_waba_id de 20260625130000 protege colisiones). Tras el upsert de tenant_integrations en integrations.py (~línea 140):
```python
try:
    supabase.table("tenants").update({"meta_waba_id": payload.waba_id}).eq("id", tenant_id).execute()
except Exception as exc:
    # 23505 = otro tenant ya registró esa WABA (config errónea) → rechazar explícito
    raise HTTPException(status_code=409, detail="WABA ID ya registrada por otro tenant") from exc
```
Alternativa estructural (mejor a mediano plazo): que _resolve_tenant_by_waba consulte `tenant_integrations.credentials->>'waba_id'` y dropear tenants.meta_waba_id (expand-contract).
```

**Notas del verificador sobre el fix**: El sync en el endpoint F3 es correcto y el índice UNIQUE parcial uniq_tenants_meta_waba_id (20260625130000, WHERE NOT NULL AND <> '') existe y protege colisiones. Dos ajustes: (1) el except Exception → 409 conflaría errores transitorios de DB con colisión WABA — inspeccionar código 23505 en el APIError antes de mapear a 409, sino 500; (2) la web ya limpia meta_waba_id en disconnect (integrations/page.tsx:407) pero el API no tiene endpoint de disconnect — coherente. La alternativa estructural (resolver por credentials->>'waba_id') requeriría índice funcional sobre JSONB y toca más superficie; la opción táctica propuesta es la correcta ahora. Interacción con F110: si se borra el settings router, este sync se vuelve el único writer API-side.

<details><summary>Verificación adversarial</summary>

Estructuralmente confirmado pero con impacto sobredimensionado. Confirmado: upsert_whatsapp_credentials (integrations.py:125-139) persiste waba_id SOLO en tenant_integrations.credentials y nunca toca tenants.meta_waba_id; la UI F3 usa exactamente ese endpoint (whatsapp-credentials-form.tsx:54). El OTRO flujo web (hub integrations/page.tsx saveWhatsApp) SÍ sincroniza ambos (:321 sb.from('tenants').update({meta_waba_id})), por lo que la divergencia ocurre específicamente cuando el tenant usa el form F3 dedicado. SOBREDIMENSIONADO: los eventos template_status_update y template_quality_update resuelven por meta_template_id contra whatsapp_templates (template_events.py:59-94, :131-158), NO por te […]

</details>

---

### F4 · 🟠 HIGH — Endpoint de reporte SIC (Ley 1581) responde 503 SIEMPRE: selecciona tenants.document_number, columna inexistente (la real es nit)

**Ubicación**: `services/api/routers/sic_report.py:55` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: tenants tiene nit (agregada en 20260415020000_tenant_identity_fields.sql); document_number no existe en ninguna migración de tenants. El select lanza APIError → el except de la línea 57-59 convierte TODO en HTTPException 503 'DB temporarily unavailable' → _build_sic_payload nunca pasa de la primera query y el reporte de cumplimiento Habeas Data para la SIC es imposible de generar. Además el payload (sic_report.py:115) referencia tenant_row.get("document_number").

**Evidencia (código real)**:
```
t_res = sb.table("tenants").select("id, name, document_number").eq(
    "id", tenant_id).limit(1).execute()
```

**Corrección propuesta**:
```
Seleccionar la columna real y mapearla al campo del reporte:

t_res = sb.table("tenants").select("id, name, nit").eq(
    "id", tenant_id).limit(1).execute()
...
"tenant": {
    "id": tenant_row.get("id"),
    "name": tenant_row.get("name"),
    "document_number": tenant_row.get("nit"),
    "role": "Responsable del Tratamiento (Ley 1581/2012)",
},
```

**Notas del verificador sobre el fix**: Correcto y mínimo: seleccionar nit y mapearlo a tenant.document_number del payload. Completo (línea 55 + línea 115 son los únicos usos). Recomendado además actualizar el mock del test test_rev101_followups.py:176 para que devuelva nit y no re-enmascare.

**Referencia oficial**: https://docs.postgrest.org/en/v12/references/errors.html

<details><summary>Verificación adversarial</summary>

sic_report.py:55 selecciona tenants.document_number. Migraciones canónicas: 20260415020000_tenant_identity_fields.sql agrega SOLO nit/email_contacto/telefono_contacto; grep de todas las migraciones confirma que ningún ALTER TABLE tenants crea document_number (solo existe en contacts). PostgREST responde 42703 → APIError → el except de líneas 57-59 lo convierte en 503 SIEMPRE. El endpoint está montado en main.py:164 y consumido por el frontend (settings/legal/_components/sic-report-download.tsx:28). El test test_rev101_followups.py:176 mockea la fila con document_number, enmascarando el bug. El path productivo wompi_webhook.py:1346 selecciona nit, confirmando la columna real.

</details>

---

### F11 · 🟠 HIGH — enqueue_whatsapp_outbound_message (SECURITY DEFINER, sin REVOKE) es invocable por authenticated/anon y el worker envía el payload sin validar contra DB → inyección de mensajes WhatsApp salientes suplantando a CUALQUIER tenant

**Ubicación**: `supabase/migrations/20260420000004_whatsapp_outbound_queue.sql:25` · **Detectado por**: db-indexes-rls · 🆕 nuevo

**Causa**: enqueue_whatsapp_outbound_message es SECURITY DEFINER sin REVOKE (expuesta vía PostgREST /rest/v1/rpc/). El consumidor worker.py toma tenant_id, customer_phone y text DIRECTO del payload de la cola (no verifica que message_id exista en DB ni pertenezca al tenant) y llama send_whatsapp_message(tenant_id=..., to_phone=..., text=...), que carga las credenciales Meta de ESE tenant desde Vault y envía. Un usuario autenticado puede encolar {tenant_id: <víctima>, customer_phone: <cualquiera>, message_id: <cualquiera>, text: <arbitrario>} y hacer que el número WhatsApp de otro tenant envíe mensajes arbitrarios (spam/impersonación a costa del tenant).

**Evidencia (código real)**:
```
CREATE OR REPLACE FUNCTION public.enqueue_whatsapp_outbound_message(p_message JSONB, p_delay INTEGER DEFAULT 0) RETURNS BIGINT LANGUAGE sql SECURITY DEFINER SET search_path = public, pgmq  // worker.py:698-741: tenant_id = str(payload.get("tenant_id")...); to_phone = str(payload.get("customer_phone")...); ... meta_message_id = await send_whatsapp_message(tenant_id=tenant_id, supabase=self.supabase, to_phone=to_phone, text=text)
```

**Corrección propuesta**:
```
Revocar exposición de los tres helpers pgmq (sólo los usan api/worker con service_role):
```sql
REVOKE ALL ON FUNCTION public.enqueue_whatsapp_outbound_message(jsonb, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.dequeue_whatsapp_outbound_messages(integer, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.ack_whatsapp_outbound_message(bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.enqueue_whatsapp_outbound_message(jsonb, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.dequeue_whatsapp_outbound_messages(integer, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.ack_whatsapp_outbound_message(bigint) TO service_role;
```
Además, endurecer el worker: antes de enviar, verificar `messages` con `.eq('id', message_id).eq('tenant_id', tenant_id).eq('direction','outbound')` y que customer_phone coincida con la conversación.
```

**Notas del verificador sobre el fix**: El REVOKE de los 3 helpers pgmq + GRANT service_role cierra el vector y no rompe a los callers backend (service_role). CUIDADO con la parte de endurecer el worker (verificar messages con .eq('id',message_id).eq('direction','outbound')): habria que garantizar que TODOS los paths de enqueue (bot orchestrator.py:2228, wompi_webhook, conversations) crean la fila messages ANTES de encolar, o romperia envios legitimos. El REVOKE por si solo ya mitiga; el hardening del worker es defensa-en-profundidad que requiere validar precondiciones.

**Referencia oficial**: https://supabase.com/docs/guides/api/securing-your-api

<details><summary>Verificación adversarial</summary>

Confirmado en 20260420000004_whatsapp_outbound_queue.sql:25-44: enqueue_whatsapp_outbound_message es SECURITY DEFINER (con SET search_path=public,pgmq) y NO tiene REVOKE (grep global). Expuesta via PostgREST rpc. worker.py:698-749: el consumidor toma tenant_id/customer_phone/text/message_id DIRECTO del payload, solo valida que sean no-vacios (linea 709), y llama send_whatsapp_message(tenant_id, to_phone, text) que carga las credenciales Meta del tenant desde Vault y ENVIA — el envio ocurre ANTES de cualquier chequeo DB (_mark_outbound_sent corre despues, linea 748, y aunque falle el mensaje ya salio). Los callers legitimos (conversations.py:847/1350 con get_service_client, wompi_webhook.py,  […]

</details>

---

### F12 · 🟠 HIGH — meli_webhook_dedup es la ÚNICA tabla del schema public sin RLS habilitado → lectura/escritura/borrado directo por anon/authenticated vía PostgREST (envenenamiento de idempotencia / DoS del sync de stock MeLi)

**Ubicación**: `supabase/migrations/20260430000000_meli_webhook_dedup.sql:12` · **Detectado por**: db-indexes-rls · 🆕 nuevo

**Causa**: Diff de CREATE TABLE (77 tablas) vs 'ENABLE ROW LEVEL SECURITY' arroja exactamente 1 tabla sin RLS: meli_webhook_dedup. En Supabase los roles anon/authenticated tienen privilegios sobre tablas del schema public y PostgREST las expone en /rest/v1/; sin RLS, un usuario puede INSERT dedup_key arbitrarios (haciendo que webhooks MeLi reales se traten como duplicados y se salte el UPDATE de stock) o DELETE FROM meli_webhook_dedup. La RPC meli_webhook_seen ya es SECURITY DEFINER, por lo que el acceso directo de authenticated a la tabla no se necesita.

**Evidencia (código real)**:
```
CREATE TABLE IF NOT EXISTS public.meli_webhook_dedup ( dedup_key TEXT PRIMARY KEY, hit_count INTEGER NOT NULL DEFAULT 1, first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), expires_at TIMESTAMPTZ NOT NULL );  -- el archivo NO contiene 'ENABLE ROW LEVEL SECURITY' ni CREATE POLICY (única tabla del repo en esa condición)
```

**Corrección propuesta**:
```
```sql
ALTER TABLE public.meli_webhook_dedup ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.meli_webhook_dedup FROM anon, authenticated;
-- sin policy: service_role (bypass RLS) y la RPC SECURITY DEFINER siguen operando; el resto queda denegado por defecto
```
```

**Notas del verificador sobre el fix**: ENABLE ROW LEVEL SECURITY + REVOKE ALL FROM anon,authenticated (sin policy) es correcto: service_role bypassa RLS y meli_webhook_seen/cleanup son SECURITY DEFINER (corren como owner). No rompe el flujo real. Nota de severidad: envenenar un webhook especifico exige adivinar dedup_key exacto (incluye timestamp 'sent', dificil); pero DELETE masivo + el gap de aislamiento en si son el nucleo real del hallazgo.

**Referencia oficial**: https://supabase.com/docs/guides/database/database-linter?lint=0010_security_definer_view#rls-disabled-in-public

<details><summary>Verificación adversarial</summary>

Confirmado: 20260430000000_meli_webhook_dedup.sql crea public.meli_webhook_dedup SIN 'ENABLE ROW LEVEL SECURITY' ni CREATE POLICY. Diff automatizado de tablas creadas vs con RLS: meli_webhook_dedup es la UNICA con 0 referencias a ROW LEVEL SECURITY/CREATE POLICY (contacts/orders/order_items/conversation_carts/etc tienen 2 refs c/u; su hermana webhook_events_seen SI tiene RLS+policy en 20260514130000:116-123). config.toml expone public via PostgREST y Supabase concede default privileges a anon/authenticated sobre tablas public. Sin RLS ni REVOKE, un authenticated puede INSERT dedup_keys, DELETE FROM meli_webhook_dedup (wipe total) o inflar la tabla. La RPC meli_webhook_seen ya es SECURITY DEF […]

</details>

---

### F7 · 🟡 MEDIUM — Preview del agente IA ('Probar agente') opera SIEMPRE sin catálogo: consulta products.name y products.is_active, columnas inexistentes (reales: title/status)

**Ubicación**: `apps/web/app/api/ai/preview/route.ts:83` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: products se define en 20260406181236_catalog_schema.sql con title y status ('active' default) — nunca existieron name ni is_active. supabase-js no lanza: retorna {data:null, error} y la ruta hace `catalogRes.data ?? []` sin chequear error → el catálogo del preview queda vacío en silencio y el bot de prueba responde sin conocer ningún producto, dando al tenant una impresión falsa de su agente. El patrón correcto está en el mismo repo: dashboard/page.tsx:50 usa .eq('status', 'active') y catalog/page.tsx selecciona title.

**Evidencia (código real)**:
```
supabase.from('products')
  .select('name, description, product_variations(price, stock_quantity, attributes)')
  .eq('tenant_id', tenantId)
  .eq('is_active', true)
  .limit(20),
```

**Corrección propuesta**:
```
supabase.from('products')
  .select('title, description, product_variations(price, stock_quantity, attributes)')
  .eq('tenant_id', tenantId)
  .eq('status', 'active')
  .limit(20),

y actualizar el tipo/uso posterior (línea 90): `Array<{ title: string; ... }>` y donde se arma el prompt usar p.title en vez de p.name.
```

**Notas del verificador sobre el fix**: Fix correcto y completo: cambia select a title + filtro status='active', y menciona actualizar el tipo de la línea 90 y `p.name`→`p.title` en la línea 159 del prompt. No rompe nada más — la ruta es el único consumidor de ese shape.

**Referencia oficial**: https://supabase.com/docs/reference/javascript/select

<details><summary>Verificación adversarial</summary>

Confirmado. supabase/migrations/20260406181236_catalog_schema.sql define products con `title` y `status TEXT DEFAULT 'active'`; ningún ALTER posterior (fase11_3, retracto, safety_note, adr0029_f2) añade `name` ni `is_active`. apps/web/app/api/ai/preview/route.ts:82-86 selecciona `name` y filtra `.eq('is_active', true)` → PostgREST retorna error (columna inexistente), la ruta hace `catalogRes.data ?? []` (línea 90) sin chequear `catalogRes.error` → catálogo vacío silencioso y el system prompt (línea 153) omite la sección CATÁLOGO siempre. El patrón correcto existe en dashboard/page.tsx:50 (`.eq('status','active')`) y todos los demás consumidores usan `title`. Ninguna defensa: no hay vista ni  […]

</details>

---

### F5 · 🟡 MEDIUM — Invariant anti cierre-pasivo (ADR-0018) desactivado de facto: cuenta items en la tabla inexistente cart_items (la canónica es conversation_cart_items)

**Ubicación**: `services/ai-orchestrator/agentic/invariants/passive_closing.py:130` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: No existe tabla cart_items en ninguna migración; la tabla real es conversation_cart_items (20260501000000_conversation_carts.sql:97). La query lanza APIError, el except de la línea 152 la silencia y retorna items_count=0 → en la línea 161 `if state["items_count"] == 0` el invariant concluye 'cart vacío → OK' y NUNCA reescribe cierres pasivos con carrito lleno — exactamente el caso runtime (conv 3b0452e8) que motivó el módulo. Guardrail permanentemente inerte sin síntoma visible.

**Evidencia (código real)**:
```
items_res = (
    supabase.table("cart_items")
    .select("id", count="exact", head=True)
    .eq("cart_id", cart["id"])
    .execute()
)
```

**Corrección propuesta**:
```
Apuntar a la tabla real y añadir el filtro tenant canónico (ADR-0025):

items_res = (
    supabase.table("conversation_cart_items")
    .select("id", count="exact", head=True)
    .eq("cart_id", cart["id"])
    .eq("tenant_id", tenant_id)
    .execute()
)
```

**Notas del verificador sobre el fix**: Correcto: conversation_cart_items existe y tiene tenant_id (índice idx_cart_items_tenant lo confirma), y añadir .eq('tenant_id', tenant_id) cumple ADR-0025. INCOMPLETO sin actualizar el mock del test (tests/agentic/test_invariant_passive_closing.py:55 'cart_items' → 'conversation_cart_items'), si no el test deja de cubrir la rama con items. Verificar también otros mocks en tests/agentic/test_invariants.py.

**Referencia oficial**: https://docs.postgrest.org/en/v12/references/errors.html

<details><summary>Verificación adversarial</summary>

CONFIRMADO con un matiz de impacto. No existe tabla cart_items: grep en supabase/migrations solo encuentra conversation_cart_items (20260501000000:97); la única referencia productiva a 'cart_items' a secas es passive_closing.py:130. La query lanza APIError, el except de la línea 152 la silencia → items_count=0. Prueba adicional: el test tests/agentic/test_invariant_passive_closing.py:55 mockea name=='cart_items' — por eso el suite pasa con la tabla inexistente. MATIZ: la afirmación 'NUNCA reescribe' es incorrecta — el flujo real es peor de otra forma: validate() SÍ retorna REWRITE (líneas 237-264) pero con el CTA de la rama items_count==0 ('¿Te muestro algún producto o categoría en particula […]

</details>

---

### F120 · 🟡 MEDIUM — Tracking de envíos partido en dos tablas solapadas (order_tracking para MeLi vs shipments para Aveonline) sin sync: cada lector ve solo un proveedor

**Ubicación**: `services/ai-orchestrator/tools/order_status_tool.py:304` · **Detectado por**: db-overlap · 🆕 nuevo

**Causa**: order_tracking (20260420000001) nació para 'centralizar tracking de cualquier proveedor' pero solo la escribe meli_webhook.py:643-668. El provider activo (Aveonline, ADR-0019) escribe shipments (shipping.py:326,594) + shipment_tracking_events. Resultado: misma responsabilidad (tracking_number/url/carrier/status por orden) en dos tablas, cada una poblada por un proveedor distinto. Los lectores divergen: el tool legacy (aún cableado vía tools/inbound_dispatcher.py:24) lee SOLO order_tracking → nunca ve guías Aveonline; el tool agentic (agentic/tools/orders.py:169) lee SOLO shipments → nunca ve tracking MeLi.

**Evidencia (código real)**:
```
order_status_tool.py:304 `supabase.table("order_tracking").select("status, tracking_number, tracking_url, carrier, estimated_delivery")` vs agentic/tools/orders.py:169-170 `ctx.supabase.table("shipments").select("order_id, status, carrier, tracking_number, tracking_url")`
```

**Corrección propuesta**:
```
Corto plazo: fallback dual-read en ambos tools. En order_status_tool._get_order_tracking, si order_tracking viene vacío:
```python
sh = (supabase.table("shipments")
      .select("status, tracking_number, tracking_url, carrier")
      .eq("tenant_id", tenant_id).eq("order_id", order_id)
      .order("created_at", desc=True).limit(1).execute())
if sh.data:
    return sh.data[0]
```
y espejo en agentic/tools/orders.py (fallback a order_tracking para órdenes MeLi). Estructural: consolidar — que meli_webhook escriba shipments (provider='mercadolibre') y deprecar order_tracking con vista de compatibilidad + drop expand-contract.
```

**Notas del verificador sobre el fix**: Dual-read correcto: shipments tiene order_id, carrier, tracking_number/url, status, created_at (20260409230000_shipments.sql). Caveats menores: (1) shipments no tiene estimated_delivery — el fallback retorna sin ese campo, el tool debe tolerarlo (ya usa .get); (2) filtrar además status != 'quoted' o exigir tracking_number no nulo, porque shipping.py:326 inserta filas 'quoted' sin guía (el .eq(order_id) ya excluye la mayoría al ser quotes sin orden). La consolidación estructural (meli_webhook → shipments con expand-contract) es la dirección correcta y coherente con el patrón del repo.

<details><summary>Verificación adversarial</summary>

Verificado por completo: order_status_tool.py:296-315 lee SOLO order_tracking, cuya única escritura es meli_webhook.py:643-668 (router registrado en services/api/main.py:172 — MeLi está live, cf. commit F4 stock sync). agentic/tools/orders.py:169 lee SOLO shipments, escrita por shipping.py:326/594 (Aveonline). Ambos lectores alcanzables en runtime: dispatcher.py decide legacy (tenant.agentic_enabled=False → inbound_dispatcher → order_status_tool) vs agentic (KAIU). Escenario concreto: meli_webhook.py:530 crea contact_id por teléfono del buyer → si ese buyer escribe al WhatsApp del tenant y pregunta por su pedido, el tool agentic lista la orden MeLi SIN tracking (shipments vacío para esa orde […]

</details>

---

### F133 · 🟡 MEDIUM — Cron de recordatorios de pago escanea orders cada 60s filtrando solo por status sin índice utilizable — seq scan perpetuo que crece con la tabla

**Ubicación**: `services/ai-orchestrator/worker.py:1156` · **Detectado por**: performance · 🆕 nuevo

**Causa**: `_send_payment_reminders_if_due` (cada PAYMENT_REMINDER_INTERVAL_SECONDS=60) y `_release_expired_pending_payment_orders` (línea 1846, cada 600s) filtran orders cross-tenant por `.eq("status", "pending_payment")` + rango de created_at. El único índice existente es `idx_orders_status ON public.orders(tenant_id, status)` (migración 20260409220000_fase9_schema_core.sql:137), cuyo prefijo tenant_id NO aparece en el predicado → un B-tree con columna líder ausente no sirve el filtro y Postgres hace sequential scan de orders completa cada 60 segundos, para siempre. A 100k órdenes son ~1440 seq scans/día de toda la tabla para encontrar típicamente 0-5 filas. El repo ya usa el patrón correcto en otros crons (idx_conversations_human_takeover_at es parcial por status, idx_conversation_carts_open_ttl idem).

**Evidencia (código real)**:
```
.eq("status", "pending_payment")
                .is_("payment_reminder_sent_at", "null")
                .lt("created_at", upper_cutoff)
                .gte("created_at", lower_cutoff)
                .limit(50)
```

**Corrección propuesta**:
```
Índice parcial que cubre ambos crons (mismo patrón ya usado en 20260702180000_f6):
```sql
-- supabase/migrations/20260703000000_orders_pending_payment_cron_idx.sql
-- Cron worker (_send_payment_reminders_if_due 60s + _release_expired_pending_payment_orders 600s)
-- filtra status='pending_payment' SIN tenant_id: idx_orders_status(tenant_id, status) no aplica.
CREATE INDEX IF NOT EXISTS idx_orders_pending_payment_cron
  ON public.orders (created_at)
  WHERE status = 'pending_payment';
```
El índice queda diminuto (solo órdenes en pending_payment, TTL 35 min) y ambas queries pasan a index scan.
```

**Notas del verificador sobre el fix**: Índice parcial correcto: (created_at) WHERE status='pending_payment' sirve ambas queries (el rango created_at es la condición selectiva restante; payment_reminder_sent_at IS NULL se filtra sobre un índice diminuto — órdenes viven ≤35 min en pending_payment por PENDING_PAYMENT_TTL_MINUTES). CREATE INDEX sin CONCURRENTLY es aceptable dentro de la transacción de migración dado el tamaño de la tabla; recordar el protocolo de feedback_supabase_migrations (drift del ledger remoto) al aplicarlo.

**Referencia oficial**: https://www.postgresql.org/docs/current/indexes-partial.html

<details><summary>Verificación adversarial</summary>

Confirmado: worker.py:1152-1161 (_send_payment_reminders_if_due, cada 60s) y worker.py:1843-1850 (_release_expired_pending_payment_orders, cada 600s) filtran orders cross-tenant por status='pending_payment' + created_at, con exemption explícito del lint tenant (tenant_filter:exempt:cron_cross_tenant_*). Índices reales de orders verificados en migraciones: idx_orders_tenant(tenant_id), idx_orders_status(tenant_id,status), idx_orders_contact(contact_id), orders_cod_pending_idx (parcial WHERE payment_method='cod', 20260531000000) e idx_orders_cancelled (parcial WHERE cancelled_at IS NOT NULL, 20260606000000). Ninguno sirve el predicado (columna líder tenant_id ausente; skip-scan es PG≥18, no as […]

</details>

---

### F9 · 🟡 MEDIUM — Endpoint /aveonline/guide-dry-run responde 500 siempre: selecciona 8 columnas planas de tenants que no existen (shipping_origin_city/state/dane/address/phone/email/nit-plano/idagente)

**Ubicación**: `services/api/routers/integrations.py:568` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: tenants guarda el origen de despacho como JSONB shipping_origin (20260409270000_tenant_shipping_origin.sql) más nit; ninguna migración crea columnas planas shipping_origin_* ni idagente. supabase-py lanza APIError no capturada → el endpoint owner-only de UAT Aveonline devuelve 500 en toda invocación. Diverge del path productivo, que lee correctamente el JSONB: wompi_webhook.py:1346 `.select("name, shipping_origin, telefono_contacto, email_contacto, nit")`.

**Evidencia (código real)**:
```
.select(
    "name, shipping_origin_city, shipping_origin_state, "
    "shipping_origin_dane, shipping_origin_address, "
    "shipping_origin_nit, shipping_origin_phone, "
    "shipping_origin_email, idagente"
)
```

**Corrección propuesta**:
```
Alinear con el path productivo (wompi_webhook.py:1346) leyendo el JSONB:

tenant_res = (
    supabase.table("tenants")
    .select("name, shipping_origin, telefono_contacto, email_contacto, nit")
    .eq("id", tenant_id).single().execute()
)
tenant = tenant_res.data or {}
origin = tenant.get("shipping_origin") or {}
# reemplazar los tenant.get("shipping_origin_city") etc. por
# origin.get("city"), origin.get("dane_code"), tenant.get("nit"),
# tenant.get("telefono_contacto"), tenant.get("email_contacto").
# idagente vive en tenant_integrations(provider='aveonline').credentials,
# no en tenants — resolverlo vía AveonlineClient como hace el path productivo.
```

**Notas del verificador sobre el fix**: Fix correcto: alinear con wompi_webhook (JSONB shipping_origin + nit/telefono_contacto/email_contacto; keys reales del JSONB: city/state/street/phone/dane_code/name). idagente efectivamente vive en tenant_integrations.credentials vía AveonlineClient (ctor: AveonlineClient(tenant_id, supabase)) — la keyword-call existente en línea 585 sigue válida. Requiere también ajustar las referencias downstream (líneas 599-642, 676).

**Referencia oficial**: https://docs.postgrest.org/en/v12/references/errors.html

<details><summary>Verificación adversarial</summary>

integrations.py:565-574 selecciona 8 columnas planas + idagente de tenants. Única migración de origen de despacho: 20260409270000_tenant_shipping_origin.sql crea shipping_origin JSONB; grep en supabase/migrations no encuentra shipping_origin_city/dane/etc ni idagente. El .single() sin try/except lanza APIError (42703) → 500 en toda invocación que pase los pasos 1-2 (order válida + cart con rate_id) — alcanzable por el owner vía POST /aveonline/guide-dry-run. El path productivo (wompi_webhook.py:1342-1353) lee el JSONB correctamente, confirmando la divergencia. Sin callers en apps/scripts: es herramienta de diagnóstico owner-only, no flujo productivo → severidad menor a la reportada.

</details>

---

### F123 · 🟡 MEDIUM — Tres tablas de dedup de webhooks coexisten (wompi_events_seen + meli_webhook_dedup + webhook_events_seen); el follow-up de consolidación (~30d) lleva ~7 semanas vencido y el shape legacy ya limita al código

**Ubicación**: `services/api/routers/wompi_webhook.py:108` · **Detectado por**: db-overlap · 📌 ya rastreado (audit finiquito §5 Canales — gap técnico 'webhook_framework (F.1) sin consumidores — meli/telegram/aveonline/wompi duplican signature verify + dedup + rate-limit ad-hoc (5 implementaciones del mismo patrón)' + §9 gap 'Webhook framework existe pero solo se usa parcialmente')

**Causa**: 20260514130000 creó webhook_events_seen como dedup genérica y documentó migrar Wompi/MeLi '~30d post-deploy'. Nunca ocurrió: wompi_webhook.py sigue en wompi_events_seen (línea 138), meli_webhook.py en la RPC meli_webhook_seen (línea 145), y solo Aveonline usa la genérica. No es solo deuda estética: el shape legacy causa pérdida funcional — wompi_events_seen.tenant_id es NOT NULL, así que los eventos huérfanos (pago de link purgado / posible fraude) NO se pueden persistir para reconciliación y quedan solo en logs, mientras la genérica ya soporta tenant_id NULL exactamente para ese caso.

**Evidencia (código real)**:
```
wompi_webhook.py:108-110 `# No persistimos en tabla porque `wompi_events_seen.tenant_id` es NOT NULL. El log con prefijo `[WOMPI][ORPHAN]` es greppable...` y 20260514130000: 'refactor de Wompi/MeLi a la genérica queda como follow-up tras estabilizar (~30d post-deploy)'
```

**Corrección propuesta**:
```
Ejecutar el follow-up documentado: 1) en wompi_webhook.py sustituir el insert manual por `from lib.webhook_dedup import check_or_register` → `is_dup = check_or_register(supabase, integration="wompi", event_uid=event_uid, tenant_id=tenant_id_for_sig, event_type=event_name)` y persistir también los huérfanos con `tenant_id=None`; 2) en meli_webhook.py reemplazar la RPC meli_webhook_seen por webhook_event_check_or_register(integration='meli', event_uid=f"{app_id}|{resource}|{sent}"); 3) migración posterior: DROP de wompi_events_seen y meli_webhook_dedup + sus RPCs tras ventana de convivencia.
```

**Notas del verificador sobre el fix**: Es el follow-up documentado y la lib ya lista wompi/meli en SUPPORTED_INTEGRATIONS (webhook_dedup.py:33-35). Ajustes: (1) el helper se llama is_duplicate, no check_or_register (la RPC es webhook_event_check_or_register); (2) is_duplicate LEVANTA excepción en fallo de RPC (webhook_dedup.py:64-66) — envolver en try/except para preservar el fail-open actual de Wompi (líneas 146-163); (3) persistir huérfanos ANTES de verificar firma registra payloads no verificados en el namespace de dedup — usar integration/tag separado (ej. 'wompi_orphan') o tabla aparte, no el UNIQUE de dedup; (4) el shape genérico pierde columnas forenses de wompi_events_seen (transaction_id, reference, status) — mapear a event_type/correlation_id o aceptar la pérdida explícitamente; (5) DROP solo tras ventana de convivencia (ya contemplado).

<details><summary>Verificación adversarial</summary>

Hechos verificados: wompi_webhook.py:138 inserta en wompi_events_seen (tabla específica), meli_webhook.py:145 usa RPC meli_webhook_seen, y solo Aveonline usa la genérica (aveonline_webhook.py:24 + webhook_framework/idempotency.py). La migración 20260514130000 documenta el follow-up '~30d post-deploy' (rev. 105, 2026-05-14) — vencido ~7 semanas al 2026-07-03. La limitación funcional es real y auto-documentada: wompi_webhook.py:108-111 'No persistimos en tabla porque wompi_events_seen.tenant_id es NOT NULL' — huérfanos (pago de link purgado, posible APPROVED) quedan solo en logs [WOMPI][ORPHAN], mientras webhook_events_seen.tenant_id es nullable exactamente para ese caso. Matiz: es deuda delib […]

</details>

---

### F14 · 🟡 MEDIUM — Falta índice en conversations(tenant_id, customer_phone): el lookup del path de entrada (cada mensaje inbound de WhatsApp) filtra por customer_phone sin índice que lo cubra

**Ubicación**: `services/connector-whatsapp/services/db_persistence.py:118` · **Detectado por**: db-indexes-rls · 🆕 nuevo

**Causa**: En CADA mensaje entrante el connector ejecuta `conversations WHERE tenant_id=X AND customer_phone=Y ORDER BY last_interaction_at DESC LIMIT 1`. Los índices existentes sobre conversations son (tenant_id, last_interaction_at DESC) [20260427030000], (tenant_id, channel) y (agentic_state); ninguno tiene customer_phone. grep de 'customer_phone' en las migraciones no arroja ningún índice. A medida que crece la tabla por tenant, este lookup caliente degrada a scan filtrado por customer_phone.

**Evidencia (código real)**:
```
res = ( supabase.table("conversations").select("id, status").eq("tenant_id", tenant_id).eq("customer_phone", customer_phone).order("last_interaction_at", desc=True).limit(1).execute() )  // sin índice (tenant_id, customer_phone) en supabase/migrations/
```

**Corrección propuesta**:
```
Nueva migración:
```sql
CREATE INDEX IF NOT EXISTS idx_conversations_tenant_phone
  ON public.conversations (tenant_id, customer_phone, last_interaction_at DESC);
```
```

**Notas del verificador sobre el fix**: Índice (tenant_id, customer_phone, last_interaction_at DESC) cubre equality+order exactamente; correcto y sin riesgo funcional. Notas: aplicar per protocolo seguro de migraciones remote (ledger con drift, memoria feedback_supabase_migrations); tabla pequeña hoy así que CREATE INDEX transaccional es aceptable, en prod grande considerar CONCURRENTLY fuera de transacción.

<details><summary>Verificación adversarial</summary>

Confirmado. db_persistence.py:119-127 ejecuta en CADA mensaje inbound `conversations WHERE tenant_id AND customer_phone ORDER BY last_interaction_at DESC LIMIT 1`. Grep exhaustivo de migraciones: los únicos índices de conversations son idx_conversations_tenant_last_interaction (20260427030000), idx_conversations_tenant_active_last_interaction parcial WHERE archived_at IS NULL (20260428000003), conversations_tenant_channel_idx (20260609000000), idx_conversations_agentic_state (20260604000000) e idx_conversations_human_takeover_at (20260702180000). NINGUNO incluye customer_phone; tampoco hay UNIQUE(tenant_id, customer_phone). Mitigación parcial: el planner puede usar (tenant_id, last_interacti […]

</details>

---

### F121 · 🟡 MEDIUM — reactivate_consent escribe el mismo evento en audit_log (decorator) Y consent_audit_log → vw_consent_events_unified lo cuenta DOS veces en el reporte SIC; record_consent hace lo inverso (solo audit_log, con event_kind no canónico)

**Ubicación**: `supabase/migrations/20260509010000_unified_audit_view.sql:65` · **Detectado por**: db-overlap · 🆕 nuevo

**Causa**: La decisión intencional (rev. 101) era 'cada tabla tiene su rol' unidas por la vista. El código la contradice: reactivate_consent lleva @audit_log(action="consent_reactivated") (contacts.py:641) Y ADEMÁS inserta consent_audit_log event='granted' (contacts.py:727) — como la vista incluye del legacy todo `action ILIKE '%consent%'`, una reactivación aparece 2 veces (origin_table distinto, mismo hecho). Simétricamente, record_consent (contacts.py:538) SOLO escribe audit_log vía decorator: sus grants/revokes entran a la vista con event_kind='consent_recorded' (rama ELSE del CASE), invisible para un filtro SIC por event_kind='granted'.

**Evidencia (código real)**:
```
Vista líneas 63-70: `WHERE al.entity_type = 'contact' AND ( al.action ILIKE '%consent%' ...` combinado con contacts.py:641 `@audit_log(entity_type="contact", action="consent_reactivated")` + contacts.py:727 `supabase.table("consent_audit_log").insert({ ... "event": "granted", "source": "tenant_console", ...})`
```

**Corrección propuesta**:
```
1) record_consent: añadir insert explícito a consent_audit_log (event='granted'/'revoked', source=body.channel) igual que hace el dispatcher agentic. 2) Excluir de la rama legacy de la vista las actions que ya tienen row canónico:
```sql
CREATE OR REPLACE VIEW public.vw_consent_events_unified AS
... -- rama legacy:
 WHERE al.entity_type = 'contact'
   AND al.action NOT IN ('consent_reactivated', 'consent_recorded')  -- ya canónicos en consent_audit_log
   AND ( al.action ILIKE '%consent%' OR al.action ILIKE '%revok%' OR al.action ILIKE '%rectif%' OR al.action = 'deleted' );
```
(aplicar la exclusión de 'consent_recorded' SOLO después de backfillear los eventos históricos de audit_log a consent_audit_log, o dejarla fuera hasta entonces).
```

**Notas del verificador sobre el fix**: El fix es correcto pero con el caveat que el propio hallazgo reconoce: (1) agregar insert explicito a consent_audit_log en record_consent corrige solo eventos NUEVOS. (2) excluir 'consent_recorded'/'consent_reactivated' de la rama legacy de la vista SOLO tras backfillear los historicos de audit_log a consent_audit_log — de lo contrario se ocultan eventos historicos que solo viven en audit_log. Aplicar en ese orden. Correcto y no rompe RLS (la vista mantiene security_invoker=true).

<details><summary>Verificación adversarial</summary>

Confirmado en codigo + vista SQL. contacts.py:640-641 reactivate_consent tiene @audit_log(action='consent_reactivated') (escribe audit_log) Y contacts.py:727 inserta consent_audit_log event='granted'. La vista vw_consent_events_unified (20260518000000:41-91) hace UNION ALL de consent_audit_log + audit_log filtrando entity_type='contact' AND action ILIKE '%consent%'; 'consent_reactivated' matchea el WHERE pero NO ninguna rama del CASE (given/granted/revok/rectif/updated) -> cae en ELSE=action. Resultado: una reactivacion produce 2 filas (origin='consent_audit_log' event_kind='granted' + origin='audit_log' event_kind='consent_reactivated') — doble aparicion para el caso de uso #1 (todos los ev […]

</details>

---

### F13 · 🟡 MEDIUM — RPCs de dedup/rate-limit SECURITY DEFINER sin REVOKE (webhook_event_check_or_register, webhook_event_mark_processed, meli_webhook_seen, rate_limit_hit) → un authenticated puede pre-registrar event_uids y anular procesamiento de webhooks / falsear el rate limiter

**Ubicación**: `supabase/migrations/20260514130000_webhook_events_seen.sql:68` · **Detectado por**: db-indexes-rls · 🆕 nuevo

**Causa**: Estas funciones SECURITY DEFINER no tienen REVOKE y quedan expuestas a anon/authenticated por PostgREST. webhook_event_check_or_register hace INSERT ... ON CONFLICT DO NOTHING y devuelve TRUE si ya existía: un atacante que llame primero con (integration,event_uid) previsibles logra que el webhook legítimo posterior se considere 'duplicado' y se descarte (impacto en Wompi/MeLi/Aveonline según integración). rate_limit_hit permite inflar/consumir la ventana de rate limit de un tenant. Sólo las usan api/worker con service_role.

**Evidencia (código real)**:
```
CREATE OR REPLACE FUNCTION public.webhook_event_check_or_register(p_integration TEXT, p_event_uid TEXT, p_tenant_id UUID DEFAULT NULL, ...) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER AS $$ ... INSERT INTO public.webhook_events_seen (...) ON CONFLICT (integration, event_uid) DO NOTHING; ... RETURN (v_inserted_rows = 0); END; $$;  -- sin REVOKE
```

**Corrección propuesta**:
```
```sql
REVOKE ALL ON FUNCTION public.webhook_event_check_or_register(text, text, uuid, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.webhook_event_mark_processed(text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.meli_webhook_seen(text, text, text, integer) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.rate_limit_hit(text, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.webhook_event_check_or_register(text, text, uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.webhook_event_mark_processed(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.meli_webhook_seen(text, text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.rate_limit_hit(text, integer, integer) TO service_role;
```
(Ajustar las firmas exactas de rate_limit_hit según 20260510070000_fix_rate_limit_hit_bigint_cast.sql)
```

**Notas del verificador sobre el fix**: REVOKE FROM PUBLIC,anon,authenticated + GRANT service_role correcto; las firmas citadas coinciden con las definiciones verificadas: rate_limit_hit(text,integer,integer), webhook_event_check_or_register(text,text,uuid,text,text), meli_webhook_seen(text,text,text,integer), webhook_event_mark_processed(text,text). No rompe callers backend.

**Referencia oficial**: https://supabase.com/docs/guides/api/securing-your-api

<details><summary>Verificación adversarial</summary>

Confirmado: webhook_event_check_or_register + webhook_event_mark_processed (20260514130000:68,96) son SECURITY DEFINER; meli_webhook_seen (20260430000000:24) y rate_limit_hit (20260510070000:22) SECURITY DEFINER. grep REVOKE global: ninguna tiene REVOKE. Expuestas via PostgREST a authenticated. webhook_event_check_or_register hace INSERT ON CONFLICT DO NOTHING y retorna TRUE si ya existia: pre-registrar (integration,event_uid) hace que el webhook legitimo posterior se descarte como duplicado. rate_limit_hit permite consumir/inflar la ventana de un tenant. Exposicion real; explotabilidad parcial: para Wompi event_uid=event.id (UUID/hash impredecible) limita el ataque, pero para MeLi (app_id|r […]

</details>

---

### F111 · 🟡 MEDIUM — Infra MA-1 outbound_idempotency_cache desplegada en DB (tabla + 3 RPCs) y módulo Python completo, con cero consumidores y cleanup jamás agendado

**Ubicación**: `supabase/migrations/20260514150000_outbound_idempotency_cache.sql:21` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: La migración crea la tabla y las funciones outbound_idempotency_lookup/register/cleanup ('Cleanup cron — borra expirados. Llamar daily desde pg_cron o worker', línea 113). El wrapper Python existe (services/api/lib/integration_client/idempotency.py) pero nadie lo importa; el framework IntegrationClient se autodocumenta 'NO consumidores aún' (__init__.py); solo retry.py se usa (wompi_client). Ni pg_cron ni worker.py llaman outbound_idempotency_cleanup (el cleanup cron del worker cubre rate_limit, meli_dedup, webhook_secrets, bot_source_log e idempotency_keys — no este). Consecuencia: la mitigación MA-1 contra doble efecto en retries figura como cerrada en la migración pero no protege ningún request real, y al día que un cliente empiece a registrar entradas, la tabla crecerá sin poda.

**Evidencia (código real)**:
```
idempotency.py:131: res = supabase_client.rpc("outbound_idempotency_cleanup", {}).execute() — función cleanup_expired sin ningún caller en services/ ni scripts/; migración :113: '-- Cleanup cron — borra expirados. Llamar daily desde pg_cron o worker.'
```

**Corrección propuesta**:
```
Paso 1 (barato, cierra el gap de poda futura) — agendar el cleanup junto a los demás en worker.py:_run_idempotency_cleanup_if_due (~línea 805):

        try:
            self.supabase.rpc("outbound_idempotency_cleanup").execute()
        except Exception as exc:
            logger.warning("outbound_idempotency_cleanup falló: %s", exc)

Paso 2 — al adoptar create_payment_link_with_resilience (hallazgo Wompi), integrar lookup/register en ese wrapper según el docstring de idempotency.py:11-19, que es exactamente el caso de uso diseñado. Si la Fase 13 lo descarta, droppear tabla+RPCs+módulo en una migración F7-style.
```

**Notas del verificador sobre el fix**: Paso 1 (agendar self.supabase.rpc('outbound_idempotency_cleanup') junto a los demas en _run_idempotency_cleanup_if_due) es barato, correcto y no rompe nada (la RPC es no-op si la tabla esta vacia). Paso 2 (integrar lookup/register al adoptar el wrapper Wompi) es coherente con el diseno. Severidad real es baja: sin consumidor no hay dano activo; es prevencion.

<details><summary>Verificación adversarial</summary>

Confirmado: worker.py:768-827 (_run_idempotency_cleanup_if_due) agenda cleanup de rate_limit_windows, meli_webhook_dedup, webhook_secrets, bot_source_log e idempotency_keys — pero NO llama outbound_idempotency_cleanup. La migracion 20260514150000:113 dice 'Cleanup cron — Llamar daily desde pg_cron o worker'. El wrapper Python existe (services/api/lib/integration_client/idempotency.py) e IntegrationClient.execute() SI lo consume (base.py:180,230 idemp.lookup/register), PERO el framework se autodocumenta 'NO consumidores aun' (__init__.py) y los clientes existentes (aveonline/wompi/meli) no lo usan; MetaBusinessManagementClient subclasea IntegrationClient pero whatsapp_templates.py lo marca co […]

</details>

---

### F108 · 🟡 MEDIUM — Tabla rma_requests (derecho de retracto Ley 1480 Art. 47): DDL completo con FSM de estados pero CERO writes y CERO reads en todo el código

**Ubicación**: `supabase/migrations/20260606000000_cancellation_and_retracto.sql:158` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: La migración crea rma_requests con enum de 7 estados, retracto_deadline (delivered + 5 días hábiles) e índices, como parte del 'ciclo completo de cancelación/retracto (Ley 1480 Art. 47)'. Su tabla hermana order_cancellations sí está cableada (services/ai-orchestrator/lib/order_cancellation.py). Pero rma_requests solo aparece en el código en la lista de borrado de offboarding (services/api/lib/tenant_offboarding.py:77). Nada la puebla (ni bot, ni claims, ni UI) y nada la lee: la mitad post-entrega del ciclo de cumplimiento anunciado en la migración no existe — tabla muerta que aparenta cumplimiento implementado.

**Evidencia (código real)**:
```
Único ref en código: services/api/lib/tenant_offboarding.py:77: "rma_requests", (lista de tablas a borrar). Migración :140: '-- ── 3. Tabla rma_requests (Retracto Ley 1480 Art. 47 — post-entrega) ────────'
```

**Corrección propuesta**:
```
Decisión founder requerida (2 caminos):
A) Cablear el flujo mínimo: en claims.py, cuando claim_type='retracto' y la orden está delivered, insertar la solicitud:
  supabase.table("rma_requests").insert({
      "tenant_id": tenant_id, "order_id": order_id,
      "status": "requested", "reason_code": "retracto_art_47",
      "retracto_deadline": deadline_iso, "items": items,
  }).execute()
y exponer lectura en la página de claims.
B) Si retracto se decide fuera de scope hoy: droppear en la próxima migración estilo F7:
  DROP TABLE IF EXISTS public.rma_requests;
y retirarla de tenant_offboarding.py:77 — evita el falso positivo de cumplimiento.
```

**Notas del verificador sobre el fix**: Ambos caminos son validos: (A) cablear insert en claims.py cuando claim_type='retracto' + orden delivered y exponer lectura; (B) DROP TABLE + retirar de tenant_offboarding.py:77. Requiere decision founder (no es un fix mecanico unico). Si se elige (A), validar que el enum de estados/reason_code coincida con el DDL. Si (B), la remocion de la linea 77 evita KeyError en el borrado de offboarding.

<details><summary>Verificación adversarial</summary>

Confirmado por grep exhaustivo: rma_requests (creada con FSM de 7 estados + retracto_deadline + indices en 20260606000000_cancellation_and_retracto.sql) aparece en TODO el codigo solo en services/api/lib/tenant_offboarding.py:77 (lista de tablas a borrar en offboarding). Cero INSERT/UPDATE/SELECT en services/ o scripts/. Su tabla hermana order_cancellations si esta cableada (services/ai-orchestrator/lib/order_cancellation.py). Es una tabla muerta: la mitad post-entrega del ciclo de retracto Ley 1480 Art. 47 anunciado en la migracion no existe en runtime — aparenta cumplimiento no implementado. No es un bug de seguridad/runtime sino un gap de completitud/cumplimiento; la afirmacion factual es […]

</details>

---

### F8 · ⚪ LOW — Readiness card de AI Agents reporta 'sin catálogo' siempre: filtra products por is_active, columna inexistente

**Ubicación**: `apps/web/app/dashboard/(ai)/ai-agents/page.tsx:45` · **Detectado por**: db-schema · 🆕 nuevo

**Causa**: Mismo drift que el preview: products no tiene is_active (la columna real es status). La query del Promise.all falla, catalogStats llega null y en la línea 89 `hasCatalog = Array.isArray(catalogStats) && catalogStats.length > 0` evalúa false permanente → la card de readiness indica al tenant que le falta catálogo aunque tenga productos activos.

**Evidencia (código real)**:
```
supabase.from('products')
  .select('id', { count: 'exact', head: false })
  .eq('tenant_id', tenantId)
  .eq('is_active', true)
  .limit(1),
```

**Corrección propuesta**:
```
Cambiar el filtro a la columna real:

supabase.from('products')
  .select('id', { count: 'exact', head: false })
  .eq('tenant_id', tenantId)
  .eq('status', 'active')
  .limit(1),
```

**Notas del verificador sobre el fix**: Fix correcto: `.eq('status', 'active')`. hasCatalog funciona con el array retornado (head: false + limit(1)). Sin efectos colaterales.

**Referencia oficial**: https://supabase.com/docs/reference/javascript/select

<details><summary>Verificación adversarial</summary>

Confirmado. ai-agents/page.tsx:42-46 filtra products por `.eq('is_active', true)` — columna inexistente (schema real: status). La query del Promise.all retorna error, `catalogStats` llega null, y línea 89 `hasCatalog = Array.isArray(catalogStats) && catalogStats.length > 0` evalúa false permanente → ReadinessCard reporta 'sin catálogo' aunque el tenant tenga productos activos. Mismo drift que F7, verificado contra las migraciones (products nunca tuvo is_active; los is_active encontrados pertenecen a kb_documents, tenant_agents, platform_categories, etc.).

</details>

---

### F15 · ⚪ LOW — Varias funciones SECURITY DEFINER sin SET search_path fijo (add_member_to_tenant, meli_webhook_seen, rate_limit_hit, webhook_event_*, outbound_idempotency_*, cleanup_expired_*) — vector search_path (CVE-2018-1058) y hallazgo del linter Supabase

**Ubicación**: `supabase/migrations/20260419000001_rbac_operator_runtime_only.sql:39` · **Detectado por**: db-indexes-rls · 🆕 nuevo

**Causa**: Estas definiciones SECURITY DEFINER no fijan search_path, por lo que resuelven objetos no calificados usando el search_path del caller; un usuario que pueda crear objetos en un schema anterior del path puede secuestrar referencias no calificadas ejecutándose con privilegios del definer. El propio repo aplica el patrón correcto en otras funciones (custom_access_token_hook, get_tenant_team, enqueue_whatsapp_outbound_message usan SET search_path), evidenciando el estándar interno.

**Evidencia (código real)**:
```
CREATE OR REPLACE FUNCTION public.add_member_to_tenant(...) RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN ... END; $$;  -- sin 'SET search_path' (idem meli_webhook_seen, webhook_event_check_or_register, rate_limit_hit, outbound_idempotency_*)
```

**Corrección propuesta**:
```
Pinnear search_path en cada función afectada, p.ej.:
```sql
ALTER FUNCTION public.add_member_to_tenant(uuid, uuid, text) SET search_path = public;
ALTER FUNCTION public.meli_webhook_seen(text, text, text, integer) SET search_path = public;
ALTER FUNCTION public.webhook_event_check_or_register(text, text, uuid, text, text) SET search_path = public;
ALTER FUNCTION public.webhook_event_mark_processed(text, text) SET search_path = public;
ALTER FUNCTION public.cleanup_expired_meli_webhook_dedup() SET search_path = public;
-- ...idem para rate_limit_hit y outbound_idempotency_lookup/register/cleanup
```
```

**Notas del verificador sobre el fix**: ALTER FUNCTION ... SET search_path=public es correcto para estas funciones (solo referencian objetos public; NO incluir pgmq salvo las de cola). Idempotente y sin impacto de runtime. Cierra el warning del Advisor.

**Referencia oficial**: https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable

<details><summary>Verificación adversarial</summary>

Factualmente confirmado: add_member_to_tenant (20260419000001:38-40), meli_webhook_seen + cleanup_expired_meli_webhook_dedup (20260430000000:31-33,58-62), webhook_event_check_or_register/mark_processed (20260514130000:77,102), rate_limit_hit (20260510070000: SECURITY DEFINER sin search_path) y outbound_idempotency_lookup/register/cleanup (20260514150000:68,95,117) son SECURITY DEFINER SIN SET search_path. El repo ya aplica el patron correcto en enqueue_whatsapp_outbound_message (SET search_path=public,pgmq) y custom_access_token_hook, evidenciando el estandar. Es un hallazgo valido del Supabase Advisor (function_search_path_mutable) + defensa en profundidad. CAVEAT de explotabilidad: el vect […]

</details>

---

### F125 · ⚪ LOW — envia_webhook_capture_log: tabla temporal de descubrimiento con raw bodies (posible PII) sigue viva sin ningún lector/escritor, sobrevivió a la deprecación de Envia y al drop de schema muerto F7

**Ubicación**: `supabase/migrations/20260514190000_envia_webhook_capture_log.sql:24` · **Detectado por**: db-overlap · 🆕 nuevo

**Causa**: La propia migración declara 'VIDA ÚTIL: temporal — esta tabla se DROPea o renombra cuando Fase B implemente procesadores reales'. El pivote Envia→Aveonline (20260601120000) eliminó el provider y F7 (20260702200000) dropeó el resto del schema Envia muerto (pickup_id, last_polled_at, envia_shipment_id), pero esta tabla quedó fuera del barrido. Cero referencias en services/, apps/ o scripts (verificado por grep). Al capturar raw_body/headers de webhooks de envíos, puede contener direcciones/teléfonos de clientes sin política de retención asociada (retention_policies no la cubre).

**Evidencia (código real)**:
```
20260514190000 líneas 14-17: '-- VIDA ÚTIL: temporal — esta tabla se DROPea o renombra cuando Fase B implemente procesadores reales' + 20260702200000 (F7) dropea attribute_values/category_attributes/columnas Envia de shipments pero no menciona envia_webhook_capture_log
```

**Corrección propuesta**:
```
Migración de drop siguiendo el patrón F7 (verificación 0 lectores ya hecha):
```sql
-- F7 follow-up: tabla temporal de captura Envia (provider deprecado 20260601120000, 0 lectores/writers)
DROP TABLE IF EXISTS public.envia_webhook_capture_log;
```
Si el founder quiere conservar las capturas históricas para forensics, exportarlas a storage antes del drop (INTERVENCION HUMANA: decidir conservar vs purgar; contiene raw bodies con posible PII).
```

**Notas del verificador sobre el fix**: DROP TABLE IF EXISTS es correcto y seguro (0 lectores/writers verificados; FK a tenants con CASCADE, sin dependientes). Bien planteada la INTERVENCION HUMANA (founder decide conservar vs purgar capturas — pueden contener PII real del shipment KAIU 171494). Añadir: seguir protocolo de migraciones remotas (ledger con drift) y regenerar fixture si aplica, como se hizo en F7.

<details><summary>Verificación adversarial</summary>

CONFIRMADO en todos sus puntos: (1) 20260514190000 líneas 14-17 declara la tabla 'VIDA ÚTIL: temporal... se DROPea o renombra' con promesa de 'migration de drop en revision posterior' que nunca llegó — grep en supabase/migrations/ no encuentra ningún DROP de envia_webhook_capture_log; 20260601120000 (deprecación Envia) solo la menciona en comentario y 20260702200000 (F7 drop dead schema) dropea attribute_values/category_attributes/pickup_id/last_polled_at pero no esta tabla. (2) Cero referencias runtime: grep en services/, apps/, scripts/ no encuentra 'envia_webhook_capture_log' ni 'capture_log' — solo migraciones y un session doc. (3) La tabla SÍ recibió datos reales: git history muestra el […]

</details>

---

## 2. Backend (API · Orchestrator · Connector)

### F42 · 🔴 CRITICAL — Un cupón aplicado (o cambio de carrier) tras generar el link Wompi no invalida la orden pending_payment y el bot reutiliza el link con el monto viejo — el cliente paga un monto distinto al total acordado

**Ubicación**: `services/ai-orchestrator/tools/payment_link_tool.py:416` · **Detectado por**: orchestrator-correctness · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: La invalidación de órdenes pending_payment (invalidate_pending_order_on_cart_change) solo está cableada a add_item/remove_item en cart_tool.py. Ni apply_coupon/revoke_coupon (lib/coupons) ni select_carrier_for_cart (legacy_adapters/cart.py que llama set_shipping_meta) la invocan. El único guard del dispatcher contra 'cupón post-link' es `if _cart["status"] == "checkout"` (dispatcher.py:1511), pero NINGÚN código del repo escribe nunca status='checkout' en conversation_carts (grep exhaustivo services/ + apps/ + supabase/migrations: solo aparece en filtros .in_()); el cart queda 'open' hasta 'converted' (services/api/routers/orders.py:566). Resultado: cliente genera link ($X), aplica cupón (cart.total baja a $X-desc, el bot confirma "Cupón aplicado: descuento -$Y"), dice "listo, pago" → handle_payment_link_if_applicable encuentra la orden pending con link vigente (case a) y lo reutiliza SIN comparar amount_in_cents contra el total actual del cart. El monto del link Wompi es inmutable post-creación.

**Evidencia (código real)**:
```
payment_link_tool.py:416-421: `if pending_order["active_link"]:\n    link = pending_order["active_link"]\n    response_text = (f"Tu pedido *#{short_id}* ya tiene link de pago activo..."` (retorna sin comparar link['amount_in_cents'] vs total_in_cents). dispatcher.py:1511: `if _cart["status"] == "checkout":` — guard muerto: status 'checkout' no se escribe en ningún lado (orders.py:566-568 pasa el cart directo de 'open' a 'converted').
```

**Corrección propuesta**:
```
1) En payment_link_tool.py case (a), validar monto antes de reutilizar:\n```python\nif pending_order["active_link"]:\n    link = pending_order["active_link"]\n    if int(link["amount_in_cents"]) != int(total_in_cents):\n        logger.warning("[PAYMENT_LINK] link vigente con monto stale (%s != %s) — invalidando orden %s",\n                       link["amount_in_cents"], total_in_cents, order_id_existing)\n        invalidate_pending_order_on_cart_change(\n            supabase, cart_id=cart_id_for_reserve or "", tenant_id=tenant_id,\n            reason="amount_mismatch_on_reuse")  # o cancelar orden directo por conversation_id\n        pending_order = None  # cae al flujo crear-desde-cero\n    else:\n        ...reutilizar como hoy...\n```\n2) Cablear la invalidación en las otras mutaciones de dinero: en lib/coupons.apply_coupon/revoke_coupon y en agentic/legacy_adapters/cart.select_carrier_for_cart llamar `invalidate_pending_order_on_cart_change(supabase, cart_id=cart["id"], tenant_id=tenant_id, reason="coupon_applied"|"carrier_changed")` antes del UPDATE de totales. 3) Reemplazar el guard muerto del dispatcher (1511) por lookup real: `orders.status='pending_payment'` para esta conversación.
```

**Notas del verificador sobre el fix**: La dirección es correcta (comparar monto en case (a) + cablear invalidación en las mutaciones de dinero), pero el sketch necesita ajustes: (1) cart_id_for_reserve se define en la línea 542, DESPUÉS del bloque de reuso (409-467) — usar cancelación directa por conversation_id o hacer el lookup del cart antes; (2) el case (b) regenerar (441-459) usa pending_order['total_amount'] stale — también debe comparar contra total_in_cents; (3) NO meter el import de tools.cart_tool dentro de api/lib/coupons.py (rompería el proceso API que no tiene tools/ en path) — cablear la invalidación en los call-sites del orchestrator (dispatcher PRE-LLM #0.4 y legacy_adapters/cart.select_carrier_for_cart) o marcar requires_requote desde coupons. | Dirección correcta (comparar monto en reuso + cablear invalidación + reemplazar guard muerto) pero el sketch tiene 3 defectos: (1) cart_id_for_reserve NO existe en el scope del case (a) — se define en payment_link_tool.py:542, DESPUÉS del bloque pending_order (:409-467) → NameError (el adapter lo atraparía como PAYMENT_ERROR y rompe el flujo); y con el fallback `or ""` propuesto, invalidate_pending_order_on_cart_change hace lookup del cart por id="" → 0 rows → retorna None SIN cancelar la orden, y el `pending_order = None` crea una SEGUNDA orden dejando el link viejo VIVO y pagable (dos links activos = peor que el bug). Corrección: cancelar directo por order_id_existing (ya en scope): UPDATE orders SET status='cancelled' WHERE id=order_id_existing AND status='pending_payment' + void payments.pending (mismo CAS que cart_tool.py:159-184), o hoistar el lookup de cart_id antes del bloque de idempotencia. (2) El fix solo cubre case (a); case (b) regenera con pending_order['total_amount'] stale (:446) → cupón aplicado >30min después del link cobraría igualmente el monto viejo. La comparación round(total_amount*100) != total_in_cents debe gatear TAMBIÉN el branch de regeneración. (3) Ubicación del wiring: apply_coupon/revoke_coupon viven en services/api/lib/coupons.py (compartido vía sys.path injection desde services/ai-orchestrator/lib/coupons.py); ese módulo NO puede importar tools/cart_tool (vive en ai-orchestrator, boundary de servicios). Cablear la invalidación en el interceptor PRE-LLM #0.4 del dispatcher (tras apply/revoke exitoso) y en el path legacy de orchestrator.py:7130-7160, o en el wrapper ai-orchestrator/lib/coupons.py. Para select_carrier_for_cart (legacy_adapters/cart.py) sí aplica el wiring directo propuesto. El punto 3 del fix (lookup real orders.pending_payment en dispatcher:1511 en vez del guard muerto) es correcto; con él, el mensaje existente 'El cupón debe aplicarse antes de generar el link' se vuelve alcanzable y es defensa redundante válida junto con el punto 1.

**Referencia oficial**: https://docs.wompi.co/docs/colombia/links-de-pago/

<details><summary>Verificación adversarial</summary>

Todos los mecanismos confirmados: (1) payment_link_tool.py:416-434 reutiliza link vigente sin comparar link['amount_in_cents'] vs total_in_cents (el caller agéntico pasa el total ACTUAL del cart con descuento, legacy_adapters/payment.py:130); (2) grep exhaustivo: NADIE escribe status='checkout' en conversation_carts — solo aparece en filtros .in_() y el cart pasa de 'open' directo a 'converted' (orders.py:566-568) → el guard anti-cupón-post-link dispatcher.py:1511 es código muerto y apply_coupon procede sobre cart 'open'; (3) apply_coupon/revoke_coupon (api/lib/coupons.py:399-405/494-500) actualizan total_cents sin invalidar orden pending ni marcar requires_requote → el gate 1.4 (payment_lin […]

</details>

---

### F16 · 🔴 CRITICAL — El guard de validación de monto del webhook Wompi está muerto y el retry de pago nunca genera link: _get_order_by_id no selecciona total_amount

**Ubicación**: `services/api/routers/wompi_webhook.py:692` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: _get_order_by_id hace .select("id, tenant_id, status, conversation_id, contact_id") SIN total_amount. En el paso 5b, `order_total = order.get("total_amount")` es SIEMPRE None → `if order_total is not None:` salta la comparación de monto y la orden se confirma con cualquier amount_in_cents (la defensa payment-integrity del audit A11 nunca corre en producción). En _maybe_offer_payment_retry (línea 442), `float(order.get("total_amount") or 0)` es siempre 0.0 → amount_in_cents=0 < 150_000 → SIEMPRE cae en la rama 'retry_monto_bajo' y el cliente jamás recibe un nuevo link tras DECLINED (venta perdida). Los tests (tests/test_a11_wompi_amount_validation.py, test_wompi_retry_payment.py) enmascaran el bug porque el mock de supabase devuelve el dict completo con total_amount sin respetar las columnas del select.

**Evidencia (código real)**:
```
wompi_webhook.py:691-693: `.select("id, tenant_id, status, conversation_id, contact_id")` — vs línea 233: `order_total = order.get("total_amount")` y línea 442: `total_amount = float(order.get("total_amount") or 0)`, ambos leyendo el dict retornado por `_get_order_by_id`
```

**Corrección propuesta**:
```
En _get_order_by_id añadir la columna al select:
```python
res = (
    supabase.table("orders")  # tenant_filter:exempt:webhook_resolution_lookup
    .select("id, tenant_id, status, conversation_id, contact_id, total_amount")
    .eq("id", order_id)
    .limit(1)
    .execute()
)
```
Y endurecer el guard 5b a fail-closed cuando falte el dato:
```python
if order_total is None:
    logger.error("[WOMPI] orden sin total_amount order_id=%s — NO se confirma", order_id)
    return
```
Además corregir los mocks de tests para que respeten las columnas del select (o añadir un test que asserte que el select incluye total_amount).
```

**Notas del verificador sobre el fix**: Añadir total_amount al select es correcto y seguro (solo agrega datos; ningún caller se rompe). Fail-closed cuando total_amount es None es seguro: orders.total_amount es NOT NULL DEFAULT 0 (20260409220000_fase9_schema_core.sql:32), None solo indicaría select roto. Imprescindible el tercer punto del fix: test que asserte las columnas del select o mock que las respete, si no el bug puede reintroducirse invisible. | El fix es correcto y no rompe otros callers (líneas 89 y 370 solo usan tenant_id/conversation_id; añadir columna es aditivo; el fail-closed con None es seguro porque la columna es NOT NULL). UNA advertencia de hardening al activar el guard: el guard usa `int(round(float(total)*100))` pero la creación de links usa `int(total*100)` sin round (orders.py:430 y wompi_webhook.py:443). Para totales con artefactos float (ej. 8.29 → int()=828 vs round()=829) el link se crearía por N-1 cents y el guard rechazaría el pago legítimo. En COP los totales son pesos enteros así que el riesgo es bajo, pero conviene unificar a `int(round(total*100))` en los 3 puntos, o mejor: comparar amount_in_cents contra payments.amount_in_cents del link real en vez de recomputar desde total_amount.

**Referencia oficial**: https://docs.wompi.co/en/docs/colombia/eventos/

<details><summary>Verificación adversarial</summary>

Verificado: _get_order_by_id (wompi_webhook.py:692) selecciona 'id, tenant_id, status, conversation_id, contact_id' SIN total_amount. El guard 5b (línea 206→233) usa ese dict: order.get('total_amount') es siempre None → 'if order_total is not None' salta la validación de monto (defensa A11 muerta; la validación de moneda línea 243 sí corre). _maybe_offer_payment_retry (línea 403→442) usa el mismo helper: float(None or 0)=0.0 → amount_in_cents=0 < 150_000 → siempre rama retry_monto_bajo → el cliente recibe el mensaje de fallo/escalación pero NUNCA un nuevo link tras DECLINED. Masking confirmado: _make_supabase_mock (test_wompi_webhook.py:129) devuelve filas completas ignorando las columnas de […]

</details>

---

### F32 · 🟠 HIGH — Cinco renderizadores de dirección divergentes: el path agentic muestra al cliente direcciones sin Torre/Apto/Piso/Casa#/Empresa que el path legacy sí renderiza

**Ubicación**: `services/ai-orchestrator/agentic/system_prompt.py:666` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo

**Causa**: Existen 5 implementaciones de 'renderizar contacts.address a una línea legible': (1) tools/known_customer_tool.py:120 `_format_address` (la más rica: Torre/Casa#/Manzana/Oficina/Piso/Empresa), (2) orchestrator.py:4531 `_format_address_for_summary` (equivalente rica), (3) agentic/system_prompt.py:666-678 CONTEXTO_CLIENTE inline que solo concatena street+neighborhood+city+state — OMITE apartment/tower/floor — y luego instruye al LLM 'incluye SU dirección REAL... literal (los de arriba)', (4) agentic/tools/contact.py:166-194 GetContactInfoTool que ignora `conjunto_type` (renderiza 'Apto X' donde el legacy dice 'Casa #X') y no renderiza nada para building_type='oficina', (5) agentic/invariants/summary_coherence.py:296 `_format_address_compact` que al REESCRIBIR el resumen omite Torre/Manzana/Empresa. Resultado: en el path agentic (primario) un cliente conocido de conjunto de torres confirma un resumen de envío sin Torre/Apto.

**Evidencia (código real)**:
```
agentic/system_prompt.py:667-678: `addr_parts = []` ... solo `street_value`, `neighborhood`, `city`, `state` — vs tools/known_customer_tool.py:123-127 (docstring de la fuente rica): `• conjunto+casas → "Casa #X".\n• oficina → "Oficina X" (+ "Piso Y" si floor).\n• edificio → "Apto X"... • conjunto torres → "Torre X" + "Apto Y".`
```

**Corrección propuesta**:
```
Extraer el cuerpo de `known_customer_tool._format_address` (implementación más completa) a `lib/address_format.py::format_address_line(addr: dict) -> str` y consumirlo desde los 5 sitios:\n\n```python\n# lib/address_format.py (nuevo — mover el cuerpo de tools/known_customer_tool.py:120-193)\ndef format_address_line(address: dict) -> str: ...\n\n# tools/known_customer_tool.py\nfrom lib.address_format import format_address_line as _format_address\n# agentic/system_prompt.py (reemplaza addr_parts inline)\nfrom lib.address_format import format_address_line\naddr_str = format_address_line(addr) or "(sin dirección guardada)"\n# agentic/tools/contact.py (GetContactInfoTool) y agentic/invariants/summary_coherence.py\nfrom lib.address_format import format_address_line  # elimina _format_address_compact y el bloque inline\n# orchestrator.py: _format_address_for_summary = format_address_line (alias)\n```
```

**Notas del verificador sobre el fix**: Dirección correcta (extraer la implementación más rica a lib/address_format.py y consumir desde los 5 sitios) y consistente con el patrón lib/ del repo. Incompleto sin resolver 3 detalles: (a) separador — _format_address usa ' — ', los otros ', '; elegir uno y actualizar asserts (tests de known_customer_tool, summary_coherence, state_renderers), (b) system_prompt hoy incluye 'state' que la versión rica no renderiza — decidir si se añade, (c) GetContactInfoTool acepta btype legacy 'apartamento' que la versión rica trata por default 'Apto' (compatible). Riesgo bajo, pero correr suite completa de invariants/prompt tras el cambio.

<details><summary>Verificación adversarial</summary>

CONFIRMADO. Los 5 renderizadores existen y divergen exactamente como se describe: (1) known_customer_tool._format_address:120-188 (rico: Torre/Manzana/Casa#/Oficina/Piso/Empresa/complex_name via conjunto_type), (2) orchestrator._format_address_for_summary:4531-4594 (equivalente rico), (3) system_prompt._render_contact_block:666-678 solo street+neighborhood+city+state — omite apartment/tower/floor/complex_name Y en 690-698 instruye al LLM a usar 'SU dirección REAL... literal (los de arriba)' en el resumen 📋, (4) contact.py GetContactInfoTool:166-194 — conjunto siempre Torre+Apto (mislabel de conjunto_type='casas' que el legacy renderiza 'Casa #X') y btype='oficina' no renderiza unidad alguna, […]

</details>

---

### F31 · 🟠 HIGH — Normalización DIAN de dirección solo existe en el path legacy: el path agentic (primario) persiste street/city crudos → formato divergente en contacts.address según qué path atendió el turno

**Ubicación**: `services/ai-orchestrator/agentic/tools/contact.py:38` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: orchestrator.py:10388-10393 normaliza `street` y `number` con `dian_normalization.normalize_dian_address` antes de persistir, con comentario explícito 'Normalización DIAN para almacenamiento unificado', y además canonicaliza `city`/`state` vía `_resolve_destination_from_query`. El SaveAddressTool agentic (`_build_address_dict`) persiste `args.street` y `args.city` tal cual vienen del LLM (solo resuelve dane_code). `normalize_dian_address` no tiene ningún otro callsite en el repo — en el path primario la normalización 'unificada' es letra muerta, produciendo dos formatos de almacenamiento distintos para la misma columna JSONB.

**Evidencia (código real)**:
```
agentic/tools/contact.py:38-40: `address = {\n        "street": args.street,\n        "city": args.city,` — vs orchestrator.py:10388-10391: `# Normalización DIAN para almacenamiento unificado\n                try:\n                    from dian_normalization import normalize_dian_address\n                    if merged_address.get("street"):\n                        merged_address["street"] = normalize_dian_address(merged_address["street"])`
```

**Corrección propuesta**:
```
Aplicar la misma normalización en `_build_address_dict` (o retirarla del legacy si el founder decide abandonar DIAN — pero en ambos paths por igual):\n\n```python\n# agentic/tools/contact.py — al final de _build_address_dict, antes de return address\n    try:\n        from dian_normalization import normalize_dian_address  # noqa: PLC0415\n        if address.get("street"):\n            address["street"] = normalize_dian_address(address["street"])\n    except Exception:\n        pass  # mismo contrato defensivo del path legacy (orchestrator.py:10388-10395)\n    return address\n```
```

**Notas del verificador sobre el fix**: El snippet es mecánicamente correcto y espeja el contrato defensivo legacy, PERO aplicarlo cambia lo que ve el cliente en el path PRIMARIO: normalize_dian_address uppercasea y abrevia ('Calle 36A # 6-87' → 'CL 36A 6-87'), y ese street almacenado es lo que renderizan CONTEXTO_CLIENTE, get_contact_info y los resúmenes de confirmación — regresión UX visible en producción (KAIU agentic). El propio finding admite la alternativa (retirar DIAN del legacy). Decisión de producto requerida: normalizar-en-consumo (cuando algún consumidor DIAN real exista) o retirar del legacy es probablemente mejor que propagar normalize-on-write al agentic. No aplicar sin decisión founder + tests de contact tools actualizados.

<details><summary>Verificación adversarial</summary>

CONFIRMADO el hecho, sobredimensionada la severidad. normalize_dian_address tiene exactamente 2 callsites, ambos en orchestrator.py:10389-10393 (path legacy contact-usync); _build_address_dict (agentic/tools/contact.py:38-79) persiste args.street/args.city crudos — verificado leyendo la función completa y sus 2 consumidores (SaveAddressTool:766, SaveContactFieldTool:1022). El path legacy sigue vivo (tenants sin flag agentic, default de provisioning), así que los dos formatos de almacenamiento coexisten de verdad. PERO: ningún consumidor downstream requiere formato DIAN (normalize_dian_address no tiene otros callers — la 'normalización unificada' no alimenta facturación, Aveonline ni Wompi),  […]

</details>

---

### F43 · 🟠 HIGH — invalidate_shipping y set_shipping_city borran shipping_meta.recipient — el destinatario alterno (envío a tercero, fix Habeas Data BUG 37) se pierde silenciosamente al agregar/quitar cualquier item

**Ubicación**: `services/ai-orchestrator/tools/cart_tool.py:1072` · **Detectado por**: orchestrator-correctness · 🆕 nuevo

**Causa**: set_shipping_recipient persiste el receptor en shipping_meta.recipient (cart_tool.py:778), pero invalidate_shipping — que corre en CADA add_item (cart_tool.py:416) y remove_item (:508) — reconstruye shipping_meta preservando SOLO ('city','dane_code','address_line'). set_shipping_city (:1006-1014) hace lo mismo. Flujo real: el resolver pre-LLM persiste el receptor (dispatcher.py PRE-LLM #-0.5, corre ANTES del purchase-intent), y en el MISMO turno el add_to_cart dispara invalidate_shipping → recipient eliminado. Los consumidores (SummaryCoherenceInvariant:440, prompt states.py:296, pii_coherence.py:151) ven has_recipient=False → el resumen y el flujo muestran los datos del titular WhatsApp como quien recibe — exactamente la regresión que BUG 37 (Ley 1581) corrigió.

**Evidencia (código real)**:
```
cart_tool.py:1072-1076: `preserved = {\n    k: meta.get(k)\n    for k in ("city", "dane_code", "address_line")\n    if meta.get(k)\n}` seguido de `.update({... "shipping_meta": preserved ...})`. Y set_shipping_city:1006-1014 arma `new_meta = {"city": ..., "dane_code": ..., "address_line": ..., "weight_inputs": ..., "city_changed_at": ...}` sin key 'recipient'.
```

**Corrección propuesta**:
```
Preservar el receptor en ambos writers:\n```python\n# invalidate_shipping\npreserved = {\n    k: meta.get(k)\n    for k in ("city", "dane_code", "address_line", "recipient")\n    if meta.get(k)\n}\n```\n```python\n# set_shipping_city\nnew_meta = {\n    "city": new_city,\n    "dane_code": new_dane_code or meta.get("dane_code"),\n    "address_line": meta.get("address_line"),\n    "weight_inputs": meta.get("weight_inputs"),\n    "recipient": meta.get("recipient"),\n    "city_changed_at": ...,\n}\n```\n+ test que agrega item después de set_shipping_recipient y asserta que recipient sobrevive.
```

**Notas del verificador sobre el fix**: Fix correcto y mínimo: añadir 'recipient' al tuple preservado en invalidate_shipping y a new_meta en set_shipping_city. Matiz menor: en cambio de ciudad, recipient.address podría quedar stale respecto a la ciudad nueva — aceptable (preservar identidad del receptor > perderla silenciosamente; el LLM re-valida address turn-by-turn). El test propuesto es necesario.

<details><summary>Verificación adversarial</summary>

Confirmado línea a línea: set_shipping_recipient persiste meta['recipient'] (cart_tool.py:778); invalidate_shipping reconstruye shipping_meta preservando SOLO ('city','dane_code','address_line') (cart_tool.py:1072-1076) y corre en cada add_item (:416) y remove_item (:508); set_shipping_city arma new_meta sin key 'recipient' (:1006-1014). Escenario runtime alcanzable verificado en el dispatcher: PRE-LLM #-0.5 recipient_intent persiste el receptor (dispatcher.py:1316-1358) ANTES de PRE-LLM #1 purchase_intent→add_to_cart (:2145) que dispara invalidate_shipping en el mismo turno. Consumidores que pierden el dato confirmados: summary_coherence.py:440, pii_coherence.py:151, prompt/states.py:296 (' […]

</details>

---

### F44 · 🟠 HIGH — El cron de carritos abandonados está funcionalmente muerto: consulta columnas inexistentes (contacts.first_name/full_name, conversation_cart_items.product_title) → consent_ok siempre False → skipea TODO y quema el flag de idempotencia

**Ubicación**: `services/ai-orchestrator/worker.py:1531` · **Detectado por**: orchestrator-correctness · 🆕 nuevo

**Causa**: El schema real de contacts solo tiene `name` (migración 20260409220000_fase9_schema_core.sql:14; grep de first_name/full_name en supabase/migrations devuelve 0 hits) y conversation_cart_items no tiene `product_title` (migración 20260501000000, columnas: product_id, variation_id, quantity, unit_price_cents, meta). PostgREST responde 42703/400 ante columna desconocida y supabase-py lanza APIError en .execute(). En _send_cart_abandoned_reminders_if_due el SELECT de contacts (worker.py:1529-1536) explota dentro de `except Exception: pass` (:1546-1547) → consent_ok queda False → CADA cart entra al branch 'sin consent' que además marca abandoned_reminder_sent_at (:1553-1557), quemando la idempotencia para siempre: el HSM cart_abandoned_24h_v1 nunca se envía a nadie, ni a clientes con consent, y el fallo es invisible (solo sube la métrica skipped_no_consent). El mismo drift en _try_send_payment_reminder_hsm (worker.py:1341: select "first_name, full_name") degrada el nombre a 'cliente' en el template de pago.

**Evidencia (código real)**:
```
worker.py:1529-1536: `contact_res = (self.supabase.table("contacts").select("consent_given, consent_revoked_at, first_name, full_name")...` con worker.py:1525 `consent_ok = False` y worker.py:1546-1547 `except Exception:\n    pass`; worker.py:1553-1557 marca `abandoned_reminder_sent_at` en el skip. worker.py:1571-1573: `.select("product_title, quantity")` sobre conversation_cart_items.
```

**Corrección propuesta**:
```
```python\n# worker.py _send_cart_abandoned_reminders_if_due (y _try_send_payment_reminder_hsm)\ncontact_res = (\n    self.supabase.table("contacts")\n    .select("consent_given, consent_revoked_at, name")\n    .eq("id", contact_id).eq("tenant_id", tenant_id)\n    .limit(1).execute()\n)\n...\nfull = (contact_rows[0].get("name") or "").strip()\ncustomer_name = full.split(" ")[0] if full else "cliente"\n```\n```python\n# items del carrito — título vía embed a products\nitems_res = (\n    self.supabase.table("conversation_cart_items")\n    .select("quantity, products(title)")\n    .eq("cart_id", cart_id).eq("tenant_id", tenant_id)\n    .limit(3).execute()\n)\ntitle = ((it.get("products") or {}).get("title") or "").strip()\n```\nAdemás: NO marcar abandoned_reminder_sent_at cuando el skip provino de una excepción de lookup (distinguir 'consent denegado' de 'lookup falló'), y backfill: `UPDATE conversation_carts SET abandoned_reminder_sent_at = NULL WHERE ...` para los flags quemados.
```

**Notas del verificador sobre el fix**: Fix correcto: select 'name' (columna real), embed products(title) funciona (FK product_id→products existe), y distinguir 'lookup falló' de 'consent denegado' antes de quemar idempotencia es la corrección clave. El backfill de flags quemados es de valor marginal (la ventana es 24-72h, los carts afectados envejecen fuera del rango), pero inofensivo. Severidad sugerida medium (no high): feature de marketing muerta que falla hacia el lado legalmente seguro (no envía sin certeza de consent) — pérdida de recovery de revenue, no de dinero ya cobrado ni compliance.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/errors.html

<details><summary>Verificación adversarial</summary>

Schema verificado: contacts solo tiene 'name' (migración 20260409220000_fase9_schema_core.sql:10-19; grep de first_name/full_name en supabase/migrations = 0 hits) y conversation_cart_items no tiene product_title (20260501000000:97+, columnas: product_id, variation_id, quantity, unit_price_cents, meta). worker.py:1531 selecciona 'consent_given, consent_revoked_at, first_name, full_name' → PostgREST 400/42703 → supabase-py lanza APIError → atrapado por except Exception: pass (:1546-1547) → consent_ok queda False (:1525) → branch skip marca abandoned_reminder_sent_at (:1553-1557) quemando idempotencia. Cron habilitado por default (CART_ABANDONED_REMINDER_ENABLED default 'true', worker.py:108) y […]

</details>

---

### F45 · 🟠 HIGH — Durante un outage sostenido de Gemini el worker se auto-mata: el heartbeat solo se actualiza al tope del loop y la cascada LLM puede dormir ~63s por llamada → /health 503 a los 120s → Render reinicia en mitad del batch (riesgo de respuestas duplicadas)

**Ubicación**: `services/ai-orchestrator/worker.py:304` · **Detectado por**: orchestrator-correctness · 🆕 nuevo

**Causa**: run() actualiza last_heartbeat_ts SOLO antes de _poll_cycle (worker.py:304). _poll_inbound_messages procesa hasta 10 mensajes secuenciales; cada turno agentic invoca generate_with_cascade con hasta 8 intentos y backoff 1+2+4+8+16+16+16 ≈ 63s de sleep (llm_invoke.py:93-95, defaults GEMINI_MAX_RETRIES=8), y agent.py puede reintentar (empty-output retry + text-only fallback) multiplicando esa espera. server.py:51 declara HEALTH_HEARTBEAT_STALE_SECONDS=120 y devuelve 503 para que Render reinicie. Con ≥2 mensajes pendientes durante un 503 sostenido de Gemini (exactamente el escenario que la cascada debe absorber), el ciclo supera 120s → restart loop. Si el kill cae entre _send_outbound_text (mensaje ya entregado a Meta) y _mark_message_processing, el sweep re-encola el mensaje y el cliente recibe la respuesta DUPLICADA tras el reinicio.

**Evidencia (código real)**:
```
worker.py:302-306: `# Heartbeat al tope del loop...\nself.last_heartbeat_ts = time.time()\ntry:\n    await self._poll_cycle()`; server.py:51: `HEALTH_HEARTBEAT_STALE_SECONDS = 120`; llm_invoke.py:94-95: `"""Backoff exponencial truncado: 1s, 2s, 4s, 8s, 16s..."""\nreturn float(min(16, 2 ** max(0, attempt - 1)))` con DEFAULT_MAX_RETRIES = 8.
```

**Corrección propuesta**:
```
Latir por mensaje procesado, no por ciclo:\n```python\n# worker.py _poll_inbound_messages, dentro del `for msg in pending:`\nfor msg in pending:\n    self.last_heartbeat_ts = time.time()  # el worker está VIVO aunque Gemini esté lento\n    attempts = int(msg.get("processing_attempts") or 0) + 1\n    ...\n```\ny (opcional, defensa en profundidad) latir también al inicio de cada sub-tarea de _poll_cycle. Alternativa complementaria: bajar GEMINI_MAX_RETRIES/backoff efectivo por turno para que el peor caso de un mensaje quede < HEALTH_HEARTBEAT_STALE_SECONDS.
```

**Notas del verificador sobre el fix**: Latir al inicio de cada iteración del for msg in pending es correcto y preserva la detección de cuelgue real (un solo mensaje colgado >120s sigue disparando restart). Incompleto: sub-tareas largas también pueden superar 120s por sí solas (p.ej. _poll_wompi_pending_voids_if_due: hasta 50 GETs × timeout 10s = 500s, worker.py:1741-1760) — latir al inicio de cada sub-task no cubre loops largos DENTRO de una sub-task; añadir beat dentro de esos loops o acotar el peor caso por mensaje (bajar GEMINI_MAX_RETRIES efectivo) como propone la alternativa.

**Referencia oficial**: https://render.com/docs/health-checks

<details><summary>Verificación adversarial</summary>

CONFIRMADO. worker.py: last_heartbeat_ts solo se escribe en __init__ (:242) y al tope de run() (:304) — grep confirma que NO hay otro beat. _poll_inbound_messages procesa hasta 10 mensajes secuenciales (:499-513). En outage sostenido de Gemini, agent.py:596 ejecuta generate_with_cascade (llm_invoke.py: 8 intentos default, sleeps 1+2+4+8+16+16+16=63s) vía run_in_executor — la corrutina espera el future, el heartbeat no avanza. Con cascada agotada, _gemini_generate_async lanza gemini_cascade_exhausted (agent.py:608) y dispatcher.py:234-248 emite degraded (sin fallback legacy), pero los ~63s+ de sleeps por mensaje ya corrieron. Con ≥2 mensajes pendientes el ciclo supera 126s > HEALTH_HEARTBEAT_ […]

</details>

---

### F17 · 🟠 HIGH — El webhook de Telegram está montado con _OFFBOARDING_GATE que exige JWT → todo POST de Telegram recibe 401 y los comandos /resolver y /estado están rotos

**Ubicación**: `services/api/main.py:177` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: main.py incluye telegram_webhook.router con dependencies=_OFFBOARDING_GATE, contradiciendo el comentario de las líneas 169-171 ('Webhooks externos NO usan _OFFBOARDING_GATE — no tienen JWT'). reject_if_tenant_deleting → get_tenant_id_internal_or_user → get_current_tenant → _extract_jwt_payload lanza 401 si falta header Authorization (dependencies/auth.py:130-132). Telegram solo envía X-Telegram-Bot-Api-Secret-Token (nunca Authorization ni X-Internal-Service-Secret), así que la dependencia rechaza con 401 ANTES de llegar al handler. El path de restauración del bot desde Telegram (arquitectura de escalación humana) está muerto. tests/test_telegram_webhook.py no lo detecta porque monta el router en una app propia SIN el gate.

**Evidencia (código real)**:
```
main.py:177: `app.include_router(telegram_webhook.router, prefix="/api/v1/integrations", dependencies=_OFFBOARDING_GATE)` — y dependencies/auth.py:130-132: `if not auth_header.startswith("Bearer "): raise HTTPException(status_code=401, detail="Authorization header faltante o inválido")`
```

**Corrección propuesta**:
```
Montar el webhook sin el gate, igual que meli/wompi/aveonline (autenticado por secret del provider):
```python
# Webhook externo Telegram — autenticado por X-Telegram-Bot-Api-Secret-Token
# (constant-time compare en el handler). Sin JWT → sin _OFFBOARDING_GATE,
# igual que meli_webhook/wompi_webhook/aveonline_webhook.
app.include_router(telegram_webhook.router, prefix="/api/v1/integrations")
```
Y añadir un test de integración que monte el router VÍA main.app (no una app ad-hoc) y asserte 200 con secret válido sin Authorization.
```

**Notas del verificador sobre el fix**: Correcto: quitar el gate iguala el tratamiento de los demás webhooks externos; el handler ya autentica con hmac.compare_digest del secret (constant-time). El riesgo de writes durante offboarding es el mismo aceptado para meli/wompi (fallan en otros guards). El test de integración vía main.app es la parte que previene regresión — incluirlo.

**Referencia oficial**: https://core.telegram.org/bots/api#setwebhook

<details><summary>Verificación adversarial</summary>

main.py:177 monta telegram_webhook con dependencies=_OFFBOARDING_GATE, contradiciendo el comentario 169-171 y el trato de meli/wompi/aveonline (líneas 172-176, sin gate). Cadena verificada: reject_if_tenant_deleting (auth.py:242) llama get_tenant_id_internal_or_user ANTES del skip GET/HEAD → sin X-Internal-Service-Secret cae a get_current_tenant → _extract_jwt_payload (auth.py:130-132) lanza 401 si no hay 'Bearer '. Telegram solo envía X-Telegram-Bot-Api-Secret-Token (telegram_webhook.py:40-54, POST único endpoint) → 401 antes del handler. git log -L177 confirma regresión: el gate se añadió en 83bd3b4d 'fix(j244-offboarding)'. tests/test_telegram_webhook.py:159-160 monta el router en FastAPI […]

</details>

---

### F30 · 🟠 HIGH — sys.path.insert(0) hacia ai-orchestrator en la API hace que imports lazy de lib.* resuelvan a las copias del orchestrator (namespace packages sin __init__.py)

**Ubicación**: `services/api/routers/ai_agents.py:37` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: services/api/lib y services/ai-orchestrator/lib son namespace packages PEP-420 (ninguno tiene __init__.py). routers/ai_agents.py inserta el dir del orchestrator en sys.path[0] al importarse en startup, y routers/data_subject_request.py:112 repite el insert(0) en runtime al primer SAR. El __path__ del namespace package `lib` se recalcula dinámicamente en orden de sys.path, por lo que todo import lazy posterior de `lib.X` (p.ej. `from lib.dane_resolver import resolve_dane_from_city` en wompi_webhook.py:1451, `from lib.tenant_carriers import upsert_preference` en integrations.py:994) carga la copia del ORCHESTRATOR, no la de la API. Verificado empíricamente: con la inyección activa, `import lib.carrier_capabilities` resuelve a services/ai-orchestrator/lib/carrier_capabilities.py. Además colisionan los top-level `observability.py` (178 líneas de diff entre servicios), `vault_helper.py` (divergido) y `main.py`; hoy vault_helper se salva porque settings.py/integrations.py lo importan a nivel de módulo antes de la inyección — protección por orden de import accidental, no por diseño.

**Evidencia (código real)**:
```
routers/ai_agents.py:36-37: `if str(_ORCHESTRATOR_DIR) not in sys.path:\n    sys.path.insert(0, str(_ORCHESTRATOR_DIR))` — y test empírico: `import lib.carrier_capabilities as cc; print(cc.__file__)` → `/home/ansible/workspaces/konvi-platform/services/ai-orchestrator/lib/carrier_capabilities.py`
```

**Corrección propuesta**:
```
1) Inyectar al FINAL, nunca en posición 0: en routers/ai_agents.py y routers/data_subject_request.py reemplazar `sys.path.insert(0, ...)` por `sys.path.append(...)`. 2) Hacer regular package el lib de la API para que siempre gane en su proceso: `touch services/api/lib/__init__.py services/ai-orchestrator/lib/__init__.py`. 3) Mover `services/ai-orchestrator/lib/agent_templates.py` → `services/api/lib/agent_templates.py` (sus ÚNICOS consumidores son routers/ai_agents.py:86,107,147 — hoy solo resuelve gracias al merge de namespace) y ajustar el import a `from lib.agent_templates import AGENT_TEMPLATES` (ya queda igual). Los imports top-level compartidos a propósito (`from llm_cascade import cascade_invoke`, `from notifications import notify_sar_received`) siguen funcionando con append porque la API no tiene módulos con esos nombres.
```

**Notas del verificador sobre el fix**: El paso 1 (insert(0)→append) es correcto y suficiente para el proceso API. El paso 2 (__init__.py en ambos lib) ROMPE el orchestrator: worker.py:2052-2054 inserta services/api en sys.path y hace `from lib.tenant_offboarding import ...` — tenant_offboarding.py solo existe en api/lib y hoy resuelve gracias al merge de namespace packages; con lib como regular package ya cacheado (orchestrator/lib se importa en boot vía lib.tenant_agents etc.), lib.__path__ queda fijado al dir del orchestrator y ese import lanza ImportError → el cron de hard-delete de offboarding se autodesactiva (worker.py:2059-2066). El fix debe además: convertir los insert(0) de worker.py:1782/2053 y del wrapper orchestrator/lib/coupons.py:18 a append, y mover lib/tenant_offboarding a un lugar compartido (o mantener namespace packages y solo aplicar paso 1+3). El paso 3 (mover agent_templates a api/lib) es correcto — verificado que sus únicos consumidores son routers/ai_agents.py:86/107/147.

**Referencia oficial**: https://docs.python.org/3/reference/import.html#namespace-packages

<details><summary>Verificación adversarial</summary>

Mecanismo verificado empíricamente en este repo: con services/ai-orchestrator insertado en sys.path[0] (ai_agents.py:36-37, importado en main.py:179 después de los routers), `import lib.dane_resolver / lib.tenant_carriers / lib.coupons` resuelven a las copias del ORCHESTRATOR (test reproducido: los 3 __file__ apuntan a ai-orchestrator/lib/). Ambos lib son namespace packages PEP-420 (sin __init__.py, verificado) y su __path__ se recalcula en orden de sys.path. Los imports lazy afectados son reales y alcanzables (wompi_webhook.py:1451 desde webhook de pagos, integrations.py:584/958/994 desde UI, orders.py:600). vault_helper/observability se salvan solo por orden de import accidental (main.py:1 […]

</details>

---

### F18 · 🟠 HIGH — Los 4 endpoints de escritura de knowledge_base encadenan .select()/.single() tras .insert()/.update() — métodos inexistentes en postgrest 2.28.3 → AttributeError y 500 en TODA llamada

**Ubicación**: `services/api/routers/knowledge_base.py:151` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: En supabase-py/postgrest 2.28.3 (pin de requirements.txt), .insert() retorna SyncQueryRequestBuilder y .update() retorna SyncFilterRequestBuilder; verificado en el venv del repo: `hasattr(SyncQueryRequestBuilder, 'select') == False`, `hasattr(SyncFilterRequestBuilder, 'select') == False`. Las cadenas `.insert(payload).select(...).single()` (línea 148-154), `.update(update)...select().single()` (220-227), `.update({"is_active": False...})...select().single()` (244-252) y `.update({"embedding"...})...select().single()` (286-294) lanzan AttributeError ANTES de enviar nada a la DB → POST/PATCH/DELETE/reindex de /api/v1/knowledge-base responden 500 siempre. El frontend delega todas las escrituras KB a estos endpoints (apps/web/app/dashboard/(ai)/knowledge-base/page.tsx:151-192), así que la gestión de Base de Conocimiento está rota end-to-end.

**Evidencia (código real)**:
```
knowledge_base.py:148-154: `res = (\n    supabase.table("kb_documents")  # tenant_filter:exempt:payload_includes_tenant_id\n    .insert(payload)\n    .select("id, title, content, category, is_active, created_at, updated_at, embedding")\n    .single()\n    .execute()\n)`
```

**Corrección propuesta**:
```
insert/update ya retornan representation por default; usar res.data[0]:
```python
res = (
    supabase.table("kb_documents")  # tenant_filter:exempt:payload_includes_tenant_id
    .insert(payload)
    .execute()
)
if not res.data:
    raise HTTPException(status_code=500, detail="No fue posible crear el documento KB")
return _strip_embedding(res.data[0])
```
Y para los updates (patch/delete/reindex):
```python
res = (
    supabase.table("kb_documents")
    .update(update)
    .eq("id", doc_id)
    .eq("tenant_id", tenant_id)
    .execute()
)
if not res.data:
    raise HTTPException(status_code=404, detail="Documento KB no encontrado")
return _strip_embedding(res.data[0])
```
```

**Notas del verificador sobre el fix**: Correcto: returning=representation es default en insert/update de esta versión → res.data[0] funciona; res.data vacío en update sin match → 404 correcto. Nota: el update con representation devuelve TODAS las columnas (incluye embedding/content) — _strip_embedding ya lo maneja en patch; en delete/reindex conviene aplicar _strip_embedding o proyectar campos al responder para no devolver el embedding completo.

**Referencia oficial**: https://supabase.com/docs/reference/python/insert

<details><summary>Verificación adversarial</summary>

Verificado empíricamente contra el entorno del repo (supabase==2.28.3, postgrest==2.28.3 instalados): hasattr(SyncQueryRequestBuilder,'select')==False y hasattr(SyncFilterRequestBuilder,'select')==False; insert() retorna SyncQueryRequestBuilder, update() SyncFilterRequestBuilder y eq() retorna Self → las 4 cadenas .insert/.update...select().single() (knowledge_base.py:148-154, 220-227, 244-252, 286-294) lanzan AttributeError antes de tocar la DB → 500 en POST/PATCH/DELETE/reindex. Sin tests del router (solo test_coherence_pact.py lo menciona). Frontend delega todas las escrituras a estos endpoints (knowledge-base/page.tsx:161-246: create/patch/delete/reindex/templates) → gestión KB rota end- […]

</details>

---

### F19 · 🟠 HIGH — Uso sistémico de .single() con check muerto 'if not res.data' — los casos not-found devuelven 500 en vez de 404, y en purchases/receive deja estado parcial (PO received sin stock aplicado)

**Ubicación**: `services/api/routers/orders.py:296` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: En postgrest 2.28.3, SyncSingleRequestBuilder.execute() lanza APIError cuando PostgREST responde no-2xx (0 filas con single → 406 PGRST116); NUNCA retorna data vacía. Hay 50 usos de .single() en 14 routers seguidos de `if not res.data: raise HTTPException(404)` — código muerto. Consecuencias verificadas: (a) GET /orders/{id} con id inexistente o de otro tenant → APIError → except Exception → 500 'Error al obtener pedido' (contrato roto: el frontend no puede distinguir not-found de error real); (b) purchases.py:302-313 receive_purchase_order: si una variación del PO fue borrada, el `.single()` del loop lanza APIError SIN try/except en el endpoint → 500 genérico DESPUÉS de marcar la PO como 'received' (línea 287-294) con stock aplicado solo parcialmente — corrupción de inventario no-atómica (el warning 'variation no existe; skip' de la línea 312 es inalcanzable).

**Evidencia (código real)**:
```
orders.py:296-300: `.single()\n            .execute()\n        )\n        if not result.data:\n            raise HTTPException(status_code=404, detail="Pedido no encontrado")` — y purchases.py:308-313: `.single()\n            .execute()\n        )\n        if not var_res.data:\n            logger.warning("[PURCHASES] receive: variation %s no existe; skip", ...)\n            continue`
```

**Corrección propuesta**:
```
Sustituir el patrón por `.limit(1)` + unwrap (patrón que ya usa telegram_webhook.py) o `.maybe_single()`:
```python
result = (
    supabase.table("orders")
    .select("*, contacts(phone, name), order_items(...)")
    .eq("id", order_id)
    .eq("tenant_id", tenant_id)
    .limit(1)
    .execute()
)
row = (result.data or [None])[0]
if not row:
    raise HTTPException(status_code=404, detail="Pedido no encontrado")
return row
```
Aplicar el mismo cambio en purchases.py:303-313 (el `continue` vuelve alcanzable y receive deja de abortar a mitad de loop). Migración mecánica de los 50 usos + regla lint (grep `\.single()` en routers/) para prevenir reintroducción.
```

**Notas del verificador sobre el fix**: Patrón .limit(1) + unwrap correcto (ya usado en telegram_webhook y maybe_single en conversations.py:295). La migración mecánica de 48 usos debe ser incremental y con tests por endpoint — algunos flujos podrían depender del APIError para abortar transacciones lógicas. La regla lint es buena prevención. Priorizar orders.py y purchases.py como propone.

**Referencia oficial**: https://supabase.com/docs/reference/python/single

<details><summary>Verificación adversarial</summary>

Confirmado en la lib instalada (postgrest 2.28.3): SyncSingleRequestBuilder.execute() retorna SingleAPIResponse solo con 2xx y lanza APIError en cualquier otro caso (0 filas con Accept single → 406 PGRST116) → los checks 'if not res.data: 404' tras .single() son código muerto (48 usos en 14 routers, no 50). Parte (a) confirmada: GET /orders/{id} (orders.py:291-306) con id inexistente/otro tenant → APIError → except Exception → 500 en vez de 404. Parte (b) DEBILITADA: purchase_order_items.variation_id tiene ON DELETE CASCADE (20260413000000_purchases_and_finance.sql:50) → borrar una variación elimina sus items del PO; no pueden existir items huérfanos, así que el .single() del loop (purchases […]

</details>

---

### F27 · 🟠 HIGH — create_order acepta contact_id/conversation_id del body sin validar que pertenezcan al tenant; el JOIN embebido en get_order/create_payment_link fuga PII cross-tenant (nombre, teléfono, cédula)

**Ubicación**: `services/api/routers/orders.py:189` · **Detectado por**: api-tenant-isolation · 🆕 nuevo

**Causa**: En `POST /orders` (create_order) los FKs `contact_id` (línea 189) y `conversation_id` (línea 190) se insertan directamente desde `OrderCreate` (schema: `contact_id: Optional[str]`, línea 98) sin ninguna verificación de ownership contra `tenant_id`. La única validación tenant-scoped que existe es el lookup de descuento del cart (líneas 163-171) y de `variation_costs` (208-215), que sólo afectan montos, no la persistencia del FK. El row `orders` queda bajo el tenant del atacante, pero apunta a un `contacts.id` de otro tenant. Como `service_role` bypassa RLS y PostgREST NO agrega `tenant_id` a los embeds, el JOIN `contacts(phone, name)` en `get_order` (línea 293) y `contacts(name, phone, email, document_type, document_number)` en `create_payment_link` (líneas 411-412) siguen el FK y devuelven PII del contacto de OTRO tenant (incluida la cédula, dato sensible bajo Ley 1581). El lint AST no cubre esto: sólo verifica filtros WHERE, no la propiedad de los valores FK en el payload de un INSERT.

**Evidencia (código real)**:
```
order_result = supabase.table("orders").insert({ "tenant_id": tenant_id, "contact_id": order.contact_id, "conversation_id": order.conversation_id, ... })  # orders.py:187-197 — luego get_order:293 hace .select("*, contacts(phone, name), order_items(...)") sobre el FK sin re-filtrar tenant
```

**Corrección propuesta**:
```
Validar ownership de cada FK antes del INSERT (y también product_id/variation_id de los items):

```python
if order.contact_id:
    _c = (supabase.table("contacts").select("id")
          .eq("id", order.contact_id).eq("tenant_id", tenant_id).limit(1).execute())
    if not _c.data:
        raise HTTPException(status_code=404, detail="Contacto no encontrado en este tenant")
if order.conversation_id:
    _cv = (supabase.table("conversations").select("id")
           .eq("id", order.conversation_id).eq("tenant_id", tenant_id).limit(1).execute())
    if not _cv.data:
        raise HTTPException(status_code=404, detail="Conversación no encontrada en este tenant")
# Además: rechazar cualquier item cuyo variation_id no aparezca en variation_costs (ya tenant-scoped),
# para no persistir variation_id/product_id ajenos en order_items.
for item in order.items:
    if item.variation_id and str(item.variation_id) not in variation_costs:
        raise HTTPException(status_code=422, detail="variation_id no pertenece a este tenant")
```
```

**Notas del verificador sobre el fix**: Conceptualmente correcto (mismo patrón tenant-scoped del repo). Ajustes: (1) la validación de items contra variation_costs requiere mover el lookup de variation_costs ANTES del insert del order (hoy está después, líneas 205-215); (2) product_id de los items queda sin validar (order_items también embebe/expone datos vía joins); (3) el mismo gap existe en el path dual-auth interno (orchestrator) — verificar que el orchestrator siempre envíe IDs propios para no romper ese flujo (envía IDs de su propia conversación, así que las validaciones pasan); costo: 2 queries extra por creación, aceptable.

**Referencia oficial**: https://postgrest.org/en/stable/references/api/resource_embedding.html

<details><summary>Verificación adversarial</summary>

Confirmado end-to-end: (1) orders.py:187-197 inserta contact_id/conversation_id directamente del body OrderCreate (líneas 98-99, Optional[str] sin validación de ownership); ningún lookup previo verifica que pertenezcan al tenant (el lookup de cart 163-171 y variation_costs 208-215 solo afectan montos). (2) FK simple en 20260409220000_fase9_schema_core.sql: contact_id UUID REFERENCES public.contacts(id) — no composite (tenant_id, id), así que un contact_id de otro tenant pasa el FK. (3) get_order (línea 293) embebe contacts(phone, name) y create_payment_link (411-412) embebe contacts(name, phone, email, document_type, document_number); el embed PostgREST sigue el FK sin filtro tenant y get_se […]

</details>

---

### F105 · 🟠 HIGH — La generación de link de pago Wompi en producción NO usa los wrappers de resiliencia: create_payment_link_*_with_resilience tiene cero callers y el 'riesgo P0' del dossier sigue abierto

**Ubicación**: `services/api/routers/orders.py:398` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: wompi_client.py define wrappers opt-in con retry exponencial + circuit breaker (rev. 105 Sem 4 H.3.2) cuyo comentario afirma 'Cierra riesgo P0 dossier Wompi 2026-05-05 sec. 6: outages temporales de Wompi causaban falla inmediata en primer intento'. Pero ningún callsite migró: grep de 'with_resilience' en services/ solo encuentra definiciones dentro de wompi_client.py. El endpoint POST /orders/{id}/payment-link (usado por el bot vía payment_link_tool.py:172) importa el create_payment_link plano — un 5xx/timeout transitorio de Wompi rompe el flow de pago en PAYMENT state al primer intento.

**Evidencia (código real)**:
```
orders.py:398: from integrations.wompi_client import create_payment_link as wompi_create_link — vs wompi_client.py:590-592: '# Cierra riesgo P0 dossier Wompi 2026-05-05 sec. 6: outages temporales de\n# Wompi causaban falla inmediata en primer intento; con retry el flow se\n# recupera'
```

**Corrección propuesta**:
```
Adoptar el wrapper en el callsite productivo (mismo contrato según docstring de create_payment_link_with_resilience):

--- services/api/routers/orders.py:398
-        from integrations.wompi_client import create_payment_link as wompi_create_link
+        from integrations.wompi_client import (
+            create_payment_link_with_resilience as wompi_create_link,
+        )

Nota: al no existir idempotencia outbound cableada (ver hallazgo outbound_idempotency_cache), validar que el retry solo reintente errores donde Wompi NO creó el link (_is_retriable_wompi ya excluye 4xx; para timeout con creación exitosa el peor caso son dos links con la misma reference, no doble cobro).
```

**Notas del verificador sobre el fix**: Contrato verificado idéntico (mismos kwargs: private_key, environment, order_id, name, description, amount_in_cents, expires_at, redirect_url, contact); lib.integration_client.retry existe con retry_async. Caveat importante: 3 intentos × 15s timeout + backoff puede superar por mucho el timeout de 20s del cliente orquestador → el orquestador vería ReadTimeout y reintentaría el POST completo (más links duplicados, misma reference — no doble cobro). Recomendar max_attempts=2 en este callsite o subir el timeout del cliente en payment_link_tool. La nota del fix sobre _is_retriable_wompi es correcta.

<details><summary>Verificación adversarial</summary>

Confirmado: orders.py:398 importa create_payment_link plano; grep 'with_resilience' en services/apps/scripts solo encuentra definiciones dentro de wompi_client.py (615/673/725) — cero callers, ni siquiera tests. El comentario wompi_client.py:591 afirma 'Cierra riesgo P0' pero es opt-in nunca adoptado. Defensa parcial que el buscador no citó pero NO refuta: payment_link_tool.py:789 tiene loop de 2 intentos, pero solo captura httpx.RequestError (transporte orquestador→API); como REQUEST_TIMEOUT_SECONDS=15 < timeout cliente 20s, un 5xx o timeout de Wompi retorna como HTTP 500 del API → raise_for_status → HTTPStatusError cae en except genérico (línea 810) → return None SIN retry. El flow de pago […]

</details>

---

### F53 · 🟠 HIGH — I/O bloqueante síncrona (Supabase/Vault HTTP) ejecutada directamente en el event loop de asyncio: serializa TODOS los webhooks y arriesga exceder el timeout de ACK de Meta

**Ubicación**: `services/connector-whatsapp/routers/webhook.py:68` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: `decouple_and_enqueue` es `async def` → Starlette la ejecuta EN el event loop (solo las background tasks sync van a threadpool per docs Starlette). Internamente llama `persist_whatsapp_message` (4-5 round-trips HTTP síncronos a Supabase por mensaje) sin await, bloqueando el loop completo. Igualmente `verify_meta_signature_for_tenant` (async, meta.py:365) llama `_resolve_tenant_app_secret` → `_fetch_tenant_credentials` + `VaultHelper.read_secret` (HTTP síncrono) dentro del loop, y `_single_flight` puede ejecutar `event.wait(timeout=5.0)` (threading.Event, meta.py:176) que congelaría el loop 5s. Consecuencia: mientras se persiste un batch, el proceso NO puede aceptar ni ACKear nuevos webhooks; con DB lenta el 200 a Meta se retrasa → Meta reintenta (duplicados absorbidos por dedup, pero degradación) y ante fallos sostenidos Meta reduce/pausa la entrega. Contradice el propio docstring 'OBLIGATORIO POLÍTICA META: responder HTTP 200 inmediatamente' (webhook.py:138).

**Evidencia (código real)**:
```
webhook.py:68: `async def decouple_and_enqueue(body_dict: dict, tenant_id_from_path: str):` que llama en línea 85 `persist_whatsapp_message(parsed_data, tenant_id_verified=tenant_id_from_path)` (función sync con múltiples `.execute()` de supabase sync client). meta.py:365-410: `async def verify_meta_signature_for_tenant(...)` → línea 400 `app_secret = _resolve_tenant_app_secret(tenant_id)` (sync, hace HTTP a Supabase+Vault). meta.py:176: `event.wait(timeout=5.0)` (threading.Event bloqueante).
```

**Corrección propuesta**:
```
1) Convertir la background task a sync para que Starlette la corra en threadpool:
```python
# routers/webhook.py
def decouple_and_enqueue(body_dict: dict, tenant_id_from_path: str):  # sin async
    ...
```
(no contiene ningún await — cambio seguro).
2) En la dependencia async, delegar los lookups bloqueantes al threadpool:
```python
from starlette.concurrency import run_in_threadpool
...
app_secret = await run_in_threadpool(_resolve_tenant_app_secret, tenant_id)
...
tenant_id_resolved = await run_in_threadpool(_resolve_tenant_id_for_phone_number, phone_number_id)
```
y en el GET handshake: `expected_token = await run_in_threadpool(_resolve_tenant_verify_token, tenant_id)`. Con esto el single-flight threading (que hoy es código muerto en loop single-thread) vuelve a ser efectivo entre threads del pool.
```

**Notas del verificador sobre el fix**: Correcto. decouple_and_enqueue no contiene ningún await → quitarle async es seguro y Starlette la ejecuta vía run_in_threadpool. run_in_threadpool para _resolve_tenant_app_secret/_resolve_tenant_id_for_phone_number/_resolve_tenant_verify_token es el patrón estándar; además vuelve funcional el single-flight threading. Añadir test que verifique que decouple_and_enqueue no es coroutine (regresión fácil).

**Referencia oficial**: https://www.starlette.io/background/

<details><summary>Verificación adversarial</summary>

Confirmado. render.yaml:111 arranca `uvicorn main:app` (1 worker, un solo event loop). webhook.py:68 `async def decouple_and_enqueue` → Starlette ejecuta background tasks async EN el loop (sólo las sync van a threadpool); internamente llama persist_whatsapp_message (db_persistence.py: 3-6 .execute() síncronos del cliente supabase por mensaje: contacts lookup, conversations select, update opcional, dedup, insert) sin ningún await → bloquea el loop durante toda la persistencia y ningún otro webhook se acepta/ACKea mientras tanto. Igual en la dependencia: meta.py:365 `async def verify_meta_signature_for_tenant` → línea 400 _resolve_tenant_app_secret (HTTP sync a Supabase + Vault en cache miss)  […]

</details>

---

### F52 · 🟠 HIGH — Eventos de template/phone-quality se persisten SIN autoridad de tenant: reintroduce el patrón WH-01 y permite escritura cross-tenant a cualquier tenant con HMAC válido

**Ubicación**: `services/connector-whatsapp/services/template_events.py:94` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: El invariant cross-tenant de dependencies/meta.py:424 solo verifica `phone_number_id`, campo AUSENTE en payloads `message_template_status_update`/`message_template_quality_update`/`phone_number_quality_update` (el check se salta con `if phone_number_id:`). Luego `decouple_and_enqueue` (routers/webhook.py:96) llama `handle_template_event(event)` SIN pasar `tenant_id_from_path` (el tenant HMAC-verificado), y los handlers actualizan `whatsapp_templates` filtrando SOLO por `meta_template_id` (sin `.eq("tenant_id", ...)` — la tabla SÍ tiene tenant_id NOT NULL y meta_template_id NO es UNIQUE per migración 20260522000000) y resuelven tenant por `meta_waba_id` del body (attacker-influenciable post-HMAC) en `persist_phone_quality_update` (línea 214). Un tenant malicioso/comprometido A firma con SU app_secret un payload con field=message_template_status_update y el meta_template_id de tenant B → corrompe status/quality de templates de B, o con phone_number_quality_update y el waba de B → sobreescribe `tenant_integrations.credentials.tier` de B. Es exactamente el patrón que A11 WH-01 cerró para mensajes inbound pero quedó abierto para eventos.

**Evidencia (código real)**:
```
template_events.py:91-95: `sb.table("whatsapp_templates")  # tenant_filter:exempt:resolution_lookup_by_external_meta_template_id\n.update(update_fields)\n.eq("meta_template_id", str(meta_template_id))\n.execute()` — sin filtro tenant_id. template_events.py:214: `tenant_id = _resolve_tenant_by_waba(sb, meta_waba_id)` con meta_waba_id proveniente del body. webhook.py:96: `result = handle_template_event(event)` — tenant_id_from_path no se pasa. meta.py:424-425: `phone_number_id = _extract_phone_number_id(raw_body)\nif phone_number_id:` — invariant saltado cuando el payload no trae metadata.phone_number_id.
```

**Corrección propuesta**:
```
Propagar el tenant HMAC-verificado y usarlo como autoridad. En routers/webhook.py:96: `result = handle_template_event(event, tenant_id_verified=tenant_id_from_path)`. En template_events.py:
```python
def handle_event(event, tenant_id_verified: Optional[str] = None) -> Optional[bool]:
    ...
    if event_type == EVENT_TYPE_TEMPLATE_STATUS_UPDATE:
        return persist_template_status_update(event, tenant_id_verified)
    ...

def persist_template_status_update(event, tenant_id_verified=None) -> bool:
    ...
    if not tenant_id_verified:
        logger.error("[WA_TPL_STATUS] sin tenant verificado — se rechaza update")
        return False
    res = (
        sb.table("whatsapp_templates")
        .update(update_fields)
        .eq("tenant_id", tenant_id_verified)
        .eq("meta_template_id", str(meta_template_id))
        .execute()
    )
```
Mismo patrón en persist_template_quality_update. En persist_phone_quality_update, reemplazar `_resolve_tenant_by_waba(sb, meta_waba_id)` por `tenant_id = tenant_id_verified` y validar `meta_waba_id == credentials.waba_id` del propio tenant (WARN+abort si difiere).
```

**Notas del verificador sobre el fix**: Dirección correcta (misma autoridad HMAC-verificada que WH-01) y fail-closed apropiado. Incompleto en 3 detalles: (a) los tests existentes en tests/test_template_events_handlers.py llaman los handlers sin tenant_id_verified y romperán con el fail-closed — deben actualizarse; (b) retirar/ajustar los tags tenant_filter:exempt para que el lint AST (BASELINE_MAX=0) no quede con exenciones falsas; (c) para status/quality conviene también validar event.meta_waba_id contra credentials.waba_id del tenant (defensa simétrica a la propuesta para phone_quality).

**Referencia oficial**: https://developers.facebook.com/docs/graph-api/webhooks/getting-started#validate-payloads

<details><summary>Verificación adversarial</summary>

Confirmado en las 4 capas citadas. (1) meta.py:424-425: el invariant cross-tenant sólo corre `if phone_number_id:` — los payloads message_template_status_update/quality y phone_number_quality_update NO traen metadata.phone_number_id (parser.py:231-289 los parsea sin metadata), así que el check se salta. (2) webhook.py:96 llama `handle_template_event(event)` sin pasar tenant_id_from_path (contraste directo con la línea 85 donde persist_whatsapp_message SÍ recibe tenant_id_verified — el cierre WH-01 quedó a medias). (3) template_events.py:91-95 y 155-159 hacen UPDATE de whatsapp_templates filtrando SOLO por meta_template_id; migración 20260522000000 confirma meta_template_id TEXT sin UNIQUE (í […]

</details>

---

### F132 · 🟡 MEDIUM — Cada turno de conversación re-carga desde cero el catálogo completo (hasta 1000 productos + variaciones + categorías + reservas) y todo el contexto del tenant sin ningún cache

**Ubicación**: `services/ai-orchestrator/agentic/dispatcher.py:1019` · **Detectado por**: performance · 📌 ya rastreado (audit finiquito §2 Productos — gap técnico 'Sin hooks que invaliden catalog_cache... orchestrator preload catalog en cada turn (cost), sin cache TTL' + §8 Configuración — gap técnico 'Cache de tenant config: orchestrator lee tenants por cada mensaje (sin cache), falta TenantConfigService TTL 30s')

**Causa**: Por CADA mensaje inbound, `dispatch_message` ejecuta secuencialmente (cliente supabase síncrono): `get_tenant_catalog` (3 queries: products+product_variations hasta MAX_CATALOG_PRODUCTS=1000 filas anidadas — catalog_tool.py:15/80 —, product_categories, stock_reservations), historial, customer_phone, upsert de contact, fetch de contact, `_load_tenant_prompt_context`, carrier capabilities, payment methods, coupons y agente activo: ≥12 round-trips a Supabase antes de invocar al LLM. Para un tenant en la cota (1000 productos × variantes) son ~0.5-1 MB de JSON re-descargados por turno: una conversación de 30 turnos re-transfiere ~20-30 MB de datos que casi no cambian, y los ~12 RTT secuenciales (~50ms c/u) agregan ~600ms de latencia fija por respuesta del bot. El connector-whatsapp ya resolvió este mismo problema con caches TTL 300s (dependencies/meta.py:65), el orchestrator no.

**Evidencia (código real)**:
```
catalog = await get_tenant_catalog(supabase, tenant_id)
    history = await _get_conversation_history(supabase, tenant_id, conversation_id)
    customer_phone = _get_conversation_customer_phone(supabase, tenant_id, conversation_id)  // + upsert contacts + _fetch_contact_for_phone + _load_tenant_prompt_context + carriers + payment_methods + coupons + get_active_agent (líneas 1019-1146)
```

**Corrección propuesta**:
```
Cache in-process con TTL corto para los datos casi-estáticos, manteniendo la verdad transaccional fresca (add_to_cart ya re-valida stock vía lib/stock_reservation.reserve → RPC en vivo, agentic/tools/cart.py:352):
```python
# catalog_tool.py
import time
_CATALOG_CACHE: dict[str, tuple[float, list[dict]]] = {}
CATALOG_CACHE_TTL_S = int(os.getenv("CATALOG_CACHE_TTL_S", "30"))

async def get_tenant_catalog(supabase: Client, tenant_id: str, *, use_cache: bool = True) -> list[dict]:
    now = time.monotonic()
    if use_cache:
        hit = _CATALOG_CACHE.get(tenant_id)
        if hit and now - hit[0] < CATALOG_CACHE_TTL_S:
            return hit[1]
    ...  # queries actuales sin cambios
    _CATALOG_CACHE[tenant_id] = (now, catalog)
    return catalog
```
Mismo patrón (TTL 300s, son configuración) para `_load_tenant_prompt_context`, carrier capabilities y payment methods. El staleness máximo de 30s en el PROMPT es seguro porque el LLM no es fuente de verdad transaccional (principio 4 CLAUDE.md) y el stock real se re-verifica en cada add_to_cart.
```

**Notas del verificador sobre el fix**: El cache de catálogo TTL 30s es viable pero con 2 correcciones: (1) la parte del fix para carrier capabilities y payment methods es REDUNDANTE — ya tienen TTL 30s; solo faltan catálogo, _load_tenant_prompt_context, coupons y get_active_agent. (2) Caveat no mencionado: cart.py:203 usa ctx.catalog_cache y cart.py:331/394 toma unit_price del snapshot → cachear introduce staleness de PRECIO ≤TTL en la escritura transaccional del cart (el stock sí se re-verifica vía RPC reserve, el precio NO). Acotado a 30s y comparable a la semántica actual de snapshot-por-turno, pero debe documentarse y ofrecer invalidate_cache() (patrón carrier_capabilities.py:288) para el flujo de edición de productos.

<details><summary>Verificación adversarial</summary>

Núcleo confirmado, pero el hallazgo sobre-declara. CONFIRMADO: get_tenant_catalog (dispatcher.py:1019) sin cache alguno — 3 queries por turno (products+variations hasta MAX_CATALOG_PRODUCTS=1000 anidadas, product_categories, stock_reservations F4), más _load_tenant_prompt_context (dispatcher.py:713, sin cache), coupons (sin cache), get_active_agent (lib/tenant_agents.py sin cache), contact upsert+fetch, history — todo secuencial por cada inbound. REFUTADO parcialmente: carrier capabilities (lib/carrier_capabilities.py:38 _TTL_SECONDS=30 per (tenant,carrier), aunque la query de nombres corre cada turno) y payment methods (lib/tenant_payment_methods.py:40 TTL 30s) YA están cacheados — el halla […]

</details>

---

### F33 · 🟡 MEDIUM — Cinco formateadores de teléfono display CO duplicados y divergentes; dos de ellos se autodeclaran 'fuente única'

**Ubicación**: `services/ai-orchestrator/agentic/invariants/summary_coherence.py:287` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo

**Causa**: Coexisten: lib/phone_format.py `format_phone_co` (docstring 'Fuente única de formateo'), lib/phone.py:133 `to_display_format` (segunda 'fuente única' con la misma responsabilidad), orchestrator.py:4507 `_format_phone_for_summary`, summary_coherence.py:287 `_format_phone` y un quinto inline en agentic/tools/contact.py:~196. Divergencia concreta: con un phone local de 10 dígitos ('312XXXXXX649'), `format_phone_co` y `_format_phone_for_summary` devuelven '+57 312 XXX X649' pero el `_format_phone` del invariant devuelve el raw sin prefijo — el resumen reescrito por summary_coherence muestra el celular en formato distinto al que emitió el prompt (format_phone_co en system_prompt.py:688).

**Evidencia (código real)**:
```
summary_coherence.py:287-293: `def _format_phone(raw: str) -> str:\n    digits = "".join(c for c in str(raw or "") if c.isdigit())\n    if digits.startswith("57") and len(digits) == 12:\n        ...\n    return str(raw)` — vs lib/phone_format.py:20-21: `if len(digits) == 10:\n        return f"+57 {digits[:3]} {digits[3:6]} {digits[6:]}"`
```

**Corrección propuesta**:
```
Consolidar en `lib/phone_format.format_phone_co` (la que ya se declara canónica):\n\n```python\n# agentic/invariants/summary_coherence.py — borrar _format_phone (líneas 287-293)\nfrom lib.phone_format import format_phone_co as _format_phone\n# agentic/tools/contact.py — borrar el bloque inline de dígitos y usar format_phone_co\n# orchestrator.py — _format_phone_for_summary delega:\n    return format_phone_co(str(phone)) if digits else ""\n# lib/phone.py — to_display_format delega en format_phone_co para eliminar la doble 'fuente única'\n```\nNota: lib/phone.py exige actualizar las 3 copias pact (api/orchestrator/connector) si se toca — preferible NO tocar phone.py y solo redirigir a phone_format.
```

**Notas del verificador sobre el fix**: Consolidar en format_phone_co es correcto y de bajo riesgo: para los datos canónicos actuales (57+12, +57..., 10 dígitos) produce output igual o mejor que las copias débiles. La nota de NO tocar lib/phone.py (3 copias pact api/orchestrator/connector) es acertada — solo redirigir los otros 4 sitios. Cambio de comportamiento menor a documentar: orchestrator._format_phone_for_summary devuelve '+digits' para números no-CO mientras format_phone_co devuelve el input crudo; el snippet propuesto conserva el gate de dígitos así que 'null'/'none' siguen filtrados. Actualizar tests que asserten los formatos actuales de summary_coherence/contact tool.

<details><summary>Verificación adversarial</summary>

CONFIRMADO. Las 5 copias existen: lib/phone_format.format_phone_co (docstring 'Fuente única de formateo', maneja 57+12 y 10 dígitos), lib/phone.to_display_format:133-145 (segunda 'fuente única' cross-service con pact), orchestrator._format_phone_for_summary:4507-4528 (maneja ambos + guards null), summary_coherence._format_phone:287-293 (SOLO 57+12; 10 dígitos → raw sin prefijo) y el inline de agentic/tools/contact.py:199-204 (SOLO 57+12). La divergencia ES alcanzable: services/api/routers/contacts.py:76-77 y 116-118 aceptan shipping_phone con pattern ^\+?[1-9]\d{7,19}$ SIN normalizar a +57 — un operador del Tenant Console puede guardar '312XXXXXX649' (10 dígitos) y entonces el resumen reescrit […]

</details>

---

### F46 · 🟡 MEDIUM — select_carrier_for_cart devuelve al LLM un total que ignora discount_cents — tras aplicar cupón, el tool reporta un total distinto al total real persistido en el cart

**Ubicación**: `services/ai-orchestrator/agentic/legacy_adapters/cart.py:61` · **Detectado por**: orchestrator-correctness · 🆕 nuevo

**Causa**: set_shipping_meta calcula el total canónico con descuento (`new_total = max(0, subtotal + shipping - discount)`, cart_tool.py:658) y lo persiste, pero el adapter recompone el total a mano como `subtotal_cents + shipping_cents` sin leer discount_cents. SelectCarrierTool expone ese valor como total_cop al LLM (agentic/tools/shipping.py:573), que lo afirma al cliente. El invariant summary_coherence luego lo reescribe (churn de rewrites) o, si el outbound no matchea el detector de resumen, el total inflado llega al cliente.

**Evidencia (código real)**:
```
legacy_adapters/cart.py:54-61: `subtotal_cents = int(cart.get("subtotal_cents") or 0)\nshipping_cents = int(rate_data.get("price_cents") or 0)\nreturn {\n    "ok": True, ...\n    "total_cents": subtotal_cents + shipping_cents,\n}` vs cart_tool.py:657-658: `discount = int(cur.data[0].get("discount_cents") or 0)\nnew_total = max(0, subtotal + int(shipping_cents) - discount)`.
```

**Corrección propuesta**:
```
Usar el snapshot que set_shipping_meta ya retorna (incluye el total con descuento):\n```python\nsnapshot = set_shipping_meta(\n    supabase, cart_id=cart["id"], tenant_id=tenant_id,\n    carrier=str(rate_data.get("carrier") or ""),\n    service_level=str(rate_data.get("service_level") or ""),\n    rate_id=rate_id,\n    shipping_cents=int(rate_data.get("price_cents") or 0),\n)\nreturn {\n    "ok": True,\n    "carrier": rate_data.get("carrier"),\n    "service_level": rate_data.get("service_level"),\n    "shipping_cents": snapshot["shipping_cents"],\n    "total_cents": snapshot["total_cents"],\n}\n```
```

**Notas del verificador sobre el fix**: Correcto y completo: el snapshot de set_shipping_meta contiene shipping_cents y total_cents con descuento; las keys retornadas coinciden con lo que SelectCarrierTool consume (carrier, service_level, shipping_cents, total_cents). No rompe el caller inline del dispatcher (solo lee ok).

<details><summary>Verificación adversarial</summary>

CONFIRMADO como divergencia de código: legacy_adapters/cart.py:54-61 recompone total_cents = subtotal + shipping SIN discount, mientras set_shipping_meta persiste new_total = max(0, subtotal + shipping - discount) (cart_tool.py:657-658, fix BUG 34 rev.109 que prueba que el flujo cupón→carrier ocurre en runtime) y YA retorna el snapshot correcto (cart_tool.py:719-726) que el adapter descarta. SelectCarrierTool expone total_cop al LLM (agentic/tools/shipping.py:569-574). Defensas parciales encontradas: (1) SummaryCoherenceInvariant reescribe outbound con 'Total'+precio contra total_cents real (summary_coherence.py:386-412) — cubre el formato resumen pero NO frases como 'tu total queda en $X' ( […]

</details>

---

### F49 · 🟡 MEDIUM — POST_PAYMENT es inalcanzable para pedidos COD: la regla del resolver exige payments.status ∈ {cod_pending, cod_collected} pero ningún código escribe filas en payments para COD

**Ubicación**: `services/ai-orchestrator/agentic/state_machine/resolver.py:79` · **Detectado por**: orchestrator-correctness · 🆕 nuevo

**Causa**: La regla 2 del StateResolver requiere has_active_order + payment_status en {'approved','cod_pending','cod_collected','refunded'}. Los únicos INSERT a payments del repo son el path payment-link Wompi (services/api/routers/orders.py:457) y wompi_webhook.py:477/656; el path COD crea la orden 'confirmed' SIN fila en payments (orders.py:181-197,237-247) y grep de 'cod_pending' solo aparece en el propio resolver y en order_cancellation.py (lectura). Tras confirmar un COD, el cart pasa a 'converted' → dispatcher carga la orden pero _payment=None → payment_status=None → la regla 2 no matchea y el estado cae a EXPLORING/GREETING: el cliente post-venta COD recibe el prompt/toolset de exploración (sin foco en tracking/reclamos) en vez del de POST_PAYMENT.

**Evidencia (código real)**:
```
resolver.py:79-82: `if ctx.has_active_order and ctx.payment_status in {\n    "approved", "cod_pending", "cod_collected", "refunded",\n}:\n    return AgenticState.POST_PAYMENT`; services/api/routers/orders.py:181-182 crea COD `initial_status = "confirmed"` sin insertar en payments (los únicos inserts a payments: orders.py:457, wompi_webhook.py:477 y 656).
```

**Corrección propuesta**:
```
Derivar POST_PAYMENT también del estado de la orden (determinístico, sin depender de payments):\n```python\n# resolver.py — build_context_from_records\norder_status = (order_row.get("status") or "").lower() or None\n...\nreturn ResolutionContext(..., extra={"order_status": order_status,\n                                     "order_payment_method": (order_row.get("payment_method") or "").lower()})\n\n# StateResolver.resolve, regla 2:\n_POST_SALE_ORDER_STATUSES = {"confirmed", "processing", "shipped", "delivered"}\nif ctx.has_active_order and (\n    ctx.payment_status in {"approved", "cod_pending", "cod_collected", "refunded"}\n    or ctx.extra.get("order_status") in _POST_SALE_ORDER_STATUSES\n):\n    return AgenticState.POST_PAYMENT\n```\ny en dispatcher._resolve_and_persist_agentic_state ampliar el SELECT de orders a `"id, status, payment_method"` (ya trae status) y pasar order_row al helper (ya lo hace).
```

**Notas del verificador sobre el fix**: Correcto y alineado con ADR-0024 (lookup DB binario, sin NLP). El dispatcher ya SELECTea orders 'id, status' (:3169) y ResolutionContext tiene el field extra. Nota: incluir 'delivered' sin ventana temporal pinnea a POST_PAYMENT a clientes que vuelven semanas después hasta que armen cart nuevo — misma semántica que ya tiene el path Wompi (payment approved eterno), aceptable pero documentarlo.

<details><summary>Verificación adversarial</summary>

CONFIRMADO. Grep exhaustivo: los únicos INSERT a payments son orders.py:457 (path payment-link) y wompi_webhook.py:477/656; 'cod_pending'/'cod_collected' solo existen en resolver.py:80 y una lectura en order_cancellation.py:667 — ningún writer. El path COD (orders.py:181-247, invocado por payment_link_tool.py:625-658 con payment_link=false) crea la orden 'confirmed' sin fila en payments. En dispatcher._resolve_and_persist_agentic_state (:3162-3190) _payment queda None → payment_status None → regla 2 (resolver.py:79-82) no matchea → con cart convertido (fuera del filtro open/checkout, :3131) cae a EXPLORING (:131-132). POST_PAYMENT es literalmente inalcanzable para COD pese a que la regla enu […]

</details>

---

### F37 · 🟡 MEDIUM — agentic/state_machine/transitions.py: API pública (is_valid_transition, allowed_next_states, transition_reason) sin ningún callsite de producción — la validación de 'saltos imposibles' que documenta nunca corre

**Ubicación**: `services/ai-orchestrator/agentic/state_machine/transitions.py:78` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo

**Causa**: El módulo declara: 'Este módulo sirve para: Validar transiciones sospechosas (telemetría / observability). Bloquear saltos imposibles (p.ej. GREETING → POST_PAYMENT...) que indican corrupción de cache'. Grep repo-wide: `is_valid_transition`/`allowed_next_states`/`transition_reason` solo se importan desde tests (tests/agentic/test_state_machine_resolver.py, test_rev109_uat_regression.py) y desde el propio __init__.py del paquete. El dispatcher persiste `conversations.agentic_state` (agentic/dispatcher.py:3098+ vía StateResolver) sin validar jamás la transición — la detección de corrupción de cache que el módulo promete no está cableada.

**Evidencia (código real)**:
```
transitions.py:6-8: `• Validar transiciones sospechosas (telemetría / observability).\n  • Bloquear saltos imposibles (p.ej. GREETING → POST_PAYMENT sin pasar\n    por CART_BUILDING + PAYMENT) que indican corrupción de cache.` — grep de callers: solo `../../tests/agentic/test_state_machine_resolver.py` y `test_rev109_uat_regression.py`
```

**Corrección propuesta**:
```
Cablear la telemetría prometida en el punto donde el dispatcher resuelve/persiste el estado (agentic/dispatcher.py, función de _resolve_agentic_state tras obtener el estado previo `_conv.get("agentic_state")` y el nuevo):\n\n```python\nfrom agentic.state_machine import AgenticState, is_valid_transition\nprev_raw = _conv.get("agentic_state")\nif _has_state_column and prev_raw and prev_raw != str(new_state):\n    try:\n        if not is_valid_transition(AgenticState(prev_raw), new_state):\n            logger.warning(\n                "[agentic.fsm] transición sospechosa %s→%s conv=%s (posible cache corrupto)",\n                prev_raw, new_state, conversation_id[:8],\n            )\n    except ValueError:\n        pass  # estado legacy no mapeable\n```\nAlternativa si el founder decide que no aporta: borrar transitions.py + sus exports del __init__ y los 2 tests (no dejar API muerta que aparenta ser una defensa activa).
```

**Notas del verificador sobre el fix**: El punto de cableo propuesto es exactamente dispatcher.py:3201-3202 donde _prev_state y _state ya existen; log-only warning es seguro y no cambia comportamiento. El try/except ValueError para estados legacy es necesario (AgenticState(prev_raw) puede fallar). La alternativa de borrar también es válida — decisión founder.

<details><summary>Verificación adversarial</summary>

Confirmado: grep repo-wide de is_valid_transition/allowed_next_states/transition_reason solo encuentra agentic/state_machine/__init__.py y 2 tests (test_state_machine_resolver.py, test_rev109_uat_regression.py). El dispatcher persiste agentic_state en _resolve_and_persist_agentic_state (dispatcher.py:3200-3206) con _prev_state disponible (línea 3201) sin validar jamás la transición. La docstring de transitions.py:6-8 promete 'Validar transiciones sospechosas' y 'Bloquear saltos imposibles' — nada de eso corre. Mitigante que baja la severidad: StateResolver es evidence-based (recomputa el estado desde cart/contact/orders cada turno, dispatcher.py:3123-3200), así que una corrupción de estado p […]

</details>

---

### F47 · 🟡 MEDIUM — UpdateCartItemQtyTool ignora el resultado de stock_reservation.reserve() cuando falla sin excepción (ok=False) — sube la cantidad del cart sin reserva válida (riesgo de oversell), gap ya corregido en AddToCartTool pero no aquí

**Ubicación**: `services/ai-orchestrator/agentic/tools/cart.py:504` · **Detectado por**: orchestrator-correctness · 🆕 nuevo

**Causa**: reserve() tiene dos modos de fallo: lanza InsufficientStock, o RETORNA ReservationResult(ok=False, error_code='VARIATION_NOT_FOUND'|'INTERNAL') (stock_reservation.py:95-124). AddToCartTool ya aborta en el segundo caso (agentic/tools/cart.py:378-385, fix auditoría 2026-06-26), pero UpdateCartItemQtyTool solo captura la excepción: si reserve retorna ok=False, el flujo continúa a update_item_quantity y el cart queda con la nueva qty SIN reserva activa (y como antes hizo release_by_cart de la reserva previa, la variation queda con 0 unidades reservadas). Bajo concurrencia (2 clientes, última unidad) esto reabre el oversell que la reserva híbrida debía impedir.

**Evidencia (código real)**:
```
agentic/tools/cart.py:503-512: `try:\n    _stock_res.reserve(\n        ctx.supabase,\n        tenant_id=ctx.tenant_id,\n        variation_id=variation_id,\n        qty=int(args.new_quantity), ...)\nexcept _stock_res.InsufficientStock as exc:` — el valor de retorno no se asigna ni se verifica, a diferencia de :378 `if not getattr(_reserve_res, "ok", False):` en AddToCartTool.
```

**Corrección propuesta**:
```
```python\ntry:\n    _res_upd = _stock_res.reserve(\n        ctx.supabase, tenant_id=ctx.tenant_id,\n        variation_id=variation_id, qty=int(args.new_quantity),\n        cart_id=cart["id"], conversation_id=ctx.conversation_id,\n        ttl_minutes=_stock_res.TTL_CART_SOFT_MINUTES,\n    )\nexcept _stock_res.InsufficientStock as exc:\n    ...restaurar previo (como hoy)...\nif not getattr(_res_upd, "ok", False):\n    # Restaurar reserva previa best-effort y abortar SIN tocar el cart.\n    try:\n        _stock_res.reserve(ctx.supabase, tenant_id=ctx.tenant_id,\n            variation_id=variation_id, qty=previous_qty, cart_id=cart["id"],\n            conversation_id=ctx.conversation_id,\n            ttl_minutes=_stock_res.TTL_CART_SOFT_MINUTES)\n    except Exception:\n        pass\n    return tool_failure(\n        "No pude reservar el stock para la nueva cantidad. Intenta de nuevo.",\n        code=getattr(_res_upd, "error_code", None) or "STOCK_RESERVE_FAILED",\n    )\n```
```

**Notas del verificador sobre el fix**: Correcto: espeja el guard de AddToCartTool + restore best-effort de la qty previa. Verificar que el check quede DENTRO del bloque `if variation_id and args.new_quantity != previous_qty:` (fuera de él _res_upd no existe). El restore puede a su vez lanzar InsufficientStock si otro cliente tomó el stock — el except Exception: pass propuesto lo cubre.

<details><summary>Verificación adversarial</summary>

CONFIRMADO. agentic/tools/cart.py:503-512: el retorno de _stock_res.reserve() no se asigna ni verifica; solo se captura InsufficientStock. stock_reservation.py:94-124 confirma los modos de fallo sin excepción: ok=False con error_code VARIATION_NOT_FOUND (:113-117), INTERNAL (:122-124) o 'reserve sin reservation_id' (:94-98). Como release_by_cart ya liberó la reserva previa (:496-501), si reserve retorna ok=False el flujo continúa a update_item_quantity (:539-548) y el cart queda con la nueva qty y CERO reservas activas para esa variation. AddToCartTool tiene el guard exacto en :374-385 con comentario citando la auditoría 2026-06-26 — el fix nunca se replicó aquí. No hay defensa downstream: u […]

</details>

---

### F35 · 🟡 MEDIUM — carrier_capabilities.py y tenant_payment_methods.py son copias completas entre api y orchestrator SIN pact test, ya drifteadas textualmente y sin declararse copias

**Ubicación**: `services/ai-orchestrator/lib/carrier_capabilities.py:27` · **Detectado por**: orchestrator-deadcode · 📌 ya rastreado (audit finiquito §10 Deuda técnica — bug HIGH 'byte-equal pero SIN pact test... mismo patrón para tenant_carriers, llm_embed, tenant_payment_methods, carrier_capabilities (5 archivos sin pact)' + gap 'Pact tests cubren solo 3 de 9 duplicados' + Plan Fase C item C3)

**Causa**: El repo tiene dos mecanismos sancionados para código compartido: copia byte-equal con pact test (lib/phone.py → tests/test_phone_helpers_pact.py; llm_embed.py) y wrapper sys.path (lib/coupons.py). carrier_capabilities.py y tenant_payment_methods.py existen duplicados en services/api/lib y services/ai-orchestrator/lib sin NINGUNO de los dos guards: ya difieren (`from dataclasses import dataclass, asdict` vs `import asdict, dataclass` + línea en blanco), sus docstrings no mencionan que hay copia gemela (ambas se llaman 'Capa de abstracción única'), y no hay test que detecte divergencia futura. Combinado con el hallazgo del sys.path.insert(0), el proceso API puede cargar la copia del orchestrator según orden de import — una edición semántica a una sola copia produciría comportamiento distinto e impredecible por proceso.

**Evidencia (código real)**:
```
`diff services/ai-orchestrator/lib/carrier_capabilities.py services/api/lib/carrier_capabilities.py` → `27c27\n< from dataclasses import dataclass, asdict\n---\n> from dataclasses import asdict, dataclass` (mismo drift en tenant_payment_methods.py); `ls tests/ | grep pact` → solo test_coherence_pact.py y test_phone_helpers_pact.py
```

**Corrección propuesta**:
```
Resincronizar el diff trivial y añadir pact test byte-equal siguiendo el patrón existente:\n\n```python\n# tests/test_shared_lib_pact.py (patrón de tests/test_phone_helpers_pact.py)\nSHARED = ["carrier_capabilities.py", "tenant_payment_methods.py", "dane_resolver.py"]\nclass TestSharedLibPact(unittest.TestCase):\n    def test_shared_lib_files_byte_identical(self):\n        for name in SHARED:\n            api = (REPO_ROOT / "services/api/lib" / name).read_bytes()\n            orch = (REPO_ROOT / "services/ai-orchestrator/lib" / name).read_bytes()\n            self.assertEqual(api, orch, f"{name} difiere entre servicios — sincronizar ambas copias")\n```\nY añadir a ambos docstrings el marcador '⚠️ ESTE ARCHIVO ES IDÉNTICO al de services/<otro>/lib/<name>' como en phone.py.
```

**Notas del verificador sobre el fix**: Correcto y sigue el patrón existente (test_phone_helpers_pact.py). Verificado que dane_resolver.py ES byte-idéntico hoy (diff exit=0) — seguro incluirlo en SHARED. Sugerencia de completitud: añadir también tenant_carriers.py (existe en ambos lib/, byte-idéntico hoy, mismo riesgo). Orden de aplicación: primero resincronizar el diff trivial (elegir el orden de import de una de las dos copias), luego el pact test, luego los marcadores de docstring — si se añade el test antes de resincronizar, falla en rojo de entrada.

<details><summary>Verificación adversarial</summary>

CONFIRMADO. diff real ejecutado: carrier_capabilities.py difiere en 'from dataclasses import dataclass, asdict' vs 'import asdict, dataclass' + 1 línea en blanco (27c27, 29d28); tenant_payment_methods.py idem (29c29, 31d30) — drift textual sin divergencia semántica HOY. tests/ solo contiene test_coherence_pact.py y test_phone_helpers_pact.py — ningún pact para estos 2 archivos. Los docstrings NO declaran copia gemela (verificado head de api/lib/carrier_capabilities.py: se autodenomina 'Capa de abstracción única' sin marcador ⚠️, a diferencia de lib/phone.py:12-14 que sí lo lleva). Los 2 mecanismos sancionados existen tal como se afirma: phone.py byte-idéntico+pact (diff exit=0) y coupons.py  […]

</details>

---

### F109 · 🟡 MEDIUM — review_queue es write-only: el path degradado del LLM encola entradas con prompt_snapshot y error_chain que ningún endpoint ni UI lee jamás

**Ubicación**: `services/ai-orchestrator/llm/degraded.py:59` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: Cuando el cascade LLM degrada (F1-10, rev. 104), on_cascade_degraded inserta en review_queue (tenant_id, conversation_id, fsm_state, reason, error_chain, prompt_snapshot) 'para el operador'. Grep de review_queue en apps/web, services/api/routers y scripts: cero lectores. El operador ve el human_takeover en el Inbox (eso sí está cableado), pero el contexto diagnóstico que se persiste para él es inaccesible — datos que nadie consume y crecen sin uso ni retention.

**Evidencia (código real)**:
```
degraded.py:59: res = supabase.table("review_queue").insert({ "tenant_id": tenant_id, "conversation_id": conversation_id, ... "prompt_snapshot": snap, — sin ningún .select de review_queue en el repo
```

**Corrección propuesta**:
```
Exponer la cola donde ya vive el takeover: en GET /api/v1/conversations/{id}/context (conversations.py:264, ya consumido por el Inbox vía /api/conversations/[id]/context) añadir:

review = (
    supabase.table("review_queue")
    .select("id, reason, error_chain, created_at")
    .eq("tenant_id", tenant_id)
    .eq("conversation_id", conversation_id)
    .order("created_at", desc=True)
    .limit(1)
    .execute()
)
context["degraded_review"] = (review.data or [None])[0]

y renderizarlo en context-panel.tsx cuando la conversación esté en human_takeover. Alternativa si no se quiere UI: dejar de insertar y loggear a Sentry, y droppear la tabla.
```

**Notas del verificador sobre el fix**: Fix viable: GET /{conversation_id}/context existe en services/api/routers/conversations.py:264 con el patrón service_role + .eq(tenant_id) explícito, y context-panel.tsx existe en apps/web/app/dashboard/inbox/_components/ (nota: el repo usa apps/web/app, no apps/web/src). Falta en el fix: marcar resolved=true al atender (o la fila queda 'abierta' para siempre) y una política de retention/purge para prompt_snapshot. La alternativa drop-tabla también es coherente si el founder no quiere la UI.

<details><summary>Verificación adversarial</summary>

Verificado con grep repo-wide (py/ts/tsx/sql): review_queue solo tiene escritores (llm/degraded.py:59 insert), tests del insert, y la migración 20260510080000 — que creó políticas RLS review_queue_tenant_select/update anticipando una UI que nunca se construyó. Cero .select() y cero updater de `resolved`. El docstring de degraded.py afirma 'El operador ve la cola en la UI Inbox / Revisión LLM' — falso, esa UI no existe. Agravante: prompt_snapshot (hasta 8KB, puede contener PII del cliente) se retiene indefinidamente sin consumidor ni retention — relevante Habeas Data (minimización). El handoff human_takeover sí funciona (dispatcher.py), pero el contexto diagnóstico es inaccesible. Medium just […]

</details>

---

### F36 · 🟡 MEDIUM — Formateo de precios COP duplicado en ~10 implementaciones locales con divergencias reales (floor vs round, '$0' vs 'N/D'), pese a que text_utils.py existe para centralizarlo

**Ubicación**: `services/ai-orchestrator/text_utils.py:50` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo

**Causa**: text_utils.py declara en su docstring 'Centralizar evita que cambios en la normalización requieran modificar 3-4 archivos y queden inconsistentes', pero después de su creación se siguieron creando copias locales: fsm/state_renderers.py:39 `_format_price_cop` (usa `int(price)` = truncado, vs `int(round(...))` de format_pesos → 13500.75 renderiza '$13.500' en un sitio y '$13.501' en otro), tools/order_status_tool.py:167 `_format_money` (None → '$0', vs 'N/D' de format_pesos), tools/image_send_tool.py:256 `_format_pesos_co`, tools/shipping_quote_tool.py:1142 `_format_money`, agentic/invariants/cart_render_coherence.py:101 `_format_cop`, agentic/invariants/variant_availability_assertion.py:95 `_fmt_price`, agentic/cart_render.py:23 `_cop`, más inlines en payment_link_tool.py:473/678, worker.py:1383, purchase_intent_resolver.py:456-479 y system_prompt.py:34.

**Evidencia (código real)**:
```
fsm/state_renderers.py:40-41: `def _format_price_cop(price: float) -> str:\n    return f"${int(price):,}".replace(",", ".")` (truncado) — vs text_utils.py:55: `return f"${int(round(amount)):,}".replace(",", ".")` (redondeo) — vs order_status_tool.py:169: `return f"${int(round(float(value or 0))):,}".replace(",", ".")` (None→'$0' en lugar de 'N/D')
```

**Corrección propuesta**:
```
Reemplazar las copias por los helpers canónicos que ya existen (format_pesos para pesos, format_cents_cop para centavos):\n\n```python\n# fsm/state_renderers.py\n-def _format_price_cop(price: float) -> str:\n-    return f"${int(price):,}".replace(",", ".")\n+from text_utils import format_pesos as _format_price_cop\n\n# tools/order_status_tool.py, tools/image_send_tool.py, agentic/invariants/*.py, agentic/cart_render.py\n+from text_utils import format_pesos, format_cents_cop\n```\nDonde el input son cents usar `format_cents_cop(cents)`; decidir UNA política para None ('N/D') y documentarla en text_utils. Priorizar los pares que se cross-validan entre sí (cart_render._cop vs cart_render_coherence._format_cop: el invariant compara texto generado por el otro).
```

**Notas del verificador sobre el fix**: Direccionalmente correcto (usar format_pesos/format_cents_cop). Cuidados: (1) distinguir sitios que reciben pesos vs cents (cart_render._cop recibe cents, invariant _format_cop recibe pesos — NO son copias byte-a-byte, cambiar pares en conjunto); (2) tests que asserten strings exactos de renderers determinísticos pueden romper al pasar de truncado a redondeo; (3) cambiar '$0'→'N/D' en order_status es cambio user-visible que debe validarse contra el template.

<details><summary>Verificación adversarial</summary>

Confirmado por grep: ~12 implementaciones locales de formato COP. Divergencias reales verificadas: fsm/state_renderers.py:41 usa int(price) (truncado) vs text_utils.py:55 int(round(amount)) (redondeo); tools/order_status_tool.py:169 renderiza None como '$0' vs 'N/D' de format_pesos; más copias en image_send_tool.py:262, shipping_quote_tool.py:1147, agentic/cart_render.py:23-28, agentic/invariants/variant_availability_assertion.py:96, agentic/system_prompt.py:34, worker.py:1383, purchase_intent_resolver.py:456-479, payment_link_tool.py:473/678. La docstring de text_utils.py:9-10 declara explícitamente que centralizar existe para evitar esto.

</details>

---

### F50 · 🟡 MEDIUM — discount_cents queda congelado al valor del momento de aplicar el cupón: mutaciones posteriores del cart (items, requote, carrier) recalculan total con un descuento stale (free_shipping y percent divergen del contrato del cupón)

**Ubicación**: `services/ai-orchestrator/tools/cart_tool.py:658` · **Detectado por**: orchestrator-correctness · 📌 ya rastreado (audit finiquito §11 Cross-module wiring — bug HIGH 'Coupons NO se re-validan ni revocan automáticamente cuando el cart muta... total_cents incoherente (subtotal nuevo + shipping − descuento viejo)' + gap 'Coupon auto-revoke en cart mutation' + Plan Fase B item B5)

**Causa**: compute_discount se evalúa UNA vez en apply_coupon (services/api/lib/coupons.py:373: percent = subtotal_al_momento × pct; free_shipping = shipping_al_momento). Después, set_shipping_meta (:658), invalidate_shipping (:1080) y set_shipping_city (:1017) recalculan `total = subtotal + shipping - discount` reutilizando el discount_cents viejo sin recomputarlo. Casos concretos: (a) cupón free_shipping aplicado con envío $10.000 → cliente cambia carrier a $15.000 → total cobra $5.000 de envío pese al cupón; (b) cupón 10% aplicado con subtotal $100.000 → cliente agrega item ($150.000) → descuento sigue siendo $10.000 en vez de $15.000; además min_subtotal ya no se revalida si el cliente QUITA items.

**Evidencia (código real)**:
```
cart_tool.py:657-658: `discount = int(cur.data[0].get("discount_cents") or 0)\nnew_total = max(0, subtotal + int(shipping_cents) - discount)` — sin recomputar; coupons.py:272-273: `if discount_type == DISCOUNT_TYPE_FREE_SHIPPING:\n    return max(0, shipping_cents)` (valor congelado al apply).
```

**Corrección propuesta**:
```
Helper de recomputo invocado por cada mutación de totales:\n```python\n# cart_tool.py\ndef _recompute_coupon_discount(supabase, *, cart_id, tenant_id, subtotal_cents, shipping_cents, coupon_id):\n    if not coupon_id:\n        return 0\n    from lib.coupons import compute_discount, validate_coupon_applicable, revoke_coupon\n    c = (supabase.table("coupons").select("*").eq("id", coupon_id)\n         .eq("tenant_id", tenant_id).limit(1).execute().data or [None])[0]\n    if not c or not validate_coupon_applicable(c, subtotal_cents).ok:\n        revoke_coupon(supabase, tenant_id=tenant_id, cart_id=cart_id, reason="no_longer_applicable")\n        return 0\n    return compute_discount(c, subtotal_cents, shipping_cents)\n```\nEn set_shipping_meta: leer también coupon_id y `discount = _recompute_coupon_discount(...)`; persistir discount_cents junto con total_cents. Aplicar igual en invalidate_shipping/set_shipping_city/remove_item.
```

**Notas del verificador sobre el fix**: Dirección correcta; imports resuelven (services/ai-orchestrator/lib/coupons.py es wrapper re-export del canónico de la API vía sys.path). Incompleto: (1) no actualiza coupon_redemptions.discount_applied_cents al recomputar (audit trail divergente); (2) el auto-revoke silencioso por no_longer_applicable deja al cliente sin aviso de que perdió el cupón — necesita señal al bot/outbound; (3) definir semántica para free_shipping aplicado con shipping=0 (hoy discount=0 permanente; el recompute en set_shipping_meta lo arregla de paso — verificarlo con test).

<details><summary>Verificación adversarial</summary>

CONFIRMADO. compute_discount se evalúa UNA sola vez en apply_coupon (coupons.py:373, con subtotal/shipping del momento; free_shipping = shipping_cents congelado, :272-273). Después: set_shipping_meta (:657-658), set_shipping_city (:1016-1017), invalidate_shipping (:1079-1080) y remove_item reutilizan discount_cents stale sin recomputar; el RPC cart_add_item incluso recalcula total_cents IGNORANDO discount por completo (migración 20260501000001:80-84; invalidate_shipping lo 'restaura' después con el valor stale). Grep confirma que apply/revoke solo corren por intención explícita del usuario (dispatcher.py:1517-1542, orchestrator.py:7130-7153) — no existe recompute en mutaciones. Los escenario […]

</details>

---

### F48 · 🟡 MEDIUM — El coalescing marca los fragmentos viejos como 'processed' ANTES de reclamar/despachar el mensaje combinado — si el dispatch falla, el retry solo procesa el último fragmento y el contenido combinado se pierde

**Ubicación**: `services/ai-orchestrator/worker.py:353` · **Detectado por**: orchestrator-correctness · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: _combine_by_conversation persiste processing_status='processed' + skip_reason='coalesced_into_next' sobre los fragmentos 1..N-1 (worker.py:353-358) y arma el contenido combinado SOLO en memoria (`last["content"] = "\n\n".join(...)`). El claim CAS y el dispatch ocurren después. Si dispatch lanza excepción, el handler resetea únicamente el ÚLTIMO mensaje a 'pending' (worker.py:571-575); en el siguiente poll, el re-fetch de la conversación solo ve ese último fragmento (los demás ya están 'processed') → el LLM recibe solo el último pedazo del mensaje del cliente como inbound del turno. Mismo efecto si otro proceso gana el claim CAS del último mensaje (log 'ya fue tomado por otro worker'): los fragmentos quedan consumidos sin haberse procesado nunca.

**Evidencia (código real)**:
```
worker.py:353-358: `self.supabase.table("messages").update({\n    "processing_status": "processed",\n    "processed": True, ...\n    "skip_reason": "coalesced_into_next",\n}).in_("id", older_ids)...` seguido de `last["content"] = "\n\n".join(...)` en memoria; y worker.py:571-575 solo resetea `msg["id"]` (el combinado) a 'pending'.
```

**Corrección propuesta**:
```
Persistir el contenido combinado o diferir el marcado: opción mínima —\n```python\n# _combine_by_conversation: marcar coalesced DESPUÉS de persistir el combinado\nlast = dict(conv_msgs[-1])\nlast["content"] = "\n\n".join(str(m.get("content") or "") for m in conv_msgs)\ntry:\n    self.supabase.table("messages").update({\n        "content": last["content"],  # el último fragmento pasa a contener el turno completo\n    }).eq("id", last["id"]).eq("tenant_id", last["tenant_id"]).execute()\n    self.supabase.table("messages").update({\n        "processing_status": "processed", "processed": True,\n        "processed_at": datetime.now(timezone.utc).isoformat(),\n        "skip_reason": "coalesced_into_next",\n    }).in_("id", older_ids).eq("tenant_id", conv_msgs[0]["tenant_id"]).execute()\nexcept Exception as exc:\n    logger.warning("[COALESCE] persist combinado falló: %s", exc)\n```\nAsí un retry (reset a 'pending') reprocesa el turno COMPLETO. Nota: al persistir content combinado, el dedupe de _build_gemini_messages sigue funcionando (compara contra el mismo content).
```

**Notas del verificador sobre el fix**: El fix propuesto (persistir content combinado en el último mensaje) introduce regresión: los fragmentos 1..N-1 siguen existiendo como filas inbound → _get_conversation_history y el Inbox UI mostrarían el texto DUPLICADO (fragmentos sueltos + combinado) en todos los turnos futuros; el dedupe de _build_gemini_messages solo remueve el ÚLTIMO mensaje exacto. Fix más limpio: diferir el marcado coalesced hasta DESPUÉS de dispatch exitoso (single worker secuencial lo permite), o si se persiste el combinado, excluir skip_reason='coalesced_into_next' del history y del render Inbox.

<details><summary>Verificación adversarial</summary>

PARCIALMENTE CONFIRMADO, sobredimensionado. Hechos verificados: _combine_by_conversation marca fragmentos 1..N-1 como processed/coalesced_into_next ANTES del claim CAS y del dispatch (worker.py:352-358), combina solo en memoria (:361-362), y el except del worker resetea SOLO el último mensaje a pending (:570-575). PERO el claim 'el contenido combinado se pierde' es incorrecto para el LLM: _get_conversation_history (orchestrator.py:1685-1697) carga TODOS los mensajes de la conversación sin filtrar processing_status/skip_reason, así que en el retry los fragmentos 1..N-1 siguen visibles como user messages consecutivos en el history; solo se pierde la agrupación como inbound del turno (degrada a […]

</details>

---

### F107 · 🟡 MEDIUM — Consentimiento Habeas Data implementado 3 veces en paralelo; los endpoints POST /contacts/{id}/consent y /reactivate-consent están muertos y su docstring afirma un caller que no existe

**Ubicación**: `services/api/routers/contacts.py:537` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: El endpoint POST /{contact_id}/consent documenta 'Llamado por el orquestador cuando el cliente responde al aviso Ley 1581', pero el orquestador escribe directo a DB (RecordConsentTool, agentic/tools/contact.py:278: ctx.supabase.table("contacts").update({...consent_given...})). La web tampoco lo llama: reactivateConsentAction (contacts/page.tsx:626-710) reimplementa la reactivación con writes directos a consent_audit_log + contacts. Grep de '/consent' y 'reactivate-consent' en apps/web y services no encuentra ningún caller. Tres implementaciones del mismo flujo legal (endpoint, bot tool, server action) sin fuente única: ya divergen en qué campos setean y qué auditan, y cualquier fix futuro de compliance debe aplicarse 3 veces.

**Evidencia (código real)**:
```
contacts.py:549-550 (docstring de record_consent): 'Llamado por el orquestador cuando el cliente responde al aviso Ley 1581.' — vs agentic/tools/contact.py:278: ctx.supabase.table("contacts").update({ "consent_given": True, ... })
```

**Corrección propuesta**:
```
Opción mínima coherente con ADR-0025 (backend service_role + writes directos): eliminar los dos endpoints muertos y dejar UNA lib compartida.
1) Borrar @router.post("/{contact_id}/consent") (contacts.py:537) y @router.post("/{contact_id}/reactivate-consent") (contacts.py:640).
2) Extraer la lógica de reactivación a una función única (p.ej. services/api/lib/consent.py::reactivate_consent(supabase, tenant_id, contact_id, actor)) y hacer que el server action web la consuma vía un endpoint fino o que el action quede como único path documentado.
3) Si se conservan los endpoints, corregir el docstring y cablear RecordConsentTool a POST /consent, igual que payment_link_tool llama a POST /payment-link.
```

**Notas del verificador sobre el fix**: Borrar los 2 endpoints muertos es seguro (0 callers verificados, incl. scripts/). Incompleto en 2 puntos: (1) no menciona actualizar el docstring del router (contacts.py:8 lista POST /{id}/consent) ni revisar tests en tests/ que puedan ejercitar los endpoints vía TestClient; (2) la opción 3 del fix (cablear RecordConsentTool al endpoint) contradice el patrón canónico ADR-0025 de writes directos service_role con .eq(tenant_id) — preferir opciones 1-2. La lib compartida de reactivación es razonable pero el server action web ya es el único path vivo documentable.

<details><summary>Verificación adversarial</summary>

Confirmado: grep de '/consent' y 'reactivate-consent' en apps/web, services y scripts encuentra 0 callers HTTP de ambos endpoints. El docstring contacts.py:550 ('Llamado por el orquestador') es falso: RecordConsentTool escribe directo a DB (agentic/tools/contact.py:278-283) igual que dispatcher.py:2050-2051. La web reimplementa reactivación con writes directos admin (contacts/page.tsx:626-710: consent_audit_log insert :664 + update :686). Divergencia verificada: el endpoint record_consent NO inserta consent_audit_log en grant (solo reactivate :727 y purge :875 lo hacen), mientras el tool sí (contact.py:324) — tres implementaciones que ya difieren en auditoría. No hay bug runtime alcanzable ( […]

</details>

---

### F20 · 🟡 MEDIUM — list_conversations traga su propio HTTPException 422 y lo convierte en 500: falta la cláusula 'except HTTPException: raise'

**Ubicación**: `services/api/routers/conversations.py:178` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: El 422 por `?status=` inválido se lanza DENTRO del try (líneas 138-142), pero el único handler es `except Exception as e:` (línea 178) sin re-raise previo de HTTPException (HTTPException hereda de Exception) → el cliente recibe 500 'Error al obtener conversaciones' en lugar del 422 con el detalle de valores permitidos. Todos los demás endpoints del archivo (get_conversation línea 211-212, send_agent_message 895-897) sí tienen `except HTTPException: raise` — inconsistencia dentro del mismo router.

**Evidencia (código real)**:
```
conversations.py:138-142 lanza `raise HTTPException(status_code=422, detail=f"Status inválido...")` dentro del try; conversations.py:178-180: `    except Exception as e:\n        logger.error("Error listando conversaciones para tenant %s: %s", tenant_id, e)\n        raise HTTPException(status_code=500, detail="Error al obtener conversaciones")` sin cláusula previa `except HTTPException: raise`
```

**Corrección propuesta**:
```
```python
        return conversations
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listando conversaciones para tenant %s: %s", tenant_id, e)
        raise HTTPException(status_code=500, detail="Error al obtener conversaciones")
```
Alternativa más limpia: mover la validación de `status` ANTES del try (como hace claims.py con _validate_status fuera de try).
```

**Notas del verificador sobre el fix**: Ambas opciones correctas. Preferible la alternativa (validar status antes del try) — elimina la clase de bug en vez de parcharlo, consistente con claims.py.

<details><summary>Verificación adversarial</summary>

Confirmado: conversations.py:138-142 lanza HTTPException(422) dentro del try; el único handler es 'except Exception as e' en línea 178 sin 'except HTTPException: raise' previo → HTTPException (subclase de Exception) se traga y se re-emite como 500 'Error al obtener conversaciones'. Inconsistencia verificada dentro del mismo archivo: get_conversation (211-212) y otros endpoints sí re-raisean. Alcanzable desde runtime real: GET /api/v1/conversations/?status=<inválido> desde cualquier consumidor de la API. Impacto limitado (sigue siendo error, solo con código/mensaje equivocado y log ruidoso) → severidad low.

</details>

---

### F25 · 🟡 MEDIUM — Rate-limit inconsistente: POST /integrations/whatsapp/credentials (escribe secretos en Vault) y todas las mutaciones de products/coupons/purchases/claims/knowledge_base carecen de RL_WRITE_DEFAULT que sí aplican orders/contacts/shipping/mfa; aveonline_webhook no aplica el webhook_rate_limit_check que sí usa meli_webhook

**Ubicación**: `services/api/routers/integrations.py:92` · **Detectado por**: api-endpoints · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: El repo tiene infraestructura de rate-limit por bucket (dependencies/security.py: RL_WRITE_DEFAULT, RL_SEND_MESSAGE, webhook_rate_limit_check) aplicada en orders.py:136, contacts.py:284+, shipping.py:466+, mfa.py:101+, tenant_offboarding.py:143+ y meli_webhook.py:225. Pero: (a) upsert_whatsapp_credentials — que hace writes a Vault (create/update_secret) y upsert de credenciales — no declara `_rl`, permitiendo martillar Vault sin límite con un JWT válido; (b) ningún endpoint de mutación de products.py (POST /, /bulk con hasta 500 productos, variations), coupons.py, purchases.py, claims.py, knowledge_base.py (embeddings Gemini síncronos por request), product_categories.py ni marketplace.py tiene rate-limit; (c) aveonline_webhook (público, hace lookups DB por request para verificar secret) no aplica webhook_rate_limit_check mientras meli_webhook sí. Superficie despareja para abuso/DoS y costo (embeddings).

**Evidencia (código real)**:
```
integrations.py:90-98: `@router.post("/whatsapp/credentials", response_model=dict)\n@audit_log(entity_type="integration", action="connected")\nasync def upsert_whatsapp_credentials(\n    payload: WhatsAppCredentialsInput,\n    request: Request,\n    tenant_id: str = Depends(get_current_tenant),\n    supabase: Client = Depends(get_service_client),\n    role: str = Depends(get_current_role),\n)` (sin `_rl`) — vs orders.py:136: `_rl: None = Depends(RL_WRITE_DEFAULT),` y meli_webhook.py:225: `allowed, retry_after = webhook_rate_limit_check(`
```

**Corrección propuesta**:
```
```python
# integrations.py
from dependencies.security import RL_WRITE_DEFAULT

async def upsert_whatsapp_credentials(
    payload: WhatsAppCredentialsInput,
    request: Request,
    tenant_id: str = Depends(get_current_tenant),
    supabase: Client = Depends(get_service_client),
    role: str = Depends(get_current_role),
    _rl: None = Depends(RL_WRITE_DEFAULT),
):
```
Aplicar el mismo `_rl: None = Depends(RL_WRITE_DEFAULT)` a las mutaciones de products/coupons/purchases/claims/knowledge_base/product_categories/marketplace, y en _handle_aveonline_webhook añadir al inicio:
```python
from dependencies.security import webhook_rate_limit_check
ip = (request.client.host if request.client else "unknown")
allowed, retry_after = webhook_rate_limit_check(bucket="webhook.aveonline", identifier=ip)
if not allowed:
    return JSONResponse(status_code=429, content={"status": "rate_limited"}, headers={"Retry-After": str(retry_after)})
```
```

**Notas del verificador sobre el fix**: La parte de RL_WRITE_DEFAULT es correcta. El snippet de aveonline NO compila: la firma real es webhook_rate_limit_check(supabase, *, ip: str, bucket: str, limit: int, window_seconds: int = 60) (dependencies/security.py:226-233) — no existe kwarg 'identifier' y faltan supabase y limit. Debe ser: allowed, retry_after = webhook_rate_limit_check(supabase, ip=ip, bucket='webhook.aveonline', limit=200, window_seconds=60). Además, colocar el check ANTES del _verify_secret para que efectivamente proteja el lookup DB.

<details><summary>Verificación adversarial</summary>

Confirmado factualmente en su totalidad: (a) upsert_whatsapp_credentials (integrations.py:90-98) no declara _rl y hace writes a Vault; grep confirma 0 usos de RL_WRITE_DEFAULT/webhook_rate_limit_check en products/coupons/purchases/claims/knowledge_base/product_categories/marketplace/integrations, mientras orders/contacts/shipping/mfa/conversations/sic_report/tenant_offboarding/data_subject_request sí lo usan; (b) knowledge_base hace embed síncrono por request (dependencies/embeddings) sin RL — costo Gemini; (c) aveonline_webhook (público, POST /{tenant_id}/{secret_token}) hace DB lookup por request para verificar secret (_verify_secret → webhook_secret_manager) sin webhook_rate_limit_check,  […]

</details>

---

### F24 · 🟡 MEDIUM — marketplace.py recibe `payload: dict = Body(...)` sin modelo Pydantic en /link, /{listing_id}/status y /import; int() sin validar produce 500 y las creaciones responden 200 en vez de 201

**Ubicación**: `services/api/routers/marketplace.py:272` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: Tres endpoints de mutación usan dict crudo (líneas 272, 392, 570) mientras el resto del repo usa modelos Pydantic (products, orders, coupons, expenses, integrations). Consecuencias concretas: (a) marketplace.py:328 `insert_data["meli_variation_id"] = int(meli_variation_id)` — un string no numérico lanza ValueError dentro del try genérico (352) → 500 'Error al crear vinculación' en vez de 422; (b) tipos sin validar llegan a la DB (meli_price puede ser string/negativo); (c) POST /link (crea marketplace_listings, retorna el row creado) y POST /import (crea product + variation + listing) responden 200 default, mientras TODAS las demás creaciones del repo declaran status_code=201 — contrato inconsistente entre routers.

**Evidencia (código real)**:
```
marketplace.py:268-272: `@router.post("/link")\n@audit_log(entity_type="marketplace_listing", action="created")\nasync def link_listing(\n    request: Request,\n    payload: dict = Body(...),` — y marketplace.py:327-328: `        if meli_variation_id is not None:\n            insert_data["meli_variation_id"] = int(meli_variation_id)`
```

**Corrección propuesta**:
```
```python
class LinkListingBody(BaseModel):
    meli_id: str = Field(..., min_length=1, max_length=32)
    variation_id: str = Field(..., min_length=1, max_length=64)
    meli_price: Optional[float] = Field(default=None, ge=0)
    meli_variation_id: Optional[int] = Field(default=None, ge=1)

class ListingStatusBody(BaseModel):
    status: Literal["active", "paused"]

class ImportBody(BaseModel):
    meli_id: str = Field(..., min_length=1, max_length=32)
    category_id: Optional[str] = None

@router.post("/link", status_code=201)
async def link_listing(request: Request, payload: LinkListingBody, ...):
    meli_id = payload.meli_id.strip().upper()
    ...
```
Con el modelo, el int() manual desaparece (Pydantic responde 422 automático) y el status queda validado por Literal.
```

**Notas del verificador sobre el fix**: Dirección correcta y consistente con el resto del repo. Caveats menores: (1) ListingStatusBody con Literal cambia el 400 actual a 422 — contrato distinto para el frontend, revisar manejo de errores en la UI; (2) cambiar a 201 es cosmético pero verificar que el frontend use res.ok y no status===200; (3) ImportBody.category_id sigue sin validar ownership contra product_categories del tenant (gap preexistente, no lo introduce el fix).

<details><summary>Verificación adversarial</summary>

Confirmado: payload: dict = Body(...) en marketplace.py:272 (/link), 392 (/{listing_id}/status) y 570 (/import). El int(meli_variation_id) en línea 328 está dentro del try de 317 cuyo except Exception (352-357) convierte ValueError en 500 'Error al crear vinculación' — un string no numérico vía llamada directa con JWT válido produce 500 donde corresponde 422. meli_price entra sin validar al insert (external_price). POST /link y /import responden 200 default vs status_code=201 del resto del repo (orders.py:125, expenses.py:29). Defensas parciales que moderan severidad: los campos requeridos se validan manualmente (295-296, 405-406, 595-596) con 400, el status endpoint valida el enum manualmen […]

</details>

---

### F23 · 🟡 MEDIUM — Fuga de detalles internos al cliente: str(exc) en 500 de MFA, excepción interpolada en payment-link, y response body crudo del proveedor MeLi en 502

**Ubicación**: `services/api/routers/mfa.py:116` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: Varios endpoints exponen el texto de excepciones internas o de proveedores directamente en detail: (1) mfa.py:116 y 175 `detail=str(exc)` en 500 — MFARecoveryCodesError encapsula la excepción subyacente (`f"No se pudieron regenerar los recovery codes: {exc}"` en lib/mfa_recovery_codes.py:102-103) que puede contener mensajes de Supabase/DB; (2) orders.py:490 `detail=f"Error al generar link de pago: {e}"` en 500 — con el .single() de la línea 416 esto incluye el JSON de error de PostgREST; (3) marketplace.py:509 y 549 pasan el response body crudo de MeLi (`get_body`/`put_body`) al cliente en 502, y marketplace.py:265/442/563/619 interpolan str(e) de httpx (URLs y detalles de infraestructura). Divergen del patrón correcto del repo (mensaje genérico + log), facilitando reconnaissance y confundiendo a la UI.

**Evidencia (código real)**:
```
mfa.py:115-116: `    except MFARecoveryCodesError as exc:\n        raise HTTPException(status_code=500, detail=str(exc))` — orders.py:490: `raise HTTPException(status_code=500, detail=f"Error al generar link de pago: {e}")` — marketplace.py:547-550: `raise HTTPException(\n                status_code=502,\n                detail=f"MeLi rechazó la actualización: {put_body}"\n            )`
```

**Corrección propuesta**:
```
Mensaje genérico al cliente, detalle solo al log (patrón ya usado en expenses.py:52-54):
```python
# mfa.py
except MFARecoveryCodesError as exc:
    logger.error("[MFA] regenerate falló user=%s: %s", user_id[:8], exc)
    raise HTTPException(status_code=500, detail="No se pudieron regenerar los recovery codes")

# orders.py:490
raise HTTPException(status_code=500, detail="Error al generar link de pago")

# marketplace.py:547-550 (el put_body ya se loguea en la línea 546)
raise HTTPException(status_code=502, detail="Mercado Libre rechazó la actualización. Revisa el estado de la publicación e intenta de nuevo.")
```
```

**Notas del verificador sobre el fix**: Correcto y sigue el patrón existente del repo. Nota: en marketplace el put_body ya se loguea (línea 546) así que no se pierde trazabilidad, pero el tenant pierde el motivo accionable del rechazo de MeLi en la UI — considerar mapear errores comunes de MeLi a mensajes seguros en vez de un genérico total. Aplicar también a marketplace.py:265/442/509/563/619 y mfa.py:175, no solo a los 3 sitios del snippet.

<details><summary>Verificación adversarial</summary>

Todo verificado: mfa.py:116 y 175 hacen detail=str(exc) donde MFARecoveryCodesError encapsula la excepción subyacente (lib/mfa_recovery_codes.py:102 y 190 interpolan {exc}, que puede ser APIError de PostgREST con detalles internos). orders.py:490 detail=f'Error al generar link de pago: {e}' — con .single() en línea 416 el APIError incluye JSON de PostgREST. marketplace.py:509 y 549 pasan el body crudo del proveedor (get_body/put_body) en el detail del 502, y 265/442/563/619 interpolan str(e) de httpx. No hay middleware/exception handler global en main.py que sanitice details (solo CORS + security headers). Matiz de severidad: todos los endpoints son autenticados (JWT tenant), y en marketplac […]

</details>

---

### F134 · 🟡 MEDIUM — Importación masiva de productos hace 2-3 round-trips secuenciales POR producto (N+1) — un CSV de 500 filas ≈ 1000-1500 llamadas HTTP a PostgREST en un solo request

**Ubicación**: `services/api/routers/products.py:363` · **Detectado por**: performance · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: El loop `for prod in payload.products` ejecuta por cada producto: SELECT de existencia por título (línea 371-374), luego UPDATE o INSERT individual (380/383), más el upsert de variantes. Con latencia típica API→Supabase de 30-80ms por round-trip, importar 500 productos toma ~45-120 segundos dentro de UN request HTTP síncrono → riesgo real de timeout del proxy/cliente con import parcialmente aplicado (sin transacción). El lookup por título es batcheable con `.in_()` y los INSERTs/upserts aceptan listas.

**Evidencia (código real)**:
```
for prod in payload.products or []:
        ...
            existing = (
                supabase.table("products").select("id")
                .eq("tenant_id", tenant_id).eq("title", prod.title).limit(1).execute()
            )
```

**Corrección propuesta**:
```
Batch en 3 fases (mismo resultado, round-trips O(1)):
```python
titles = [p.title for p in payload.products or []]
existing = (
    supabase.table("products").select("id, title")
    .eq("tenant_id", tenant_id).in_("title", titles).execute()
)
by_title = {r["title"]: r["id"] for r in (existing.data or [])}

new_rows = [{...} for p in payload.products if p.title not in by_title]
if new_rows:
    ins = supabase.table("products").insert(new_rows).execute()
    by_title.update({r["title"]: r["id"] for r in (ins.data or [])})

all_vrows = []  # acumular variantes de TODOS los productos con product_id resuelto
...
if all_vrows:
    supabase.table("product_variations").upsert(all_vrows, on_conflict="tenant_id,sku").execute()
```
Mantener la validación de ownership de categorías (ya está deduplicada vía owned_cats) y el acumulador de errors por producto en la fase de armado.
```

**Notas del verificador sobre el fix**: El batch O(1) propuesto introduce regresiones semánticas: (1) pierde el UPDATE de productos reusados ({status:'active', category_id}) — la reactivación de archivados en re-import (products.py:377-380) desaparece; (2) rompe la tolerancia per-producto documentada ('un producto que falla NO detiene los demás'): errores DB-level (constraint, FK) en un insert/upsert batcheado tumban TODO el lote, y la validación 'en fase de armado' no puede anticiparlos; (3) SKU duplicado DENTRO del payload (común en Excel reales) hace fallar el upsert único global con 'ON CONFLICT cannot affect row a second time' — hoy con upserts per-producto solo afecta a ese producto; (4) .in_('title', [500 títulos]) puede exceder límites de URL (supabase-py usa GET con query params). Alternativa correcta: sub-batches de 25-50 con el mismo flujo actual por chunk (preserva semántica, reduce round-trips ~20x) + dedup intra-payload de SKUs, o mover el import a procesamiento async con polling.

<details><summary>Verificación adversarial</summary>

Confirmado y alcanzable: mass-importer.tsx arma UN solo payload con todos los productos del Excel (líneas 220-252) y hace UN fetch a POST /products/bulk (línea 254) sin chunking client-side; BulkImport permite hasta 500 productos (products.py:121 max_length=500). El server (products.py:363-417) ejecuta por producto: SELECT por título (371-374) + UPDATE (380) o INSERT (383) + upsert de variantes (416) — 2-3 round-trips secuenciales síncronos por producto dentro del request. Con 500 productos son 1000-1500 llamadas PostgREST secuenciales en un request HTTP único, sin transacción (import parcial si el request muere). El riesgo de timeout del proxy depende del límite de Render (no verificado en  […]

</details>

---

### F21 · 🟡 MEDIUM — GET /api/v1/settings/team devuelve SIEMPRE lista vacía: la RPC get_tenant_team depende de auth.jwt() pero se invoca con el cliente service_role

**Ubicación**: `services/api/routers/settings.py:196` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: get_tenant_team() (supabase/migrations/20260415010000_get_tenant_team_confirmed.sql) resuelve el tenant con `v_tenant_id := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid` y hace `RETURN;` (vacío) si es NULL. El endpoint la llama vía get_service_client() (service key, sin JWT de usuario ni app_metadata.tenant_id) → v_tenant_id es NULL siempre → []. Endpoint muerto: el frontend real ya no lo usa (apps/web/app/dashboard/(settings-group)/team/page.tsx:119 llama la RPC directo con el JWT del usuario), pero el endpoint sigue publicado devolviendo datos incorrectos a cualquier consumidor.

**Evidencia (código real)**:
```
settings.py:196: `result = supabase.rpc("get_tenant_team").execute()` con `supabase: Client = Depends(get_service_client)` (service_role); migración: `v_tenant_id := (auth.jwt() -> 'app_metadata' ->> 'tenant_id')::uuid; IF v_tenant_id IS NULL THEN RETURN; END IF;`
```

**Corrección propuesta**:
```
Opción A (mínima) — eliminar el endpoint muerto de settings.py (el frontend usa la RPC directa con RLS). Opción B — hacerlo funcional consultando con el tenant del JWT del request:
```python
result = (
    supabase.table("tenant_users")
    .select("user_id, role, created_at")
    .eq("tenant_id", tenant_id)
    .order("created_at")
    .execute()
)
return result.data or []
```
(los emails requieren sb.auth.admin.get_user_by_id o una RPC nueva `get_tenant_team_admin(p_tenant_id uuid)` restringida a service_role).
```

**Notas del verificador sobre el fix**: Opción A (eliminar el endpoint muerto) es la correcta y mínima — el frontend ya usa la RPC con RLS. Si se elige la Opción B, notar que pierde el campo email/confirmed que la RPC provee vía auth.users (requeriría la RPC admin nueva que el fix ya menciona). Verificar que ningún script en scripts/ lo consuma antes de borrar (grep no encontró consumidores).

<details><summary>Verificación adversarial</summary>

Confirmado: settings.py:196 invoca supabase.rpc('get_tenant_team') con el cliente de get_service_client (service_role). La función (20260415010000_get_tenant_team_confirmed.sql) resuelve v_tenant_id := (auth.jwt()->'app_metadata'->>'tenant_id') y hace RETURN vacío si es NULL; el JWT service_role no tiene app_metadata.tenant_id → [] siempre. Frontend confirmado usando la RPC directa con JWT de usuario (team/page.tsx:119,155) — el endpoint no tiene consumidores. Es un endpoint publicado que devuelve datos incorrectos (lista vacía con 200) a cualquier consumidor futuro, pero sin impacto runtime actual → severidad low.

</details>

---

### F22 · 🟡 MEDIUM — PATCH /settings/team/{member_user_id} permite degradar a un owner (incluso a sí mismo) dejando al tenant sin owner — DELETE protege al owner pero PATCH no

**Ubicación**: `services/api/routers/settings.py:222` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: patch_team_member valida que el rol DESTINO no sea 'owner' (línea 214) pero no protege la fila ORIGEN: el UPDATE aplica sobre cualquier user del tenant sin excluir a los que tienen role='owner'. Un owner que pase su propio user_id (o el de otro owner) con role='operator' se degrada → como todos los endpoints de gestión exigen require_owner_role, el tenant queda sin nadie que pueda administrar equipo/settings (lockout hasta fix manual en DB). remove_team_member (línea 250-256) sí incluye el guard `.neq("role", "owner")` — asimetría entre ambos endpoints del mismo recurso.

**Evidencia (código real)**:
```
settings.py:220-226: `result = (\n            supabase.table("tenant_users")\n            .update({"role": patch.role})\n            .eq("user_id", member_user_id)\n            .eq("tenant_id", tenant_id)\n            .execute()\n        )` — vs DELETE settings.py:255: `.neq("role", "owner")  # No eliminar al owner`
```

**Corrección propuesta**:
```
Replicar el guard del DELETE:
```python
result = (
    supabase.table("tenant_users")
    .update({"role": patch.role})
    .eq("user_id", member_user_id)
    .eq("tenant_id", tenant_id)
    .neq("role", "owner")  # el rol del owner no se cambia vía API (simétrico al DELETE)
    .execute()
)
if not result.data:
    raise HTTPException(status_code=404, detail="Miembro no encontrado o es el owner (rol no modificable vía API)")
```
```

**Notas del verificador sobre el fix**: Correcto y completo: replica el guard del DELETE y del server action web (que ya usa .neq('role','owner')). No rompe nada — ASSIGNABLE_ROLES ya prohíbe asignar 'owner', así que las filas owner nunca deben ser target válido. El mensaje 404 combinado es consistente con el DELETE (línea 259).

<details><summary>Verificación adversarial</summary>

Confirmado en services/api/routers/settings.py:219-226: el UPDATE de patch_team_member solo filtra user_id+tenant_id; no existe .neq('role','owner') como sí existe en remove_team_member (línea 255). No hay trigger DB que lo impida (el único trigger sobre tenant_users, on_tenant_assignment, fue eliminado en 20260426080000). El rol viene del Custom Access Token Hook que lee tenant_users al emitir el JWT, así que la degradación se materializa al refrescar sesión → tenant sin owner → nadie pasa require_owner_role (auth.py:186-197) ni los server actions del web (page.tsx exige m.role==='owner'). Matiz: la UI web NO usa este endpoint — usa un server action propio (team/page.tsx changeRole) que SÍ  […]

</details>

---

### F110 · 🟡 MEDIUM — Router /api/v1/settings completo (10 endpoints: tenant, team, notifications, plan-capabilities, maintenance) sin ningún caller — la web reimplementa todo con Supabase directo

**Ubicación**: `services/api/routers/settings.py:112` · **Detectado por**: wiring-end2end · 📌 ya rastreado (audit finiquito §11 Cross-module wiring — gap técnico 'Settings actions.ts escribe directo a tablas via Supabase client (sin pasar por API gateway)... bypass del API layer rompe single source of truth' (+ §8 mismo patrón en server actions de settings))

**Causa**: Grep de 'api/v1/settings' en apps/web y services solo encuentra el propio router y main.py:165. La web usa paths paralelos: settings/actions.ts:28 (sb.from('tenants').update), team/page.tsx:227 (sb.from('tenant_users').update({role})) y :251 (delete), integrations/page.tsx:126 (notification_settings upsert), dashboard/layout.tsx:101 (plan_capabilities). Incluso POST /maintenance/idempotency-cleanup duplica el cron del worker (worker.py:811). El router mantiene RBAC owner-only y validaciones que NO se ejercen nunca: dos jerarquías de autorización (RBAC FastAPI muerto vs RLS vivo) que divergirán en silencio, más ~260 líneas y tests que protegen código muerto.

**Evidencia (código real)**:
```
settings.py:5-13 (docstring lista los 10 endpoints) — vs apps/web/app/dashboard/(settings-group)/settings/actions.ts:28: await sb.from('tenants').update(data).eq('id', tenantId)
```

**Corrección propuesta**:
```
Elegir un canal por recurso y borrar el otro. Dado que la web ya opera 100% vía RLS para settings (patrón vigente), eliminar el router muerto:

--- services/api/main.py
-app.include_router(settings.router, prefix="/api/v1/settings", dependencies=_OFFBOARDING_GATE)

y borrar services/api/routers/settings.py + sus tests. Antes de borrar, verificar con una revisión puntual que las políticas RLS de tenants/tenant_users/notification_settings imponen el mismo owner-only que el router imponía (p.ej. que un rol agent no pueda UPDATE tenants) — si RLS es más laxa, ese gap pasa a ser el hallazgo de seguridad real.
```

**Notas del verificador sobre el fix**: Borrar el router + tests/test_settings_api.py es viable (0 callers, incl. scripts admin). La precaución del propio fix (verificar paridad RLS owner-only antes de borrar) es correcta y necesaria — los server actions validan role en app_metadata server-side, pero conviene confirmar que RLS de tenants/tenant_users no es más laxa. Interacción con F117: settings.py:73/150 es uno de los dos writers de tenants.meta_waba_id; si se borra este router, el sync en el endpoint F3 de integrations.py (fix F117) pasa de recomendado a obligatorio. Ejecutar en PR dedicada como propone.

<details><summary>Verificación adversarial</summary>

Confirmado: grep 'api/v1/settings' en apps/, services/, scripts/ solo retorna main.py:165 (mount) — cero callers. Paths paralelos vivos verificados: settings/actions.ts:28 (sb.from('tenants').update), team/page.tsx:227/:251 (tenant_users update/delete directo), integrations/page.tsx:126 (notification_settings upsert), dashboard/layout.tsx:101 (plan_capabilities read). El worker ejecuta cleanup_expired_idempotency_keys vía RPC (worker.py:810-813), duplicando POST /maintenance/idempotency-cleanup. El router mantiene RBAC owner-only (require_owner_role) nunca ejercido vs guards de server actions (getOwnerTenantId + RLS) — dos jerarquías de autorización que pueden divergir en silencio. tests/tes […]

</details>

---

### F63 · 🟡 MEDIUM — vault_helper.py divergió: update_secret retorna bool(r.data) en API/connector (siempre False porque la RPC RETURNS void) y True incondicional en orchestrator

**Ubicación**: `services/api/vault_helper.py:48` · **Detectado por**: cross-service-dup · 🆕 nuevo

**Causa**: Las 3 copias de vault_helper.py (deuda conocida ADR-0023 con mandato 'Mantener en sync con la fuente', header del connector líneas 4-6) ya divergieron en comportamiento en update_secret. La RPC `pgsec_update_secret` es `RETURNS void` desde su creación (20260426020000:30) y sigue siéndolo tras el hardening de ownership (20260624000000:84-85, que además la hace 'no-op silencioso si ajeno'). PostgREST responde sin body para funciones void, así que `r.data` es None/'' y `bool(r.data)` es SIEMPRE False: la copia API/connector reporta fallo en updates exitosos. La copia del orchestrator retorna True incondicional: reporta éxito incluso cuando la RPC hizo no-op por ownership. Hoy los 8 call sites (integrations.py:115/119/280/285, settings.py:314, meli_client.py:350/354) ignoran el retorno, por eso es latente — pero cualquier caller nuevo que haga `if not vault.update_secret(...)` obtiene el resultado opuesto según el servicio.

**Evidencia (código real)**:
```
services/api/vault_helper.py:45-48 `r = self._sb.rpc("pgsec_update_secret", {\n    "p_id": secret_id, "p_secret": new_secret,\n}).execute()\nreturn bool(r.data)` — vs — services/ai-orchestrator/vault_helper.py:45-48 `self._sb.rpc("pgsec_update_secret", {\n    "p_id": secret_id, "p_secret": new_secret,\n}).execute()\nreturn True` — y supabase/migrations/20260624000000_vault_rpc_tenant_ownership.sql:83-84 `CREATE OR REPLACE FUNCTION pgsec_update_secret(p_id uuid, p_secret text)\nRETURNS void`
```

**Corrección propuesta**:
```
Hacer que la RPC devuelva boolean real y unificar las 3 copias. Migración:
```sql
DROP FUNCTION IF EXISTS pgsec_update_secret(uuid, text);
CREATE FUNCTION pgsec_update_secret(p_id uuid, p_secret text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = vault, public, pg_catalog AS $$
DECLARE v_name text; v_owner uuid;
BEGIN
    SELECT name INTO v_name FROM vault.secrets WHERE id = p_id;
    IF v_name IS NULL THEN RETURN false; END IF;
    IF auth.uid() IS NOT NULL THEN
        BEGIN v_owner := split_part(v_name, '/', 1)::uuid;
        EXCEPTION WHEN others THEN v_owner := NULL; END;
        IF v_owner IS NULL OR NOT EXISTS (
            SELECT 1 FROM public.tenant_users
            WHERE tenant_id = v_owner AND user_id = auth.uid()
        ) THEN RETURN false; END IF;
    END IF;
    PERFORM vault.update_secret(p_id, p_secret);
    RETURN true;
END; $$;
GRANT EXECUTE ON FUNCTION pgsec_update_secret TO authenticated, service_role;
```
Y en las 3 copias del helper el mismo cuerpo:
```python
r = self._sb.rpc("pgsec_update_secret", {"p_id": secret_id, "p_secret": new_secret}).execute()
return r.data is True
```
Agregar un pact test de hash entre las 3 copias (patrón tests/test_phone_helpers_pact.py).
```

**Notas del verificador sobre el fix**: Migración correcta: DROP + CREATE con RETURNS boolean es necesario (no se puede cambiar el return type con CREATE OR REPLACE), el cuerpo replica exactamente la semántica de ownership de 20260624000000 y los GRANTs coinciden. Compatible con código viejo durante deploy (bool(r.data) con data=true → True; orchestrator sigue True). `return r.data is True` correcto para postgrest-py. Caveats: ventana breve sin función entre DROP y CREATE (los callers toleran: except → False y el retorno se ignora); aplicar al remote con el protocolo de drift del ledger (memoria feedback_supabase_migrations); el pact test de hash entre copias es buena adición y sigue patrón existente.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/api/functions.html

<details><summary>Verificación adversarial</summary>

Divergencia confirmada en las 3 copias: services/api/vault_helper.py:45-48 y services/connector-whatsapp/lib/vault_helper.py:46-53 hacen `return bool(r.data)`; services/ai-orchestrator/vault_helper.py:44-48 hace `return True` incondicional. La RPC pgsec_update_secret es RETURNS void tanto en su creación (20260426020000:30-31) como tras el hardening de ownership (20260624000000:83-84, que además hace RETURN silencioso si el secret es ajeno) — PostgREST no devuelve body para void, r.data es falsy, así que API/connector reportan False en updates EXITOSOS y el orchestrator reporta True incluso en no-ops por ownership. PERO: verificado que los 7 call sites (integrations.py:115/119/280/285, meli_c […]

</details>

---

### F56 · 🟡 MEDIUM — _resolve_tenant_id_for_phone_number hace full-table scan de tenant_integrations y filtra en Python: O(N tenants) por cache miss y trae credentials JSONB de TODOS los tenants a memoria

**Ubicación**: `services/connector-whatsapp/dependencies/meta.py:327` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: El lookup phone_number_id→tenant_id (invariant cross-tenant, ejecutado en cada webhook con cache miss de 300s) selecciona TODAS las filas whatsapp de tenant_integrations sin filtro por phone_number_id y las recorre client-side. Con N tenants: latencia creciente en el hot path del HMAC (agrava el timeout de ACK a Meta) y transfiere los blobs credentials (verify_tokens en claro + referencias Vault) de todos los tenants al proceso en cada miss — superficie innecesaria. PostgREST soporta filtrar por campo JSONB con operador flecha, eliminando el scan.

**Evidencia (código real)**:
```
meta.py:326-343: `res = (\n    sb.table("tenant_integrations")  # tenant_filter:exempt:resolution_lookup_phone_number_id_to_tenant\n    .select("tenant_id, credentials")\n    .eq("provider", "whatsapp")\n    .in_("status", ["connected", "pending_token"])\n    .execute()\n)\nrows = res.data or []\n...\nfor row in rows:\n    creds = (row or {}).get("credentials") or {}\n    ...\n    if str(creds.get("phone_number_id") or "") == phone_number_id:` — sin filtro server-side por phone_number_id.
```

**Corrección propuesta**:
```
Filtrar server-side con el operador JSON de PostgREST:
```python
res = (
    sb.table("tenant_integrations")  # tenant_filter:exempt:resolution_lookup_phone_number_id_to_tenant
    .select("tenant_id")
    .eq("provider", "whatsapp")
    .eq("credentials->>phone_number_id", phone_number_id)
    .in_("status", ["connected", "pending_token"])
    .limit(1)
    .execute()
)
rows = res.data or []
tenant_id = rows[0]["tenant_id"] if rows else None
_cache_put(_phone_to_tenant_cache, phone_number_id, tenant_id)
return tenant_id
```
Opcional: índice de soporte `CREATE INDEX idx_ti_wa_phone_number_id ON tenant_integrations ((credentials->>'phone_number_id')) WHERE provider = 'whatsapp';`
```

**Notas del verificador sobre el fix**: Correcto: PostgREST soporta filtros con operador JSON en horizontal filtering (`credentials->>phone_number_id=eq.X`) y supabase-py pasa el string de columna verbatim. Semántica equivalente al loop actual (comparación texto). Mantener el tag exempt (lookup de resolución legítimo). El índice de expresión parcial opcional es válido y barato.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/api/tables_views.html#json-columns

<details><summary>Verificación adversarial</summary>

Confirmado en meta.py:326-349: SELECT de tenant_id+credentials de TODAS las filas whatsapp de tenant_integrations (sin filtro por phone_number_id server-side) y match en loop Python. Se ejecuta en el hot path del HMAC en cada cache miss (TTL 300s por phone_number_id, meta.py:65). Es factual, sin defensa que lo mitigue (el cache sólo amortiza por clave). Impacto HOY casi nulo (1-2 tenants provisionados), por lo que es deuda de escalabilidad + higiene (trae credentials JSONB de todos los tenants a memoria, aunque el proceso ya es service_role y maneja todos los tenants — no es un cruce de boundary de seguridad). Real como defecto de diseño en path caliente; severidad baja, no media.

</details>

---

### F55 · 🟡 MEDIUM — La deduplicación por meta_message_id corre DESPUÉS de _upsert_conversation: un reintento de Meta de un mensaje ya persistido muta estado de conversación (reabre 'closed' → 'bot_active')

**Ubicación**: `services/connector-whatsapp/services/db_persistence.py:223` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: En persist_whatsapp_message el orden es: (1) resolver tenant, (2) `_upsert_conversation` — que tiene side-effect de reabrir conversaciones 'closed' como 'bot_active' (línea 148-154) —, (2.5) dedup check por meta_message_id. Meta reintenta webhooks con frecuencia decreciente durante horas si una entrega previa no recibió 200 a tiempo (plausible con el hallazgo del event loop): si entre el original y el retry un operador cerró la conversación, el retry del MISMO mensaje (que el dedup luego descarta) ya reabrió la conversación y reactivó el bot sobre un mensaje viejo. El estado 'opted_out' sí está protegido por el gate de consent, pero 'closed' no.

**Evidencia (código real)**:
```
db_persistence.py:222-242 — orden: `conversation_id = _upsert_conversation(supabase, tenant_id, customer_phone)` (línea 223) ANTES de `# ── 2.5 Deduplicación por meta_message_id ──` (línea 225-242). Y db_persistence.py:148-154: `elif current_status in {"closed"} or ...: supabase.table("conversations").update({"status": "bot_active"}).eq("id", conversation_id).execute()`.
```

**Corrección propuesta**:
```
Mover el dedup ANTES del upsert de conversación, filtrando por tenant (tenant_id ya está resuelto en el paso 1; `meta_message_id` es UNIQUE global en DB per migración 20260406181237, así que no requiere conversation_id):
```python
# ── 1.5 Dedup ANTES de tocar estado de conversación ──
if meta_message_id:
    dup_check = (
        supabase.table("messages")
        .select("id")
        .eq("tenant_id", tenant_id)
        .eq("meta_message_id", meta_message_id)
        .limit(1)
        .execute()
    )
    if dup_check.data:
        logger.info("[INBOUND] meta_message_id=%s duplicado (retry Meta). Se omite sin tocar conversación.", meta_message_id)
        return

# ── 2. Find-or-Create Conversación ──
conversation_id = _upsert_conversation(supabase, tenant_id, customer_phone)
```
```

**Notas del verificador sobre el fix**: Correcto: mover dedup antes del upsert. tenant_id ya está resuelto (línea 218), messages tiene columna tenant_id, meta_message_id es UNIQUE global con índice parcial (20260427030000:17-19) → el filtro (tenant_id, meta_message_id) es válido y satisface el lint ADR-0025 sin tag exempt. Mantener el catch 23505 para la race insert-insert.

**Referencia oficial**: https://developers.facebook.com/docs/graph-api/webhooks/getting-started

<details><summary>Verificación adversarial</summary>

Orden confirmado en db_persistence.py: línea 223 _upsert_conversation ANTES del dedup check (225-242), y _upsert_conversation:148-154 reabre status 'closed' → 'bot_active' como side-effect incondicional (sólo 'opted_out' está protegido por el gate de consent, líneas 134-147). El UNIQUE global de meta_message_id (migración 20260406181237:20) y el catch 23505 (líneas 271-276) evitan el mensaje duplicado pero NO deshacen la reapertura ya ejecutada. Escenario alcanzable: entrega at-least-once de Meta (retry cuando el 200 se pierde en red aunque el background task ya persistió) + operador cierra la conversación en la ventana → el retry reabre 'closed' a 'bot_active' sin mensaje nuevo. Ventana rea […]

</details>

---

### F54 · 🟡 MEDIUM — parse_webhook_payloads descarta el BATCH COMPLETO de mensajes si uno solo lanza excepción (try/except envuelve todo el loop y retorna [])

**Ubicación**: `services/connector-whatsapp/services/parser.py:139` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: El try (línea 89) envuelve la iteración completa de entry→changes→messages y el except retorna `[]` desechando `parsed_messages` ya acumulados. Meta agrupa múltiples mensajes por webhook cuando hay backlog (escenario probable dado el bloqueo del event loop del hallazgo 2): un solo mensaje con estructura inesperada (p.ej. `entry` no-dict — a diferencia de `parse_webhook_events` que sí guarda con `isinstance(entry, dict)` en línea 332, aquí no hay guard; o `text`/`image` presentes con valor null → `.get(...)` sobre None → AttributeError en líneas 48/50) pierde TODOS los mensajes legítimos del batch. Al responder 200 igualmente (webhook.py:148), Meta NO reintenta → pérdida silenciosa de mensajes de clientes.

**Evidencia (código real)**:
```
parser.py:89 `try:` ... parser.py:139-141: `except Exception as e:\n        logger.error(f"Error parseando dict de WhatsApp: {e}")\n        return []` — retorna lista vacía descartando parsed_messages ya parseados. Contraste con parser.py:331-337 (parse_webhook_events) que sí tiene `if not isinstance(entry, dict): continue`.
```

**Corrección propuesta**:
```
Aislar el fallo por mensaje y añadir los mismos guards que parse_webhook_events:
```python
for entry in entries:
    if not isinstance(entry, dict):
        continue
    waba_account_id = entry.get("id")
    for change in entry.get("changes", []) or []:
        if not isinstance(change, dict):
            continue
        value = change.get("value", {}) or {}
        metadata = value.get("metadata", {}) or {}
        phone_number_id = metadata.get("phone_number_id")
        for msg in value.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            try:
                ... # bloque actual de parseo de UN msg
                parsed_messages.append({...})
            except Exception as e:
                logger.error("Error parseando mensaje individual (batch preservado): %s", e)
                continue
return parsed_messages
```
```

**Notas del verificador sobre el fix**: Fix correcto y sin riesgo: guards isinstance idénticos a parse_webhook_events + try/except por mensaje preservando el batch. No rompe tests existentes (tests/test_whatsapp_parser_context.py usa payloads bien formados). Mantener también el try externo como última red.

**Referencia oficial**: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components

<details><summary>Verificación adversarial</summary>

El hecho de código es exacto: parser.py:89 `try:` envuelve el triple loop entero y parser.py:139-141 retorna [] descartando parsed_messages ya acumulados; webhook.py:148 responde 200 igual → Meta no reintenta → pérdida silenciosa del batch. El contraste con parse_webhook_events (parser.py:332,337 isinstance guards + su propio try) confirma que el propio repo considera plausibles esas formas. PERO el trigger concreto desde tráfico Meta real es especulativo: los ejemplos citados (entry no-dict, text:null → parser.py:48 AttributeError, caption:null → .strip() sobre None en línea 50) no corresponden a payloads documentados de Meta (omite campos en vez de null), y un tenant que se auto-forja payl […]

</details>

---

### F39 · ⚪ LOW — invalidate_cache está muerto en las 4 copias (api+orchestrator × carrier_capabilities+tenant_payment_methods): el CRUD de Settings nunca invalida el cache que la docstring exige invalidar

**Ubicación**: `services/ai-orchestrator/lib/carrier_capabilities.py:288` · **Detectado por**: orchestrator-deadcode · 📌 ya rastreado (audit finiquito §11 Cross-module wiring — bug LOW 'Settings UI escribe... invalidate_cache existe pero NO se invoca desde el web app' + gap funcional 'Cache invalidation desde settings UI' + §8 Configuración bug LOW 'savePaymentMethods no invalida cache server-side') · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: La función se define con contrato explícito 'Invalida cache. Llamar tras cambios en tenant_carriers o aveonline_carrier_capabilities', pero grep repo-wide muestra CERO callers en los 4 archivos donde existe. Los endpoints que mutan tenant_carriers/tenant_payment_methods (services/api/routers/integrations.py:994 upsert_preference, :1124 insert) no invalidan, así que el propio proceso API sirve datos stale hasta expirar el TTL. El impacto real es acotado porque _TTL_SECONDS=30 — pero la docstring del módulo aún dice 'TTL cache 5min' (línea 14), drift adicional que sobrestima el riesgo aparente.

**Evidencia (código real)**:
```
lib/carrier_capabilities.py:288-290: `def invalidate_cache(tenant_id: Optional[str] = None) -> None:\n    """Invalida cache. Llamar tras cambios en tenant_carriers o\n    aveonline_carrier_capabilities."""` — grep repo-wide `invalidate_cache` sin `def`: 0 resultados; línea 14 dice `TTL cache 5min` pero línea 38: `_TTL_SECONDS = 30`
```

**Corrección propuesta**:
```
Cablear la invalidación en los endpoints de mutación de la API (misma-proceso; el proceso orchestrator queda cubierto por el TTL 30s) y corregir las docstrings:\n\n```python\n# services/api/routers/integrations.py — tras upsert_preference / insert en tenant_carriers\nfrom lib.carrier_capabilities import invalidate_cache as _invalidate_carrier_caps\n_invalidate_carrier_caps(tenant_id)\n# ídem en el CRUD de tenant_payment_methods con lib.tenant_payment_methods.invalidate_cache\n```\nY en ambos módulos: docstring `TTL cache 5min` → `TTL cache 30s (rev. 108 modular tuning)`. Alternativa mínima: borrar invalidate_cache de las 4 copias y documentar 'TTL-only, sin invalidación explícita'.
```

**Notas del verificador sobre el fix**: El fix principal (cablear invalidate_cache en integrations.py) NO tiene efecto: el proceso API no tiene lectores de esos caches y el proceso orchestrator (donde sí hay lectores) no comparte memoria — solo agregaría complejidad muerta. La 'alternativa mínima' del propio hallazgo es la correcta: borrar invalidate_cache de las 4 copias + corregir docstrings 5min→30s.

<details><summary>Verificación adversarial</summary>

Hechos confirmados: 4 definiciones de invalidate_cache (api+orchestrator × carrier_capabilities:287/288 + tenant_payment_methods:208/209), CERO callers repo-wide; docstring header dice 'TTL cache 5min' (carrier_capabilities.py:14, tenant_payment_methods.py:16) pero _TTL_SECONDS=30 (líneas 38/39). PERO la parte 'el propio proceso API sirve datos stale' es INCORRECTA: grep muestra que NINGÚN endpoint del API lee esos caches — todos los lectores viven en el proceso ai-orchestrator (dispatcher.py:1074/1091/1397, orchestrator.py:4816, payment_coherence.py:341, legacy_adapters/aveonline.py:338), donde una invalidación in-process desde la API es inalcanzable. Impacto runtime real: nulo (TTL 30s ya  […]

</details>

---

### F65 · ⚪ LOW — observability.py triplicado ya divergió: la copia del orchestrator agrega 177 líneas de OTEL (start_span/track_op) que API y connector no tienen, sin test de paridad que contenga el drift

**Ubicación**: `services/ai-orchestrator/observability.py:119` · **Detectado por**: cross-service-dup · 📌 ya rastreado (audit finiquito §10 Deuda técnica — bug HIGH 'orchestrator.observability.py vs api.observability.py byte-equal pero SIN pact test — drift puede entrar sin detectarse' + gap 'Pact tests cubren solo 3 de 9 duplicados' + Plan Fase C item C3)

**Causa**: observability.py existe copiado en services/api, services/connector-whatsapp y services/ai-orchestrator. API y connector siguen byte-idénticos (diff exit 0), pero el orchestrator forkeó en Rev.109: agregó todo el bloque OTEL (líneas 119-295: _init_otel_tracer, start_span, track_op, current_span_set_attr). Las 118 líneas base (init_sentry + before_send con filtrado PII Habeas Data) aún coinciden, pero ya no hay una fuente única: el próximo ajuste al before_send (p.ej. un filtro PII nuevo) se aplicará en una copia y no en las otras, exactamente el patrón que ya materializó el bug de vault_helper.update_secret. A diferencia de lib/phone.py (pact test tests/test_phone_helpers_pact.py) y de lib/coupons.py del orchestrator (wrapper sys.path re-export, cero duplicación), aquí no hay ningún mecanismo que fuerce la sincronía.

**Evidencia (código real)**:
```
diff services/api/observability.py services/ai-orchestrator/observability.py → `118a119,295` con `# ─── Rev. 109 P1 #2 — OpenTelemetry tracing mínimo ──...` solo en el orchestrator; diff services/api/observability.py services/connector-whatsapp/observability.py → exit 0 (idénticos)
```

**Corrección propuesta**:
```
Contener el drift de la parte compartida con un pact test de hash sobre el prefijo común (mientras llega packages/shared-py). tests/test_observability_pact.py:
```python
import hashlib
from pathlib import Path

_COPIES = [
    "services/api/observability.py",
    "services/connector-whatsapp/observability.py",
    "services/ai-orchestrator/observability.py",
]

def _base_hash(path: str) -> str:
    # Las primeras 118 líneas (init_sentry + before_send) son el contrato compartido;
    # el bloque OTEL del orchestrator (Rev. 109) es extensión local permitida.
    lines = Path(path).read_text().splitlines()[:118]
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()

def test_observability_shared_base_in_sync():
    hashes = {p: _base_hash(p) for p in _COPIES}
    assert len(set(hashes.values())) == 1, hashes
```
Alternativa estructural (preferible al hacer packages/shared-py): mover init_sentry a un módulo único y que el orchestrator lo extienda con su capa OTEL, como ya hace services/ai-orchestrator/lib/coupons.py con sys.path re-export.
```

**Notas del verificador sobre el fix**: El pact test por hash de prefijo funciona hoy, pero el 118 hardcodeado se vuelve stale silenciosamente: si la base compartida crece a >118 líneas en las 3 copias, las líneas 119+ quedan sin comparar. Mejor partir por sentinel (p.ej. el header '# ─── Rev. 109 P1 #2 — OpenTelemetry' en orchestrator y EOF en las otras dos) que por número de línea. La alternativa estructural (módulo único + extensión, patrón lib/coupons.py) es la correcta a largo plazo.

<details><summary>Verificación adversarial</summary>

Verificado: `diff services/api/observability.py services/ai-orchestrator/observability.py` → 118a119,295 (bloque OTEL Rev.109 solo en orchestrator); api↔connector byte-idénticos (diff exit 0). No existe ningún mecanismo de sincronía: tests/test_phone_helpers_pact.py cubre lib/phone, y tests/agentic/test_observability.py testea agentic/observability.py (módulo distinto, compute_agentic_metrics). Las primeras 118 líneas compartidas (init_sentry + before_send con filtrado PII Habeas Data) no tienen guard contra drift futuro. Hallazgo de mantenibilidad real, severidad low correcta.

</details>

---

### F40 · ⚪ LOW — orchestrator.py::_detect_conjunto_type_from_text es código muerto: cero callsites, su familia ya migró a fsm/address.py

**Ubicación**: `services/ai-orchestrator/orchestrator.py:4302` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo

**Causa**: Escaneo de todas las funciones top-level de orchestrator.py contra el repo completo (services + tests + scripts): `_detect_conjunto_type_from_text` es la única sin ningún caller. Las funciones hermanas de normalización de address (`normalize_building_type`, `normalize_conjunto_type`, `missing_address_fields`, `has_real_address_data`) fueron extraídas a fsm/address.py en rev. 104 (comentario en línea 4328: 'Rev. 104 (F1-2) — extraídos a fsm/address.py') pero este detector quedó atrás sin consumidores ni extracción.

**Evidencia (código real)**:
```
orchestrator.py:4302: `def _detect_conjunto_type_from_text(text: str) -> Optional[str]:` — grep repo-wide del nombre excluyendo la definición: 0 resultados; orchestrator.py:4328: `# Rev. 104 (F1-2) — extraídos a fsm/address.py.`
```

**Corrección propuesta**:
```
Borrar el bloque orchestrator.py:4302-4325 completo:\n\n```python\n-def _detect_conjunto_type_from_text(text: str) -> Optional[str]:\n-    """Sem 7 F2 cierre 2026-05-19 — Detecta si un conjunto residencial...\n-    ...\n-    return None\n```\nSi el heurístico se quiere conservar para el FSM, moverlo a fsm/address.py junto a sus hermanos y añadirle test — pero no dejarlo huérfano en el monolito.
```

**Notas del verificador sobre el fix**: Borrar orchestrator.py:4302-4325 es seguro: cero callers, cero tests que la referencien. Nota: la función vecina _detect_building_type_from_text (líneas ~4270-4299) SÍ puede tener callers — verificar que el borrado no arrastre esa.

<details><summary>Verificación adversarial</summary>

Confirmado: grep repo-wide (services + tests + scripts) de _detect_conjunto_type_from_text devuelve únicamente la definición en orchestrator.py:4302. Las hermanas (normalize_building_type, normalize_conjunto_type, missing_address_fields, has_real_address_data) fueron extraídas a fsm/address.py en rev. 104 (import en orchestrator.py:4328-4334) y fsm/address.py no contiene ningún detector equivalente — la función quedó huérfana sin consumidores.

</details>

---

### F41 · ⚪ LOW — normalize_text triplicado: safety/domain_filter.py y safety/content_safety.py replican text_utils.normalize_text citando un import circular que no existe

**Ubicación**: `services/ai-orchestrator/safety/domain_filter.py:74` · **Detectado por**: orchestrator-deadcode · 🆕 nuevo

**Causa**: Ambos módulos de safety/ duplican byte-a-byte la lógica de `text_utils.normalize_text` con la justificación 'evita import circular cuando orchestrator importe safety y safety necesita text_utils que orchestrator también importa'. La justificación es falsa: text_utils.py importa únicamente stdlib (`re`, `unicodedata`, `typing`) — no puede formar ciclo con nada. Es exactamente el anti-patrón que la docstring de text_utils advierte ('evita que cambios en la normalización... queden inconsistentes'): un cambio futuro al tokenizer/normalizador canónico dejaría los detectores de safety (queries médicas, crisis) evaluando texto normalizado distinto al del resto del pipeline.

**Evidencia (código real)**:
```
safety/domain_filter.py:77-80: `Replica el comportamiento de `text_utils.normalize_text` localmente\n    para que `safety/` sea independiente del módulo `text_utils` (evita\n    import circular cuando orchestrator importe safety y safety necesita\n    text_utils que orchestrator también importa).` — pero text_utils.py:12-14 solo importa `re`, `unicodedata`, `typing`
```

**Corrección propuesta**:
```
```python\n# safety/domain_filter.py y safety/content_safety.py\n-def _normalize(text: str) -> str:\n-    """...replica text_utils..."""\n-    if not text:\n-        return ""\n-    norm = _ud.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")\n-    return " ".join(norm.lower().split())\n+from text_utils import normalize_text as _normalize\n```\nImportar text_utils desde safety/ no crea ciclo (verificable con `python -c "import safety.domain_filter"` tras el cambio).
```

**Notas del verificador sobre el fix**: Fix correcto y verificable con `python -c "import safety.domain_filter"`. Riesgo mínimo: content_safety.py usa _normalize también dentro de detect_mental_health_crisis (safety-critical) — el comportamiento es idéntico así que no cambia detección, pero correr los tests de safety tras el cambio.

<details><summary>Verificación adversarial</summary>

Confirmado: safety/domain_filter.py:74-85 y safety/content_safety.py:58-63 replican byte-equivalente text_utils.normalize_text (NFKD → ascii ignore → lower → split/join, idéntico a text_utils.py:17-24). La justificación 'evita import circular' (domain_filter.py:77-80) es demostrablemente falsa: text_utils.py importa solo stdlib (re, unicodedata, typing — líneas 12-14), no puede formar ciclo con nada. safety/ y text_utils.py viven en el mismo directorio raíz del orchestrator, así que el import funciona en todos los contextos donde safety se importa hoy (dispatcher, orchestrator, tests).

</details>

---

### F103 · ⚪ LOW — ai-orchestrator usa el decorador deprecado @app.on_event('startup') en vez de lifespan

**Ubicación**: `services/ai-orchestrator/server.py:179` · **Detectado por**: best-practices-docs · 🆕 nuevo

**Causa**: FastAPI deprecó los handlers @app.on_event('startup')/@app.on_event('shutdown') en favor del parámetro lifespan. La doc oficial advierte además que 'If you provide a lifespan parameter, startup and shutdown event handlers will no longer be called' — es un footgun: si alguien añade un lifespan al FastAPI() de este servicio (como ya se hizo en services/api/main.py, que sí usa lifespan), el arranque del worker en background dejaría de ejecutarse silenciosamente. Inconsistencia con services/api/main.py que ya migró al patrón moderno.

**Evidencia (código real)**:
```
server.py:179-184 `@app.on_event("startup")\ndef startup_event(): ... t = threading.Thread(target=_run_worker_thread, daemon=True, ...) ; t.start()` — mientras services/api/main.py:96-102 ya usa `@asynccontextmanager async def lifespan(app)` + `FastAPI(..., lifespan=lifespan)`
```

**Corrección propuesta**:
```
Migrar a lifespan con asynccontextmanager:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_run_worker_thread, daemon=True, name='orchestrator-worker')
    t.start()
    logger.info('Worker thread iniciado. Servidor HTTP escuchando en $PORT.')
    yield

app = FastAPI(title='AI Orchestrator', description='...', lifespan=lifespan)
```
Eliminar el bloque `@app.on_event('startup')`.
```

**Notas del verificador sobre el fix**: Correcto pero requiere reordenar: `app = FastAPI(` está en server.py:39 y `_run_worker_thread` se define en ~línea 151. La función lifespan debe definirse ANTES de línea 39; puede referenciar _run_worker_thread sin problema (resolución de nombre en runtime, post-import del módulo). Verificar tests que usen TestClient sin context manager (el startup no corre en ninguno de los dos patrones, así que no hay regresión).

**Referencia oficial**: https://fastapi.tiangolo.com/advanced/events/

<details><summary>Verificación adversarial</summary>

Verificado: services/ai-orchestrator/server.py:179 usa @app.on_event("startup") para lanzar el worker thread (crítico: sin él no hay polling de mensajes), mientras services/api/main.py:97-102 ya migró a lifespan. FastAPI 0.128.8 (requirements.txt) mantiene on_event deprecado pero funcional — hoy NO hay fallo runtime; el riesgo es el footgun documentado (agregar lifespan al FastAPI() de línea 39 silenciaría el startup del worker). Hallazgo preventivo/consistencia real, severidad low correcta.

</details>

---

### F135 · ⚪ LOW — Cada mensaje WhatsApp saliente re-consulta tenant_integrations + Vault RPC sin cache — el connector ya resolvió esto con TTL 300s y el orchestrator no

**Ubicación**: `services/ai-orchestrator/whatsapp_sender.py:19` · **Detectado por**: performance · 🆕 nuevo

**Causa**: `_get_tenant_wa_credentials` ejecuta 1 SELECT a tenant_integrations + 1 RPC `pgsec_read_secret` (desencriptado Vault) en CADA envío. El bot responde varios mensajes por turno (texto + imagen + cron reminders): a 1000 mensajes salientes/día son ~2000 queries + 1000 desencriptaciones Vault redundantes para credenciales que cambian casi nunca. services/connector-whatsapp/dependencies/meta.py:65-70 ya implementa el cache TTL 300s con single-flight para exactamente los mismos datos — asimetría injustificada entre servicios.

**Evidencia (código real)**:
```
res = (
            supabase.table("tenant_integrations")
            .select("credentials, status")
            .eq("tenant_id", tenant_id)
            .eq("provider", "whatsapp")
            .single()
            .execute()
        )
        ...
        access_token = resolve_secret(vault, creds, "access_token") or ""
```

**Corrección propuesta**:
```
Replicar el patrón del connector (module-level, thread-safe no necesario en el worker single-loop):
```python
import time
_WA_CREDS_CACHE: dict[str, tuple[float, tuple[str, str]]] = {}
_WA_CREDS_TTL_S = int(os.getenv("WA_CREDS_CACHE_TTL_S", "300"))

def _get_tenant_wa_credentials(tenant_id: str, supabase: Client) -> tuple[str, str]:
    hit = _WA_CREDS_CACHE.get(tenant_id)
    if hit and time.monotonic() - hit[0] < _WA_CREDS_TTL_S:
        return hit[1]
    ...  # lookup actual
    _WA_CREDS_CACHE[tenant_id] = (time.monotonic(), (phone_id, access_token))
    return phone_id, access_token
```
Invalidar entrada en el flujo de reconexión/rotación de credenciales (integrations router) o aceptar staleness ≤300s como hace el connector.
```

**Notas del verificador sobre el fix**: Patrón correcto con 2 ajustes: (1) NO cachear resultados vacíos ('','') — el lookup retorna vacío si status!='connected' o ante excepción; cachear el fallo dejaría al tenant mudo hasta 300s tras reconectar. Cachear solo lookups exitosos. (2) La invalidación propuesta 'en el flujo de reconexión (integrations router)' NO es viable: ese router vive en services/api, proceso distinto al orchestrator — no puede invalidar un dict in-process ajeno. La opción realista es la que el propio fix da como alternativa: aceptar staleness ≤300s, igual que ya hace el connector para las mismas credenciales. Thread-safety del dict es suficiente bajo GIL para el patrón get/set atómico.

<details><summary>Verificación adversarial</summary>

Confirmado: whatsapp_sender.py:19-44 _get_tenant_wa_credentials hace 1 SELECT tenant_integrations + 1 RPC pgsec_read_secret (vault_helper.py:36, sin cache interno) en CADA llamada; send_whatsapp_message tiene 11 call sites en el orchestrator (orchestrator.py, worker.py crons, agentic) y se invoca varias veces por turno (texto+imagen+reminders). El connector sí cachea exactamente estos datos con TTL 300s + single-flight (dependencies/meta.py:55-75, _CACHE_TTL_SECONDS=300). Asimetría real sin defensa existente en el orchestrator. Severidad low correcta (costo/latencia, no correctness).

</details>

---

### F113 · ⚪ LOW — services/api/lib/whatsapp_templates.py (562 líneas, 'helper canonical') no es importado por nadie; la lógica real vive duplicada en el connector y el script admin

**Ubicación**: `services/api/lib/whatsapp_templates.py:1` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: El módulo implementa CRUD + lifecycle completo (create_template_draft, mark_submitted_to_meta, update_status_from_webhook, get_approved_template...) y whatsapp_sender.py:152 lo referencia como 'helper canonical, mismo schema'. Pero grep de imports: cero consumidores. El pipeline real usa writes directos a la tabla: seed por migración 20260523000000_seed_kaiu_templates.sql, submit por scripts/admin/submit_template_to_meta.py:89 (sb.table directo), status por services/connector-whatsapp/services/template_events.py:43 (persist_template_status_update reimplementa update_status_from_webhook), y lectura por whatsapp_sender.py:187. Además el 'canonical' es estructuralmente inalcanzable desde el connector (servicios separados sin package compartido) — la premisa de canonicidad no puede cumplirse; dos validadores de status divergirán.

**Evidencia (código real)**:
```
whatsapp_sender.py:151-152: '#   - services/api/lib/whatsapp_templates.py (helper canonical, mismo schema)' — vs grep 'from lib.whatsapp_templates|import whatsapp_templates' en services/ y scripts/: sin resultados
```

**Corrección propuesta**:
```
Borrar services/api/lib/whatsapp_templates.py y actualizar los dos comentarios que lo citan (whatsapp_sender.py:152, meta_business_management_client.py:28) apuntando a los paths reales (template_events.py + submit_template_to_meta.py). Si se prefiere conservar un canonical, mover la validación de status compartida a un doc de contrato (.context/06-contracts.md) ya que el import cross-service no es posible en el layout actual.
```

**Notas del verificador sobre el fix**: Correcto pero incompleto: debe borrar TAMBIÉN tests/test_whatsapp_templates.py (carga el módulo por path — el CI rompe si solo se borra la lib). meta_business_management_client.py NO queda huérfano (scripts/admin/submit_template_to_meta.py:121 lo importa y whatsapp_templates.py ni siquiera lo importaba). Mover la validación de status compartida a .context/06-contracts.md es coherente con la política documental del repo.

<details><summary>Verificación adversarial</summary>

Confirmado: grep estricto de imports ('from lib.whatsapp_templates|import whatsapp_templates|lib.whatsapp_templates') en services/ y scripts/ retorna 0 hits de producción. El único consumidor es tests/test_whatsapp_templates.py que lo carga por file path (importlib.util.spec_from_file_location, línea 28) — test protegiendo código muerto. template_events.py:18 declara explícitamente 'NO usa el helper services/api/lib/whatsapp_templates.py por isolation', confirmando que la duplicación fue deliberada y la premisa 'canonical' es estructuralmente incumplible (servicios separados sin package compartido). El pipeline real verificado: web escribe drafts directo (whatsapp/page.tsx:188+), submit vía  […]

</details>

---

### F112 · ⚪ LOW — ~15 endpoints REST sin ningún caller en web ni servicios: conversations (5 GET), claims (3), catalog (2), integrations (guide-dry-run, GET /), shipping (DELETE /orphans)

**Ubicación**: `services/api/routers/conversations.py:68` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: Superficie API muerta verificada por grep exhaustivo de cada path en apps/web (incl. proxies app/api/*) y services/: conversations GET /stats (:68), GET / (:116), GET /{id} (:183), GET /{id}/messages (:218), GET /{id}/cart (:1440) — el Inbox usa Supabase Realtime directo (use-conversations.ts) y solo consume los proxies de acciones (send, notes, context...); claims GET / (:106), GET /{id} (:162), POST /{id}/resolve (:214) — la web lee from('claims') directo (claims/page.tsx:19) y muta solo con POST/PATCH; catalog GET / y GET /categories (catalog.py:57,96); integrations POST /aveonline/guide-dry-run (:494) y GET / (:149); shipping DELETE /orphans (:622). Cada endpoint muerto arrastra RBAC, rate-limit y tests que se mantienen sin ejercitarse, y confunde a la siguiente sesión sobre cuál es el path real.

**Evidencia (código real)**:
```
Ejemplo: conversations.py:68 @router.get("/stats") sin ninguna referencia a 'conversations/stats' fuera del propio router; claims.py:214 @router.post("/{claim_id}/resolve") vs claims/actions.ts que solo hace fetch a /api/v1/claims/ y /api/v1/claims/${claimId}
```

**Corrección propuesta**:
```
Auditoría de poda en una PR dedicada: borrar los handlers listados (y sus tests) o documentar el consumidor previsto con fecha. Ejemplo de contracción segura:

--- services/api/routers/shipping.py
-@router.delete("/orphans")
-async def delete_orphan_shipments(...):
-    ...

Excepciones a conservar con justificación explícita: GET /catalog/ si es el contrato cross-surface planificado para Fase 13 (marcarlo con comentario '# consumidor: connector-mercadolibre F13'), y GET /conversations/{id}/cart si el Inbox lo va a consumir en el rediseño del context-panel.
```

**Notas del verificador sobre el fix**: Poda en PR dedicada es el approach correcto; las excepciones propuestas (GET /catalog/ para F13 connector-mercadolibre, GET /{id}/cart para rediseño Inbox) son razonables y coherentes con CLAUDE.md (Fase 13 futura). Añadir: borrar también los tests que ejercitan cada handler podado o el CI (validate.sh pytest) fallará; y actualizar los docstrings-índice de cada router que listan los endpoints eliminados.

<details><summary>Verificación adversarial</summary>

Confirmado endpoint por endpoint: conversations.py define GET /stats(:68), /(:116), /{id}(:183), /{id}/messages(:218), /{id}/cart(:1440) y los proxies web solo consumen send/context/send-image/notes/rerun/status (grep app/api/conversations/*); claims/actions.ts solo hace POST /api/v1/claims/(:36) y PATCH /{claimId}(:61) — GET /(:106), GET /{id}(:162), POST /{id}/resolve(:214) sin callers; catalog.py GET /(:57) y /categories(:96) sin callers (solo el proxy suggest-content); integrations guide-dry-run y GET /(:149) sin callers (el hub web lee tenant_integrations directo); shipping.py DELETE /orphans(:622) sin callers (scripts/wipe_conversation.py tiene su propia lógica _wipe_contact_orphans, n […]

</details>

---

### F26 · ⚪ LOW — expenses.expense_date es string libre sin validación de formato: una fecha malformada revienta el INSERT y responde 500 en vez de 422

**Ubicación**: `services/api/routers/expenses.py:26` · **Detectado por**: api-endpoints · 🆕 nuevo

**Causa**: ExpenseCreate declara `expense_date: Optional[str] = None` con el comentario '# ISO' pero sin validación Pydantic. Cualquier string ('mañana', '31/02/2026') pasa el modelo y llega al INSERT; Postgres rechaza el cast a timestamptz → APIError → except Exception (línea 52) → 500 'Error al registrar el gasto' donde corresponde 422. Es un registro financiero (el propio docstring del módulo destaca integridad contable) alimentado desde el dashboard.

**Evidencia (código real)**:
```
expenses.py:22-26: `class ExpenseCreate(BaseModel):\n    category: str = Field(..., min_length=1, max_length=120)\n    description: str = Field(..., min_length=1, max_length=500)\n    amount: float = Field(..., gt=0)\n    expense_date: Optional[str] = None  # ISO; default = ahora si se omite`
```

**Corrección propuesta**:
```
```python
from datetime import datetime

class ExpenseCreate(BaseModel):
    category: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1, max_length=500)
    amount: float = Field(..., gt=0)
    expense_date: Optional[datetime] = None  # Pydantic valida ISO 8601 → 422 automático
```
Y en el insert:
```python
"expense_date": (expense.expense_date or datetime.now(timezone.utc)).isoformat(),
```
```

**Notas del verificador sobre el fix**: Correcto: Pydantic v2 datetime valida ISO 8601 (acepta también date-only '2026-07-02') y responde 422 automático. Matiz: un datetime naive (sin tz) se serializa sin offset y Postgres lo interpreta en el TZ del servidor — considerar normalizar a UTC si falta tzinfo (expense.expense_date.replace(tzinfo=timezone.utc) si naive). No rompe al frontend existente.

<details><summary>Verificación adversarial</summary>

Confirmado: expenses.py:26 declara expense_date: Optional[str] = None sin validador; el insert (línea 45) pasa el string crudo a la columna expense_date timestamptz (20260413000000_purchases_and_finance.sql:68). String malformado → APIError PostgREST → except Exception (52) → 500 'Error al registrar el gasto' donde corresponde 422. Reachable con JWT válido vía llamada directa; el dashboard probablemente envía fechas válidas, así que es un defecto de contrato menor auto-infligido, sin corrupción de datos (Postgres rechaza). Severidad low es correcta.

</details>

---

### F59 · ⚪ LOW — hmac.compare_digest sobre str lanza TypeError (→ HTTP 500) si el header X-Hub-Signature-256 contiene bytes no-ASCII

**Ubicación**: `services/connector-whatsapp/dependencies/meta.py:362` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: `hmac.compare_digest` con argumentos str exige que ambos sean ASCII-only (per doc oficial Python: 'a TypeError is raised if a or b contain non-ASCII characters'). Starlette decodifica headers como latin-1, así que un atacante que envíe bytes 0x80-0xFF en `X-Hub-Signature-256: sha256=\xf1...` produce un str no-ASCII → TypeError no capturado en la dependencia → 500 en vez de 403. Meta nunca lo envía (siempre hex), pero permite a un tercero generar 5xx/ruido Sentry a voluntad y desvía la semántica de 'todo fallo de auth = 403' del diseño.

**Evidencia (código real)**:
```
meta.py:355-362: `def _hmac_verify(raw_body: bytes, signature_hex: str, app_secret: str) -> bool:\n    expected = hmac.new(...).hexdigest()\n    return hmac.compare_digest(expected, signature_hex)` — signature_hex proviene directo de `x_hub_signature_256.partition("=")` (línea 390) sin validar que sea hex.
```

**Corrección propuesta**:
```
Validar formato hex del signature antes de comparar (rechazo temprano 403):
```python
import re
_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")

# en verify_meta_signature_for_tenant, tras partition("="):
algo, _, signature_hex = x_hub_signature_256.partition("=")
if algo != "sha256" or not _HEX64_RE.fullmatch(signature_hex or ""):
    _incr_metric("hmac_fail_unsupported_algo")
    logger.warning("[META_HMAC] tenant=%s firma malformada algo=%s", tenant_id, algo)
    raise HTTPException(status_code=403, detail="Unsupported signature algorithm")
```
```

**Notas del verificador sobre el fix**: Correcto y suficiente: regex ^[0-9a-fA-F]{64}$ con fullmatch rechaza temprano con 403 antes de compare_digest; permitir A-F no crea bypass (hexdigest es lowercase y la comparación fallaría igual). No rompe tests existentes (firmas inválidas siguen recibiendo 403, solo más temprano). Detalle cosmético: reutiliza la métrica hmac_fail_unsupported_algo para hex malformado — preferible métrica propia hmac_fail_malformed_signature para no contaminar el conteo.

**Referencia oficial**: https://docs.python.org/3/library/hmac.html#hmac.compare_digest

<details><summary>Verificación adversarial</summary>

Confirmado empíricamente: hmac.compare_digest(str_ascii, str_no_ascii) lanza TypeError ('comparing strings with non-ASCII characters is not supported'). meta.py:390-394 solo valida algo=='sha256' y signature_hex no vacío — ningún check hex antes de compare_digest (meta.py:362). Starlette decodifica headers latin-1 y h11/httptools permiten obs-text 0x80-0xFF, así que el str no-ASCII es alcanzable vía POST directo al webhook público. connector main.py no registra exception handlers ni middleware (grep vacío), por lo que el TypeError en la dependencia produce 500 en vez del 403 de diseño. Ningún test cubre firmas no-ASCII (tests/test_meta_hmac_model_b.py). Sin bypass de auth (solo semántica de  […]

</details>

---

### F58 · ⚪ LOW — Oráculo de enumeración de tenants en el GET handshake: request sin query params retorna 400 si el tenant existe y 403 si no existe

**Ubicación**: `services/connector-whatsapp/routers/webhook.py:47` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: El código resuelve el verify_token del tenant ANTES de validar la forma del request: tenant desconocido → 403 siempre (línea 54); tenant conocido sin `hub.mode`/`hub.verify_token` → cae al `raise HTTPException(400)` final (línea 65). Un atacante hace `GET /api/v1/whatsapp/webhook/{uuid}` sin params y distingue por status code qué tenant_id existen con integración WhatsApp — contradice el comentario del propio código ('Mismo response que mismatch — no leak existencia tenant', línea 53). Impacto acotado (UUIDs poco adivinables, pero tenant_ids pueden filtrarse por otros canales) — el POST sí es uniforme (403 en todos los fallos).

**Evidencia (código real)**:
```
webhook.py:47-65: `expected_token = _resolve_tenant_verify_token(tenant_id)\nif not expected_token:\n    ...\n    raise HTTPException(status_code=403, detail="Forbidden")\n\nif mode == "subscribe" and token == expected_token:\n    ...\nif mode and token:\n    ...\n    raise HTTPException(status_code=403, detail="Forbidden")\nraise HTTPException(status_code=400, detail="Bad Request")` — el 400 solo es alcanzable cuando expected_token existe.
```

**Corrección propuesta**:
```
Validar la forma del request ANTES del lookup para uniformar respuestas:
```python
mode = request.query_params.get("hub.mode")
token = request.query_params.get("hub.verify_token")
challenge = request.query_params.get("hub.challenge")

if not (mode and token):
    raise HTTPException(status_code=400, detail="Bad Request")

expected_token = _resolve_tenant_verify_token(tenant_id)
if not expected_token or mode != "subscribe" or token != expected_token:
    logger.warning("[WH_VERIFY] tenant=%s handshake FAIL", tenant_id)
    raise HTTPException(status_code=403, detail="Forbidden")

return Response(content=challenge or "", media_type="text/plain")
```
```

**Notas del verificador sobre el fix**: Correcto: validar shape (400) antes del lookup y colapsar todos los fallos dependientes de tenant en 403 uniforme. Meta siempre envía hub.mode+hub.verify_token en el handshake real → sin regresión funcional. Verificar que ningún test asserte el 400 actual para tenant conocido (tests/test_meta_hmac_model_b.py test_09 sólo cubre lookup del token).

**Referencia oficial**: https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests

<details><summary>Verificación adversarial</summary>

Confirmado leyendo webhook.py:40-65: el lookup _resolve_tenant_verify_token corre ANTES de validar la forma del request. GET sin query params: tenant sin integración/inexistente → 403 (línea 54); tenant existente con whatsapp → cae al `raise HTTPException(400)` final (línea 65), porque el 400 sólo es alcanzable cuando expected_token resolvió. Oráculo de existencia unauthenticated, contradiciendo el comentario de la línea 53 ('no leak existencia tenant'). Alcanzable trivialmente desde internet; impacto acotado: tenant_id es UUIDv4 no enumerable a ciegas (el atacante necesita candidatos filtrados por otro canal) y sólo confirma 'existe con integración whatsapp'. Real, low correcto. El POST sí  […]

</details>

---

### F57 · ⚪ LOW — Read-modify-write no atómico del JSONB credentials en persist_phone_quality_update puede pisar una rotación de credenciales concurrente (lost update)

**Ubicación**: `services/connector-whatsapp/services/template_events.py:249` · **Detectado por**: connector-whatsapp · 🆕 nuevo

**Causa**: El handler lee el dict credentials completo, le mergea `tier`/`quality_signal` en Python y reescribe el JSONB ENTERO. Si entre el SELECT (línea 226) y el UPDATE (línea 249) otro proceso actualiza credentials (p.ej. rotación de access_token_secret_id vía Tenant Console o provision script), esa escritura se pierde silenciosamente — el webhook de quality restaura los valores viejos. El propio comentario del código reconoce la limitación ('PostgREST no soporta esa sintaxis nativa → leemos, mergeamos, escribimos', línea 223-224) sin mitigarla.

**Evidencia (código real)**:
```
template_events.py:241-251: `creds = (rows[0] or {}).get("credentials") or {}\n...\ncreds["tier"] = str(current_limit).strip().upper()\n...\nsb.table("tenant_integrations").update({"credentials": creds}).eq(\n    "tenant_id", tenant_id,\n).eq("provider", "whatsapp").execute()` — reescritura del JSONB completo tras lectura previa no serializada.
```

**Corrección propuesta**:
```
Merge atómico server-side vía RPC (una migración):
```sql
CREATE OR REPLACE FUNCTION public.merge_integration_credentials(
  p_tenant_id uuid, p_provider text, p_patch jsonb
) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE tenant_integrations
     SET credentials = COALESCE(credentials, '{}'::jsonb) || p_patch
   WHERE tenant_id = p_tenant_id AND provider = p_provider;
$$;
REVOKE ALL ON FUNCTION public.merge_integration_credentials FROM anon, authenticated;
```
Y en el handler:
```python
patch = {"tier": str(current_limit).strip().upper()}
if event_type in ("FLAGGED", "UNFLAGGED"):
    patch["quality_signal"] = event_type
sb.rpc("merge_integration_credentials", {
    "p_tenant_id": tenant_id, "p_provider": "whatsapp", "p_patch": patch,
}).execute()
```
```

**Notas del verificador sobre el fix**: RPC con `credentials || p_patch` es el fix atómico correcto. Dos caveats: (a) añadir también `REVOKE ALL ON FUNCTION ... FROM PUBLIC` — en Postgres las funciones nuevas otorgan EXECUTE a PUBLIC por defecto y revocar sólo anon/authenticated no lo elimina; (b) aplicar la migración per protocolo remote con drift (memoria feedback_supabase_migrations). service_role conserva acceso, el connector no se rompe.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/api/functions.html

<details><summary>Verificación adversarial</summary>

Confirmado: template_events.py:226-251 hace SELECT credentials → merge en Python → UPDATE del JSONB completo, sin CAS ni merge server-side; el comentario en líneas 222-224 reconoce la limitación sin mitigarla. Ambos escritores concurrentes existen y son reales (webhook phone_number_quality_update vs rotación de credentials desde Tenant Console/provision_tenant.py). Lost update factual, pero la ventana es de milisegundos y ambos eventos son poco frecuentes → probabilidad minúscula, impacto recuperable (re-rotar). Severidad low correcta.

</details>

---

### F114 · ⚪ LOW — El connector parsea eventos outbound_status (delivered/read), phone_quality_update y account_alert de Meta y los descarta sin persistir

**Ubicación**: `services/connector-whatsapp/services/template_events.py:294` · **Detectado por**: wiring-end2end · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: parser.py normaliza value.statuses[] a eventos EVENT_TYPE_OUTBOUND_STATUS (:212-215) y define EVENT_TYPE_PHONE_QUALITY_UPDATE / EVENT_TYPE_ACCOUNT_ALERT, pero el dispatch solo persiste template_status/quality: la rama else está explícitamente vacía ('no persistence todavía (futuro Sem 11)'). Consecuencia funcional hoy: los delivery receipts que Meta ya envía al webhook se pierden — el Inbox no puede mostrar entregado/leído (chat-panel.tsx solo muestra processing_status==='failed') y la calidad del número solo se obtiene por polling del worker (health_metrics.py), no por los eventos push que ya llegan. Trabajo parcialmente cableado: se paga el costo de parseo sin obtener el dato.

**Evidencia (código real)**:
```
template_events.py:294: '# outbound_status, account_alert, etc. → no persistence todavía (futuro Sem 11)' — mientras parser.py:212-215 construye el evento: "event_type": EVENT_TYPE_OUTBOUND_STATUS,
```

**Corrección propuesta**:
```
Cablear el mínimo con valor inmediato: persistir el status en messages usando meta_message_id (columna que el worker ya guarda vía ack_whatsapp_outbound_message):

elif event["event_type"] == EVENT_TYPE_OUTBOUND_STATUS:
    supabase.table("messages").update({
        "delivery_status": event["status"],          # sent|delivered|read|failed
        "delivery_status_at": event["timestamp"],
    }).eq("tenant_id", tenant_id).eq("meta_message_id", event["message_id"]).execute()

(con migración ADD COLUMN delivery_status TEXT, delivery_status_at TIMESTAMPTZ en messages). Si Sem 11 sigue siendo el plan, dejar el descarte pero registrar métrica de eventos dropeados para dimensionarlo.
```

**Notas del verificador sobre el fix**: El fix propuesto tiene 4 defectos: (1) usa event["message_id"] pero la key del parser es meta_message_id (parser.py:218) → KeyError; (2) escribe event["timestamp"] (epoch string de Meta, ej. '1751...') directo a columna TIMESTAMPTZ → error de cast en PostgREST, requiere conversión epoch→ISO; (3) tenant_id no está en scope dentro de handle_event(event) — habría que cambiar la firma o cablear desde decouple_and_enqueue (webhook.py:93-96); (4) sin guard de orden: un 'delivered' que llegue tras 'read' regresa el estado. La alternativa sugerida (métrica de eventos dropeados mientras Sem 11 sigue en plan) sí es segura.

**Referencia oficial**: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/components

<details><summary>Verificación adversarial</summary>

Parcialmente cierto, parcialmente refutado. CIERTO: eventos outbound_status y account_alert se parsean (parser.py:212-228, 350-358) y se descartan — handle_event retorna None (template_events.py:294) y webhook.py:97-105 solo los loguea; chat-panel.tsx:361-367 solo renderiza failed/skipped, sin delivered/read; escenario runtime real (Meta ya envía statuses al webhook). FALSO: el título y la causa incluyen phone_quality_update como descartado, pero handle_event SÍ lo persiste vía persist_phone_quality_update (template_events.py:291-292 → update tier en tenant_integrations.credentials :244-251), refutando también 'la calidad solo por polling'. Además es un deferral explícitamente documentado (' […]

</details>

---

## 3. Frontend (Tenant Console)

### F82 · 🔴 CRITICAL — removeMember/inactivateMember ejecutan deleteUser/ban con service_role sobre un user_id arbitrario sin verificar que pertenezca al tenant del caller (destrucción cross-tenant de cuentas)

**Ubicación**: `apps/web/app/dashboard/(settings-group)/team/page.tsx:264` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: El DELETE/UPDATE sobre tenant_users sí está scoped con .eq('tenant_id', m.tenant_id).neq('role','owner'), pero su resultado (filas afectadas) nunca se comprueba. Las operaciones admin posteriores (signOut global, deleteUser(targetId, true) en removeMember; ban_duration '876600h' en inactivateMember línea 292; signOut en changeRole línea 235) se ejecutan incondicionalmente con service_role sobre el targetId que llega crudo del FormData. Un owner del tenant A que envíe el UUID de un usuario del tenant B no matchea filas en tenant_users (0 rows, sin error), pero igualmente banea/soft-deletea la cuenta auth.users del otro tenant. auth.admin.deleteUser opera globalmente sobre auth.users, no está limitado por tenant.

**Evidencia (código real)**:
```
await sb.from('tenant_users').delete()
      .eq('user_id', targetId)
      .eq('tenant_id', m.tenant_id)
      .neq('role', 'owner')

    const adminSb = createAdminClient()

    // 2. signOut global — revoca sesión activa inmediatamente
    await adminSb.auth.admin.signOut(targetId, 'global')

    // 3. Soft-delete en auth.users — preserva el ID para audit trails pero anonimiza PII
    await adminSb.auth.admin.deleteUser(targetId, true)
```

**Corrección propuesta**:
```
Verificar membership ANTES de cualquier llamada admin, usando el resultado del write scoped. En removeMember (aplicar el mismo patrón en inactivateMember y changeRole):

```ts
const { data: removed } = await sb.from('tenant_users').delete()
  .eq('user_id', targetId)
  .eq('tenant_id', m.tenant_id)
  .neq('role', 'owner')
  .select('user_id')
if (!removed?.length) {
  redirect('/dashboard/team?error=miembro-no-encontrado')
}
const adminSb = createAdminClient()
await adminSb.auth.admin.signOut(targetId, 'global')
await adminSb.auth.admin.deleteUser(targetId, true)
```

En inactivateMember: `.update({...}).eq(...).select('user_id')` y abortar si `!data?.length` antes de `updateUserById(targetId, { ban_duration: '876600h' })`. En changeRole: idem antes de `signOut(targetId, 'global')`.
```

**Notas del verificador sobre el fix**: Correcto: añadir `.select('user_id')` al write scoped y abortar si `!removed?.length` ANTES de las llamadas admin cierra el gap (con RLS + filtros el DELETE/UPDATE devuelve 0 filas para users de otro tenant). Aplicar el mismo patrón en inactivateMember (update...select) y changeRole. No rompe el flujo normal (miembro propio devuelve su fila). Completo. | Fix correcto y suficiente para las tres actions destructivas citadas. Recomendación adicional: aplicar el mismo patrón (verificar filas afectadas antes de la llamada admin) también en activateMember (updateUserById ban_duration:'none') para eliminar el residuo de mismo defecto, aunque su impacto es menor.

**Referencia oficial**: https://supabase.com/docs/reference/javascript/auth-admin-deleteuser

<details><summary>Verificación adversarial</summary>

Confirmado en team/page.tsx. removeMember (251-264): `sb.from('tenant_users').delete().eq('user_id',targetId).eq('tenant_id',m.tenant_id).neq('role','owner')` SIN inspeccionar filas afectadas, seguido incondicionalmente de `adminSb.auth.admin.signOut(targetId,'global')` y `deleteUser(targetId,true)`. inactivateMember (281-297) igual con `updateUserById(targetId,{ban_duration:'876600h'})`. changeRole (227-235) con signOut global. `targetId` viene crudo de FormData. Las ops admin usan service_role sobre auth.users (global, no scoped por tenant). Un owner del tenant A que envíe el UUID de un user del tenant B: el write scoped afecta 0 filas sin error (RLS 'Tenant Isolation — tenant_users' + fil […]

</details>

---

### F127 · 🟠 HIGH — La página de Métricas trae tablas enteras (order_items sin filtro de fecha, conversations, contacts, products, messages fila-a-fila) para contar en JS — KPIs silenciosamente truncados a 1000 filas

**Ubicación**: `apps/web/app/dashboard/(analytics)/metrics/page.tsx:67` · **Detectado por**: performance · 📌 ya rastreado (audit finiquito §7 Finanzas y Analítica — bug HIGH 'MetricsPage carga todos los conversations, contacts, products SIN paginación ni gte(created_at)... límite implícito 1000 rows → KPIs subreportados silenciosamente' + esfuerzo '2d fix bugs runtime (... paginación metrics ...)')

**Causa**: Siete queries traen filas crudas para agregarlas en JavaScript en el Server Component. `order_items` no tiene NINGÚN filtro temporal (toda la historia del tenant, para siempre), `conversations`/`contacts`/`products` tampoco, y con period distinto de 7/30/90 `since = new Date(0)` (línea 60-62) trae messages/orders completos. PostgREST aplica `db-max-rows` (default 1000 en Supabase): una vez que el tenant supera 1000 mensajes/items —días de operación WhatsApp real— los KPI (revenue, conversión, top productos, mensajes/día) quedan SILENCIOSAMENTE MAL sin error alguno. Si se sube max-rows, el payload por page-view crece a MBs.

**Evidencia (código real)**:
```
supabase.from('order_items').select('title, quantity, unit_price').eq('tenant_id', tenantId),
    supabase.from('contacts').select('id').eq('tenant_id', tenantId),
    supabase.from('conversations').select('id, status').eq('tenant_id', tenantId),
```

**Corrección propuesta**:
```
Conteos con `head: true` y agregación en SQL vía RPC. Ejemplo:
```ts
const [inbound, outbound, contactsCnt] = await Promise.all([
  supabase.from('messages').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('direction', 'inbound').gte('created_at', since),
  supabase.from('messages').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('direction', 'outbound').gte('created_at', since),
  supabase.from('contacts').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
])
```
Y para top-productos/revenue una función SQL:
```sql
create or replace function public.metrics_top_products(p_tenant uuid, p_since timestamptz)
returns table(title text, quantity bigint, revenue numeric)
language sql stable security invoker as $$
  select oi.title, sum(oi.quantity), sum(oi.quantity * oi.unit_price)
  from public.order_items oi
  join public.orders o on o.id = oi.order_id and o.tenant_id = oi.tenant_id
  where oi.tenant_id = p_tenant and o.created_at >= p_since and o.status <> 'cancelled'
  group by oi.title order by 2 desc limit 5;
$$;
```
```

**Notas del verificador sobre el fix**: Direccionalmente correcto (head:true counts + RPC SQL; order_items SÍ tiene tenant_id — migración 20260409220000_fase9_schema_core.sql:45 — el join propuesto funciona). Incompleto como está: la página también necesita histograma mensajes-por-día-de-semana, ordersByStatus y agregados de claims (requieren RPCs group-by adicionales o quedar acotados por ventana+limit), y la RPC exige migración nueva (seguir protocolo feedback_supabase_migrations, ledger con drift).

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/configuration.html#db-max-rows

<details><summary>Verificación adversarial</summary>

Confirmado en metrics/page.tsx:63-71: order_items sin NINGÚN filtro temporal (:67), conversations/contacts/products tablas completas (:65,68,69), y con period fuera de 7/30/90 since=new Date(0) (:59-61) trae messages/orders/claims completos. Toda la agregación (revenue :87-93, top productos :104-111, mensajes/día :114-119) es reduce/filter en JS. supabase/config.toml max_rows=1000 (default también en Supabase hosted) → truncamiento silencioso de KPIs de dinero sin error. No existe RPC ni vista agregada en supabase/migrations/ (grep metrics_top_products/finance_summary: 0 hits). Sin defensa alguna.

</details>

---

### F68 · 🟠 HIGH — Server actions de Contactos usan `throw new Error(msg)` para errores esperados; en producción Next.js enmascara el mensaje y el operador nunca ve la causa (duplicado 409, guard Wompi, validación consent)

**Ubicación**: `apps/web/app/dashboard/(sales)/contacts/page.tsx:259` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: Las server actions inline de contacts/page.tsx lanzan 17 `throw new Error` con mensajes destinados al operador (líneas 153, 165, 211, 235, 259-260, 338, 344, 414, 441, 480+, incluyendo el guard Wompi 409 que el propio comentario dice 'propagamos mensaje claro al operador en lugar de error genérico'). En producción, Next.js 14 reemplaza el mensaje de un Error no controlado lanzado en una Server Action por uno genérico + digest (protección anti-leak). Consecuencias: (a) en `confirmDelete` (contacts-manager.tsx:383-394) el `catch (e) { window.alert(e.message) }` muestra el texto genérico, no la instrucción de esperar 30 min por el link Wompi; (b) en `handleAdd`/`handleEdit` (contacts-manager.tsx:335-336, 353-354) NO hay try/catch, así que el rechazo dentro de `startTransition` escala al error boundary `dashboard/error.tsx` y tumba la página completa por un simple teléfono duplicado. El propio repo ya tiene el patrón correcto: promotions-manager.tsx recibe `ActionResult = { ok: boolean; error?: string }`.

**Evidencia (código real)**:
```
page.tsx:259-260: `if (res.status === 409) throw new Error('Ya existe un contacto con ese teléfono.')\n      throw new Error(detail || 'Error al crear el contacto.')` — y contacts-manager.tsx:335-336: `startTransition(async () => {\n      await addAction(fd)` (sin try/catch)
```

**Corrección propuesta**:
```
Adoptar el contrato ActionResult ya canónico en promotions. En page.tsx:
```ts
type ActionResult = { ok: boolean; error?: string }
async function addContact(formData: FormData): Promise<ActionResult> {
  'use server'
  try {
    // ...lógica existente, sustituyendo cada `throw new Error(msg)` por:
    if (res.status === 409) return { ok: false, error: 'Ya existe un contacto con ese teléfono.' }
    // ...
    return { ok: true }
  } catch (e) {
    console.error('[addContact]', e)
    return { ok: false, error: 'Error inesperado al crear el contacto.' }
  }
}
```
Y en contacts-manager.tsx handleAdd:
```ts
startTransition(async () => {
  const res = await addAction(fd)
  if (!res.ok) { window.alert(`No se puede guardar: ${res.error}`); return }
  addFormRef.current?.reset()
  // ...
})
```
Aplicar igual a editContact/deleteContact/reactivateConsent (este último ya devuelve `{ok,status,message}` — usarlo de plantilla).
```

**Notas del verificador sobre el fix**: Fix correcto y con plantilla ya canónica en el repo. Incompleto en un detalle mecánico: cambiar el retorno de las actions exige actualizar las Props de contacts-manager.tsx (addAction/editAction/deleteAction hoy tipadas Promise<void>, líneas 70-77) y los 3 handlers; el fix lo cubre para handleAdd y hay que replicarlo en handleEdit/confirmDelete. Sin riesgo de romper otra cosa.

**Referencia oficial**: https://nextjs.org/docs/14/app/building-your-application/routing/error-handling

<details><summary>Verificación adversarial</summary>

Confirmado. contacts/page.tsx tiene 14 `throw new Error` con mensajes operador-facing dentro de server actions (líneas 153, 165, 211, 235, 259-260, 338, 344, 414, 441, 460, 468, 515, 524), incluido el guard Wompi cuyo comentario en contacts-manager.tsx:387-391 asume que e.message llega al operador. Next.js 14 en producción enmascara el message de un Error no controlado lanzado en Server Action (lo reemplaza por texto genérico + digest, protección anti-leak documentada) → (a) confirmDelete (líneas 382-394) muestra alert genérico en vez de la instrucción del link Wompi; (b) handleAdd (335-344) y handleEdit (353-357) NO tienen try/catch → un 409 por teléfono duplicado rechaza la promesa dentro  […]

</details>

---

### F62 · 🟠 HIGH — Estado de orden 'pending_payment' existe en el backend (7 estados) pero falta en las 5 copias TypeScript del enum: el operador no puede filtrar ni avanzar esos pedidos

**Ubicación**: `apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:45` · **Detectado por**: cross-service-dup · 🆕 nuevo

**Causa**: El contrato de estados de orden está duplicado en 5 archivos TS y todos omiten 'pending_payment', que es el estado con el que el backend crea toda orden bot con link Wompi (services/api/routers/orders.py:185 `"pending_payment" if order.payment_link else "pending"`). La API además permite explícitamente la transición manual pending_payment→confirmed (orders.py:371) y la cancelación, pero en la UI: STATUS_NEXT (línea 54) no tiene entrada para pending_payment → `nextStatus` es undefined → el botón 'Avanzar' no se renderiza (línea 412 `{canWrite && nextStatus && ...}`); TAB_FILTERS (línea 86) no lo incluye → esos pedidos solo aparecen en 'Todas'; STATUS_LABELS/STATUS_COLORS caen al fallback y muestran el string crudo 'pending_payment' sin traducir (línea 360 `{STATUS_LABELS[o.status] ?? o.status}`). Mismo hueco en apps/web/app/dashboard/inbox/_lib/constants.ts:17-33, dashboard-client.tsx:55-71, (analytics)/metrics/metrics-charts.tsx:13-20 y (analytics)/metrics/page.tsx:20-27. La DB no protege nada: 'orders.status es TEXT sin CHECK constraint en la tabla base' (supabase/migrations/20260424200000_wompi_payments_phase_c.sql:10).

**Evidencia (código real)**:
```
services/api/routers/orders.py:48 `VALID_STATUSES = {"pending", "pending_payment", "confirmed", "processing", "shipped", "delivered", "cancelled"}` — vs — orders-manager.tsx:45-52 `const STATUS_LABELS: Record<string, string> = {\n  pending:    'Pendiente',\n  confirmed:  'Confirmado',\n  processing: 'En proceso',\n  shipped:    'Enviado',\n  delivered:  'Entregado',\n  cancelled:  'Cancelado',\n}` y :54-59 `const STATUS_NEXT: Record<string, string> = { pending: 'confirmed', confirmed: 'processing', processing: 'shipped', shipped: 'delivered' }`
```

**Corrección propuesta**:
```
Consolidar en un módulo único y agregar el estado faltante. Crear apps/web/lib/order-status.ts:
```ts
// Espejo de services/api/routers/orders.py VALID_STATUSES + _ORDER_STATUS_RANK.
export const ORDER_STATUS_LABELS: Record<string, string> = {
  pending:         'Pendiente',
  pending_payment: 'Esperando pago',
  confirmed:       'Confirmado',
  processing:      'En proceso',
  shipped:         'Enviado',
  delivered:       'Entregado',
  cancelled:       'Cancelado',
}
export const ORDER_STATUS_NEXT: Record<string, string> = {
  pending: 'confirmed', pending_payment: 'confirmed',
  confirmed: 'processing', processing: 'shipped', shipped: 'delivered',
}
```
Importarlo en los 5 archivos (orders-manager.tsx, inbox/_lib/constants.ts, dashboard-client.tsx, metrics-charts.tsx, metrics/page.tsx) eliminando las copias locales, y agregar 'pending_payment' a TAB_FILTERS. Complemento DB (patrón de 20260624010000_claims_status_check.sql):
```sql
ALTER TABLE public.orders ADD CONSTRAINT orders_status_check
  CHECK (status IN ('pending','pending_payment','confirmed','processing','shipped','delivered','cancelled')) NOT VALID;
```
```

**Notas del verificador sobre el fix**: Consolidación correcta; pending_payment→confirmed coincide con orders.py:371. El CHECK NOT VALID es seguro: verifiqué TODOS los writers de orders.status (orders.py, wompi_webhook, meli_webhook MELI_*_STATUS_MAP, cart_tool, order_cancellation, worker, orchestrator) y todos mapean a los 7 valores. Faltas menores del fix: agregar también entradas a STATUS_COLORS (fallback no verificado) y a los COLORS de dashboard-client/metrics; STATUS_ICONS ya tiene fallback `?? LayoutList` (línea 295).

<details><summary>Verificación adversarial</summary>

Confirmado en las 5 copias. Backend: orders.py:48 VALID_STATUSES incluye pending_payment, :185 crea toda orden bot con payment_link en pending_payment, :371 permite manual pending_payment→confirmed, _ORDER_STATUS_RANK:56-57 lo rankea. UI: orders-manager.tsx:45-52/54-59/61-68/86 lo omiten → nextStatus undefined → línea 412 no renderiza ActionButton (ni Avanzar ni Cancelar, que además exige originalStatus==='pending' en línea 182); línea 360 muestra el string crudo; TAB_FILTERS sin entrada. El fetch de orders/page.tsx:43-47 NO filtra status → esas órdenes SÍ llegan a la UI. inbox/_lib/constants.ts, dashboard-client.tsx:55-71, metrics-charts.tsx:13-20 y metrics/page.tsx:12-27 igual. DB sin CHEC […]

</details>

---

### F139 · 🟠 HIGH — Cambio/cancelación de estado de pedido falla en silencio: fetch sin check de res.ok, catch vacío y action Promise<void> sin feedback al usuario

**Ubicación**: `apps/web/app/dashboard/(sales)/orders/page.tsx:109` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: updateOrderStatus hace PATCH al API sin comprobar `res.ok` y envuelve todo en `catch { /* non-fatal */ }`; además retorna void. En el cliente, ActionButton (orders-manager.tsx:154-170) solo hace `await updateStatusAction(fd)` sin estado de error. Si el API responde 400/403/409 (transición inválida, RBAC) o hay timeout (AbortController 15s), el spinner termina, revalidatePath repinta el mismo estado y el operador no recibe NINGÚN mensaje — incluye 'Cancelar pedido', que además se ejecuta a un click sin confirmación.

**Evidencia (código real)**:
```
orders/page.tsx:102-109 `await fetch(`${CORE_API_URL}/api/v1/orders/${orderId}`, { method: 'PATCH', … })` sin leer res.ok, seguido de `} catch { /* non-fatal */ }`; orders-manager.tsx:36 `updateStatusAction: (fd: FormData) => Promise<void>` y l.155-159 `startTransition(async () => { …; await updateStatusAction(fd) })` sin manejo de error.
```

**Corrección propuesta**:
```
Devolver resultado tipado y mostrarlo en ActionButton:

```ts
// page.tsx
async function updateOrderStatus(formData: FormData): Promise<{ ok: boolean; error?: string }> {
  'use server'
  // …auth igual…
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/orders/${orderId}`, { /* … */ })
    clearTimeout(timeout)
    if (!res.ok) {
      const detail = await res.text()
      return { ok: false, error: detail.slice(0, 200) || `Error HTTP ${res.status}` }
    }
  } catch {
    return { ok: false, error: 'Timeout o error de red — reintenta.' }
  }
  revalidatePath('/dashboard/orders')
  return { ok: true }
}

// orders-manager.tsx (ActionButton)
const [error, setError] = useState<string | null>(null)
const handleNext = () => startTransition(async () => {
  setError(null)
  const r = await updateStatusAction(fd)
  if (!r.ok) setError(r.error ?? 'No se pudo actualizar')
})
// …render: {error && <p className="text-xs text-red-700">{error}</p>}
```
```

**Notas del verificador sobre el fix**: Correcto y con precedente en el mismo archivo (patrón generateShippingGuide). Completar: (1) actualizar el tipo Props `updateStatusAction` en orders-manager.tsx:36 a `Promise<{ok: boolean; error?: string}>`; (2) considerar llamar revalidatePath también en fallo — un 409 suele significar UI stale y refrescar muestra el estado real; (3) cubrir también los returns silenciosos de auth/token (l.86,94) con `{ok:false}`.

<details><summary>Verificación adversarial</summary>

Confirmado en orders/page.tsx:102-109: `await fetch(...PATCH...)` sin leer `res.ok` + `catch { /* non-fatal */ }` + retorno void, y guards tempranos (l.86,94) que también retornan void silencioso. En orders-manager.tsx:36 el tipo es `Promise<void>` y ActionButton (l.154-170) solo hace `await updateStatusAction(fd)` sin estado de error. El escenario de fallo es alcanzable: services/api/routers/orders.py:354-358 devuelve 409 explícito por transición inválida (UI stale / dos operadores), 404, 422 y 500 — todos tragados. El contraste dentro del MISMO archivo lo prueba: generateShippingGuide (page.tsx:117-179) sí retorna `{ok, message}` y GenerateGuideButton sí lo renderiza. 'Cancelar pedido' (so […]

</details>

---

### F104 · 🟠 HIGH — El botón 'Desconectar' de MercadoLibre usa un server action que NO revoca el token ni borra los secretos de Vault; el endpoint completo DELETE /api/v1/integrations/meli queda muerto

**Ubicación**: `apps/web/app/dashboard/(settings-group)/integrations/page.tsx:88` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: Doble implementación del disconnect MeLi: el backend tiene DELETE /api/v1/integrations/meli (services/api/routers/integrations.py:321) que revoca el token en MeLi, elimina access_token_secret_id y refresh_token_secret_id de Vault y persiste meta.last_disconnected_user_id (feature rev. 108). Pero la UI cablea el server action disconnectMeli (page.tsx:88-97) que solo hace update de tenant_integrations con credentials={} y meta={}. Ningún código llama al endpoint (grep de 'integrations/meli' en apps/web solo encuentra auth-url). Resultado: tokens OAuth quedan vivos y huérfanos en Vault (el puntero secret_id se pierde al vaciar credentials), MeLi sigue enviando webhooks al tenant 'desconectado', y la detección same-user de reconexión se rompe al borrar meta.

**Evidencia (código real)**:
```
page.tsx:94: await sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {}, meta: {} }) — vs integrations.py:355-356: vault.delete_secret(creds.get("access_token_secret_id")); vault.delete_secret(creds.get("refresh_token_secret_id")) y :350 await meli_client.revoke_token(access_token)
```

**Corrección propuesta**:
```
Reemplazar el body del server action por una llamada al endpoint existente (mismo patrón que claims/actions.ts):

async function disconnectMeli() {
  'use server'
  const sb = createClient()
  const { data: { session } } = await sb.auth.getSession()
  if (!session) return
  const res = await fetch(`${CORE_API_URL}/api/v1/integrations/meli`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${session.access_token}` },
  })
  if (!res.ok && res.status !== 204) {
    console.error('[disconnectMeli] core API', res.status)
    redirect(`/dashboard/integrations?error=${encodeURIComponent('No se pudo desconectar MeLi')}`)
  }
  revalidatePath('/dashboard/integrations')
}
```

**Notas del verificador sobre el fix**: Dirección correcta (mismo patrón fetch a core API que orders/page.tsx y claims). Ajustes: (1) importar CORE_API_URL desde '@/lib/runtime-env' (page.tsx no lo importa hoy); (2) 204 ya cumple res.ok, el `&& res.status !== 204` es redundante; (3) conservar el guard de rol owner client-side para UX (el backend igual devuelve 403); (4) considerar AbortController con timeout como los demás server actions del repo.

<details><summary>Verificación adversarial</summary>

Confirmado: page.tsx:88-97 disconnectMeli solo hace update({status:'disconnected',credentials:{},meta:{}}) contra tenant_integrations. El backend DELETE /api/v1/integrations/meli (services/api/routers/integrations.py:321-379) revoca token (meli_client.revoke_token, meli_client.py:213), borra access_token_secret_id y refresh_token_secret_id de Vault y persiste meta.last_disconnected_user_id (rev.108 Layer C). Grep en apps/web: ningún caller del DELETE (solo auth-url en integrations-manager.tsx:165 y app/api/integrations/meli/auth-url/route.ts). El botón de la card usa el server action (integrations-manager.tsx:640). Los tokens MeLi se guardan como secret_ids en credentials (integrations.py:29 […]

</details>

---

### F93 · 🟠 HIGH — El dashboard muestra a los tenants URLs de webhook ERRÓNEAS para Wompi y Telegram — los eventos de pago registrados según la UI caerían en 404

**Ubicación**: `apps/web/app/dashboard/(settings-group)/integrations/wompi/_components/wompi-setup.tsx:97` · **Detectado por**: config-secrets · 🆕 nuevo

**Causa**: La ruta real del webhook Wompi es POST /api/v1/webhooks/wompi (main.py:173 `prefix="/api/v1/webhooks"` + wompi_webhook.py:39 `@router.post("/wompi")`, confirmado por .env.example:116), pero la UI instruye configurar en el panel Wompi `https://api.konvi.co/api/v1/wompi/webhook` (segmentos invertidos). Un tenant que siga la instrucción registra una URL 404: los transaction.updated nunca llegan, los pagos APPROVED no se confirman y las órdenes pending_payment se quedan colgadas (impacto dinero, mitigado solo por el poll de reconciliación). Mismo patrón en telegram-setup.tsx:71: muestra `/api/v1/telegram/webhook` cuando la ruta real es `/api/v1/integrations/telegram/webhook` (main.py:177 + telegram_webhook.py:40). meli-setup.tsx:80 sí es correcta.

**Evidencia (código real)**:
```
wompi-setup.tsx:97: `https://api.konvi.co/api/v1/wompi/webhook` — vs ruta real montada: main.py:173 `app.include_router(wompi_webhook.router, prefix="/api/v1/webhooks")` + wompi_webhook.py:39 `@router.post("/wompi")` y .env.example:116 "Producción: https://commerce-ops-api.onrender.com/api/v1/webhooks/wompi"
```

**Corrección propuesta**:
```
```tsx
// wompi-setup.tsx:97
-            https://api.konvi.co/api/v1/wompi/webhook
+            https://api.konvi.co/api/v1/webhooks/wompi
```
```tsx
// telegram-setup.tsx:71
-            https://api.konvi.co/api/v1/telegram/webhook
+            https://api.konvi.co/api/v1/integrations/telegram/webhook
```
Opcional: derivar estas URLs de una constante compartida (p.ej. lib/webhook-urls.ts) para que UI y backend no diverjan.
```

**Notas del verificador sobre el fix**: Los dos reemplazos de string son correctos respecto a las rutas reales montadas. Incompleto en un detalle: queda la discrepancia de HOST (wompi-setup muestra api.konvi.co, integrations-manager muestra konvi-api.onrender.com) — confirmar cuál es el host público canónico del API y unificar. La sugerencia de constante compartida (lib/webhook-urls.ts) es la solución estructural correcta.

<details><summary>Verificación adversarial</summary>

Divergencia confirmada: ruta real Wompi = POST /api/v1/webhooks/wompi (main.py:173 prefix '/api/v1/webhooks' + wompi_webhook.py:39 @router.post('/wompi'); .env.example:115-116 lo corrobora) vs UI wompi-setup.tsx:97 'https://api.konvi.co/api/v1/wompi/webhook' (segmentos invertidos → 404). Telegram: ruta real /api/v1/integrations/telegram/webhook (main.py:177 + telegram_webhook.py:40, docstring del router líneas 15-17 con el curl setWebhook correcto) vs UI telegram-setup.tsx:71 '/api/v1/telegram/webhook'. MeLi correcto como afirma el hallazgo. PERO hay mitigante que rebaja la severidad de high a medium: el flujo de conexión (integrations-manager.tsx:773) muestra la URL Wompi CORRECTA ('https:/ […]

</details>

---

### F128 · 🟠 HIGH — Analítica Financiera carga TODAS las órdenes históricas con order_items anidados y todos los expenses sin límite ni ventana temporal — unit economics erróneos al superar 1000 filas

**Ubicación**: `apps/web/app/dashboard/finance/page.tsx:27` · **Detectado por**: performance · 📌 ya rastreado (audit finiquito §7 Finanzas y Analítica — gap técnico 'Arquitectura ad-hoc: cada page hace 5-7 queries directas a tablas operativas en cada render... lectura masiva, sin materialized views ni snapshot' + estado real (filtro client-side sobre fetch completo) + Plan Fase B item B6 'Finanzas... + paginación')

**Causa**: Sin `.limit()`, sin `.gte(created_at)` y sin paginación: las dos queries traen la tabla completa de orders (con items anidados) y expenses en cada visita a /dashboard/finance, y todo se pasa como props a un Client Component. Con el cap PostgREST de 1000 filas, en cuanto el tenant supera 1000 órdenes los números financieros (ingresos, COGS, márgenes) se calculan sobre un subconjunto arbitrario sin ningún aviso — cifras de dinero incorrectas mostradas como ciertas. Antes de eso, el payload crece linealmente (1000 órdenes × ~3 items ≈ 4000 filas serializadas al cliente por visita).

**Evidencia (código real)**:
```
const { data: oRes } = await supabase
    .from('orders')
    .select('id, status, total_amount, created_at, order_items(quantity, unit_cost, unit_price)')
    .eq('tenant_id', meta.tenant_id)
```

**Corrección propuesta**:
```
Acotar por ventana temporal explícita (con selector de período como en Métricas) y ordenar, dejando la agregación histórica a un RPC SQL:
```ts
const since = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString()
const { data: oRes } = await supabase
  .from('orders')
  .select('id, status, total_amount, created_at, order_items(quantity, unit_cost, unit_price)')
  .eq('tenant_id', meta.tenant_id)
  .gte('created_at', since)
  .order('created_at', { ascending: false })
  .limit(1000)
```
y mover los totales de todo-el-tiempo a una función SQL `finance_summary(p_tenant, p_since)` con SUM/GROUP BY (mismo patrón que metrics_top_products).
```

**Notas del verificador sobre el fix**: Técnicamente correcto pero cambia semántica de producto: hoy la página es P&L de todo-el-tiempo; acotar a 90 días requiere decisión founder (memoria feedback_phase_handoff_pattern) + selector de período + RPC finance_summary para totales históricos (migración nueva). Aplicar la misma ventana/límite a expenses y reemplazar select('*') por columnas explícitas.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/configuration.html#db-max-rows

<details><summary>Verificación adversarial</summary>

Confirmado en finance/page.tsx:25-39: orders con order_items anidados sin .limit()/.gte()/.order() (:25-28) y expenses select('*') sin límite (:33-37); todo se pasa como props a FinanceDashboard (Client Component, :52-55), serializado al browser en cada visita. Con max_rows=1000, pasado ese umbral el P&L (ingresos, COGS vía unit_cost, márgenes) se calcula sobre un subconjunto arbitrario sin aviso. Es la única página financiera y no hay RPC/vista agregada de respaldo en migraciones.

</details>

---

### F126 · 🟠 HIGH — El Inbox descarga el historial COMPLETO de mensajes de las 50 conversaciones cada 20 segundos solo para mostrar el preview del último mensaje

**Ubicación**: `apps/web/app/dashboard/inbox/_hooks/use-conversations.ts:103` · **Detectado por**: performance · 🆕 nuevo

**Causa**: El embed PostgREST `messages(content, direction, created_at)` no tiene límite en la tabla referenciada, por lo que devuelve TODAS las filas de messages de cada conversación; el hook luego solo usa `msgs.sort(...)[0]` (el último mensaje). Además `loadConversations()` se re-ejecuta en un `setInterval` de 20000 ms (línea 241-243) y en cada INSERT Realtime de conversations. Con 50 convs × 200 mensajes promedio ≈ 10.000 filas con `content` (~2-4 MB) transferidas 3 veces por minuto por cada pestaña de Inbox abierta, y Postgres ejecuta la agregación lateral completa en cada poll. El costo crece linealmente con el historial (messages nunca se poda).

**Evidencia (código real)**:
```
.select('id, customer_phone, status, agentic_state, created_at, last_interaction_at, archived_at, messages(content, direction, created_at)') ... .limit(50)  // y más abajo: const pollInterval = setInterval(() => { loadConversations() }, 20000)
```

**Corrección propuesta**:
```
Limitar el embed a 1 fila ordenada desc (supabase-js ^2.101.1 soporta `referencedTable`):
```ts
let query = supabase
  .from('conversations')
  .select('id, customer_phone, status, agentic_state, created_at, last_interaction_at, archived_at, messages(content, direction, created_at)')
  .order('last_interaction_at', { ascending: false })
  .order('created_at', { referencedTable: 'messages', ascending: false })
  .limit(1, { referencedTable: 'messages' })
  .limit(50)
```
y simplificar el mapeo: `last_message: msgs?.[0] ?? null` (eliminar el `.sort()` en JS).
```

**Notas del verificador sobre el fix**: Correcto: `.order('created_at',{referencedTable:'messages',ascending:false}).limit(1,{referencedTable:'messages'})` es API soportada en supabase-js 2.101. Simplificar a msgs?.[0] elimina el sort JS. No rompe el resto del hook (conversation_reads y Realtime no dependen del embed).

**Referencia oficial**: https://supabase.com/docs/reference/javascript/limit

<details><summary>Verificación adversarial</summary>

Confirmado: use-conversations.ts:101-105 embebe messages(content,direction,created_at) sin limit en la tabla referenciada, y :122-131 solo usa msgs.sort(...)[0]. El poll de 20s existe (:241-243) y además loadConversations() se re-dispara en cada INSERT Realtime de conversations (:217). No hay guard server-side: PostgREST max_rows (config.toml:18 = 1000) limita el nivel superior, no acota el embed a lo necesario — cada conversación arrastra su historial completo de content por poll. supabase-js ^2.101.1 (package.json) soporta limit/order con referencedTable, así que el problema no es limitación de la lib sino del query.

</details>

---

### F69 · 🟠 HIGH — Polling fallback de useMessages descarta el historial paginado cada 5s: reemplaza el estado con los últimos 100 mensajes aunque el operador haya cargado más con loadMore

**Ubicación**: `apps/web/app/dashboard/inbox/_hooks/use-messages.ts:143` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: El fallback se activa cuando `Date.now() - lastRealtimeAt.current > 8000`, pero `lastRealtimeAt` solo se actualiza cuando llega un evento postgres_changes — y Realtime solo emite cuando los datos CAMBIAN. En una conversación sin mensajes nuevos (el caso normal mientras el operador lee historial), 'sin eventos' es indistinguible de 'canal caído', así que el poll corre cada 5s siempre (además `lastRealtimeAt` inicia en 0 → el primer tick siempre dispara). Ese poll hace `setMessages(((data||[]) as Message[]).reverse())` con `.limit(PAGE_INITIAL)` = 100, reemplazando el array completo: los mensajes históricos cargados vía `loadMore` (líneas 167-202) desaparecen y el scroll salta, a los pocos segundos de haberlos cargado.

**Evidencia (código real)**:
```
use-messages.ts:144-156: `const sinceLastEvent = Date.now() - lastRealtimeAt.current\n      if (sinceLastEvent > POLLING_FALLBACK_THRESHOLD_MS) {\n        supabase ... .limit(PAGE_INITIAL)\n          .then(({ data, error: qErr }) => {\n            if (qErr) return\n            setMessages(((data || []) as Message[]).reverse())`
```

**Corrección propuesta**:
```
Merge en lugar de replace — preservar los mensajes ya cargados anteriores a la ventana del poll:
```ts
.then(({ data, error: qErr }) => {
  if (qErr) return
  const fetched = ((data || []) as Message[]).reverse()
  setMessages(prev => {
    if (prev.length === 0 || fetched.length === 0) return fetched
    const ids = new Set(fetched.map(m => m.id))
    const cutoff = fetched[0].created_at
    const olderLoaded = prev.filter(m => !ids.has(m.id) && m.created_at < cutoff)
    return [...olderLoaded, ...fetched]
  })
})
```
Opcional: además, solo activar el fallback si el canal reportó problema real: `let healthy = true` en `.subscribe(status => { healthy = status === 'SUBSCRIBED' })` y `if (healthy) return` en el interval.
```

**Notas del verificador sobre el fix**: El merge propuesto es correcto: preserva mensajes anteriores al cutoff no incluidos en fetched; la comparación de ISO strings de PostgREST es válida. Edge case aceptable: si fetched llega vacío retorna [] (solo posible si la conversación realmente no tiene mensajes). No regresa el comportamiento de mensajes optimistas (el replace actual ya los perdía igual). El gate opcional por status del canal es un buen complemento pero conviene mantener el poll como fallback real si el status nunca llega a SUBSCRIBED.

**Referencia oficial**: https://supabase.com/docs/guides/realtime/postgres-changes

<details><summary>Verificación adversarial</summary>

Confirmado en use-messages.ts:142-158. lastRealtimeAt.current solo se actualiza al recibir postgres_changes (línea 119) e inicia en 0 → en conversación sin tráfico nuevo (caso normal al revisar historial) sinceLastEvent siempre > 8000 y el poll corre cada 5s haciendo `setMessages(((data||[]) as Message[]).reverse())` con limit(PAGE_INITIAL)=100 — replace total del array. loadMore (167-202) hace prepend de mensajes históricos que el siguiente tick del poll descarta (≤5s después), con salto de scroll. Ninguna defensa: el subscribe callback (136-140) solo loguea, no gatea el interval; el dedupe A6 aplica solo al path realtime. Escenario alcanzable: operador abre conversación >100 mensajes, scro […]

</details>

---

### F140 · 🟠 HIGH — SubmitButton muestra 'Guardado ✓' aunque la mutación haya fallado — y las actions que lo usan (settings, purchases, team) tragan los errores del backend

**Ubicación**: `apps/web/components/ui/submit-button.tsx:31` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: SubmitButton infiere éxito de la transición pending→false de useFormStatus, sin señal real del resultado. Las actions que lo consumen nunca propagan fallos: settings/actions.ts:26-29 `updateTenant` hace `await sb.from('tenants').update(data).eq('id', tenantId)` sin destructurar `error` (supabase-js NO lanza excepción, retorna { error }); purchases/actions.ts:45,70,76,82 hace `if (!res.ok) console.error(…)` y sigue con revalidatePath. Resultado: si el UPDATE es bloqueado (RLS, constraint) o el API devuelve 4xx/5xx (p.ej. receivePurchaseOrder, que ajusta inventario), el usuario ve 'Guardado ✓' y cree que persistió.

**Evidencia (código real)**:
```
submit-button.tsx:29-34 `useEffect(() => { if (prevPending.current && !pending) { setSaved(true) … } })` — éxito inferido solo del fin del pending; settings/actions.ts:26-29 `async function updateTenant(…) { const sb = createClient(); await sb.from('tenants').update(data).eq('id', tenantId) }` sin check de error; purchases/actions.ts:82 `if (!res.ok) console.error('receivePurchaseOrder failed:', await res.text())` seguido de revalidatePath incondicional.
```

**Corrección propuesta**:
```
1) Verificar error en el helper:
```ts
async function updateTenant(tenantId: string, data: Record<string, unknown>) {
  const sb = createClient()
  const { error } = await sb.from('tenants').update(data).eq('id', tenantId)
  if (error) throw new Error(`No se pudo guardar: ${error.message}`)
}
```
(y en purchases: `if (!res.ok) throw new Error((await res.text()).slice(0,200))`).
2) Migrar los forms a `useFormState`/`useActionState` con resultado `{ ok, error }` para que SubmitButton reciba el resultado real:
```ts
interface Props { …; result?: { ok: boolean; error?: string } | null }
// solo setSaved(true) si result?.ok === true; si result?.error, render banner rojo
```
```

**Notas del verificador sobre el fix**: Dirección correcta pero el paso 1 solo (throw en server action) es insuficiente en producción: Next.js REDACTA los mensajes de errores lanzados en server actions en prod (el usuario vería el error.tsx genérico con digest, no el mensaje). El paso 2 (resultado tipado `{ok,error}` vía useActionState) es la parte load-bearing y debe ser el patrón principal. Alcance real: ~30 usos de SubmitButton en 10+ archivos (integrations-manager, catalog, knowledge-base, finance, team) — migración amplia; hacer el prop `result` opcional para migrar incremental es acertado.

**Referencia oficial**: https://supabase.com/docs/reference/javascript/update

<details><summary>Verificación adversarial</summary>

Confirmado en las tres capas: submit-button.tsx:29-37 infiere éxito solo de pending→false (useFormStatus no distingue éxito/fallo); settings/actions.ts:26-29 `updateTenant` no destructura `{error}` (supabase-js v2 no lanza, retorna error en el objeto) y saveTenant/saveFilosofia/saveHorarioAsesor/savePresenciaDigital/saveShippingOrigin lo usan; purchases/actions.ts:45,70,76,82 hace `console.error` y sigue con revalidatePath (receivePurchaseOrder ajusta inventario — mostrar 'Recibida ✓' en fallo es grave); team/page.tsx:177-204,351 igual (console.error, el usuario ve '¡Invitación enviada!'). settings/page.tsx:153,229,325 usa `<form action={...}>` plano sin useFormState. El contraejemplo savePa […]

</details>

---

### F83 · 🟠 HIGH — Bypass total del enforcement MFA: la cookie mfa_recovery_session es un literal '1' sin firma que cualquier cliente puede fabricar

**Ubicación**: `apps/web/middleware.ts:80` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: El middleware acepta como bypass AAL2 la mera presencia de la cookie con valor '1'. La cookie la setea /api/mfa/recovery-codes/verify (route.ts:65-73) con `value: '1'` — el comentario del route dice 'Cookie firmada' pero NO hay firma. HttpOnly/Secure/SameSite solo protegen contra XSS/terceros; un atacante que controla su propio cliente (con la contraseña robada de la víctima, sesión AAL1) simplemente añade `Cookie: mfa_recovery_session=1` a sus requests y el middleware omite el check de AAL2, anulando el TOTP — exactamente el escenario contra el que MFA defiende.

**Evidencia (código real)**:
```
const recoveryBypass = request.cookies.get('mfa_recovery_session')?.value === '1'
    if (!recoveryBypass) {  // middleware.ts:80-81
...
// app/api/mfa/recovery-codes/verify/route.ts:65-68
response.cookies.set({
        name: RECOVERY_SESSION_COOKIE,
        value: '1',
        httpOnly: true,
```

**Corrección propuesta**:
```
Firmar la cookie con HMAC ligado al user id + expiry y verificarla en el middleware (Web Crypto funciona en Edge). En verify/route.ts tras `upstream.ok && data.ok` (obtener userId con `sb.auth.getUser()`):

```ts
const exp = Math.floor(Date.now() / 1000) + RECOVERY_SESSION_MAX_AGE_SECONDS
const payload = `${user.id}:${exp}`
const key = await crypto.subtle.importKey('raw',
  new TextEncoder().encode(process.env.MFA_RECOVERY_COOKIE_SECRET!),
  { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
const sigBuf = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload))
const sig = Buffer.from(sigBuf).toString('base64url')
response.cookies.set({ name: RECOVERY_SESSION_COOKIE, value: `${payload}:${sig}`, httpOnly: true, ... })
```

En middleware.ts, reemplazar la comparación `=== '1'` por: parsear `userId:exp:sig`, recomputar el HMAC con el mismo secreto, y exigir `sig` válida + `userId === user.id` + `exp > now`. INTERVENCION HUMANA REQUERIDA: provisionar env `MFA_RECOVERY_COOKIE_SECRET` en Render (web).
```

**Notas del verificador sobre el fix**: Firmar la cookie con HMAC ligado a user.id+exp y verificar en middleware (Web Crypto funciona en Edge) es la solución correcta. Requiere provisionar MFA_RECOVERY_COOKIE_SECRET (marcado como intervención humana — correcto). Incompleto en un detalle: layout.tsx:61 y settings/security/page.tsx:87 comparan `=== '1'` para mostrar banner de recovery; al cambiar el formato del valor esos checks dejarían de detectar la sesión recovery (banner no aparece). No es regresión de seguridad, pero deben actualizarse a parsear/verificar el nuevo formato para no perder el banner.

<details><summary>Verificación adversarial</summary>

Confirmado. middleware.ts:80 `request.cookies.get('mfa_recovery_session')?.value === '1'` acepta el valor CONSTANTE '1' como bypass AAL2. verify/route.ts:65-73 setea exactamente `value:'1'` (el comentario del route dice 'Cookie firmada' pero NO hay HMAC/firma). HttpOnly/Secure/SameSite protegen contra XSS y lectura por terceros, pero NO contra un atacante que fabrica su propia request: con la contraseña robada obtiene sesión AAL1 válida y añade `Cookie: mfa_recovery_session=1`; el middleware omite `getAuthenticatorAssuranceLevel()` y concede /dashboard sin TOTP. Bypass total del enforcement MFA — exactamente el ataque contra el que MFA defiende. Escenario runtime alcanzable (login password + […]

</details>

---

### F89 · 🟡 MEDIUM — Open redirect en /auth/confirm: el parámetro next se usa sin validar y new URL(next, origin) acepta URLs absolutas externas

**Ubicación**: `apps/web/app/auth/confirm/route.ts:56` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: `new URL(next, origin)` con next absoluto ('https://evil.com') o protocol-relative ('//evil.com') ignora el base origin y resuelve al host externo. Un atacante envía a la víctima un link legítimo de konvi `/auth/confirm?token_hash=...&type=recovery&next=//evil.com/login`; tras verificar el OTP real (sesión recién creada), la víctima aterriza en un clon del login/set-password del atacante — vector de phishing de credenciales post-verificación, especialmente en el flujo de recovery de contraseña.

**Evidencia (código real)**:
```
const next      = searchParams.get('next') ?? '/dashboard'
...
  if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code)
    if (!error) {
      return NextResponse.redirect(new URL(next, origin))
    }
```

**Corrección propuesta**:
```
Aceptar solo paths internos:

```ts
const rawNext = searchParams.get('next') ?? '/dashboard'
// Solo paths relativos internos: debe empezar con '/' y no con '//' ni '/\\'
const next = rawNext.startsWith('/') && !rawNext.startsWith('//') && !rawNext.startsWith('/\\')
  ? rawNext
  : '/dashboard'
```

y usar `next` saneado en los tres NextResponse.redirect del handler (líneas 56, 65). Aplicar la misma validación al `?next=` de /auth/callback si lee el parámetro.
```

**Notas del verificador sobre el fix**: Correcto y completo: sanitizar a path interno (startsWith('/') && !startsWith('//') && !startsWith('/\\')) cubre absolute, protocol-relative y backslash-bypass. Aplicar en las 2 líneas que usan next (56, 65; los redirects de error usan strings fijos) y también en /auth/callback/page.tsx:26 como indica el fix. No rompe los flujos legítimos existentes (next=/set-password es path relativo).

<details><summary>Verificación adversarial</summary>

Confirmado en apps/web/app/auth/confirm/route.ts:31,56,65: `next = searchParams.get('next') ?? '/dashboard'` se usa sin validación en `new URL(next, origin)`, que con input absoluto ('https://evil.com') o protocol-relative ('//evil.com') ignora el base y resuelve al host externo. No existe defensa en ninguna capa: el middleware excluye auth/confirm de su matcher (middleware.ts:107), no hay allowlist ni tests (grep de startsWith('/')/open redirect en apps/web = 0 hits). El mismo patrón sin sanitizar existe en /auth/callback/page.tsx:26,45 (router.replace(next)). El vector es alcanzable: forgot-password-form.tsx:30 y team/page.tsx:166,345 generan links con ?next=, y un atacante puede iniciar r […]

</details>

---

### F78 · 🟡 MEDIUM — Duplicación del generador de matriz de variantes: catalog-form.tsx re-implementa inline (cartesian + builder de atributos + preview) lo que ya existe como VariantMatrixGenerator en variant-matrix.tsx (~60% de solape)

**Ubicación**: `apps/web/app/dashboard/(products)/catalog/_components/catalog-form.tsx:35` · **Detectado por**: frontend-components · 📌 ya rastreado (audit finiquito §2 Productos — gap técnico 'VariantMatrixGenerator y InlineMatrixBuilder (catalog-form.tsx) duplican el cartesian product builder + suggestPrefix logic. Misma feature, dos implementaciones') · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: catalog-form.tsx (crear producto) define `InlineMatrixBuilder` con su propia `cartesian()` (línea 35), el estado defs/addDef/updateName/addValue/updateValue/removeValue, bulkPrice/bulkStock y preview — el mismo flujo 'atributos → producto cartesiano → preview → generar variantes' que variant-matrix.tsx:21+ (`VariantMatrixGenerator`, 232 líneas) ya implementa y que product-edit-drawer.tsx importa. Solape funcional ~60-70%; solo difiere en que el inline trabaja sin product_id (drafts locales). Igual patrón menor: `fmtAttrs`/`fmtPrice` copiados entre catalog-table.tsx:37-49 y product-edit-drawer.tsx:25-32. Bugs de UX de la matriz (p.ej. trims, dedupe de combos) deben arreglarse dos veces.

**Evidencia (código real)**:
```
catalog-form.tsx:35: `function cartesian(defs: { name: string; values: string[] }[]): Record<string, string>[] {` vs variant-matrix.tsx:21: `function cartesian(defs: AttrDef[]): Record<string, string>[] {` — ambos con la misma reducción flatMap y el mismo trío addValue/updateValue/removeValue
```

**Corrección propuesta**:
```
Parametrizar VariantMatrixGenerator para operar sin product_id, entregando los combos por callback en lugar de submit directo:
```tsx
// variant-matrix.tsx
interface Props {
  productTitle: string
  attrSuggestions?: { names: string[]; values: string[] }
  onGenerate: (combos: Record<string, string>[], opts: { skuPrefix: string; bulkPrice: number; bulkStock: number }) => void
  onClose: () => void
}
```
En catalog-form.tsx, reemplazar InlineMatrixBuilder por `<VariantMatrixGenerator onGenerate={(combos, o) => setVariants(combos.map(c => ({ ...DEFAULT_VARIANT, attrs: Object.entries(c).map(([key, value]) => ({ key, value })), price: o.bulkPrice, stock: o.bulkStock, sku: buildSku(o.skuPrefix, c) })))} ... />`. Mover fmtAttrs/fmtPrice a `catalog/_lib/format.ts` e importarlos en catalog-table y product-edit-drawer.
```

**Notas del verificador sobre el fix**: La Props propuesta (onGenerate con skuPrefix/bulkPrice/bulkStock) no corresponde al componente real: VariantMatrixGenerator no tiene bulk ni skuPrefix, y adoptarla eliminaría la edición por-fila de precio/stock/sku de la que depende product-edit-drawer, o exige un refactor bimodal mucho mayor al mostrado. Consolidación segura: extraer solo las primitivas compartidas (cartesian + el editor de AttrDefs) a un módulo común y mantener las dos fases de salida; mover fmtAttrs a catalog/_lib/format.ts sí es directo (fmtPrice no, son funciones distintas).

<details><summary>Verificación adversarial</summary>

Confirmado: catalog-form.tsx:35 define cartesian() idéntica en lógica a variant-matrix.tsx:21-28 (misma reducción flatMap), y InlineMatrixBuilder (catalog-form.tsx:53+) replica el trío addValue/updateValue/removeValue (68-71) y el flujo defs→cartesiano→preview que VariantMatrixGenerator (variant-matrix.tsx:40-232) ya implementa y product-edit-drawer.tsx:411 consume. Diferencia real que el hallazgo subestima: el inline usa bulkPrice/bulkStock + attrSuggestions y produce drafts locales; VariantMatrixGenerator NO tiene bulk (edición precio/stock/sku POR FILA, líneas 88-112) y submite per-combo vía server action con product_id. El solape es real (cartesian + editor de atributos ≈ mitad del códig […]

</details>

---

### F143 · 🟡 MEDIUM — Acciones destructivas/irreversibles a un solo click sin confirmación: 'Reembolsar'/'Rechazar' reclamo y 'Cancelar pedido'

**Ubicación**: `apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx:252` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: En claims-manager, los botones Reembolsar (marca el ticket refunded — tras lo cual el header deja de renderizar acciones, l.242: `status !== 'refunded' && status !== 'rejected'`) y Rechazar ejecutan handleUpdateStatus directamente sin diálogo de confirmación; igual 'Cancelar pedido' en orders-manager.tsx:163-170. El resto del producto SÍ confirma acciones menos graves (eliminar una nota de conversación, eliminar un cupón con Dialog, borrar producto con confirm). Un misclick en 'Reembolsar' deja el reclamo en estado terminal money-adjacent sin camino de vuelta en la UI.

**Evidencia (código real)**:
```
claims-manager.tsx:251-254 `<Button size="sm" onClick={() => handleUpdateStatus('refunded')} disabled={isSubmitting} className="bg-emerald-600 …">Reembolsar</Button>` — sin confirm ni Dialog; orders-manager.tsx:163-170 `const handleCancel = () => { startTransition(async () => { … fd.append('cancel', 'true'); await updateStatusAction(fd) }) }` invocado directo desde el botón l.183-191.
```

**Corrección propuesta**:
```
Reusar el patrón Dialog de promotions-manager (setDeleting → Dialog → confirmar):
```tsx
const [confirmAction, setConfirmAction] = useState<'refunded' | 'rejected' | null>(null)
<Button size="sm" onClick={() => setConfirmAction('refunded')} disabled={isSubmitting}
  className="bg-emerald-700 hover:bg-emerald-800 text-white text-xs h-8">Reembolsar</Button>
<Dialog open={!!confirmAction} onOpenChange={() => setConfirmAction(null)}>
  <DialogContent>
    <DialogTitle>{confirmAction === 'refunded' ? '¿Confirmar reembolso?' : '¿Rechazar reclamo?'}</DialogTitle>
    <DialogDescription>Esta acción deja el ticket en estado final y no puede revertirse desde la consola.</DialogDescription>
    <DialogFooter>
      <Button variant="outline" onClick={() => setConfirmAction(null)}>Cancelar</Button>
      <Button onClick={() => { handleUpdateStatus(confirmAction!); setConfirmAction(null) }} disabled={isSubmitting}>Confirmar</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```
Aplicar lo mismo a handleCancel en orders-manager.
```

**Notas del verificador sobre el fix**: Patrón Dialog correcto y ya existente en promotions (setDeleting→Dialog→confirmar). El snippet es válido: handleUpdateStatus captura el valor antes de setConfirmAction(null). Mantener disabled={isSubmitting} en el botón Confirmar. Para orders, aplicar igual a handleCancel (puede ser confirm() nativo como GenerateGuideButton para consistencia mínima). Nota: el mismo tratamiento aplica al Dialog mobile de claims si existe vista responsive de acciones.

<details><summary>Verificación adversarial</summary>

Confirmado: claims-manager.tsx:251-262 'Reembolsar' y 'Rechazar' llaman handleUpdateStatus directo (l.118-131, sin confirm) y l.242 oculta las acciones cuando status∈{refunded,rejected} → terminal en UI (el backend claims.py:191-210 aceptaría revertir vía API pero no hay camino en la consola). orders-manager.tsx:163-170 handleCancel también a un click (solo pending, l.182 — blast radius acotado: aún sin decremento de stock, que ocurre al confirmar). La asimetría con el resto del producto está verificada: conversation-notes.tsx:132 confirm() para borrar una nota, promotions coupons-manager Dialog para eliminar cupón, catalog-table.tsx:269 window.confirm para borrar producto, y GenerateGuideBu […]

</details>

---

### F76 · 🟡 MEDIUM — Contactos: filtro de consent implementado DOS veces (rama server muerta vía searchParams que ninguna UI setea + re-filtro client en memoria) y fetch sin .limit() pese a que el comentario promete 'los primeros 500'

**Ubicación**: `apps/web/app/dashboard/(sales)/contacts/page.tsx:104` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: page.tsx filtra por `searchParams?.consent` en SQL (líneas 104, 119-120) y declara `q?: string` (línea 95, nunca leído), pero ContactsManager ignora la URL: mantiene su propio `consentFilter` useState (contacts-manager.tsx:162) y filtra en memoria — grep de `consent=` en todo apps/web devuelve 0 sitios que construyan ese param. La rama server es código muerto que, si alguien la activa por URL, rompe los contadores del header (consentCount/revokedCount se calculan sobre el subset ya filtrado) y desincroniza los dos filtros. Además el comentario de la línea 127 afirma 'traemos los primeros 500 contactos para que paginen local' pero el query NO tiene `.limit()` (grep 'limit(' en el archivo: 0 hits) — el fetch crece sin techo propio hasta el max-rows de PostgREST, serializando todo el PII del tenant en cada render del RSC.

**Evidencia (código real)**:
```
page.tsx:104: `const consentFilter = searchParams?.consent ?? 'all'` + 127: `// traemos los primeros 500 contactos para que paginen local.` — sin ningún `.limit(` en el archivo, y contacts-manager.tsx:162: `const [consentFilter, setConsentFilter] = useState('all')`
```

**Corrección propuesta**:
```
```ts
// page.tsx — una sola fuente del filtro (el cliente) y fetch acotado:
export default async function ContactsPage() {   // eliminar searchParams
  // ...
  const { data } = await supabase
    .from('contacts')
    .select('id, phone, shipping_phone, name, email, notes, document_type, document_number, consent_given, consent_date, consent_source, consent_notice_version, consent_evidence, consent_actor_email, consent_revoked_at, consent_revoked_reason, created_at, address')
    .eq('tenant_id', tenantId)
    .order('name', { ascending: true, nullsFirst: false })
    .limit(500)   // lo que el comentario ya prometía
  // borrar: const consentFilter = ... y los dos .eq('consent_given', ...)
```
El filtrado consent/search queda solo en ContactsManager (ya lo hace).
```

**Notas del verificador sobre el fix**: Correcto: eliminar searchParams (consent y q) y añadir .limit(500) alinea código con el comentario y deja una sola fuente del filtro (cliente). Trade-off aceptado y ya asumido por el comentario original: tenants con >500 contactos no verán el resto hasta que exista búsqueda server-side.

<details><summary>Verificación adversarial</summary>

Confirmado todo: (1) page.tsx:104 lee searchParams?.consent y 119-120 lo aplican en SQL, pero grep de 'consent=' en apps/web devuelve 0 constructores de ese param — rama server muerta; ContactsManager mantiene su propio useState('all') (contacts-manager.tsx:162) y filtra en memoria (171-172). (2) searchParams.q declarado (page.tsx:95) y jamás leído. (3) El comentario de la línea 127 promete 'los primeros 500' pero el query (109-122) no tiene .limit() — fetch de PII sin techo propio (acotado solo por max-rows de PostgREST). (4) Si alguien activara ?consent=yes por URL, consentCount/revokedCount (130-131) se calcularían sobre el subset filtrado y el header mentiría. Sin defensa que lo refute.

</details>

---

### F77 · 🟡 MEDIUM — Tipos de dominio duplicados y divergentes entre rutas (Contact x2 con campos distintos, Product/Variation x3) mientras packages/shared-types existe pero solo contiene 5 type aliases

**Ubicación**: `apps/web/app/dashboard/(sales)/contacts/page.tsx:73` · **Detectado por**: frontend-components · 📌 ya rastreado (audit finiquito §2 Productos — gap técnico 'Tipos TS Product/Variation duplicados en types.ts y catalog-table.tsx... Drift garantizado' + .context/04-next-steps §Pendientes reales item 6 'Arquitectura de paquetes compartidos — consumo real de @commerce/shared-types' (parte Contact x2 no descrita)) · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: `type Contact` está definido en contacts/page.tsx:73 SIN `document_type`/`document_number` (aunque el SELECT de la línea 112 sí los pide — el cast `data as unknown as Contact[]` de la línea 123 oculta el drift) y otra vez en contacts-manager.tsx:38 CON ellos y con `address: ContactAddress | null` vs `Record<string, string> | null`. `Product`/`Variation` están definidos 3 veces con shapes divergentes: catalog/types.ts:16-31 (completo, `price: number`), inbox/_lib/types.ts:70 (subset), orders-new-form.tsx:13-23 (`price: number | null`). packages/shared-types/src/index.ts — el lugar diseñado para esto — solo exporta TenantRole, ConversationStatus, MessageProcessingStatus, PlanCode y PlanCapability. Cada cambio de esquema (p.ej. rev. 103 shipping_phone) exige cazar N copias, y el compilador no ayuda porque los casts unknown desconectan los tipos de los SELECT reales.

**Evidencia (código real)**:
```
page.tsx:73-89: `type Contact = {\n  id: string\n  phone: string\n  shipping_phone: string | null ...` (sin document_type) vs contacts-manager.tsx:45-46: `document_type?: string | null   // rev. 69 — CC/CE/NIT/PP/TI/OTHER\n  document_number?: string | null` — y el SELECT de page.tsx:112 sí incluye `'id, phone, shipping_phone, name, email, notes, document_type, document_number, ...'`
```

**Corrección propuesta**:
```
Mover las shapes base a packages/shared-types y derivar proyecciones con Pick:
```ts
// packages/shared-types/src/index.ts
export interface ContactBase {
  id: string; phone: string; shipping_phone?: string | null
  name: string | null; email: string | null; notes: string | null
  document_type?: string | null; document_number?: string | null
  consent_given: boolean; consent_date: string | null
  consent_source?: string | null; consent_revoked_at?: string | null
  created_at: string; address: Record<string, unknown> | null
}
export interface VariationBase {
  id: string; sku?: string | null; price: number | null
  stock_quantity?: number; attributes: Record<string, string> | null
  image_url?: string | null
}
```
```ts
// orders-new-form.tsx
import type { VariationBase } from '@konvi/shared-types'
type Variation = Pick<VariationBase, 'id' | 'price' | 'attributes'>
```
```

**Notas del verificador sobre el fix**: Dirección correcta pero el fix como está escrito no compila: el package se llama @commerce/shared-types (no @konvi/shared-types) y grep muestra CERO consumidores — apps/web no lo tiene en package.json ni en tsconfig paths, hay que wirear el workspace dep primero. Además ContactBase.address como Record<string, unknown> degrada el ContactAddress estructurado existente. Como todas las copias viven dentro de apps/web, una alternativa más barata es consolidar en apps/web/lib/types (o en los types.ts de módulo existentes) y derivar con Pick, dejando shared-types para cuando haya un segundo consumidor real.

<details><summary>Verificación adversarial</summary>

Confirmado: contacts/page.tsx:73-90 define Contact SIN document_type/document_number aunque el SELECT (112) sí los pide, y el cast `data as unknown as Contact[]` (123) desconecta el tipo del query; contacts-manager.tsx:38-57 redefine Contact CON esos campos y con address: ContactAddress|null vs Record<string,string>|null. Product/Variation ×3 shapes divergentes: catalog/types.ts:16-40 (price: number, irónicamente comentado 'en un solo lugar para evitar duplicación'), inbox/_lib/types.ts:60-77 (ProductVariation subset), orders-new-form.tsx:13-23 (price: number|null). packages/shared-types/src/index.ts solo tiene 5 type aliases. Drift real de mantenibilidad, sin impacto runtime hoy (los datos  […]

</details>

---

### F73 · 🟡 MEDIUM — STATUS_LABELS/STATUS_COLORS de estados de pedido duplicados en 4 archivos y con colores contradictorios: el pie de Métricas asigna color POSICIONAL mientras Dashboard asigna por estado — el mismo estado se pinta distinto según la página

**Ubicación**: `apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:45` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: El mismo mapa {pending→Pendiente, confirmed→Confirmado, processing→En proceso, shipped→Enviado, delivered→Entregado, cancelled→Cancelado} está copiado en orders-manager.tsx:45-59 (STATUS_LABELS+STATUS_COLORS), metrics/page.tsx:11-28, dashboard-client.tsx:55-71 (ORDER_STATUS_COLORS hex + LABELS) y metrics-charts.tsx:13-20. Peor: dashboard-client mapea hex POR ESTADO (`pending:'#D4A843', confirmed:'#38A875'...`) pero metrics-charts.tsx pinta su pie con `COLORS[i % COLORS.length]` posicional sobre un array distinto — si un tenant no tiene pedidos 'pending', TODOS los estados cambian de color y el mismo estado luce diferente entre /dashboard y /dashboard/metrics. Agregar un estado nuevo (p.ej. refund) exige tocar 4 archivos.

**Evidencia (código real)**:
```
orders-manager.tsx:45: `const STATUS_LABELS: Record<string, string> = {\n  pending:    'Pendiente', ...` — metrics-charts.tsx:11: `const COLORS = ['#a3e635', '#facc15', '#60a5fa', '#f472b6', '#34d399', '#f87171']` con `<Cell key={i} fill={COLORS[i % COLORS.length]} />` vs dashboard-client.tsx:55: `const ORDER_STATUS_COLORS: Record<string, string> = {\n  pending:    '#D4A843',`
```

**Corrección propuesta**:
```
Crear `apps/web/lib/order-status.ts` como single source:
```ts
export const ORDER_STATUS_LABELS: Record<string, string> = {
  pending: 'Pendiente', confirmed: 'Confirmado', processing: 'En proceso',
  shipped: 'Enviado', delivered: 'Entregado', cancelled: 'Cancelado',
}
export const ORDER_STATUS_BADGE: Record<string, string> = { /* clases Tailwind badge */ }
export const ORDER_STATUS_HEX: Record<string, string> = {
  pending: '#D4A843', confirmed: '#38A875', /* ... */
}
```
Importar en los 4 archivos y en metrics-charts.tsx keyear el pie por estado:
```tsx
{data.map((entry) => (
  <Cell key={entry.name} fill={ORDER_STATUS_HEX[entry.name] ?? '#7A9490'} />
))}
```
```

**Notas del verificador sobre el fix**: Correcto crear apps/web/lib/order-status.ts y keyear el pie de metrics por estado. Incluir también ORDER_STATUS_BADGE (clases Tailwind de orders-manager/metrics-page, que hoy también divergen levemente en formato). Aprovechar para alinear la paleta hex con feedback_ui_colors (evitar 300-500).

<details><summary>Verificación adversarial</summary>

Confirmadas las 4 copias: orders-manager.tsx:45-68 (STATUS_LABELS + STATUS_COLORS Tailwind), metrics/page.tsx:11-27 (STATUS_COLORS + STATUS_LABELS), dashboard-client.tsx:55-71 (ORDER_STATUS_COLORS hex por estado + LABELS), metrics-charts.tsx:11-20 (COLORS posicional + ORDER_STATUS_LABELS). El contraste clave es exacto: dashboard-client.tsx:315 pinta el pie con `ORDER_STATUS_COLORS[entry.status]` (por estado) mientras metrics-charts.tsx:55-56 usa `<Cell key={i} fill={COLORS[i % COLORS.length]} />` (posicional) sobre una paleta distinta — el mismo estado se colorea diferente entre /dashboard y /dashboard/metrics, y la asignación en metrics depende de qué estados existan y en qué orden. Sin sin […]

</details>

---

### F75 · 🟡 MEDIUM — Confirmaciones destructivas inconsistentes: 17 sitios usan confirm()/alert() nativos del browser mientras contacts/team/security migraron a Dialog shadcn (Rev. 102); uno además filtra un env var interno al operador

**Ubicación**: `apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:109` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: Rev. 102 estableció Dialog shadcn como patrón para confirmaciones (contacts-manager.tsx:360 '// Rev. 102 — Eliminar ahora usa Dialog shadcn/ui (no `confirm()` nativo)', security-form.tsx:60, team/*-button.tsx) pero quedaron 17 `confirm()`/`window.confirm()` nativos: orders-manager.tsx:109, categories-manager.tsx:97, agents-list.tsx:187, aveonline-setup.tsx:65/540/571/598, aveonline-carriers.tsx:205, gallery-picker-modal.tsx:125, catalog-table.tsx:269, integrations-manager.tsx:149, retention-policies-form.tsx:49, legal-acceptance-client.tsx:31, conversation-notes.tsx:132, attribute-contract-editor.tsx:93. El confirm de guía COD además expone al tenant el nombre de un env var interno de la plataforma ('AVEONLINE_GENERATE_REAL_GUIDES=true') — detalle de configuración que el operador no controla ni debe conocer.

**Evidencia (código real)**:
```
orders-manager.tsx:109-113: `if (!confirm(\n      'Generar guía Aveonline para este pedido COD? '\n      + 'Tarda ~10-15s. Si tu cuenta tiene AVEONLINE_GENERATE_REAL_GUIDES=true, '\n      + 'la guía será facturable.',\n    )) return`
```

**Corrección propuesta**:
```
Extraer el patrón ya triplicado en team/*.tsx a un componente compartido y migrar los 17 sitios:
```tsx
// components/ui/confirm-dialog.tsx
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel = 'Confirmar', destructive, pending, onConfirm }: {
  open: boolean; onOpenChange: (v: boolean) => void; title: string
  description: React.ReactNode; confirmLabel?: string; destructive?: boolean
  pending?: boolean; onConfirm: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader><DialogTitle>{title}</DialogTitle>
          <DialogDescription className="pt-1">{description}</DialogDescription></DialogHeader>
        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" size="sm" onClick={() => onOpenChange(false)} disabled={pending}>Cancelar</Button>
          <Button variant={destructive ? 'destructive' : 'default'} size="sm" onClick={onConfirm} disabled={pending}>
            {pending ? <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> : null}{confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```
En el texto COD, sustituir la mención del env var por lenguaje de producto: 'Si tu cuenta tiene generación real de guías activada, la guía será facturable.'
```

**Notas del verificador sobre el fix**: El componente ConfirmDialog propuesto es razonable (calca el patrón team/*.tsx). Advertencia de alcance: confirm() es síncrono dentro de handlers; migrar los 15 sitios exige reestructurar cada handler a estado open/onConfirm (no es un swap 1:1). El reemplazo del texto del env var por lenguaje de producto es correcto y puede hacerse de inmediato como quick-win independiente.

<details><summary>Verificación adversarial</summary>

Confirmado el patrón Rev. 102 (contacts-manager.tsx:360 y 462 documentan la migración a Dialog shadcn; security-form.tsx:60 ídem) y los confirm() nativos restantes. Grep encontró 15 call sites (no 17): orders-manager:109, categories-manager:97, agents-list:187, aveonline-setup:65/540/571/598, aveonline-carriers:205, gallery-picker-modal:125, catalog-table:269, integrations-manager:149, retention-policies-form:49, legal-acceptance-client:31, conversation-notes:132, attribute-contract-editor:93. El leak del env var interno es literal en orders-manager.tsx:110-112: 'Si tu cuenta tiene AVEONLINE_GENERATE_REAL_GUIDES=true, la guía será facturable' — configuración de plataforma que el operador ten […]

</details>

---

### F129 · 🟡 MEDIUM — Página de Pedidos y Dashboard traen todas las filas de orders (select('status')) y todos los contacts solo para contar por estado y llenar un picker

**Ubicación**: `apps/web/app/dashboard/(sales)/orders/page.tsx:59` · **Detectado por**: performance · 🆕 nuevo

**Causa**: `allOrdersRes` selecciona `status` de TODAS las órdenes del tenant (sin límite) para hacer `reduce` de conteos por estado en JS; `app/dashboard/page.tsx:69` repite el mismo patrón (`supabase.from('orders').select('status').eq('tenant_id', tenantId)`). Con el cap de 1000 filas de PostgREST los contadores de las pestañas quedan mal en silencio; sin cap, cada visita transfiere N filas para producir 6 números. Además `contacts.select('id, phone, name')` (línea 53-57) trae la lista completa de contactos para el diálogo de creación.

**Evidencia (código real)**:
```
supabase
        .from('orders')
        .select('status')
        .eq('tenant_id', tenantId),
    ])
    const allOrders = (allOrdersRes.data as unknown as { status: string }[]) || []
    counts = allOrders.reduce(...)
```

**Corrección propuesta**:
```
Conteos por estado con `head: true` (6 queries paralelas baratas — mismo patrón que ya usa dashboard/page.tsx:47-62 para sus contadores):
```ts
const STATUSES = ['pending','confirmed','processing','shipped','delivered','cancelled'] as const
const statusCounts = await Promise.all(STATUSES.map(s =>
  supabase.from('orders').select('id', { count: 'exact', head: true })
    .eq('tenant_id', tenantId).eq('status', s)))
counts = Object.fromEntries(STATUSES.map((s, i) => [s, statusCounts[i].count ?? 0]))
counts['all'] = statusCounts.reduce((a, r) => a + (r.count ?? 0), 0)
```
Para el picker de contacts: `.limit(500)` + búsqueda server-side (`.ilike('name', ...)`) bajo demanda. Aplicar el mismo fix en app/dashboard/page.tsx:69.
```

**Notas del verificador sobre el fix**: Correcto y consistente con el patrón head:true ya usado en dashboard/page.tsx:47-62. Mejora: counts['all'] con un solo head-count sin filtro de status (evita perder órdenes con status inesperado fuera del array STATUSES). El picker de contacts con búsqueda server-side requiere cambio en el componente cliente del diálogo (no solo el query).

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/configuration.html#db-max-rows

<details><summary>Verificación adversarial</summary>

Confirmado: orders/page.tsx:58-61 selecciona status de TODAS las órdenes y hace reduce en JS (:64-69); app/dashboard/page.tsx:69 repite el patrón exacto (irónicamente en el mismo Promise.all donde las líneas 47-62 ya usan head:true+count para otros contadores — el patrón correcto existe al lado). contacts.select('id, phone, name') sin límite (:53-57) para el picker. Con max_rows=1000 los contadores de pestañas quedan mal en silencio. Sin defensa.

</details>

---

### F106 · 🟡 MEDIUM — disconnectWhatsApp borra de Vault solo access_token_secret_id y deja huérfano app_secret_secret_id

**Ubicación**: `apps/web/app/dashboard/(settings-group)/integrations/page.tsx:403` · **Detectado por**: wiring-end2end · 🆕 nuevo

**Causa**: POST /api/v1/integrations/whatsapp/credentials guarda DOS secretos en Vault: app_secret_secret_id y access_token_secret_id (integrations.py:111-136, docstring: 'app_secret + access_token → Vault (cifrado)... Idempotente: reusa los secret_id existentes para no dejar secretos huérfanos'). El server action disconnectWhatsApp solo borra el access token y luego hace credentials={} — el App Secret de Meta (usado para HMAC per-tenant, ADR-0023) queda cifrado en Vault sin puntero, para siempre. disconnectWompi y disconnectTelegram sí borran todos sus secretos.

**Evidencia (código real)**:
```
page.tsx:403-405: const sid = (existing?.credentials as Record<string, string>)?.access_token_secret_id\nif (sid) await sb.rpc('pgsec_delete_secret', { p_id: sid })\nawait sb.from('tenant_integrations').update({ status: 'disconnected', credentials: {}, meta: {} })
```

**Corrección propuesta**:
```
Borrar ambos secretos antes de vaciar credentials:

-    const sid = (existing?.credentials as Record<string, string>)?.access_token_secret_id
-    if (sid) await sb.rpc('pgsec_delete_secret', { p_id: sid })
+    const creds = (existing?.credentials ?? {}) as Record<string, string>
+    for (const sid of [creds.access_token_secret_id, creds.app_secret_secret_id]) {
+      if (sid) await sb.rpc('pgsec_delete_secret', { p_id: sid })
+    }
```

**Notas del verificador sobre el fix**: Correcto y completo: itera ambos secret_ids con el mismo RPC pgsec_delete_secret ya usado en el archivo; consistente con disconnectWompi. La ownership check del RPC (migración 20260624000000_vault_rpc_tenant_ownership.sql) permite el borrado porque el secreto se nombró `{tenant_id}/whatsapp/app_secret`.

<details><summary>Verificación adversarial</summary>

Confirmado: page.tsx:403-404 solo borra access_token_secret_id vía pgsec_delete_secret y luego credentials={}. El flujo real de conexión (whatsapp-credentials-form.tsx:54 → POST /api/v1/integrations/whatsapp/credentials, integrations.py:111-136) guarda DOS secretos: app_secret_secret_id y access_token_secret_id. Tras disconnect, una reconexión vía ese endpoint encuentra existing_creds={} y crea secretos NUEVOS (integrations.py:110-121), dejando el app_secret viejo huérfano en Vault permanentemente. disconnectWompi (page.tsx:387-388) y disconnectTelegram (146) sí borran todos sus secretos — la asimetría es real. Ninguna otra defensa ni job de limpieza de huérfanos encontrado.

</details>

---

### F86 · 🟡 MEDIUM — updateTenant ignora el error de Supabase: todos los formularios de Settings (nombre, filosofía, horario, presencia, origen de envío) reportan éxito aunque el UPDATE falle

**Ubicación**: `apps/web/app/dashboard/(settings-group)/settings/actions.ts:28` · **Detectado por**: frontend-data · 📌 ya rastreado (audit finiquito §8 Configuración — gap técnico 'settings/actions.ts no usa estructura { ok, error }... saveTenant/saveFilosofia/savePresenciaDigital/saveShippingOrigin no retornan resultado al cliente... Sin UX de error explícita al failure')

**Causa**: supabase-js v2 no lanza excepción en errores de query: retorna { error } que aquí se descarta. Si el UPDATE a tenants falla (RLS, constraint, red), saveTenant/saveFilosofia/saveHorarioAsesor/savePresenciaDigital/saveShippingOrigin continúan, ejecutan revalidatePath y el form vuelve limpio — el owner cree que guardó (p.ej. shipping_origin, que alimenta el cotizador Aveonline del bot) y el dato viejo sigue en DB. El mismo archivo ya maneja el error correctamente en savePaymentMethods (retorna {ok,error}).

**Evidencia (código real)**:
```
async function updateTenant(tenantId: string, data: Record<string, unknown>) {
  const sb = createClient()
  await sb.from('tenants').update(data).eq('id', tenantId)
}
```

**Corrección propuesta**:
```
Propagar el error y alinear las actions al patrón {ok,error} que ya usa savePaymentMethods:

```ts
async function updateTenant(tenantId: string, data: Record<string, unknown>): Promise<{ ok: boolean; error?: string }> {
  const sb = createClient()
  const { error } = await sb.from('tenants').update(data).eq('id', tenantId)
  if (error) return { ok: false, error: `Error guardando: ${error.message}` }
  return { ok: true }
}

export async function saveTenant(formData: FormData) {
  const tenantId = await getOwnerTenantId()
  const result = await updateTenant(tenantId, { ... })
  if (!result.ok) return result
  revalidateSettings()
  return result
}
```

y mostrar result.error en los forms cliente (store-presence-form.tsx, shipping-origin-form.tsx ya son client components con estado).
```

**Notas del verificador sobre el fix**: Propagar {ok,error} en updateTenant es correcto. PERO surfacing incompleto: verifiqué que saveTenant/saveFilosofia/saveHorarioAsesor están bound como plain `<form action={saveTenant}>` en page.tsx (153/229/325) — el valor de retorno se descarta salvo que se envuelvan en useActionState. Con el fix, en fallo se salta revalidate pero el usuario aún no ve error. Para completar realmente hay que mover esos 3 forms a client + useActionState (o lanzar para el error boundary). savePresenciaDigital/saveShippingOrigin sí van vía store-presence-form.tsx/shipping-origin-form.tsx (client). El core (dejar de ignorar el error) es correcto; el fix debe completarse en la capa cliente como el propio hallazgo indica.

<details><summary>Verificación adversarial</summary>

Confirmado. settings/actions.ts:26-29 `updateTenant` hace `await sb.from('tenants').update(data).eq('id',tenantId)` y descarta el `{error}` que supabase-js v2 retorna (no lanza). saveTenant/saveFilosofia/saveHorarioAsesor/savePresenciaDigital/saveShippingOrigin llaman updateTenant y ejecutan revalidatePath incondicionalmente → si el UPDATE falla (RLS/constraint/red) el owner cree que guardó (p.ej. shipping_origin que alimenta el cotizador Aveonline). El mismo archivo maneja el error bien en savePaymentMethods (145-151 retorna {ok,error}). Defecto real de integridad/UX.

</details>

---

### F145 · 🟡 MEDIUM — Violación sistemática de la regla de paleta del repo: 462 usos de text/border-*-300/400/500 (fluorescentes) sobre fondo crema, coexistiendo con componentes nuevos que sí usan la escala 700

**Ubicación**: `apps/web/app/dashboard/(settings-group)/team/page.tsx:49` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: La regla del repo prohíbe shades 300-500 en texto/borders (usar 700). El canvas del dashboard es crema claro (globals.css `--background: 30 25% 96%`), donde text-amber-400/text-blue-400/text-yellow-400 tienen contraste insuficiente. `grep -rnoE "(text|border)-…-(300|400|500)"` arroja 462 ocurrencias en apps/web: team/page.tsx:40-58 (badges de rol: text-amber-400, text-blue-400, text-slate-400) y :563-602 (Pendiente/Reenviar/Activar), orders-manager.tsx:62-67 (STATUS_COLORS completo), claims-manager.tsx:40-43 (STATUS_MAP), shipping/page.tsx:23-28, submit-button.tsx:45 (text-emerald-400 en el check de 'Guardado'). Los componentes recientes prueban que el canon es viable: promotions-manager.tsx usa emerald-700/40 + text-emerald-900 y rose-700/40 + text-rose-900.

**Evidencia (código real)**:
```
team/page.tsx:49-52 `color: 'bg-blue-500/10 text-blue-400 border-blue-500/25', … textColor: 'text-blue-400', iconColor: 'text-blue-400',` renderizado sobre el canvas crema (globals.css:18 `--background: 30 25% 96%; /* #F8F5F1 — Kaiu Cream */`); orders-manager.tsx:62 `pending: 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30',`; conteo real: 462 matches del grep sistemático.
```

**Corrección propuesta**:
```
Migrar los mapas de color al patrón 700/900 ya establecido en promotions-manager, ej. orders-manager.tsx:
```ts
const STATUS_COLORS: Record<string, string> = {
  pending:    'bg-amber-700/10 text-amber-900 border-amber-700/30',
  confirmed:  'bg-blue-700/10 text-blue-900 border-blue-700/30',
  processing: 'bg-purple-700/10 text-purple-900 border-purple-700/30',
  shipped:    'bg-indigo-700/10 text-indigo-900 border-indigo-700/30',
  delivered:  'bg-emerald-700/10 text-emerald-900 border-emerald-700/30',
  cancelled:  'bg-rose-700/10 text-rose-900 border-rose-700/30',
}
```
Y agregar guard al validate.sh para ratchet decreciente (mismo patrón que BASELINE_RUFF_ERRORS):
```bash
PALETTE_HITS=$(grep -rnoE '(text|border)-[a-z]+-(300|400|500)' apps/web/app apps/web/components --include='*.tsx' | wc -l)
[ "$PALETTE_HITS" -le "${BASELINE_PALETTE:-462}" ] || { echo "Paleta: $PALETTE_HITS > baseline"; exit 1; }
```
Excepción legítima: el sidebar oscuro (.sidebar-gradient) puede quedar exento vía path.
```

**Notas del verificador sobre el fix**: Migración de mapas correcta (sigue el patrón promotions ya validado). El guard grep en validate.sh replica el patrón BASELINE_RUFF_ERRORS del repo — coherente. Ajustes: (1) la exención por path para superficies oscuras (sidebar-client usa el gradiente oscuro; su ROLE_BADGE usa text-amber-200/white que igual no matchea) es necesaria como dice el fix; (2) el regex no cubre clases dot `bg-*-400` (claims STATUS_MAP dots) — aceptable como fase 1; (3) migrar en tandas por módulo para revisión visual, no un sed masivo.

<details><summary>Verificación adversarial</summary>

Verificado empíricamente: el grep `(text|border)-[a-z]+-(300|400|500)` sobre apps/web/app + components devuelve exactamente 462 matches; globals.css:17 confirma `--background: 30 25% 96%` (crema claro); team/page.tsx:40-58 usa text-amber-400/text-blue-400/text-slate-400, orders-manager.tsx:61-68 STATUS_COLORS completo en *-400, claims-manager.tsx:39-44 STATUS_MAP igual, submit-button.tsx:45 text-emerald-400. La regla es real y explícita (memoria feedback_ui_colors: NUNCA 300-500, usar 700), y promotions-manager demuestra que el patrón 700/900 ya es viable. Ninguna defensa (no hay lint de paleta en validate.sh).

</details>

---

### F72 · 🟡 MEDIUM — Dashboard: router.refresh() sin debounce en CADA postgres_change de conversations/orders — cada mensaje WhatsApp entrante re-ejecuta las ~10 queries del server page

**Ubicación**: `apps/web/app/dashboard/dashboard-client.tsx:103` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: El canal Realtime suscribe `event: '*'` sobre las tablas conversations y orders del tenant y llama `router.refresh()` directo en el callback. Cada mensaje inbound del bot actualiza `conversations.last_interaction_at` (UPDATE) → refresh → el RSC dashboard/page.tsx re-ejecuta sus 10 queries (4 counts stats + 4 counts ops + messages 7d + orders status). En un tenant con tráfico WhatsApp real, un operador con el dashboard abierto genera una avalancha de re-fetches server-side sin ningún throttle, y el bot puede generar varios UPDATEs por turno de conversación.

**Evidencia (código real)**:
```
dashboard-client.tsx:106-113: `const channel = supabase.channel(`dashboard_ops_${tenantId}`)\n      .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations', filter: `tenant_id=eq.${tenantId}` }, () => {\n        router.refresh()\n      })\n      .on('postgres_changes', { event: '*', schema: 'public', table: 'orders', ... }, () => {\n        router.refresh()\n      })`
```

**Corrección propuesta**:
```
```ts
useEffect(() => {
  if (!tenantId) return
  const supabase = createClient()
  let t: ReturnType<typeof setTimeout> | null = null
  const debouncedRefresh = () => {
    if (t) clearTimeout(t)
    t = setTimeout(() => router.refresh(), 3000)
  }
  const channel = supabase.channel(`dashboard_ops_${tenantId}`)
    .on('postgres_changes', { event: '*', schema: 'public', table: 'conversations', filter: `tenant_id=eq.${tenantId}` }, debouncedRefresh)
    .on('postgres_changes', { event: '*', schema: 'public', table: 'orders', filter: `tenant_id=eq.${tenantId}` }, debouncedRefresh)
    .subscribe()
  return () => { if (t) clearTimeout(t); supabase.removeChannel(channel) }
}, [tenantId, router])
```
```

**Notas del verificador sobre el fix**: Debounce 3s con cleanup del timer es correcto y suficiente. Nota adicional: el listener de orders nunca dispara porque orders no está en la publication realtime — issue latente separado (pendingOrders no se actualiza live); si se quiere que funcione hay que añadir orders a supabase_realtime vía migración.

<details><summary>Verificación adversarial</summary>

Confirmado dashboard-client.tsx:103-115: router.refresh() directo sin debounce en cada postgres_change de conversations. La migración 20260422150000_conversations_last_interaction_sync.sql crea trigger que actualiza conversations.last_interaction_at en CADA insert de message (inbound y outbound) → cada turno del bot genera ≥2 UPDATEs → refresh → dashboard/page.tsx re-ejecuta 11 queries server-side (1 tenants + 10 en Promise.all, líneas 27-70). conversations SÍ está en la publication realtime (20260417000000_enable_realtime.sql:5). Matiz que el buscador no vio: orders NO está en supabase_realtime (grep de ALTER PUBLICATION: solo conversations, messages, conversation_carts, conversation_cart_i […]

</details>

---

### F87 · 🟡 MEDIUM — addExpense no verifica res.ok y traga excepciones de red: gastos financieros se pierden silenciosamente sin feedback al usuario

**Ubicación**: `apps/web/app/dashboard/finance/actions.ts:42` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: El POST a /api/v1/expenses no comprueba el status de respuesta (un 4xx/5xx del backend pasa inadvertido) y el `catch { /* non-fatal */ }` absorbe timeouts/red. Después ejecuta revalidatePath igual: el owner registra un gasto para su P&L, el form se limpia, y el gasto nunca existió — corrompe el unit economics sin señal alguna. Mismo antipatrón en purchases/actions.ts (líneas 45, 70, 76, 82) donde el error solo va a console.error del servidor, invisible para el operador.

**Evidencia (código real)**:
```
await fetch(`${CORE_API_URL}/api/v1/expenses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({...}),
      signal: ctrl.signal,
    })
    clearTimeout(timeout)
  } catch { /* non-fatal */ }

  revalidatePath('/dashboard/finance')
```

**Corrección propuesta**:
```
```ts
export async function addExpense(formData: FormData): Promise<{ ok: boolean; error?: string }> {
  ...
  try {
    const res = await fetch(`${CORE_API_URL}/api/v1/expenses`, { ...opciones })
    clearTimeout(timeout)
    if (!res.ok) {
      const detail = await res.text().catch(() => '')
      return { ok: false, error: detail.slice(0, 200) || `HTTP ${res.status}` }
    }
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Error de red' }
  }
  revalidatePath('/dashboard/finance')
  return { ok: true }
}
```

Aplicar el mismo cambio a addSupplier/createPurchaseOrder/cancelPurchaseOrder/receivePurchaseOrder en app/dashboard/purchases/actions.ts y renderizar el error en el form.
```

**Notas del verificador sobre el fix**: Retornar {ok,error} y chequear res.ok es correcto. Surfacing incompleto igual que F86: expenses-manager.tsx:52 usa `<form action={async (fd)=>{ await addExpense(fd); setShowAdd(false) }}>` — el closure ignora el retorno y cierra el panel; hay que capturar {ok,error} y renderizarlo (useState/toast) para que el operador lo vea. Cambiar la firma de addExpense a devolver objeto no rompe el binding actual. El fix del core es correcto; requiere el cambio cliente que el hallazgo menciona.

<details><summary>Verificación adversarial</summary>

Confirmado. finance/actions.ts:30-42 hace el POST a /api/v1/expenses SIN comprobar res.ok y con `catch { /* non-fatal */ }` que absorbe timeout/red; luego revalidatePath igual → un 4xx/5xx del backend o un fallo de red hace que el gasto no se registre pero el form se limpia sin señal, corrompiendo el P&L. Mismo antipatrón en purchases/actions.ts: addSupplier(45), createPurchaseOrder(70), cancelPurchaseOrder(76), receivePurchaseOrder(81) solo hacen console.error (server-side, invisible al operador). Defecto real.

</details>

---

### F71 · 🟡 MEDIUM — useConversations hace doble fetch completo al montar: dos useEffect distintos invocan loadConversations() en el primer render (4 queries en vez de 2, x2 en StrictMode dev)

**Ubicación**: `apps/web/app/dashboard/inbox/_hooks/use-conversations.ts:180` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: El efecto 'Carga inicial' (deps `[loadConversations]`, estable porque solo depende de `supabase`) corre al montar, y el efecto 'Refresh al togglear archivadas' (deps `[showArchived]`) TAMBIÉN corre al montar con el valor inicial `false`. Cada invocación de `loadConversations` ejecuta 2 queries (conversations con embed de messages + conversation_reads). Resultado: 4 queries duplicadas al abrir el Inbox (8 en dev por StrictMode), más el re-render doble de la lista. Se suma al fetch completo disparado por cada INSERT realtime (línea 217) y al polling de 20s — tres fuentes del mismo fetch sin coordinación.

**Evidencia (código real)**:
```
use-conversations.ts:179-190: `// Carga inicial.\n  useEffect(() => {\n    loadConversations()\n  // eslint-disable-next-line react-hooks/exhaustive-deps\n  }, [loadConversations])\n\n  // Refresh al togglear archivadas.\n  useEffect(() => {\n    showArchivedRef.current = showArchived\n    loadConversations()\n  ...\n  }, [showArchived])`
```

**Corrección propuesta**:
```
Eliminar el efecto de carga inicial redundante; el de `showArchived` ya cubre el mount:
```ts
// BORRAR:
// useEffect(() => {
//   loadConversations()
// }, [loadConversations])

// CONSERVAR (cubre mount + toggles):
useEffect(() => {
  showArchivedRef.current = showArchived
  loadConversations()
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [showArchived])
```
```

**Notas del verificador sobre el fix**: Correcto: el efecto [showArchived] corre igualmente al mount (con false inicial, coherente con showArchivedRef inicial) y cubre toggles. Como supabase es estable (useMemo []), eliminar el efecto [loadConversations] no pierde ningún re-fetch real. Riesgo residual nulo con el único caller actual (inbox-manager.tsx:42).

<details><summary>Verificación adversarial</summary>

Confirmado en use-conversations.ts:179-190: el efecto 'Carga inicial' (deps [loadConversations], estable porque loadConversations solo depende de supabase, que inbox-manager.tsx:27 memoiza con useMemo(()=>createClient(),[])) y el efecto 'Refresh al togglear archivadas' (deps [showArchived]) corren AMBOS al montar → 2 invocaciones de loadConversations = hasta 4 queries (conversations con embed messages + conversation_reads, líneas 101-139). No existe dedupe in-flight ni guard de primera ejecución. El tercer useEffect (193) no ejecuta fetch al mount (solo suscripción + interval 20s), así que no agrava. Sin defensa existente que refute.

</details>

---

### F64 · 🟡 MEDIUM — Contrato de messages desalineado en 3 capas: el backend escribe content_type template/escalation_audit/sla_breach_audit/claim_audit y processing_status processing/ack_pending que TypeScript y el contrato 'canónico' de la API no conocen — el Inbox renderiza burbujas vacías por cada escalación

**Ubicación**: `apps/web/app/dashboard/inbox/_hooks/use-messages.ts:93` · **Detectado por**: cross-service-dup · 🆕 nuevo

**Causa**: El union MessageContentType (types.ts:38-46, creado en Rev.72 precisamente para 'cerrar drift M2') volvió a divergir: el backend escribe 'template' (worker.py:1423,1636), 'escalation_audit' (agentic/tools/escalation.py:73, dispatcher.py:3391, invariants/fake_escalation.py:174), 'sla_breach_audit' (worker.py:1016) y 'claim_audit' (agentic/tools/claims.py:183) — todos con content:"" y direction:'outbound'. El filtro runtime solo excluye 'context_snapshot' (use-messages.ts:93,123,150,179 y API conversations.py:1175), y chat-panel.tsx:325-341 mapea TODOS los mensajes → cada escalación/SLA breach/claim inserta una burbuja outbound VACÍA que el operador ve justo al tomar control. Peor: use-conversations.ts:103-104 embebe `messages(content, direction, created_at)` sin filtro alguno (ni context_snapshot) y toma el más reciente como last_message → preview en blanco en la lista cuando el último row es un audit/snapshot (que es exactamente el momento de una escalación). Mismo patrón en el endpoint API list_conversations (conversations.py:148-172). Y processing_status: DB CHECK permite 6 valores (20260428000001:23 incluye 'processing','ack_pending'; worker.py:2002 escribe ack_pending) pero types.ts:56 declara solo 4 y PROCESSING_STATUSES en services/api/domain/conversation_contract.py:16 ('canonical contract') también omite ambos.

**Evidencia (código real)**:
```
apps/web/app/dashboard/inbox/_lib/types.ts:38-46 `export type MessageContentType =\n  | 'text' | 'image' | 'audio' | 'video' | 'document' | 'sticker' | 'location' | 'context_snapshot'` — vs — services/ai-orchestrator/agentic/tools/escalation.py:69-75 `ctx.supabase.table("messages").insert({ ..., "content_type": "escalation_audit", "content": "", ...` — y use-messages.ts:93 `.neq('content_type', 'context_snapshot')` (único filtro) — y 20260428000001_messages_ack_pending_status.sql:23 `CHECK (processing_status IN ('pending', 'processing', 'processed', 'skipped', 'failed', 'ack_pending'))` vs types.ts:56 `processing_status?: 'pending' | 'processed' | 'skipped' | 'failed'`
```

**Corrección propuesta**:
```
Definir la lista de tipos internos UNA vez y filtrarla en los 3 consumidores. En apps/web/app/dashboard/inbox/_lib/types.ts:
```ts
export type MessageContentType =
  | 'text' | 'image' | 'audio' | 'video' | 'document' | 'sticker' | 'location' | 'template'
  | 'context_snapshot' | 'escalation_audit' | 'sla_breach_audit' | 'claim_audit'
export const INTERNAL_CONTENT_TYPES = ['context_snapshot', 'escalation_audit', 'sla_breach_audit', 'claim_audit'] as const
export type MessageProcessingStatus = 'pending' | 'processing' | 'processed' | 'skipped' | 'failed' | 'ack_pending'
```
En use-messages.ts (los 4 puntos) reemplazar `.neq('content_type', 'context_snapshot')` por:
```ts
.not('content_type', 'in', `(${INTERNAL_CONTENT_TYPES.join(',')})`)
```
(y en el handler realtime: `if (INTERNAL_CONTENT_TYPES.includes(newMsg.content_type as never)) return`). En use-conversations.ts y en services/api/routers/conversations.py excluir esos tipos al calcular last_message; lado Python definir `INTERNAL_CONTENT_TYPES` en domain/conversation_contract.py junto a PROCESSING_STATUSES (actualizado con 'processing' y 'ack_pending') y usarlo en el `.neq`/filtro del preview.
```

**Notas del verificador sobre el fix**: Correcto: lista INTERNAL_CONTENT_TYPES compartida + `.not('content_type','in','(...)')` (sintaxis supabase-js válida) mantiene 'template' visible (tiene content real — correcto). Para use-conversations el filtro embebido es `.not('messages.content_type','in',...)`. Recordar sincronizar también el union en el handler realtime (el fix lo incluye) y el Python del preview API.

<details><summary>Verificación adversarial</summary>

Confirmado en las 3 capas. Backend escribe content_type fuera del union TS: escalation_audit (escalation.py:73, dispatcher.py:3391, fake_escalation.py:174), sla_breach_audit (worker.py:1016), claim_audit (claims.py:183) — todos con content:'' y direction:'outbound' (verificado en los inserts) — y template (worker.py:1423 con content real). types.ts:38-46 solo conoce 8 tipos; use-messages.ts:93/123/150/179 y conversations.py:1175 solo excluyen context_snapshot; chat-panel.tsx:325 mapea TODOS los mensajes sin filtro → burbuja outbound vacía por cada escalación/SLA/claim. use-conversations.ts:103 embebe messages(content,direction,created_at) SIN filtro y conversations.py:148-172 igual → last_me […]

</details>

---

### F70 · 🟡 MEDIUM — Race condition en carga inicial de useMessages: al cambiar rápido de conversación A→B, la respuesta lenta de A puede resolver después y sobrescribir los mensajes de B; además los mensajes de A quedan visibles mientras B carga

**Ubicación**: `apps/web/app/dashboard/inbox/_hooks/use-messages.ts:83` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: El efecto de carga inicial (líneas 83-108) lanza el query con `.then()` sin flag de cancelación ni AbortController; el cleanup del efecto no invalida la promesa pendiente. Si el operador selecciona conv A y de inmediato conv B, y la respuesta de A llega después de la de B, `setMessages(fetched)` pisa el chat de B con los mensajes de A. Además, al cambiar de conversación no se limpia el estado (`setMessages([])` solo ocurre si `conversationId` es null), así que el chat muestra los mensajes de la conversación anterior hasta que resuelve el fetch nuevo. El hook hermano use-conversation-context.ts SÍ implementa el patrón `cancelled` + AbortController (líneas 84-133) — la protección existe en el repo pero no se aplicó aquí.

**Evidencia (código real)**:
```
use-messages.ts:83-104: `useEffect(() => {\n    if (!conversationId) {\n      setMessages([])\n      return\n    }\n    setHasMore(true)\n    supabase\n      .from('messages') ... .then(({ data, error: qErr }) => { ... setMessages(fetched)` — sin flag cancelled ni cleanup de la promesa
```

**Corrección propuesta**:
```
```ts
useEffect(() => {
  if (!conversationId) { setMessages([]); return }
  setMessages([])          // limpia el chat de la conv anterior
  setHasMore(true)
  let cancelled = false
  supabase.from('messages').select(MESSAGE_COLUMNS)
    .eq('conversation_id', conversationId)
    .neq('content_type', 'context_snapshot')
    .order('created_at', { ascending: false })
    .limit(PAGE_INITIAL)
    .then(({ data, error: qErr }) => {
      if (cancelled) return
      // ...resto igual
    })
  return () => { cancelled = true }
}, [conversationId, supabase])
```
```

**Notas del verificador sobre el fix**: Fix correcto y mínimo (flag cancelled + limpiar estado al cambiar). Nota menor de UX: setMessages([]) inmediato hace aparecer el estado 'Sin mensajes aún.' de chat-panel.tsx:320 durante el fetch en vez de un spinner — aceptable y preferible a mostrar la conversación equivocada. El handler realtime de B con dedupe por id convive bien con el fetch inicial cancelable.

<details><summary>Verificación adversarial</summary>

Confirmado en use-messages.ts:83-108. El efecto de carga inicial lanza el query con .then() sin flag cancelled ni cleanup — nada invalida la promesa pendiente al cambiar conversationId. Race real: seleccionar conv A y de inmediato conv B; si la respuesta de A (p. ej. 100 rows pesadas) resuelve después de la de B (2 rows), setMessages(fetched) pisa el chat de B con mensajes de A — alcanzable desde la UI clickeando rápido la lista lateral. Además setMessages([]) solo ocurre con conversationId null (línea 84-87), así que al cambiar A→B los mensajes de A permanecen visibles hasta que resuelve el fetch de B. Verificado que el hook hermano use-conversation-context.ts SÍ implementa cancelled + Abor […]

</details>

---

### F142 · 🟡 MEDIUM — Sidebar diverge del árbol funcional canónico L1 (00-product.md): Promociones y Categorías no existen en el árbol, label 'Cotizador' contradice el canon 'Despachos', y whatsapp-templates no está en el registro de rutas hidden

**Ubicación**: `apps/web/app/dashboard/sidebar-client.tsx:65` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: .context/00-product.md se declara 'L1 — Autoridad Máxima' y exige 'La navegación visible debe calzar exactamente en este árbol' (Ventas = Pedidos, Contactos, Despachos, Reclamos; PRODUCTOS = hoja única /dashboard/catalog). El sidebar expone 'Promociones' (l.66) y 'Categorías' (l.73) que no existen en el árbol Rev.5, renombra Despachos a 'Cotizador' (l.65) — 'Despachos' no aparece en ninguna UI (grep 0 hits) — y la ruta /dashboard/(settings-group)/whatsapp-templates existe sin estar ni en el árbol ni en la sección 5.1 de rutas hidden (que obliga: 'cualquier ruta hidden debe quedar listada aquí con razón explícita'). Las 5 hojas extra de Configuración (Seguridad/Salud/Legal/Retención/Cerrar cuenta, Rev.102/109) tampoco fueron consolidadas al doc.

**Evidencia (código real)**:
```
sidebar-client.tsx:65-66 `{ kind: 'leaf', href: '/dashboard/shipping', label: 'Cotizador', … }` y `{ kind: 'leaf', href: '/dashboard/promotions', label: 'Promociones', … }`; :73 `{ kind: 'leaf', href: '/dashboard/categories', label: 'Categorías', … }`. 00-product.md:34-37 lista VENTAS como `Pedidos/Contactos/Despachos/Reclamos` y §5.1 solo registra media e inventory como rutas hidden; `grep -rn "Despachos" apps/web/app --include=*.tsx` solo devuelve el comentario de sidebar-client.tsx:48.
```

**Corrección propuesta**:
```
Dos movimientos, ambos requieren decisión formal según la política del propio doc: (1) actualizar 00-product.md Rev.7 agregando Promociones (VENTAS), Categorías (PRODUCTOS), las 5 hojas de CONFIGURACIÓN y registrando whatsapp-templates en §5.1; (2) alinear el label al canon mientras tanto:
```tsx
// sidebar-client.tsx l.65
{ kind: 'leaf', href: '/dashboard/shipping', label: 'Despachos', icon: Truck, roles: [], integration: 'shipping' },
```
Si 'Cotizador' es el nombre deseado, el cambio va primero al doc L1 (política §6: 'Todo agente debe leer este archivo antes de proponer crear o mover un módulo').
```

**Notas del verificador sobre el fix**: El fix correctamente enruta ambas partes por decisión formal (política §6 del propio doc). Matiz: la dirección más probable es actualizar el DOC al código (Rev.7 consolidando Promociones/Categorías/Cotizador/whatsapp-templates/hojas Config), no renombrar 'Cotizador'→'Despachos' en UI — el módulo actual ES un cotizador y el repo valora nombres honestos ('IA y Conocimiento'). No ejecutar el rename unilateralmente; requiere input del founder. Es deuda documental/gobernanza, sin impacto runtime.

<details><summary>Verificación adversarial</summary>

Divergencia factualmente confirmada: 00-product.md:24-25 exige 'La navegación visible debe calzar exactamente en este árbol' y §2 lista VENTAS={Pedidos,Contactos,Despachos,Reclamos} y PRODUCTOS como hoja única. sidebar-client.tsx:65 label 'Cotizador', :66 'Promociones' y :73 'Categorías' no existen en el árbol Rev.5; grep 'Despachos' en apps/web/app solo da el comentario de sidebar-client.tsx:48. La ruta (settings-group)/whatsapp-templates existe (verificado con ls) y no está ni en el árbol ni en §5.1 (que solo lista media e inventory, con política explícita l.141: 'cualquier ruta hidden debe quedar listada aquí'). Las 5 hojas extra de Configuración (l.125-132, Rev.102/109) tampoco están en  […]

</details>

---

### F85 · 🟡 MEDIUM — El matcher del middleware excluye /api por completo: el enforcement AAL2 (MFA) no aplica a ningún route handler y una sesión solo-password accede a todos los datos

**Ubicación**: `apps/web/middleware.ts:107` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: El gate MFA (J.2.4.3) solo corre para paths /dashboard/*. Todos los handlers de app/api/* (audit/export sirve el CSV de auditoría directo desde Next, insights lee inventario/pedidos/contactos, conversations/* proxy de envío de mensajes) autentican con getUser()/getSession() que aceptan sesiones AAL1. Un atacante con la contraseña de un usuario con TOTP habilitado no puede abrir /dashboard (redirect a /login/mfa) pero puede llamar GET /api/audit/export o POST /api/conversations/{id}/send con la sesión AAL1 y operar todos los datos del tenant, dejando el MFA como control cosmético a nivel API.

**Evidencia (código real)**:
```
export const config = {
  matcher: [
    '/((?!_next/static|_next/image|favicon.ico|login|forgot-password|auth/confirm|auth/callback|cuenta-suspendida|api).*)',
  ],
}
```

**Corrección propuesta**:
```
Quitar `api` de la exclusión del matcher y responder 401 JSON (no redirect) para paths /api cuando falta AAL2, exceptuando el flujo de recovery:

```ts
// middleware.ts — dentro del bloque `if (user && ...)`
const isApi = request.nextUrl.pathname.startsWith('/api')
const isMfaApi = request.nextUrl.pathname.startsWith('/api/mfa/')
if ((request.nextUrl.pathname.startsWith('/dashboard') || (isApi && !isMfaApi)) && !recoveryBypass) {
  const { data: aalData } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel()
  if (aalData?.nextLevel === 'aal2' && aalData.currentLevel === 'aal1') {
    if (isApi) return NextResponse.json({ detail: 'MFA requerida' }, { status: 401 })
    const url = request.nextUrl.clone(); url.pathname = '/login/mfa'
    return NextResponse.redirect(url)
  }
}
// matcher: '/((?!_next/static|_next/image|favicon.ico|login|forgot-password|auth/confirm|auth/callback|cuenta-suspendida).*)'
```

Nota: el backend FastAPI también debería validar el claim `aal` del JWT (el token AAL1 sigue siendo válido contra CORE_API directo) — registrar como follow-up de capa backend.
```

**Notas del verificador sobre el fix**: Quitar `api` del matcher y devolver 401 JSON para /api sin AAL2, exceptuando /api/mfa/*, es correcto. Verificar que se exceptúen TODOS los endpoints necesarios pre-AAL2: /api/mfa/recovery-codes/verify, /api/mfa/recovery/change-password, /api/mfa/recovery/reset-totp y recovery-codes/regenerate|clear (el prefijo `/api/mfa/` propuesto los cubre). Costo: getUser()+getAAL por cada request /api (aceptable). El follow-up de validar claim `aal` en el backend FastAPI es acertado y necesario, porque un token AAL1 sigue siendo válido contra CORE_API directo — sin eso el fix solo cierra la capa Next.

**Referencia oficial**: https://supabase.com/docs/guides/auth/server-side/nextjs

<details><summary>Verificación adversarial</summary>

Confirmado. matcher (107) excluye `api`, así que el middleware (única capa que corre getAuthenticatorAssuranceLevel) NO se ejecuta para /api/*. Verifiqué que ningún route handler bajo app/api valida AAL (0 hits de getAuthenticatorAssuranceLevel/aal en app/api). audit/export/route.ts autentica con getUser()+role owner y lee audit_log directo de Supabase (acepta sesión AAL1). conversations/[id]/send/route.ts usa getSession().access_token y proxya a CORE_API. El backend FastAPI (dependencies/auth.py) valida firma JWT pero NO el claim aal. Un atacante con contraseña de un user con TOTP: no puede abrir /dashboard (redirect /login/mfa) pero SÍ puede llamar GET /api/audit/export o POST /api/convers […]

</details>

---

### F101 · 🟡 MEDIUM — El middleware pierde las cookies de sesión refrescadas al redirigir al challenge MFA

**Ubicación**: `apps/web/middleware.ts:89` · **Detectado por**: best-practices-docs · 🆕 nuevo

**Causa**: En la rama de enforcement MFA el usuario YA está autenticado, por lo que la llamada previa `supabase.auth.getUser()` (línea 60) puede haber refrescado el access/refresh token e invocado el callback `set`, reconstruyendo `supabaseResponse` con las nuevas cookies. Al hacer `return NextResponse.redirect(url)` se devuelve una respuesta nueva SIN copiar esas cookies de `supabaseResponse`, de modo que las cabeceras Set-Cookie del refresh se descartan. En la siguiente request el cliente conserva el token viejo (posiblemente ya rotado/invalidado), lo que produce fallos de getUser y logouts espurios. El patrón oficial exige copiar las cookies a cualquier NextResponse nuevo que se retorne desde el middleware. (La redirección a /login con user==null en la línea 66 sí es aceptable porque no hay sesión que refrescar.)

**Evidencia (código real)**:
```
middleware.ts:86-90 `if (needsMfa) { const url = request.nextUrl.clone(); url.pathname = '/login/mfa'; return NextResponse.redirect(url) }` — no se transfieren las cookies de `supabaseResponse` (construido en set() líneas 25-34) a la redirección
```

**Corrección propuesta**:
```
Copiar las cookies de supabaseResponse a la respuesta de redirect:

```ts
if (needsMfa) {
  const url = request.nextUrl.clone()
  url.pathname = '/login/mfa'
  const redirect = NextResponse.redirect(url)
  supabaseResponse.cookies.getAll().forEach((c) => redirect.cookies.set(c))
  return redirect
}
```
```

**Notas del verificador sobre el fix**: Fix correcto: copiar supabaseResponse.cookies.getAll() al redirect preserva los tokens rotados. forEach((c) => redirect.cookies.set(c)) funciona en Next 14 (RequestCookie objects son aceptados por cookies.set). No rompe nada: si no hubo refresh, getAll() está vacío y es no-op.

**Referencia oficial**: https://supabase.com/docs/guides/auth/server-side/nextjs

<details><summary>Verificación adversarial</summary>

Confirmado en middleware.ts:86-90: la rama needsMfa retorna NextResponse.redirect(url) nuevo sin copiar las cookies de supabaseResponse, que puede contener los tokens rotados si getUser() (línea 60) refrescó la sesión vía el callback set() (líneas 19-35). El patrón oficial de Supabase para middleware exige copiar cookies a cualquier response nuevo retornado. Escenario alcanzable: usuario con TOTP verified cuya sesión quedó en AAL1 con access token expirado (p.ej. tab abierta en /login/mfa >1h y luego navega a /dashboard) → refresh rota el refresh token → redirect descarta los Set-Cookie → el cliente conserva el token viejo → siguiente refresh fuera del reuse interval (~10s default) dispara r […]

</details>

---

### F136 · ⚪ LOW — Ruta /api/insights carga product_variations, contacts y conversations completos del tenant para calcular contadores en JS

**Ubicación**: `apps/web/app/api/insights/route.ts:139` · **Detectado por**: performance · 🆕 nuevo

**Causa**: El módulo inventory trae TODAS las product_variations (sin límite) para contar out_of_stock/low_stock con `.filter().length`; el módulo customers trae todos los contacts (línea 177) y el summary todas las conversations (línea 192). Mismo patrón de agregación client-side: payload creciente + truncamiento silencioso a 1000 filas de PostgREST que alimenta al LLM de insights con números incorrectos (contradice el principio 'el LLM no decide verdad transaccional' si los datos de entrada ya llegan mal).

**Evidencia (código real)**:
```
supabase.from('product_variations').select('id, product_id, attributes, stock_quantity, price')
        .eq('tenant_id', tenantId).order('stock_quantity'),
      ...
      out_of_stock: (varRes.data ?? []).filter(v => (v as { stock_quantity: number }).stock_quantity === 0).length,
```

**Corrección propuesta**:
```
Conteos con head:true y solo filas relevantes acotadas:
```ts
const [outOfStock, lowStock, totalVars, lowRows] = await Promise.all([
  supabase.from('product_variations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).eq('stock_quantity', 0),
  supabase.from('product_variations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId).gt('stock_quantity', 0).lte('stock_quantity', threshold),
  supabase.from('product_variations').select('id', { count: 'exact', head: true }).eq('tenant_id', tenantId),
  supabase.from('product_variations').select('id, product_id, attributes, stock_quantity, price').eq('tenant_id', tenantId).lte('stock_quantity', threshold).order('stock_quantity').limit(50),
])
```
Aplicar el mismo patrón a contacts (with_consent/without_consent con head counts) y conversations.
```

**Notas del verificador sobre el fix**: Correcto: head:true counts + lowRows limit(50) acota también lo que entra al prompt. Aplicar igualmente al módulo orders (:159-160, trae 30d sin límite) y verificar que el prompt use los agregados y no listas crudas. Bajo impacto: solo afecta calidad del texto de insights, no verdad transaccional.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/configuration.html#db-max-rows

<details><summary>Verificación adversarial</summary>

Confirmado en app/api/insights/route.ts: product_variations completas sin límite (:139-140) con filter().length para out_of_stock/low_stock (:150-154), contacts completos (:177-178), conversations completas (:192). Peor aún: el array `variations` completo se inyecta al prompt de Gemini vía JSON.stringify(data) (:28, :145), así que el truncamiento a 1000 filas alimenta conteos incorrectos al LLM y el payload del prompt crece con el catálogo. Ruta alcanzable desde UI (AiInsightPanel, owner/manager). Sin defensa server-side.

</details>

---

### F137 · ⚪ LOW — Página de Catálogo hace dos fetches completos (activos + archivados) con las 12 columnas de cada variante y sin paginación — productos invisibles a partir de la fila 1001

**Ubicación**: `apps/web/app/dashboard/(products)/catalog/page.tsx:49` · **Detectado por**: performance · 📌 ya rastreado (audit finiquito §2 Productos — bug MEDIUM 'list_products... el frontend filtra cliente-side trayendo TODAS las rows... Sin pagination real (catalog/page.tsx:33-49 trae todo activo + todo archivado)' + gap funcional 'Búsqueda real / paginación') · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: Dos queries paralelas idénticas (status=active y status=inactive) sin `.limit()`/`.range()`, cada una embebiendo product_variations con todas las columnas (dimensiones, costos, image_url). El backend soporta explícitamente tenants de hasta MAX_CATALOG_PRODUCTS=1000 productos (catalog_tool.py:15, cota diseñada en ADR-0027), pero esta página truncaría silenciosamente en 1000 filas PostgREST: un tenant grande no vería parte de su catálogo y el payload SSR por visita serían MBs.

**Evidencia (código real)**:
```
supabase
        .from('products')
        .select(`id, title, description, safety_note, cover_image_url, platform_category_id, category_id, attributes,
                 retracto_excluded, retracto_excluded_reason,
                 product_variations(id, sku, cost_price, price, compare_at_price, stock_quantity, attributes, weight_kg, length_cm, width_cm, height_cm, image_url)`)
        .eq('tenant_id', tenantId)
        .eq('status', 'active')
        .order('title'),
```

**Corrección propuesta**:
```
Paginación server-side con count para la tabla (searchParam `page`):
```ts
const PAGE_SIZE = 100
const page = Number(searchParams?.page ?? 1)
const from = (page - 1) * PAGE_SIZE
const activeRes = await supabase
  .from('products')
  .select(`id, title, ..., product_variations(...)`, { count: 'exact' })
  .eq('tenant_id', tenantId)
  .eq('status', 'active')
  .order('title')
  .range(from, from + PAGE_SIZE - 1)
```
y cargar los archivados lazy (solo al abrir la pestaña de archivados) en vez de siempre en paralelo.
```

**Notas del verificador sobre el fix**: La paginación server-side como está planteada rompe funcionalidad existente: ProductsManager calcula lowStockCount/zeroStockCount sobre allVariations de la lista completa (products-manager.tsx:53-54) y su búsqueda/filtrado es client-side — con range() esos contadores y la búsqueda solo verían la página actual. Fix completo exige rework del componente (counts vía head:true, búsqueda server-side). Alternativa de menor riesgo alineada a la cota ADR-0027: .limit(1000) explícito + carga lazy de archivados al abrir la pestaña.

**Referencia oficial**: https://docs.postgrest.org/en/stable/references/configuration.html#db-max-rows

<details><summary>Verificación adversarial</summary>

Confirmado en catalog/page.tsx:48-76: dos fetches paralelos (active + inactive) con 12 columnas de product_variations embebidas, sin .limit()/.range(); los archivados se cargan SIEMPRE aunque no se abra esa pestaña. MAX_CATALOG_PRODUCTS=1000 confirmado (catalog_tool.py:15) y max_rows=1000 (config.toml:18): el truncamiento coincide exactamente con la cota diseñada del backend, así que dentro del envelope soportado (≤1000 productos) no hay pérdida de datos — el bug de 'productos invisibles' solo aparece al exceder la cota de diseño. Real como ineficiencia (payload SSR creciente + fetch archived innecesario), pero el escenario de corrección es marginal hoy. Severidad low es correcta.

</details>

---

### F147 · ⚪ LOW — Identificador corto de pedido inconsistente dentro del mismo módulo Reclamos: el selector muestra los ÚLTIMOS 8 chars del UUID y el detalle/Pedidos los PRIMEROS 8

**Ubicación**: `apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx:348` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: orders-manager.tsx:371 y el detalle de claims (l.232) abrevian el pedido como `id.split('-')[0].toUpperCase()` (primer segmento del UUID), pero el Select de creación de reclamo usa `o.id.slice(-8).toUpperCase()` (últimos 8). El operador que crea un ticket con '#B0C4DE12' no puede correlacionarlo después con 'Pedido 3F2A19B0' en la lista de Pedidos ni en el propio detalle del ticket — son extremos opuestos del mismo UUID.

**Evidencia (código real)**:
```
claims-manager.tsx:348 `#{o.id.slice(-8).toUpperCase()} — ${o.total_amount?.toLocaleString('es-CO') ?? '0'}` vs claims-manager.tsx:232 `Pedido {selectedClaim.order.id.split('-')[0].toUpperCase()}` y orders-manager.tsx:371 `{o.id.split('-')[0].toUpperCase()}`.
```

**Corrección propuesta**:
```
Centralizar la convención en un helper y usarlo en ambos módulos:
```ts
// apps/web/lib/format.ts
export const shortOrderId = (id: string) => id.split('-')[0].toUpperCase()
```
```tsx
// claims-manager.tsx l.348
<SelectItem key={o.id} value={o.id}>
  #{shortOrderId(o.id)} — ${o.total_amount?.toLocaleString('es-CO') ?? '0'}
</SelectItem>
```
```

**Notas del verificador sobre el fix**: Helper centralizado correcto (split('-')[0] = primer segmento de 8 hex chars, alinea con la convención dominante orders/claims-detalle). Ampliar el barrido a shipping/page.tsx:220,236 y shipping-quote-form.tsx:265 que también usan slice(-8) — si no, la inconsistencia solo se traslada de módulo.

<details><summary>Verificación adversarial</summary>

Confirmado carácter por carácter: claims-manager.tsx:348 `o.id.slice(-8).toUpperCase()` (últimos 8) vs :232 `selectedClaim.order.id.split('-')[0].toUpperCase()` (primeros 8) y orders-manager.tsx:371 igual al segundo. Son extremos opuestos del mismo UUID dentro del mismo flujo (crear ticket → ver ticket → correlacionar con Pedidos). Además el grep revela que la inconsistencia es más amplia de lo reportado: shipping/page.tsx:220,236 y shipping-quote-form.tsx:265 también usan slice(-8).

</details>

---

### F79 · ⚪ LOW — formatPhone duplicado con implementaciones divergentes: Inbox y Contactos renderizan el mismo teléfono no-colombiano de forma distinta, pese a que el comentario promete 'Mismo formato que Inbox'

**Ubicación**: `apps/web/app/dashboard/(sales)/contacts/_components/helpers/phone-countries.ts:33` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: Existen dos `formatPhone`: inbox/_lib/format.ts:16 (solo formatea CO de 12 dígitos; el resto cae a `+${digits}` sin espacio) y contacts/helpers/phone-countries.ts:33 (detecta 10 prefijos y separa `+${p} ${resto}`). contacts-manager.tsx:152-153 documenta la intención de paridad ('Mismo formato que Inbox') que ya no es cierta: un cliente mexicano (+52) se ve `+525512345678` en Inbox y `+52 5512345678` en Contactos. Cualquier mejora futura (nuevos países) se hará en una copia y no en la otra.

**Evidencia (código real)**:
```
inbox/_lib/format.ts:16-21: `export const formatPhone = (raw: string): string => {\n  const digits = (raw || '').replace(/\\D/g, '')\n  if (digits.startsWith('57') && digits.length === 12)\n    return `+57 ${digits.slice(2, 5)} ...`\n  return digits ? `+${digits}` : (raw || '')` vs phone-countries.ts:33-47 con loop de prefijos `['593', '52', '54', '55', '56', '51', '57', '58', '34', '1']`
```

**Corrección propuesta**:
```
Consolidar en `apps/web/lib/format-phone.ts` con la implementación completa (la de phone-countries.ts, que es superset) y re-exportar desde ambos módulos para no romper imports:
```ts
// apps/web/lib/format-phone.ts  (mover aquí el cuerpo de phone-countries.formatPhone)
export const formatPhone = (raw: string): string => { /* impl actual de phone-countries.ts:33 */ }
```
```ts
// inbox/_lib/format.ts
export { formatPhone } from '@/lib/format-phone'
```
```ts
// contacts/helpers/phone-countries.ts
export { formatPhone } from '@/lib/format-phone'
```
```

**Notas del verificador sobre el fix**: Consolidar en apps/web/lib/format-phone.ts con la implementación de phone-countries (superset, con el orden de prefijos largo→corto que evita el match prematuro de +1) y re-exportar desde ambos módulos es correcto y no rompe imports. Verificar si existen tests de inbox/_lib/format.ts que asserten el output viejo `+${digits}` para números no-CO y actualizarlos.

<details><summary>Verificación adversarial</summary>

Confirmado: dos formatPhone divergentes — inbox/_lib/format.ts:16-21 (solo CO 12 dígitos; resto cae a `+${digits}` sin espacio) vs phone-countries.ts:33-48 (CO + loop de 10 prefijos con espacio, superset). El comentario de paridad existe en contacts-manager.tsx:152 ('Mismo formato que Inbox') y ya es falso: +52 5512345678 renderiza `+525512345678` en Inbox y `+52 5512345678` en Contactos. Divergencia introducida en Rev. 103 sin backport; no hay módulo compartido (apps/web/lib no tiene format-phone).

</details>

---

### F148 · ⚪ LOW — Accesibilidad: botones icon-only sin nombre accesible (paginación '<'/'>' y limpiar búsqueda) — solo 21 aria-label en toda la app

**Ubicación**: `apps/web/app/dashboard/(sales)/orders/_components/orders-manager.tsx:446` · **Detectado por**: ux-ui · 🆕 nuevo

**Causa**: Los controles de paginación de orders-manager (l.442-448) y contacts-manager (l.1414-1418) renderizan `<span>{'<'}</span>` / `<span>{'>'}</span>` sin aria-label (un lector de pantalla anuncia 'menor que, botón'); el botón X de limpiar búsqueda (orders-manager.tsx:276) tampoco tiene nombre accesible. Los icon-buttons de promotions (Pencil/Power/Trash2) dependen solo de `title`. `grep -rn aria-label apps/web/app apps/web/components` arroja 21 hits en 191 archivos — el sidebar sí lo hace bien (l.220 'Abrir menú'), el resto no siguió el patrón.

**Evidencia (código real)**:
```
orders-manager.tsx:442-443 `<Button variant="outline" size="sm" className="w-8 h-8 p-0" disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}> <span>{'<'}</span>` — sin aria-label; orders-manager.tsx:276 `<button onClick={() => setSearch('')} className="absolute right-3 …"><X className="h-3.5 w-3.5" /></button>`; conteo global: 21 `aria-label` en todo apps/web.
```

**Corrección propuesta**:
```
```tsx
// orders-manager.tsx paginación
<Button variant="outline" size="sm" className="w-8 h-8 p-0" aria-label="Página anterior"
  disabled={currentPage === 1} onClick={() => setCurrentPage(p => p - 1)}>
  <ChevronLeft className="h-4 w-4" aria-hidden="true" />
</Button>
<Button variant="outline" size="sm" className="w-8 h-8 p-0" aria-label="Página siguiente"
  disabled={currentPage === totalPages} onClick={() => setCurrentPage(p => p + 1)}>
  <ChevronRight className="h-4 w-4" aria-hidden="true" />
</Button>
// limpiar búsqueda l.276
<button aria-label="Limpiar búsqueda" onClick={() => setSearch('')} …>
```
Mismo tratamiento en contacts-manager y aria-label espejo del title en los icon-buttons de promotions-manager.
```

**Notas del verificador sobre el fix**: Correcto. Detalle de implementación: ChevronLeft NO está importado en orders-manager.tsx (ChevronRight y X sí) — agregar al import de lucide-react; igual verificación en contacts-manager. Alternativa mínima sin cambiar iconografía: mantener los spans y solo añadir aria-label, reduciendo el diff visual. Extender a los icon-buttons de promotions (Pencil/Power/Trash2) como indica el fix.

<details><summary>Verificación adversarial</summary>

Confirmado: orders-manager.tsx:442-448 botones de paginación con `<span>{'<'}</span>`/`<span>{'>'}</span>` sin aria-label; contacts-manager.tsx:1414-1420 idéntico; orders-manager.tsx:275-278 botón X de limpiar búsqueda solo con icono lucide sin nombre accesible. Conteo verificado: 21 aria-label en todo apps/web/app + components. El propio repo tiene el patrón correcto (sidebar 'Abrir menú') pero no se propagó. Sin defensa (no hay eslint-plugin-jsx-a11y con regla de nombre accesible activa que lo hubiera bloqueado — ESLint pasa con 0 warnings según commit 7b93f023).

</details>

---

### F80 · ⚪ LOW — Formato de moneda inconsistente: Finance y Compras usan toLocaleString() SIN locale (separador depende del browser del usuario) mientras el resto del dashboard fija es-CO; formatCOP además duplicado

**Ubicación**: `apps/web/app/dashboard/finance/_components/finance-dashboard.tsx:87` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: finance-dashboard.tsx:87, purchase-orders-manager.tsx:187/195 y expenses-manager.tsx:118 formatean dinero con `toLocaleString()` sin argumento — el separador de miles depende del locale del browser (en-US → '$1,000'; es-CO → '$1.000') — mientras orders-manager, catalog-table, shipping-quote-form, claims-manager, marketplace-manager y metrics fijan `'es-CO'`. Un operador con browser en inglés ve $1,250,000 en Finanzas y $1.250.000 en Pedidos en la misma sesión. promotions-manager.tsx:41 además define su propio `formatCOP` (con semántica centavos÷100 distinta al resto, que opera en pesos). No existe helper compartido de moneda.

**Evidencia (código real)**:
```
finance-dashboard.tsx:87: `const fmt = (n: number) => `$${Math.round(n).toLocaleString()}`` vs orders-manager.tsx:385: `${revenue.toLocaleString('es-CO', { minimumFractionDigits: 0 })}`
```

**Corrección propuesta**:
```
```ts
// apps/web/lib/format-money.ts
/** Formatea pesos COP (unidad: pesos, no centavos). */
export const formatCOP = (pesos: number): string =>
  `$${Math.round(pesos).toLocaleString('es-CO', { minimumFractionDigits: 0 })}`
```
Sustituir: finance-dashboard.tsx:87 `const fmt = formatCOP`; purchase-orders-manager/expenses-manager usar `formatCOP(o.total_amount)`; en promotions-manager conservar la conversión centavos→pesos en el call-site: `formatCOP(c.discount_value)` para fixed_amount (documentando la unidad del campo en el tipo Coupon).
```

**Notas del verificador sobre el fix**: Helper compartido lib/format-money.ts con `toLocaleString('es-CO', {minimumFractionDigits:0})` es correcto y resuelve la inconsistencia. Debe preservarse la conversión centavos→pesos en el call-site de promotions (discount_value en centavos) como el propio fix indica; no romperlo al centralizar. Completo para los 3 sitios señalados.

<details><summary>Verificación adversarial</summary>

Confirmado en código: finance-dashboard.tsx:87 `Math.round(n).toLocaleString()`, purchase-orders-manager.tsx:187/195 `o.total_amount.toLocaleString()`/`i.unit_cost.toLocaleString()`, y expenses-manager.tsx:118 `e.amount.toLocaleString()` — todos SIN locale. Los tres son componentes `'use client'`, así que en runtime browser el separador de miles depende del locale del navegador (en-US → coma, es-CO → punto). El resto (orders-manager.tsx:385/395/401, catalog-table.tsx:47/94, marketplace, shipping-quote-form, claims-manager, metrics) fija `'es-CO'`. Inconsistencia real de UI; también riesgo de hydration-mismatch porque el SSR usa locale de Node distinto al del browser. promotions-manager.tsx:4 […]

</details>

---

### F81 · ⚪ LOW — Cobertura inconsistente de loading.tsx: solo 9 de 24 rutas del dashboard tienen skeleton de carga — Finance, Inbox, Purchases, Claims, Promotions, Shipping, Categories, Inventory, Media, Marketplace y Audit navegan con pantalla en blanco

**Ubicación**: `apps/web/app/dashboard/finance/page.tsx:1` · **Detectado por**: frontend-components · 🆕 nuevo

**Causa**: App Router solo muestra feedback instantáneo de navegación si el segmento define loading.tsx. Existen para ai-agents, knowledge-base, metrics, catalog, contacts, orders, integrations, settings y team, pero faltan en 15 rutas con páginas server-side que hacen múltiples queries (finance, purchases, claims, promotions, shipping, categories, inventory, media, marketplace, audit, account, inbox). El operador percibe la app 'congelada' al navegar a esas secciones mientras el RSC resuelve — el mismo tipo de página (manager con tabla) tiene skeleton en Pedidos y nada en Compras. Es exactamente la clase de inconsistencia loading/empty por página que ya se estandarizó a medias.

**Evidencia (código real)**:
```
find apps/web/app/dashboard -name 'loading.tsx' → 9 resultados: (ai)/ai-agents, (ai)/knowledge-base, (analytics)/metrics, (products)/catalog, (sales)/contacts, (sales)/orders, (settings-group)/integrations, (settings-group)/settings, (settings-group)/team — ninguno para finance/, purchases/, (sales)/claims, (sales)/promotions, (sales)/shipping, (products)/categories, (products)/inventory, (products)/media, (channels)/marketplace, (analytics)/audit
```

**Corrección propuesta**:
```
Extraer un skeleton compartido y añadir loading.tsx de 3 líneas a las rutas faltantes:
```tsx
// components/page-skeleton.tsx
export function PageSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-4 max-w-7xl animate-pulse">
      <div className="h-8 w-48 rounded-lg bg-muted" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-16 rounded-xl border border-border bg-muted/40" />
      ))}
    </div>
  )
}
```
```tsx
// app/dashboard/finance/loading.tsx (replicar en las 14 rutas restantes)
import { PageSkeleton } from '@/components/page-skeleton'
export default function Loading() { return <PageSkeleton /> }
```
```

**Notas del verificador sobre el fix**: PageSkeleton compartido + loading.tsx de 3 líneas por ruta es el patrón idiomático de App Router y no rompe nada (loading.tsx es aditivo). Correcto. Verificar que el import `@/components/page-skeleton` coincida con el alias real del repo.

**Referencia oficial**: https://nextjs.org/docs/14/app/api-reference/file-conventions/loading

<details><summary>Verificación adversarial</summary>

Verificado con find: existen 9 loading.tsx (ai-agents, knowledge-base, metrics, catalog, contacts, orders, integrations, settings, team). Faltan en finance/, purchases/, (sales)/claims, (sales)/promotions, (sales)/shipping, (products)/categories, (products)/inventory, (products)/media, (channels)/marketplace, (analytics)/audit, inbox, account — todas con page.tsx server-side que hacen queries (p.ej. finance/page.tsx es `force-dynamic` con 2 queries). Inconsistencia de UX real y factual: mismo patrón manager+tabla tiene skeleton en orders y nada en purchases. Es progressive-enhancement faltante, severidad baja, no un bug funcional.

</details>

---

### F90 · ⚪ LOW — La fila de tenants se consulta 3 veces por render de /dashboard (generateMetadata, layout y page) pese a existir infra React.cache para deduplicar

**Ubicación**: `apps/web/app/dashboard/layout.tsx:77` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: En el mismo render tree: (1) generateMetadata → getCachedTenantName() hace SELECT name (cached-user.ts:104-108), (2) el layout hace su propio SELECT name, logo_url (layout.tsx:77) sin reutilizar el cache, y (3) dashboard/page.tsx:27-31 hace un tercer SELECT name, low_stock_threshold, además secuencial ANTES del Promise.all (waterfall extra). El comentario de cached-user.ts documenta que cada round-trip costó ~640ms en el entorno del founder; la infraestructura de dedupe existe pero el layout y la page no la usan para tenants.

**Evidencia (código real)**:
```
supabase.from('tenants').select('name, logo_url').eq('id', tenantId).single(),  // layout.tsx:77
// cached-user.ts:104
  const { data } = await supabase
    .from('tenants')
    .select('name')
// dashboard/page.tsx:27
  const tenantRes = await supabase
    .from('tenants')
    .select('name, low_stock_threshold')
```

**Corrección propuesta**:
```
Unificar en un solo helper cacheado en utils/supabase/cached-user.ts:

```ts
export const getCachedTenant = cache(async () => {
  const { tenantId } = await getCachedTenantMeta()
  if (!tenantId) return null
  const supabase = createClient()
  const { data } = await supabase
    .from('tenants')
    .select('name, logo_url, low_stock_threshold')
    .eq('id', tenantId)
    .maybeSingle()
  return data
})
```

getCachedTenantName pasa a derivar de getCachedTenant; el layout elimina tenantRes del Promise.all y lee `await getCachedTenant()`; dashboard/page.tsx obtiene low_stock_threshold del mismo helper, eliminando también su await secuencial previo al Promise.all.
```

**Notas del verificador sobre el fix**: Fix correcto en dirección. Dos cuidados: (1) getCachedTenantName hoy normaliza (trim + null si vacío, cached-user.ts:109-110) — al derivarlo de getCachedTenant preservar esa semántica para no romper el fallback 'Tu tienda'; (2) en dashboard/page.tsx el threshold se necesita antes del batch paralelo — el await de getCachedTenant() previo al Promise.all queda, pero es gratis porque generateMetadata/layout ya lo poblaron en el cache del mismo request.

<details><summary>Verificación adversarial</summary>

Confirmado: en el mismo render tree de /dashboard hay 3 SELECTs a tenants: (1) generateMetadata → getCachedTenantName() SELECT name (cached-user.ts:104-108), (2) layout.tsx:77 SELECT name, logo_url dentro del Promise.all (no reutiliza el cache), (3) dashboard/page.tsx:27-31 SELECT name, low_stock_threshold aguardado secuencialmente ANTES del Promise.all (waterfall real, porque lowStockRes necesita el threshold). La infra React.cache existe y está documentada con el costo de ~640ms/round-trip (cached-user.ts:23). Hay un 4to caller en integrations/whatsapp/page.tsx:333 que sí usa el helper cacheado. Hallazgo de perf válido, sin impacto funcional — severidad low correcta.

</details>

---

### F91 · ⚪ LOW — Waterfall de queries secuenciales independientes en purchases (3 round-trips), finance (2) y catalog (2) — paralelizables con Promise.all como ya hace el resto del dashboard

**Ubicación**: `apps/web/app/dashboard/purchases/page.tsx:24` · **Detectado por**: frontend-data · 🆕 nuevo

**Causa**: suppliers (línea 24), purchase_orders (línea 33) y products (línea 49) no dependen entre sí pero se aguardan en serie: la latencia de página es la suma de 3 round-trips en vez del máximo. Mismo patrón en finance/page.tsx:25-37 (orders → expenses) y catalog/page.tsx:18-38 (product_categories → product_attribute_definitions antes del Promise.all). El repo ya estandarizó Promise.all en dashboard/page.tsx, layout.tsx y knowledge-base/page.tsx; estas páginas quedaron fuera de la convención.

**Evidencia (código real)**:
```
const { data: suppliersRes } = await supabase
    .from('suppliers')
    ...
  const { data: posRes } = await supabase
    .from('purchase_orders')
    ...
  const { data: prods } = await supabase
    .from('products')
```

**Corrección propuesta**:
```
```ts
const [{ data: suppliersRes }, { data: posRes }, { data: prods }] = await Promise.all([
  supabase.from('suppliers').select('*').eq('tenant_id', meta.tenant_id).order('name'),
  supabase.from('purchase_orders').select(`id, status, expected_date, total_amount, created_at,
      suppliers(id, name),
      purchase_order_items(id, quantity, unit_cost, variation_id, product_variations(sku, price, products(title)))`)
    .eq('tenant_id', meta.tenant_id).order('created_at', { ascending: false }),
  supabase.from('products').select(`id, title, status,
      product_variations(id, sku, price, cost_price, stock_quantity)`)
    .eq('tenant_id', meta.tenant_id).eq('status', 'active').order('title'),
])
```

Aplicar el mismo refactor en finance/page.tsx (orders + expenses) y catalog/page.tsx (mover product_categories y product_attribute_definitions dentro del Promise.all existente).
```

**Notas del verificador sobre el fix**: El snippet para purchases es correcto (preserva selects, filtros tenant_id y orders). Para catalog notar que pcats/adefs usan ternario condicional en tenantId (líneas 18-25, 32-38): al moverlas al Promise.all del bloque `if (tenantId)` (línea 47) el ternario se elimina limpiamente. Finance tiene guard de role antes de las queries — no afectado. Sin riesgo de regresión.

<details><summary>Verificación adversarial</summary>

Confirmado en los 3 archivos: purchases/page.tsx:24,33,49 (suppliers → purchase_orders → products, tres awaits secuenciales independientes entre sí), finance/page.tsx:25,33 (orders → expenses), catalog/page.tsx:18,32 (product_categories → product_attribute_definitions aguardadas en serie antes del Promise.all de la línea 48). Ninguna query depende del resultado de la anterior. La convención Promise.all ya existe en dashboard/page.tsx:46, layout.tsx:76 y catalog/page.tsx:48, así que es inconsistencia real, no decisión deliberada. Perf-only, severidad low correcta.

</details>

---

## 4. Configuración y buenas prácticas

### F95 · 🟡 MEDIUM — .env.example (referencia canónica declarada) omite ~40 env vars leídas por los servicios y describe mal OPENAI_API_KEY: el tier-4 LLM real es ANTHROPIC_API_KEY, que no aparece

**Ubicación**: `.env.example:149` · **Detectado por**: config-secrets · 🆕 nuevo

**Causa**: Cruce código↔.env.example (verificado con grep de os.getenv sobre services/): faltan entre otras ANTHROPIC_API_KEY, ANTHROPIC_MODEL, LLM_CASCADE_TIERS, todas las AGENTIC_* (AGENTIC_MODEL/TEMPERATURE/MAX_TOOL_TURNS/MAX_TOOL_CALLS/SHADOW_*: el path agentic es el PRIMARIO), TENANT_HARD_DELETE_ENABLED (render.yaml la pone en true pero la referencia canónica no la documenta), HUMAN_TAKEOVER_SLA_HOURS (+NEXT_PUBLIC_HUMAN_TAKEOVER_SLA_HOURS del frontend), CART_ABANDONED_*, WOMPI_VOID_POLL_*, WOMPI_PAYMENT_LINK_TTL_MINUTES, STALE_PROCESSING_*, MESSAGE_COALESCE_*, MULTIMODAL_MODEL, WHISPER_MODEL. Además .env.example:147-149 dice que OPENAI_API_KEY es el "Fallback LLM tier 4" cuando el código la usa SOLO para transcripción Whisper (multimodal_whisper.py:29-30); el rescue tier-4 real usa ANTHROPIC_API_KEY (llm_claude_rescue.py:43, presente en render.yaml:304 pero ausente de .env.example). Onboarding/tuning operativo con documentación incorrecta.

**Evidencia (código real)**:
```
.env.example:147-149: "# [RENDER orchestrator] Fallback LLM tier 4 (rev. 109 cascade multi-vendor). # Solo se invoca si Gemini Flash Lite/Flash/Pro fallan consecutivos. Opcional.\nOPENAI_API_KEY=..." — vs multimodal_whisper.py:30 `return bool(os.getenv("OPENAI_API_KEY"))` (solo Whisper) y llm_claude_rescue.py:43 `if not os.getenv("ANTHROPIC_API_KEY"):` (el tier 4 real, ausente de .env.example)
```

**Corrección propuesta**:
```
Corregir el bloque LLM y añadir las vars faltantes:
```
# [RENDER orchestrator] LLM cascade tier 4 — Claude rescue (llm_claude_rescue.py).
ANTHROPIC_API_KEY="your_anthropic_api_key"
ANTHROPIC_MODEL="claude-sonnet-4-5"
LLM_CASCADE_TIERS=""   # override CSV de tiers (llm_cascade.py)
# [RENDER orchestrator] Whisper fallback transcripción audio (NO es tier LLM).
OPENAI_API_KEY="your_openai_api_key"
# [RENDER orchestrator] Agentic FSM (path primario)
AGENTIC_MODEL="gemini-2.5-flash"
AGENTIC_TEMPERATURE="0.0"
AGENTIC_MAX_TOOL_TURNS="8"
AGENTIC_MAX_TOOL_CALLS="20"
AGENTIC_SHADOW_ENABLED="false"
TENANT_HARD_DELETE_ENABLED="true"
HUMAN_TAKEOVER_SLA_HOURS="2"
NEXT_PUBLIC_HUMAN_TAKEOVER_SLA_HOURS="2"   # debe coincidir con la anterior (inbox UI)
```
y extender el check de scripts/validate.sh sección 7 (hoy solo valida 8 vars) para diffear os.getenv del código contra .env.example.
```

**Notas del verificador sobre el fix**: Direccionalmente correcto y sin riesgo de romper nada (archivo de documentación). Defaults propuestos verificados contra código: AGENTIC_MODEL=gemini-2.5-flash, TEMPERATURE=0.0, MAX_TOOL_TURNS=8, MAX_TOOL_CALLS=20, SHADOW_ENABLED=false (agent.py:47-50, dispatcher.py:34); ANTHROPIC_MODEL=claude-sonnet-4-5 (llm_claude_rescue.py:29). Tres ajustes necesarios: (1) TENANT_HARD_DELETE_ENABLED debe ir 'false' en el example (default de código worker.py:146; es flag destructivo — documentar que prod render.yaml lo pone true), no 'true' como propone. (2) Incompleto: el bloque cubre ~14 de 46 vars faltantes; faltan AGENTIC_SHADOW_TIMEOUT_S (default 30) y los grupos CART_ABANDONED_*, WOMPI_VOID_POLL_*, WOMPI_PAYMENT_LINK_TTL_MINUTES, STALE_PROCESSING_*, MESSAGE_COALESCE_*, MULTIMODAL_MODEL, WHISPER_MODEL, HUMAN_TAKEOVER_SLA_CHECK_INTERVAL_SECONDS. (3) El check automático propuesto en validate.sh necesita allowlist de vars inyectadas por plataforma (RENDER_GIT_COMMIT, RENDER_SERVICE_NAME, RENDER_ENVIRONMENT, NODE_ENV, APP_ENV, OTEL_*) o dará falsos positivos. También corregir el comentario erróneo de render.yaml:306-307 que repite que OPENAI_API_KEY es fallback LLM.

<details><summary>Verificación adversarial</summary>

.env.example:2 se declara 'referencia canónica' y :147-149 describe OPENAI_API_KEY como 'Fallback LLM tier 4', pero el código la usa SOLO para Whisper (agentic/multimodal_whisper.py:30,49); el tier-4 real es Claude vía ANTHROPIC_API_KEY (llm_cascade.py:134 _DEFAULT_TIERS=[3 Gemini + claude-sonnet-4-5]; llm_claude_rescue.py:43,82-86), ausente de .env.example pero presente en render.yaml:304. Diff grep os.getenv sobre services/ confirma 46 vars leídas por código y ausentes del example, incluidas todas las enumeradas (AGENTIC_* x6, LLM_CASCADE_TIERS, ANTHROPIC_MODEL, HUMAN_TAKEOVER_SLA_HOURS, CART_ABANDONED_*, WOMPI_VOID_POLL_*, WOMPI_PAYMENT_LINK_TTL_MINUTES, STALE_PROCESSING_*, MESSAGE_COALES […]

</details>

---

### F102 · 🟡 MEDIUM — CSP de producción incluye 'unsafe-eval' en script-src, contra la recomendación oficial de Next.js

**Ubicación**: `apps/web/next.config.js:139` · **Detectado por**: best-practices-docs · 🆕 nuevo

**Causa**: La política CSP global aplica `script-src 'self' 'unsafe-inline' 'unsafe-eval'` de forma incondicional (mismo valor en dev y en producción). La doc oficial de Next.js indica explícitamente: "'unsafe-eval' is not required for production. Neither React nor Next.js use 'eval' in production by default" y en todos sus ejemplos lo condiciona a `isDev`. Habilitar 'unsafe-eval' en producción amplía la superficie de XSS (permite eval/new Function) sin necesidad funcional.

**Evidencia (código real)**:
```
next.config.js:139 `"script-src 'self' 'unsafe-inline' 'unsafe-eval'",` — sin gate por NODE_ENV, se sirve igual en producción (headers() aplica securityHeaders a source '/(.*)')
```

**Corrección propuesta**:
```
Condicionar 'unsafe-eval' a desarrollo:

```js
const isDev = process.env.NODE_ENV === 'development'
// ...
"script-src 'self' 'unsafe-inline'" + (isDev ? " 'unsafe-eval'" : ''),
```
Opcionalmente migrar a CSP basada en nonce vía proxy/middleware (ya existe middleware.ts) para además eliminar 'unsafe-inline'.
```

**Notas del verificador sobre el fix**: Fix correcto y seguro: gate por NODE_ENV funciona porque next.config.js se evalúa con NODE_ENV=development en `next dev` (que sí requiere unsafe-eval para HMR/eval-source-map) y production en build/start de Render. Verificar tras el cambio que ninguna dependencia del bundle prod use eval/new Function (Next/React no lo hacen; no se detectaron libs sospechosas). La migración a nonce vía middleware es la mejora sustantiva pero es un cambio mayor separado.

**Referencia oficial**: https://nextjs.org/docs/app/guides/content-security-policy

<details><summary>Verificación adversarial</summary>

Confirmado en next.config.js:139: "script-src 'self' 'unsafe-inline' 'unsafe-eval'" es estático, sin gate por NODE_ENV (grep de isDev/NODE_ENV en next.config.js = 0 hits), y headers() lo aplica a source '/(.*)'  (líneas 175-179), o sea idéntico en producción. La doc oficial de Next.js confirma que 'unsafe-eval' no es necesario en producción. Real, pero severidad matizada: script-src ya incluye 'unsafe-inline' (necesario para hydration sin nonces), que es el agujero dominante — un XSS que pueda inyectar markup ya ejecuta scripts inline sin necesitar eval, así que quitar 'unsafe-eval' aporta hardening marginal mientras 'unsafe-inline' permanezca. Sugiero low; el valor real está en la migración […]

</details>

---

### F96 · 🟡 MEDIUM — RESEND_FROM_EMAIL en render.yaml usa el dominio inverificable 'konvi.local': cuando se configure RESEND_API_KEY, los emails (confirmación de pago + Habeas Data) fallarán silenciosamente

**Ubicación**: `render.yaml:411` · **Detectado por**: config-secrets · 🆕 nuevo · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: Resend exige que el dominio remitente esté verificado (DNS SPF/DKIM); '.local' no es un TLD registrable, por lo que 'noreply@konvi.local' nunca podrá verificarse y la API rechazará cada envío con validation_error. El código trata el fallo como no-crítico (logger + continue), así que al completar el paso founder documentado ("Configurar la key en Render Dashboard") los emails de confirmación de pedido (wompi_webhook.py) y notificaciones Habeas Data (notifications.py) fallarán en silencio. El default de código 'noreply@commerce-ops.local' (wompi_webhook.py:1209) tiene el mismo problema.

**Evidencia (código real)**:
```
render.yaml:410-411: `- key: RESEND_FROM_EMAIL\n        value: "Konvi <noreply@konvi.local>"` y wompi_webhook.py:1208-1210: `from_email = os.getenv("RESEND_FROM_EMAIL", "Konvi <noreply@commerce-ops.local>")`
```

**Corrección propuesta**:
```
Usar el dominio real ya operado en Cloudflare y verificarlo en Resend:
```yaml
      - key: RESEND_FROM_EMAIL
        value: "Konvi <noreply@konvi.co>"   # requiere verificar konvi.co en Resend (SPF+DKIM)
```
INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: 1) Resend → Domains → Add konvi.co, 2) crear registros DNS que indique Resend en Cloudflare, 3) esperar verified. INSUMOS: acceso Resend + Cloudflare. CRITERIO DE EXITO: envío de prueba 200 desde /emails con from=noreply@konvi.co. Mientras tanto, para pruebas usar 'onboarding@resend.dev'.
```

**Notas del verificador sobre el fix**: Direccionalmente correcto (konvi.co en Cloudflare es el dominio real; pasos IH bien definidos) pero INCOMPLETO: 1) Debe también agregar RESEND_FROM_EMAIL al bloque envVars de konvi-api (líneas ~182-183 de render.yaml) — el email de confirmación Wompi corre en el servicio api, que hoy no declara la var y caería al default .local del código. 2) Debe actualizar los defaults de código: notifications.py:22-24 y wompi_webhook.py:1208-1210 ('Konvi <noreply@commerce-ops.local>'), y .env.example:269. 3) Nota: 'onboarding@resend.dev' solo permite enviar al email del dueño de la cuenta Resend — inútil para emails a clientes, válido solo para smoke test. 4) Cloudflare konvi.co tiene Email Routing receive-only: verificar que los registros SPF que pida Resend no colisionen con los de Email Routing (Resend suele usar subdominio send.konvi.co, normalmente sin conflicto).

**Referencia oficial**: https://resend.com/docs/dashboard/domains/introduction

<details><summary>Verificación adversarial</summary>

render.yaml:410-411 fija RESEND_FROM_EMAIL="Konvi <noreply@konvi.local>" (valor concreto, se sincroniza desde blueprint) en konvi-orchestrator. '.local' es TLD reservado mDNS (RFC 6762), imposible de verificar en Resend (que exige dominio remitente verificado con SPF/DKIM — validar en docs oficiales resend.com/docs/dashboard/domains). Peor de lo reportado: el bloque konvi-api en render.yaml NO declara RESEND_FROM_EMAIL (solo RESEND_API_KEY línea 182-183), así que el email de confirmación de pago (wompi_webhook.py:1208-1210) usaría el default de código 'noreply@commerce-ops.local', igual de inverificable. Fallo silencioso confirmado en código: wompi_webhook.py:1232-1238 solo logger.warning y  […]

</details>

---

### F94 · 🟡 MEDIUM — WHATSAPP_CONNECTOR_URL se lee en código pero no existe en .env.example ni render.yaml; el default https://api.konvi.co depende de DNS aún no configurado (OQ-4 ADR-0023)

**Ubicación**: `services/api/routers/integrations.py:141` · **Detectado por**: config-secrets · 📌 ya rastreado (audit finiquito §14c tabla A12-NUEVO 'Configurar dominio estable api.konvi.co para webhook tenant — NECESARIO para producción real' + Plan Model B Fase 6 (cubre la dependencia DNS; la ausencia de WHATSAPP_CONNECTOR_URL en .env.example/render.yaml NO está rastreada)) · ⚠️ FIX requiere ajuste (ver notas)

**Causa**: El endpoint de alta de credenciales WhatsApp devuelve al tenant la webhook_url a registrar en Meta usando os.getenv("WHATSAPP_CONNECTOR_URL", "https://api.konvi.co"). La var no está declarada en .env.example (referencia canónica) ni en render.yaml (ningún servicio), así que en Render siempre aplica el default. Según ADR-0023 OQ-4, el CNAME api.konvi.co → connector está pendiente de acción founder: hoy el onboarding devuelve una URL que no resuelve al connector (konvi-connector.onrender.com) y no hay knob documentado para corregirlo sin redeploy de código.

**Evidencia (código real)**:
```
webhook_base = os.getenv("WHATSAPP_CONNECTOR_URL", "https://api.konvi.co").rstrip("/")  — y docs/adr/0023-...md:150: "OQ-4: Render Starter activation + DNS `api.konvi.co` → connector. Owner: Founder. Timeline: pre-producción real (TBD)."
```

**Corrección propuesta**:
```
Declararla en ambos lados. render.yaml (konvi-api):
```yaml
      # URL pública del connector WhatsApp que se devuelve al tenant en onboarding.
      # Hoy: URL Render del connector. Cambiar a https://api.konvi.co al cerrar OQ-4.
      - key: WHATSAPP_CONNECTOR_URL
        value: https://konvi-connector.onrender.com
```
.env.example (sección SERVICE commerce-ops-api):
```
# [RENDER api] Base pública del connector para la webhook_url mostrada al tenant (Meta).
WHATSAPP_CONNECTOR_URL="http://localhost:8000"
```
```

**Notas del verificador sobre el fix**: Declarar la var es correcto, pero el fix tiene 3 problemas: (1) setear render.yaml a https://konvi-connector.onrender.com hace que el API retorne una URL distinta a la que la UI hardcodea (whatsapp-setup.tsx:95 muestra api.konvi.co) — divergencia UI/API nueva; (2) contradice el diseño de URL permanente de ADR-0023 (tenants tendrían que re-registrar webhook en Meta al cerrar OQ-4); (3) ignora que .env.example:59 ya tiene CONNECTOR_URL huérfana — mejor consolidar en UN nombre (renombrar la lectura a CONNECTOR_URL o borrar la var muerta) y actualizar whatsapp-setup.tsx:95 en el mismo cambio. Nota: el puerto local del connector sí es 8000 según .env.example:59.

<details><summary>Verificación adversarial</summary>

Confirmado: integrations.py:141 lee WHATSAPP_CONNECTOR_URL con default https://api.konvi.co; grep en render.yaml y .env.example retorna 0 hits (verificado, exit 1). ADR-0023:150 confirma OQ-4 (DNS api.konvi.co pendiente founder). Hallazgo adicional que lo refuerza: .env.example:59 declara CONNECTOR_URL="http://localhost:8000" que NINGÚN código lee — el knob existe con nombre equivocado en la referencia canónica, así que ni un operador diligente puede corregir la URL sin redeploy. Mitigante: onboarding es admin-controlado y la UI (whatsapp-setup.tsx:95) muestra la misma URL api.konvi.co, coherente con el diseño de URL permanente del ADR.

</details>

---

### F97 · ⚪ LOW — render.yaml define NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE y el código web lee NEXT_PUBLIC_SENTRY_TRACES_RATE (ídem server): el knob de sampling del frontend es letra muerta

**Ubicación**: `apps/web/sentry.client.config.ts:31` · **Detectado por**: config-secrets · 🆕 nuevo

**Causa**: Divergencia de nombres: render.yaml:84 declara NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE="0.1" pero sentry.client.config.ts:31 lee process.env.NEXT_PUBLIC_SENTRY_TRACES_RATE; sentry.server.config.ts:25 lee SENTRY_TRACES_RATE mientras render.yaml:78 y .env.example:288 declaran SENTRY_TRACES_SAMPLE_RATE (el nombre que sí leen los servicios Python). Hoy no hay impacto porque el default hardcodeado (0.1) coincide con el value, pero cualquier ajuste operativo del sampling vía Render Dashboard en apps/web no tendrá efecto y será difícil de diagnosticar.

**Evidencia (código real)**:
```
sentry.client.config.ts:31: `tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_RATE || 0.1)` vs render.yaml:84: `- key: NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE`; sentry.server.config.ts:25: `Number(process.env.SENTRY_TRACES_RATE || 0.1)` vs render.yaml:78 `SENTRY_TRACES_SAMPLE_RATE`
```

**Corrección propuesta**:
```
Unificar al nombre que ya usan render.yaml y los servicios Python:
```ts
// sentry.client.config.ts:31
-  tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_RATE || 0.1),
+  tracesSampleRate: Number(process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE || 0.1),
// sentry.server.config.ts:25 y sentry.edge.config.ts:18
-  tracesSampleRate: Number(process.env.SENTRY_TRACES_RATE || 0.1),
+  tracesSampleRate: Number(process.env.SENTRY_TRACES_SAMPLE_RATE || 0.1),
```
y actualizar .env.example:293 `NEXT_PUBLIC_SENTRY_TRACES_RATE` → `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE`.
```

**Notas del verificador sobre el fix**: Fix correcto y completo: unifica al nombre que ya usan render.yaml + Python + .env.example:288, incluye los 3 configs TS y actualiza .env.example:293. Nota operativa: NEXT_PUBLIC_* se inlinea en build time — cambios en Render Dashboard requieren rebuild para surtir efecto incluso con el nombre corregido.

<details><summary>Verificación adversarial</summary>

Confirmado con exactitud: render.yaml:84 declara NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE pero sentry.client.config.ts:31 lee NEXT_PUBLIC_SENTRY_TRACES_RATE; render.yaml:78 declara SENTRY_TRACES_SAMPLE_RATE pero sentry.server.config.ts:25 y sentry.edge.config.ts:18 leen SENTRY_TRACES_RATE. Los servicios Python (services/*/observability.py:81) sí leen SENTRY_TRACES_SAMPLE_RATE, alineados con render.yaml. .env.example:293 usa el nombre viejo NEXT_PUBLIC_SENTRY_TRACES_RATE. Sin impacto hoy (default 0.1 coincide con el value), pero el knob operativo del frontend es inerte. Severidad low correcta.

</details>

---

### F98 · ⚪ LOW — render.yaml aún declara META_APP_SECRET, META_VERIFY_TOKEN y ALLOWED_ORIGINS en konvi-connector aunque el runtime del connector no lee ninguna (ADR-0023 ordena removerlas)

**Ubicación**: `render.yaml:121` · **Detectado por**: config-secrets · 🆕 nuevo

**Causa**: Post-rewrite Model B (ADR-0023), el connector resuelve app_secret/verify_token per-tenant desde tenant_integrations + Vault (dependencies/meta.py) — grep confirma que META_VERIFY_TOKEN no la lee nadie y META_APP_SECRET solo el script one-shot scripts/admin/seed_konvi_dev_app_secret_vault.py (que no corre en Render). ALLOWED_ORIGINS tampoco: el connector no monta CORSMiddleware (solo services/api/main.py:107 la lee), pese a que .env.example:50 dice "api + connector". .env.example:85 instruye explícitamente "Remover de Render env vars del servicio". Mantener secretos vivos en un servicio que no los usa amplía superficie de exposición y confunde la rotación (H7).

**Evidencia (código real)**:
```
render.yaml:121-126 (konvi-connector): `- key: META_APP_SECRET\n        sync: false\n      - key: META_VERIFY_TOKEN\n        sync: false\n      - key: ALLOWED_ORIGINS\n        sync: false` — vs grep: único lector `scripts/admin/seed_konvi_dev_app_secret_vault.py:32: meta_app_secret = os.getenv("META_APP_SECRET")` y ALLOWED_ORIGINS solo en services/api/main.py:107
```

**Corrección propuesta**:
```
En render.yaml, bloque konvi-connector, eliminar las tres entradas:
```yaml
-      - key: META_APP_SECRET
-        sync: false
-      - key: META_VERIFY_TOKEN
-        sync: false
-      - key: ALLOWED_ORIGINS
-        sync: false
```
y en .env.example:50 corregir el comentario `ALLOWED_ORIGINS="..."  # api + connector` → `# solo api`. INTERVENCION HUMANA REQUERIDA — RESPONSABLE: founder. PASOS: borrar esas 3 env vars también en Render Dashboard del servicio konvi-connector. CRITERIO DE EXITO: connector redeploy sano con /health 200 y HMAC per-tenant funcionando.
```

**Notas del verificador sobre el fix**: Correcto y completo. Eliminar las 3 entradas de render.yaml es seguro (nada las lee en el connector); sync:false son placeholders de dashboard, por lo que el paso IH de borrarlas también en Render Dashboard es necesario y está incluido. La corrección del comentario .env.example:50 ('api + connector' → 'solo api') es acertada — coincide con que solo services/api/main.py:107 la consume. Criterio de éxito (redeploy /health 200 + HMAC per-tenant) es verificable. Nit menor: al borrar META_APP_SECRET/META_VERIFY_TOKEN de .env.example NO — el fix correctamente las conserva ahí como input del seed script one-shot, solo las quita de Render.

<details><summary>Verificación adversarial</summary>

render.yaml:121-126 (konvi-connector) declara META_APP_SECRET, META_VERIFY_TOKEN y ALLOWED_ORIGINS con sync:false. Grep exhaustivo de os.getenv/environ en services/connector-whatsapp: solo lee vars Sentry/Render (observability.py:74-80) más Supabase/APP_ENV — ninguna de las 3. dependencies/meta.py:237+ resuelve app_secret per-tenant vía Vault (app_secret_secret_id) y verify_token desde tenant_integrations.credentials JSONB, con caches per-tenant (_app_secret_cache/_verify_token_cache) — confirma Model B ADR-0023. ALLOWED_ORIGINS solo la lee services/api/main.py:107; el connector no importa CORSMiddleware. Único lector de META_APP_SECRET es scripts/admin/seed_konvi_dev_app_secret_vault.py:32  […]

</details>

---

### F99 · ⚪ LOW — Archivos scratch trackeados en git pese a que .gitignore ignora scratch/: incluyen tenant UUID real de dev y credenciales de prueba

**Ubicación**: `scratch_test_orch.py:21` · **Detectado por**: config-secrets · 📌 ya rastreado (audit finiquito §10 Deuda técnica — 'Basura abandonada: scratch/test_orch.py + scripts/debug/ — recomendación borrar carpetas enteras' + esfuerzo '1d limpiar scratch/ + scripts/debug/' (los scratch_* de raíz no están listados explícitamente))

**Causa**: .gitignore incluye `scratch/` pero gitignore no des-trackea archivos ya committeados: `git ls-files` muestra scratch/test_orch.py trackeado, y además scratch.js, scratch_test.py y scratch_test_orch.py viven en la raíz donde ningún patrón los cubre. scratch_test_orch.py hardcodea el tenant UUID de dev y scratch.js un email/password de test — contradice la política del propio repo (CLAUDE.md: "scratch/ ... temporales locales") y ensucia la higiene de secretos (contexto H7 rotación).

**Evidencia (código real)**:
```
git ls-files → `scratch.js`, `scratch/test_orch.py`, `scratch_test.py`, `scratch_test_orch.py`; scratch_test_orch.py:21: `tenant_id = "f86ba52f-1932-4467-bc8f-e14bcfad9162" # Test tenant`; scratch.js:14-15: `email: "c.garzon@commerceops.test", password: "password123"`
```

**Corrección propuesta**:
```
```bash
git rm --cached scratch/test_orch.py scratch.js scratch_test.py scratch_test_orch.py
```
y en .gitignore, sección Scratch:
```
 scratch/
 scripts/debug/
+scratch.js
+scratch_test*.py
```
(Los archivos siguen disponibles localmente; solo dejan de versionarse.)
```

**Notas del verificador sobre el fix**: git rm --cached + patrones .gitignore (scratch.js, scratch_test*.py) es correcto y no rompe nada (cero referencias en CI/tests/scripts). Mejora sugerida: usar git rm sin --cached (borrado total) — los scripts están stale (scratch/test_orch.py invoca handle_incoming_message, función que ya no existe según .context/01-state.md:1772) y el audit finiquito ya recomienda eliminarlos; conservarlos localmente no aporta valor.

<details><summary>Verificación adversarial</summary>

git ls-files confirma los 4 archivos trackeados (scratch.js, scratch/test_orch.py, scratch_test.py, scratch_test_orch.py). .gitignore tiene 'scratch/' pero no des-trackea archivos ya committeados y ningún patrón cubre los 3 de raíz. scratch_test_orch.py:20 y scratch/test_orch.py:20 hardcodean tenant UUID f86ba52f-1932-4467-bc8f-e14bcfad9162; scratch.js:13-14 tiene c.garzon@commerceops.test/password123; scratch_test.py:16 otro tenant UUID. Sin defensas: nadie los referencia (grep en *.py/*.sh/*.yml/*.ts solo halla menciones en docs de auditoría). El propio audit (docs/research/audit-finiquito-2026-05-31.md:1677) recomienda borrarlos y .context/01-state.md:1772 documenta que un gemelo en servi […]

</details>

---

## Hallazgos refutados (descartados por verificación adversarial)

Se listan por transparencia — el verificador encontró defensas existentes o el escenario no es alcanzable en runtime:

- **F34** `services/ai-orchestrator/tools/shipping_quote_tool.py` — shipping_quote_tool usa text_utils.normalize_phone (débil) para lookup de contacts en DB, divergente del canónico lib/phone.to_canonical. _Razón_: REFUTADO por reachability. Los únicos 2 usos de text_utils.normalize_phone en el repo son shipping_quote_tool.py:1398 y :1427 (_get_contact_address / _get_contact_shipping_phone), y TODOS sus callsites (shipping_quote_tool.py:1661-1663, 1761-1807) alimentan customer_phone exclusi
- **F51** `services/ai-orchestrator/worker.py` — _poll_wompi_pending_voids_if_due usa httpx.Client síncrono dentro del worker async — bloquea el event loop hasta 10s por transacción (hasta 50 por ciclo), congelando polling de inbound y heartbeat. _Razón_: REFUTADO: el mecanismo del hallazgo mischaracteriza la arquitectura. (1) El heartbeat/health NO se congela por bloquear el loop: /health lo sirve uvicorn en el thread PRINCIPAL mientras el worker corre en su propio event loop en un thread daemon separado (server.py:152-183) — lee
- **F60** `services/connector-whatsapp/dependencies/meta.py` — Cache de secrets per-tenant sin vía de invalidación operable (_cache_invalidate_all tiene CERO callers) y negative-caching de 300s que retrasa onboarding/reconexión. _Razón_: Los hechos base son ciertos (negative-cache de None 300s en meta.py:132/182/348; _cache_invalidate_all sin caller productivo — solo tests/test_meta_hmac_model_b.py:144 como cleanup de fixture), pero existen defensas que refutan el impacto runtime: (1) la afirmación 'sin forma de 
- **F61** `services/ai-orchestrator/integrations/wompi_client.py` — wompi_base_url divergió entre API y orchestrator: ante environment no-canónico la API cae a SANDBOX y el orchestrator a PRODUCTION. _Razón_: REFUTADO por reachability. La divergencia de código ES real (API wompi_client.py:46 default-sandbox case-sensitive vs orchestrator wompi_client.py:22-27 default-production salvo 'sandbox' exacto lowercased) y el pact test prometido tests/test_wompi_void.py NO existe (find vacío) 
- **F67** `apps/web/app/dashboard/finance/actions.ts` — Server actions del web hacen POST a /api/v1/expenses y /api/v1/coupons sin trailing slash contra routers definidos como @router.post("/"): dependen del redirect 307 de Starlette, modo de fallo que el propio repo documenta. _Razón_: Los hechos de código son exactos (verificados: actions.ts:30 y promotions/page.tsx:163 sin slash; expenses.py:29 y coupons.py:102 `@router.post("/")`; main.py:102 sin override de redirect_slashes), pero NO hay escenario de fallo alcanzable hoy: ambas llamadas corren server-side e
- **F88** `apps/web/app/dashboard/(sales)/contacts/page.tsx` — sarAction y sarPrintableAction deciden RBAC (owner/manager) leyendo app_metadata de getSession() sin verificar — viola la regla del repo y la guía oficial Supabase. _Razón_: El código descrito existe (contacts/page.tsx:545 y 581-582 usan getSession().user.app_metadata para el gate owner/manager, divergiendo de deleteContact:455 que usa getUser()). PERO existe defensa efectiva que contiene el impacto, y el propio hallazgo lo admite: ambas actions solo
- **F100** `apps/web/middleware.ts` — @supabase/ssr usa la interfaz de cookies get/set/remove deprecada en lugar de getAll/setAll (riesgo de logouts aleatorios). _Razón_: El patrón get/set/remove existe donde se cita (middleware.ts:15-52, utils/supabase/server.ts:11-33, packages/auth/lib/server-client.ts:9-19, auth/confirm/route.ts:39-49) y está deprecado, pero la evidencia central del hallazgo es incorrecta: verifiqué el @supabase/ssr 0.10.0 INST
- **F118** `services/api/routers/products.py` — El ledger de inventario (stock_movements) diverge del snapshot (product_variations.stock_quantity): patch_variation actualiza stock sin registrar movimiento. _Razón_: El escenario UI afirmado no existe. El form de edición de variante (product-edit-drawer.tsx VariantEditRow, líneas 97-140) NO renderiza input de stock y muestra explícitamente 'El stock se gestiona en Inventario ↓' (línea 102); el único Input name="stock" (línea 438) pertenece al
- **F122** `supabase/migrations/20260501000001_fix_cart_add_item_rpc.sql` — La RPC cart_add_item recalcula conversation_carts.total_cents ignorando discount_cents: fórmula del lado DB divergió de la fórmula Python tras introducir cupones. _Razón_: La divergencia de fórmula es factual (la RPC en 20260501000001 líneas 80-84 computa total = SUM(items) + shipping sin discount_cents, que existe desde 20260515000000), pero NO hay escenario runtime alcanzable: (1) el ÚNICO caller de la RPC en todo el repo es cart_tool.add_item (g
- **F124** `supabase/migrations/20260610000000_consolidate_ai_agents.sql` — ai_agents.pitch y ai_agents.tone quedaron vivas y pobladas (backfill 2026-06-10) pese a que rev. 109 declaró tenants.business_pitch/tono_comunicacion única fuente de verdad — F7 dropeó solo persona_block. _Razón_: REFUTADO por migración que el buscador no vio: supabase/migrations/20260611000000_ai_agents_cleanup_duplicates.sql (rev. 109, un día después de la consolidación) ya ejecutó `ALTER TABLE ai_agents DROP COLUMN IF EXISTS pitch, DROP COLUMN IF EXISTS tone` (líneas 30-32), documentand
- **F131** `services/api/routers/conversations.py` — Endpoint GET /conversations/stats carga TODAS las filas de conversations del tenant para contarlas en Python. _Razón_: El defecto existe en el código del endpoint (conversations.py:79-84, select sin límite + conteo en Python) pero NO hay escenario runtime alcanzable: grep repo-wide de 'conversations/stats' y '/stats' solo encuentra la definición del router (conversations.py:10,68) — cero consumid

## Metodología

1. **Find**: 16 agentes especializados (esquema DB, índices+RLS, tablas duplicadas, endpoints API, aislamiento multi-tenant/IDOR, código muerto orchestrator, corrección agentic, connector WhatsApp, duplicación cross-servicio, componentes frontend, data-fetching/auth, UX/UI, cableado end-to-end, performance, secretos/env, buenas prácticas vs docs oficiales).
2. **Dedup**: consolidación semántica (15 duplicados eliminados).
3. **Verify**: lotes por módulo con verificador adversarial (default: refutar) + re-verificación individual de todos los critical con lente de reproducibilidad runtime. 11 refutados.
4. **Triage**: cruce contra `docs/research/audit-finiquito-2026-05-31.md` + `.context/04-next-steps.md`.