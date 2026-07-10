# ADR-0032 — BLOQUE 0: Endurecimiento de seguridad (P0 PII + tamper-evidence + RLS write-path + MFA gateway)

- **Estado:** Aceptado (2026-07-10)
- **Contexto:** Primer bloque de la remediación production-grade (Prompt Maestro FASE 1),
  derivado de la auditoría `docs/audit/production-readiness-2026-07-09.md`. Cierra el P0 y los
  P1 de seguridad verificados adversarialmente contra HEAD. Una **revisión adversarial
  multi-agente pre-PR** (13 agentes) endureció el bloque: destapó que el gate MFA original
  dejaba crown jewels sin cubrir, que la migración de audit_log cerraba UPDATE/DELETE pero no
  la forja por INSERT, y que `create_claim` compartía el vector del P0 — los tres remediados aquí.

## Decisiones

### 1. Los tools del bot que operan sobre datos de un cliente scopean por cliente (fail-closed)
`get_claim_status` filtraba por `(tenant_id, ticket_number)` — y `ticket_number` es un secuencial
per-tenant — permitiendo a un cliente leer por WhatsApp el reclamo de **otro** cliente del mismo
tenant (PII enumerable). **Decisión:** todo tool que exponga u opere sobre datos ligados a un cliente
debe filtrar por `contact_id == ctx.contact_id`, y **fail-closed** si `ctx.contact_id` no está resuelto
(no correr el query). El aislamiento por tenant NO basta cuando el identificador es adivinable.
El mismo criterio se aplicó a `create_claim` (hallazgo del review): su lookup del pedido filtraba solo
por tenant, permitiendo radicar un reclamo sobre el pedido de otro cliente (misatribución de
`customer_id` / inyección de reclamos); ahora scopea por `contact_id` y hace fail-closed sin contacto.

### 2. `audit_log`: inmutabilidad de filas escritas + anti-forja de atribución (no service_role-only)
`audit_log` tenía una única policy `FOR ALL` sin REVOKE ni trigger → cualquier miembro autenticado
podía UPDATE/DELETE/forjar entradas. **Decisión (dos propiedades):**
(a) **Inmutabilidad**: `REVOKE UPDATE, DELETE FROM authenticated/anon` + trigger `BEFORE UPDATE/DELETE`
que rechaza cuando `auth.role()` es de miembro (`service_role`/retención permitidos).
(b) **Anti-forja de atribución**: policy `RESTRICTIVE FOR INSERT` que ata `user_id` al propio caller
(`auth.uid()`) o `NULL` → un miembro no puede fabricar una entrada atribuida a **otro** usuario
(p.ej. framing del owner). **Nota honesta (corrige una afirmación previa de este ADR):** audit_log
**NO** es service_role-only como `consent_audit_log`/`pii_access_log` — el frontend escribe audit_log
**directo** con el cliente `authenticated` (catalog/team/whatsapp/ai-agents/insights/index-pending),
por lo que revocar INSERT rompería el trail. Se conserva INSERT pero constreñido. Queda como
**follow-up (fuera de BLOQUE 0)** re-routear toda la escritura de audit_log por service_role/API para
alcanzar el mismo patrón que consent_audit_log; hasta entonces un miembro aún puede insertar una entrada
veraz sobre sí mismo o NULL-atribuida (no puede falsificar autoría ajena ni mutar filas). La API escribe
con `service_role` → bypassa RLS. Se corrige además el GRANT faltante de `pii_access_log` (la pestaña de
accesos a PII estaba rota: RLS `TO authenticated` sin `GRANT SELECT`).

### 3. Las tablas de negocio con lógica de servidor son read-only por RLS; la escritura va por la API
`suppliers`/`purchase_orders`/`purchase_order_items` tenían policy `FOR ALL` → escritura directa por
PostgREST del rol `authenticated`, saltándose el RBAC owner-only + `@audit_log` + WAC/stock que viven
en `services/api`. **Decisión (espejo de `expenses`, 20260704154200):** policy `FOR SELECT` únicamente;
sin policy de escritura para `authenticated` → las mutaciones pasan obligatoriamente por la API
(`service_role` bypassa RLS). El frontend LEE directo (se conserva) y ESCRIBE vía `/api/v1/...`.

