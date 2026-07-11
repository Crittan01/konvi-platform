# ADR-0037 — Mercado Libre: reliability del spine token/webhook + roadmap de habilitación completa

- **Estado:** Aceptado (2026-07-11). Fix de reliability implementado (PR pendiente); roadmap = decisión de secuencia + gates.
- **Contexto:** Tras cerrar BLOQUE D (coherencia de stock, ADR-0036), el founder pidió "investigar y ejecutar todo lo aprovechable para tener ML en la plataforma". Investigación multi-agente (7 agentes, dossier-first sobre `docs/research/mercadolibre-dossier-2026-05-05.md` + audit §MeLi + código).
- **Veredicto de madurez ~40%:** núcleo inbound-commerce sólido y endurecido (~80-85%): OAuth per-tenant Model B + Vault, webhook IPN hardened (IP allowlist + dedup distribuido RPC + rate-limit + 200-en-500ms + validación de `resource` SSRF de ADR-0036), ingesta orders/items/shipments, import unit/bulk, sync de stock bidireccional, consola marketplace. **Ciego en todo lo customer-facing y outbound:** publish catálogo→MeLi (~10%, import-only), Q&A pre-venta (~5%), mensajería post-venta (~5%), claims/mediaciones (~10%, sistema interno pero MeLi-blind).

## Decisión 1 — Reliability del refresh de token (implementado en este PR)

`get_valid_token` (meli_client.py) tiene un **bug real de producción**: el guard de marcado de error
(`if not access_token`) es **código muerto** (la línea 322 ya retorna None si el token es falsy) → un
refresh fallido devuelve siempre el token stale/expirado y **nunca marca `status='error'`** → el tenant
queda en un **401-loop silencioso e indefinido** sin señal "Reconectar". Además, los ~8 callsites async
comparten el refresh_token de un solo uso (MeLi rota en cada refresh) → sin serializar, el 1º rota y los
demás fallan con un token ya inválido.

**Lo que SÍ se ship en este PR (code-only, sin migración, meli_client.py — archivo NO tocado por BLOQUE D
→ independiente):** las mejoras de concurrencia **seguras y sin regresión**:
- **Double-check re-read:** antes de refrescar, re-leer credenciales; si otro caller ya refrescó a un
  token válido, usarlo → evita el refresh redundante (dedup del storm de 8 callsites).
- **Recuperación graceful del perdedor:** en fallo de refresh, re-leer; si el ganador de un refresh
  concurrente ya persistió un token válido, devolverlo (no un token stale/fallido) → menos 401s.
- **Write-before-consume:** el token rotado se persiste a Vault+DB ANTES de retornarlo (un crash entre
  la rotación MeLi y la persistencia perdería el refresh de un solo uso → muerte permanente).
- Tests: `tests/test_meli_token_refresh_reliability.py` (6 casos). Reforzado por revisión adversarial en
  2 pasadas (12 agentes + 1 verificador).

**Por qué se DIFIERE el marcado de error + el single-flight (hallazgo de la revisión adversarial):**
- Un `asyncio.Lock` a nivel módulo NO es loop-portable: `get_valid_token` corre tanto en el loop
  principal (`await`) como en loops EFÍMEROS de `asyncio.run` (path threadpool de wompi_webhook →
  orders.sync). Un Lock compartido cross-loop lanza `RuntimeError: bound to a different event loop` →
  tragado por el `except` → `return None` → sync MeLi omitido → **oversell**. → **se eliminó el lock**.
- Marcar `status='error'` en un fallo de refresh es intrínsecamente **racy sin single-flight real**: el
  'perdedor' de un refresh concurrente (token ya expirado + burst) recibe un 400 (invalid_grant, token
  ya rotado) y, antes de que el ganador persista, marcaría 'error' a una integración SANA → el filtro
  `status='connected'` bloquea el auto-heal → sync omitido → oversell. No se puede distinguir
  "genuinamente muerto" de "perdedor concurrente" sin serializar el refresh.
- **Decisión quality-first:** NO shipear un marcado de error a medias en un path money-critical. El
  surfacing del 401-loop se implementa **junto con** el single-flight cross-loop/cross-réplica (lease /
  advisory lock en DB — misma clase que el single-flight de `sync_meli_stock`, ADR-0036) como el
  **primer follow-up** del Bloque 1. Este PR deja el flujo estrictamente mejor que antes, sin regresión.

## Decisión 2 — Roadmap de habilitación completa (secuencia + gates)

