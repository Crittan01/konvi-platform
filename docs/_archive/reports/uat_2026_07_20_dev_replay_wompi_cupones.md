> **⚠️ ARCHIVADO — 2026-08-02.** Reporte de sesión (replay de migraciones a DEV + certificación Wompi/cupones, 2026-07-20) — ejecutado y cerrado; DEV ya tiene ledger. Conservado solo como registro histórico.

---

# UAT 2026-07-20 — Replay de migraciones a DEV + certificación Wompi/cupones

**Entorno**: DEV `konvi-dev` (`qkltqxbhssgnyjqltwcr`), tenant KAIU Dev
`d0000000-0000-0000-0000-000000000001`. PROD no se tocó en ningún momento
(guard `_env_guard` fail-closed en todos los scripts; la CLI de Supabase sigue
linkeada a PROD y NO se usó).

---

## 1. Replay canónico de migraciones a DEV

**Problema de origen**: DEV se había creado como *snapshot*, sin ledger
`supabase_migrations.schema_migrations`. Nadie sabía qué migraciones tenía
realmente aplicadas, y el drift silencioso ya había roto el UAT anterior.

**Ejecución** (`scripts/db/replay_migrations_dev.sh`): 224/224 migraciones
aplicadas sin un solo error, en 518 s. Ledger poblado con las 224 versiones.

**Diseño defendible del teardown**: se vacían los OBJETOS de `public`, **no** se
hace `DROP SCHEMA public`. Un drop borra los *default privileges* de
`supabase_admin`, que el rol `postgres` no puede restaurar → toda tabla creada
después quedaría sin `GRANT` a `anon/authenticated/service_role` y PostgREST
devolvería 403 en todo. Se usa el session pooler (5432), no el de transacciones
(6543), y las migraciones con `CONCURRENTLY` o `BEGIN/COMMIT` explícito se
aplican fuera de transacción envolvente.

### Verificación de fidelidad

No es posible comparar contra PROD (su password fue rotada y no está —ni debe
estar— en el entorno de desarrollo). Se usó la comparación equivalente y más
estricta: contra `tests/dbharness/schema_baseline.sql`, que es el output del
replay-desde-cero de las mismas migraciones y lo que el CI enforcea.

| Objeto | Baseline | DEV | Δ |
|---|---:|---:|---|
| Tablas `public` | 76 | 76 | **0** |
| Funciones `public` | 100 | 100 | **0** |
| Índices `public` | 281 | 281 | **0** |
| Policies | 94 | 104 | +10 *(todas de `storage.objects`; el baseline no cubre ese schema porque `supabase db dump` lo excluye — no es drift)* |

### Drift real que el replay cerró

- **Colas pgmq** `whatsapp_outbound_messages` y `human_takeover_notifications`:
  las crean las migraciones; DEV no las tenía (era el gap que rompía escalación
  y outbound).
- **7 cron jobs**: DEV tenía **0**. Se verificó además que `pg_cron` **sí
  ejecuta en el plan Free** (`expire_stock_reservations` corriendo cada minuto,
  `succeeded`).

**Conclusión**: el schema incompleto de DEV era un gap de *ejecución* (snapshot
en vez de replay), no una consecuencia de estar en una org Free.

---

## 2. UAT de cupones — 9 turnos, conversación real turn-a-turn

Cupones sembrados (`scripts/uat/_setup_dev_coupons.py`): 3 anunciables, 1
targeted, 4 inválidos (inactivo / vencido / no vigente / agotado).

| # | Caso | Resultado |
|---|---|---|
| T1 | "¿tienen promociones?" | **PASS** — lista exactamente los 3 anunciables con sus términos; NO filtra el targeted ni los 4 inválidos |
| T2 | Agregar al carrito | PASS |
| T3 | `AHORRA20K` con subtotal $45.000 (< mínimo $100.000) | **PASS** — "te faltan *$55.000*", cálculo exacto |
| T4 | `VENCIDO` | PASS — "expiró y ya no se puede usar" |
| T5 | `AGOTADO` (1/1 redenciones) | PASS — "llegó a su límite de usos" |
| T6 | `FUTURO` | PASS — informa la fecha exacta de disponibilidad |
| T7 | `INACTIVO` | PASS |
| T8 | `VIP15` targeted (nunca anunciado) | **PASS** — aplica 15% de $45.000 = $6.750 |
| T9 | Agregar ítem con cupón vivo | **PASS** — recálculo a 15% de $174.000 = $26.100 |

DB coherente en todo momento; el índice único parcial "un cupón vivo por
carrito" aguantó las 5 tentativas sucesivas (1 sola redención `applied`).