### 4. El MFA se hace cumplir en el gateway FastAPI, no solo en el middleware web
El gate MFA (F85) vivía solo en el middleware de Next; la API pública FastAPI aceptaba tokens AAL1.
**Decisión:** dependencia `enforce_mfa` que exige **AAL2 si el usuario tiene un factor MFA verificado**
(lookup del factor cacheado 60s, **fail-open** ante error de infra para no tumbar disponibilidad).
**Alcance (endurecido por el review — el set original dejaba crown jewels expuestos):** se aplica a
`settings` (config), `integrations` (credenciales), `expenses`/`purchases` (dinero), y —agregados tras
el review por ser *igual o más* sensibles— `tenant_offboarding` **/export** y **/request-deletion**
(gate por-endpoint: dump total + borrado de cuenta), `data_subject_request` (export/printable de PII
Habeas Data) y `sic_report` (datos de crédito). **NO** se gatea: el router `mfa` (se necesita AAL1-con-
factor para completar el 2º factor), `tenant_offboarding` **/status** y **/cancel-deletion** (deben
correr durante grace/recovery, o se crea un deadlock), ni webhooks (sin JWT). Un test de wiring a nivel
de app fija este contrato. Usuarios sin MFA no se ven afectados.
**`orders` money-movement (decisión delegada por founder — "calidad primero"):** en vez de gatear el
router completo (rompería lecturas de alta frecuencia), se gatearon **solo los endpoints que mueven
dinero**, dejando GETs/creación intactos:
- `PATCH /orders/{id}` (user-only; su transición *cancel* dispara refund/void) → `enforce_mfa` directo.
- `POST /orders/{id}/payment-link` (**dual-auth**: operador *o* el orchestrator/bot vía
  `X-Internal-Service-Secret`) → guard **`enforce_mfa_internal_or_user`** que hace **NO-OP en la llamada
  del bot** (verificación constant-time del secret interno) y aplica AAL2 solo al operador. Esto cierra
  el bypass money-movement **sin romper la generación automática de links del bot** (probado: test
  unitario del skip interno + delegación). `enforce_mfa` deja pasar sesiones AAL2 sin lookup → el
  operador con MFA hace step-up **1×/sesión**, no por acción. `create_order` y `generate-shipping-guide`
  quedan sin gate (no mueven dinero; alto volumen del bot).

## Consecuencias
- **Positivas:** cierra 1 P0 (fuga PII) + los P1 de seguridad; audit_log gana inmutabilidad de filas
  escritas + anti-forja de autoría; el bypass de MFA por la API directa queda cerrado para las
  operaciones sensibles, incluidos los crown jewels (borrado/export de cuenta, export de PII, crédito).
- **Alcance NO cerrado (declarado, no oculto):** audit_log sigue permitiendo INSERT veraz/NULL de
  miembros (falta re-routear la escritura del frontend por service_role — follow-up). `orders` cierra
  el money-movement (PATCH + payment-link); `create_order`/`shipping-guide` sin gate por diseño (no
  mueven dinero). Documentado, no asumido como resuelto.
- **Costo:** `enforce_mfa` en AAL1 hace un lookup de factores (cacheado 60s). Las 3 migraciones requieren
  aplicación manual al remote (protocolo seguro por el drift del ledger) — ver §Intervención humana.
- **Reversible:** el scope de `enforce_mfa` puede ampliarse/reducirse por router/endpoint sin cambio de
  contrato; la policy restrictiva de audit_log es DROP-eable.

## Intervención humana
Aplicar 3 migraciones al remote productivo (protocolo `supabase db query --linked` + `migration repair`):
`20260710000000_b0_audit_log_append_only`, `20260710000010_b0_purchases_rls_read_only`,
`20260710000020_b0_pii_access_log_grant_select`. El código Python (P0 + MFA) se despliega con el push.