**SAFE_NOW (code-only, sin compromiso externo, verificable — ejecutables por bloques con el método Prompt Maestro):**
1. **Reliability del spine** (este PR = crown jewels 401-loop+single-flight). Resto del bloque (tocan
   archivos de BLOQUE D o worker, van tras merge de #36 / verificación): retry-with-backoff honrando
   Retry-After en los clientes httpx MeLi; single-flight de `sync_meli_stock` (cierra el residual de
   ADR-0036); centralizar `X-Forwarded-For` en un helper hop-aware (default-preserving, 4 callsites);
   `missed_feeds` recovery cron (VERIFY endpoint); corregir drift de doc retry 8→5 + runbook refund.
2. **Console truth-fixes & connection-health:** Seller ID lee `meta.user_id` (no el campo inexistente);
   relabel expiry del access token 6h (no vida de conexión); devolver `meli_condition`+`synced_at` en
   listings; strip de salud de conexión; link a la consola marketplace funcional; botón "sync todo".
3. **Q&A pre-venta ingestión (read-only) + observabilidad:** handler `_process_question` + tabla
   `meli_questions` + tab "Preguntas" con SLA countdown + métrica CBT. Sin auto-respuesta.
4. **Mensajería post-venta ingestión (read-only, worker-safe):** ingesta a `conversations(channel='meli')`
   con `processing_status` NO 'pending' (⚠️ crítico: el worker orquestador poll `inbound`+`pending` SIN
   filtro de canal y responde por WhatsApp a `customer_phone` → un inbound MeLi 'pending' haría que el
   bot WhatsApp respondiera a un comprador MeLi a un teléfono nulo/ajeno). Badge de canal en Inbox +
   banner read-only que deshabilita el envío WhatsApp en hilos MeLi.
5. **Claims/post_purchase ingestión (read-only) + alerta operador:** tabla `marketplace_claims`
   (separada de `claims` interna para no romper sus invariantes) + handler + alerta Telegram. Resolución
   manual en la UI de MeLi.
6. **Publish plumbing (validate-only, flag-gated — NO crea nada vivo):** cache de categorías MeLi,
   predictor de categoría, capa de mapping categoría/atributos (ADR-0029→MeLi con validación SET-membership
   binaria), `create_item`/`validate_item` (POST /items/validate dry-run como palanca de de-risk),
   endpoint publish DEFAULT validate-only + UI preview.
7. **Guardrails outbound dormant & shadow scaffolding (sin cablear — ningún POST dispara):** invariantes
   binarios MeLi (no-contact-info/no-URL/price-stock-matches-catalog), subsets de tools restringidos
   (catálogo+KB only), adaptador single-shot en SHADOW mode, wrappers POST inertes tras flag.

**FOUNDER_GATED (externo/marca/dinero — requieren decisión/acción founder):**
- Suscribir los tópicos customer-facing (questions/messages/claims) en el panel MeLi de CADA tenant
  (INTERVENCIÓN HUMANA per-tenant, Model B). Desplegar la ingestión read-only ANTES de suscribir.
- Curar el mapping real categoría/atributos Konvi→MeLi por vertical (ADR-0029 §8: curaduría humana +
  legal en categorías reguladas).
- GO-LIVE de publish real (flip flag validate-only → POST /items real): crea listings comprables,
  comisión/moderación MeLi → compromiso de marca/dinero. Recomendación: validate-only permanente por
  default; go-live por-tenant con consentimiento explícito.
- Respuesta tipeada por operador a un comprador/mediación (POST /answers, /messages, claim-response) y
  luego automatización autónoma del bot — solo tras shadow-mode UAT + invariantes verdes + subset
  restringido + UAT en sandbox. Claims automation = lo último y más riesgoso (draft-to-review, nunca
  autónomo inicialmente).
- Refund real (Mercado Pago API separada, tópico `payments`) — MeLi/MP reembolsa auto al comprador en
  cancelación forzada; el `cancellation_refund` del código es un KEY de idempotencia de stock, NO dinero.
  NO construir refunds programáticos ahora.
- Activar el hop XFF (setear TRUSTED_PROXY_HOPS a la cuenta real de proxies de Render) — requiere
  verificar la topología (Cloudflare + LB); un conteo errado deja spoofable o rompe TODOS los webhooks.

**VERIFY-OFFICIAL-DOC (bloquean construir sin adivinar — el dossier no pudo fetchear, portal 403):**
`missed_feeds` vs `myfeeds` (endpoint/auth/params/schema); rate-limits + headers Retry-After; topología
proxies Render; schema exacto de POST /items MCO + attributes + pictures format + listing_types +
comisión; endpoints category_predictor vs domain_discovery; el `resource` string exacto del tópico
'messages' + attachments API + ventanas de moderación + pack_id vs order_id; spelling/subscribabilidad
de 'claims' vs 'post_purchase' + la Claims REST API (AUSENTE del dossier — NO inventar paths); umbrales
CBT 2026 MCO exactos; Mercado Pago refund API.

## Consecuencias
- El fix de reliability protege el spine que TODA capacidad presente y futura usa; cierra un bug vivo.
- La secuencia respeta el método Prompt Maestro (un bloque a la vez, checkpoint founder) y product-first
  (compromisos externos gated). Read-only ingestión primero → visibilidad + protege reputación CBT sin
  compromiso externo; publish y automatización después, gated.
- Referencias: [ADR-0023] (Model B per-tenant), [ADR-0024] (invariantes binarios), [ADR-0025]
  (aislamiento tenant), [ADR-0029] (contrato de atributos), [ADR-0036] (stock cross-canal).