**Nota positiva**: en T9 el LLM alucinó UUIDs de producto; `add_to_cart` los
rechazó por no pertenecer al catálogo y el invariante `cart_render_coherence`
reescribió la salida para no afirmarle un éxito falso al cliente. La defensa
anti-alucinación funcionó como está diseñada.

---

## 3. UAT de Wompi — 6 escenarios contra el sandbox REAL

Link de pago generado de verdad contra `sandbox.wompi.co`
(`checkout.wompi.co/l/test_W38pVR`, $162.800).

| # | Escenario | Resultado |
|---|---|---|
| W1 | Firma inválida | **PASS** — rechazado (comparación constant-time); orden y pago intactos |
| W2 | APPROVED firmado | **PASS** — orden `confirmed`, pago `approved` + `wompi_txn_id`, stock 12→11 y 22→21, reservas `consumed`, cupón `consumed` (+1), carrito `converted` |
| W3 | Replay del mismo checksum | **PASS** — descartado; sin doble descuento de stock ni doble conteo de cupón |
| W4 | DECLINED tardío sobre orden pagada | **PASS** (orden protegida, `retry_skip` correcto) / **FALLA en el ledger** → hallazgo #2 |
| W5 | APPROVED con monto manipulado (firma válida) | **PASS** (anti-fraude: no confirma) / **FALLA en el ledger** → hallazgo #2 |
| W6 | DECLINED sobre orden pendiente | **PASS** — reserva `released`, email `payment_failed`, **nuevo link** generado, orden intacta |

La ruta de dinero calculó siempre el total correcto ($162.800 = $174.000 +
$14.900 − $26.100), con el descuento **recomputado del lado API** desde la
redención viva (guard anti doble-descuento).

### Alcance NO certificado

La **cotización y selección de carrier (Aveonline)** no está certificada: DEV no
tiene credenciales ni `tenants.shipping_origin`, y **no existe modo simulado para
cotizar** (verificado). Se stubbeó únicamente la llamada HTTP al courier, con el
escritor canónico `cart_tool.set_shipping_meta`; todo lo aguas abajo se ejercitó
de verdad. Certificar esa pata requiere credenciales Aveonline → **founder-gated**.

Como subproducto se verificó que ante fallo del courier el bot **degrada con
gracia y escala a humano** en vez de inventar un envío.

---

## 4. Hallazgos

### #1 — ALTO · El bot afirmó un total equivocado y ningún guard disparó

El bot dijo *"El total con el descuento aplicado es **$167.250**"* con el
carrito real en **$147.900** (Δ $19.350): hizo aritmética sobre un descuento
viejo del historial ($6.750 en vez de $26.100 recalculado).

Causa raíz: `summary_coherence` sólo entra si el texto trae la palabra "Resumen"
o el formato etiqueta `Total: $X`. El patrón exige el monto **contiguo** a
"total", así que la redacción en prosa lo esquiva. Probado determinísticamente:
también se escapan *"El total a pagar es $X"* y *"Quedaría en un total de $X"*.

La DB y el cobro siempre estuvieron correctos — el error quedó confinado al
texto, pero el guard existe precisamente para eso.

**Fix**: patrón adicional de prosa (exige `$`, no cruza oración ni salto de
línea) + reconocer el recap de carrito. Con anti-falso-positivo explícito para
no confundir un listado de catálogo con un resumen de pedido.

### #2 — ALTO · El libro de pagos podía contradecir a la orden

`_upsert_payment_record` escribe `payments.status` **antes** de los guards de
monto/moneda/estado-terminal y sin ninguna máquina de estados. Reproducido en
ambas direcciones:

| orden | pago | cómo |
|---|---|---|
| `confirmed` (pagada) | `declined` | DECLINED tardío: el lookup por `txn_id` falla y el de `(order_id, link_id)` pega en la fila aprobada. Disparador real sin atacante: 2 intentos sobre el mismo link con webhooks fuera de orden (Wompi reintenta a 30m/3h/24h) |
| `pending_payment` (correcta) | `approved` | APPROVED con monto falso: el guard de monto protege la orden, pero el ledger igual quedó "aprobado" |

No hay pérdida de dinero (el estado de la ORDEN se protege bien), pero
`payments` es la fuente de verdad de conciliación.

**Fix**: máquina de estados en el ledger — (1) nunca degradar un pago aprobado;
(2) nunca marcar aprobado si el monto no coincide con el registrado. En ambos
casos se conserva `raw_webhook` (auditoría íntegra) y sólo se congela el estado.

### #3 — MEDIO · Guard de la línea "Descuento" inalcanzable

El guard de Rev. 109 BUG 38d (motivado por riesgo de reclamo SIC) estaba
**después** del early-return "total no parseable", justo el peor caso: un recap
de ítems con precios, sin total y sin mostrar el descuento aplicado.

**Fix**: se evalúa primero; no depende del total afirmado.

### #4 — MEDIO · RPC de redención de cupones inexistente

`services/api/lib/coupons.py` invoca `coupon_increment_redemption` "para
aprovechar PostgreSQL atomicity", pero **ninguna migración la definía**.
Confirmado en el DEV replicado y en runtime:

```
PGRST202 Could not find the function public.coupon_increment_redemption
[COUPON] consume RPC fallback ...
```

Es decir: el camino atómico **nunca** se ejecutó. Cada redención tomaba el
fallback read-modify-write y dejaba un WARNING. Dos webhooks APPROVED
concurrentes del mismo cupón leen el mismo N y ambos escriben N+1 → el contador
subcuenta y `max_redemptions` puede excederse (el CHECK no lo impide: N+1 ≤ max
sigue siendo válido).

**Fix**: migración `20260720120000_coupon_increment_redemption_rpc.sql` —
incremento y tope en UNA sentencia bajo el row lock, con `p_tenant_id`
obligatorio (ADR-0025). Verificado en DEV: incrementa, devuelve NULL en el cupón
agotado, y devuelve NULL con un tenant ajeno.

---

## 4.bis — Regresión introducida por el propio fix #1 (y cómo se atrapó)

Vale la pena registrarlo porque casi se despliega.

La primera versión del fix ensanchaba `_looks_like_summary` con "tu pedido" +
cualquier precio. Al reiniciar el worker y probar **en vivo**, el primer turno ya
falló: a *"¿qué precio tiene el Serum de Vitamina C?"* el bot respondió con los
precios correctos y el invariante la **reescribió** como *"No tengo aún tu pedido
confirmado"*. Es decir: se rompía una respuesta de catálogo correcta — una
regresión **peor que el bug original**.

Causa: el bot usa "para tu pedido" / "a tu carrito" en venta normal
constantemente. Lo que distingue de verdad a un recap es la **línea con
cantidad** (`* 1 *Producto* — *$45.000*`); un listado de catálogo enumera sin
cantidad. Ahora se exigen ambas señales, y el patrón de prosa exige además un
conector (`es/será/sería/de/:`) pegado al `$`.

**La lección**: los tests unitarios pasaban en verde con la versión defectuosa —
sólo el turno real contra el bot lo expuso. Los 7 casos anti-falso-positivo (2 de
ellos reproducidos en vivo) quedaron como tests permanentes.

Verificación posterior al ajuste, en vivo:
- Pregunta de catálogo → respuesta intacta, sin reescritura.
- Con cupón vivo, el bot dijo *"el total actual es de **$93.500**"*: el patrón de
  prosa **sí lo extrajo** y lo validó contra el cart real
  ($110.000 − $16.500 = $93.500) → `invariant=ok`. Antes del fix ese total ni
  siquiera se parseaba.

## 5. Observaciones menores (sin fix, para backlog)

- El tenant DEV no tiene fila en `ai_agents` → cae al fallback "Sara Camila"
  (documentado, no es error).
- `product_categories` vacío en DEV → el catálogo usa el fallback título-head.
  Es un gap del seed, no del código.
- Tras rechazar UUIDs alucinados, el bot pide al cliente repetir el producto en
  vez de usar el `list_catalog` que acaba de traer en el mismo turno. UX
  mejorable; la corrección de fondo (no mentir) funciona.

---

## 6. Reproducibilidad

```bash
REPLAY_CONFIRM=1 bash scripts/db/replay_migrations_dev.sh   # 224 migraciones + ledger
python3.11 scripts/db/bootstrap_dev_sandbox.py             # tenant + owners + agentic
python3.11 scripts/uat/_setup_dev_kaiu_whatsapp.py         # WhatsApp (Vault)
python3.11 scripts/uat/_setup_dev_wompi.py                 # Wompi sandbox (Vault)
python3.11 scripts/uat/_setup_dev_coupons.py               # 8 cupones (3 anunciables + 4 borde + 1 targeted)
python3.11 scripts/seed_kaiu_dev_ux.py                     # catálogo
python3.11 scripts/seed_kaiu_dev_finance.py                # finanzas

python3.11 scripts/uat/e2e_chat.py --tenant-id d0000000-0000-0000-0000-000000000001 send "..." --wait 45
python3.11 scripts/uat/_send_wompi_webhook.py APPROVED            # también: DECLINED | --bad-signature | --amount=N
```

Todos los scripts abortan si el destino no clasifica como `dev-safe`.
