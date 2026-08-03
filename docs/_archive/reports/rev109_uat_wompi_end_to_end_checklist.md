> **⚠️ ARCHIVADO — 2026-08-02.** Checklist de la certificación inicial Wompi E2E (rev. 109, 2026-05-28) — ya cumplida; el flujo está live en prod. Referencia vigente: `docs/integrations/wompi.md`. Conservado solo como registro histórico.

---

# Rev. 109 — Checklist UAT END-TO-END Wompi (acción founder)

**Fecha**: 2026-05-28
**Branch**: `phase-2-agentic-rewrite`
**Pre-requisito**: `RESEND_API_KEY` + `RESEND_FROM_EMAIL` configurados (✓ verificado).

---

## Flow APPROVED — Lo que se valida (8 sistemas)

```
Cliente paga Wompi sandbox
        ↓
[1] Wompi webhook (firma SHA256 + idempotency)
        ↓
[2] payments.status: pending → approved + wompi_txn_id persistido
[3] orders.status: pending_payment → confirmed
[4] stock_reservations: 'active' → 'consumed' + stock_quantity decremented
                                  + stock_movements audit row insertada
[5] EMAIL "Pago recibido" (Resend) → cliente recibe en su email
[6] Aveonline genera guía automática (best-effort ~10-15s)
[7] EMAIL "Guía generada" (si Aveonline OK) → cliente recibe segundo email
[8] WhatsApp con tracking + URL PDF guía → cliente recibe mensaje
[9] Inbox UI: badge agentic_state → POST_PAYMENT + status confirmed
```

### Verificación por sistema

| # | Sistema | Cómo verificar |
|---|---|---|
| 1 | Wompi webhook | Tab Wompi sandbox → ver evento APPROVED enviado |
| 2 | DB payments | Inbox → conversación → cart panel → mostrar status |
| 3 | DB orders | Inbox → conversación → ver "Pedido confirmado" |
| 4 | DB stock | Tenant Console → Catálogo → ver stock_quantity bajó por qty pedida |
| 5 | Email pago | Inbox `crittan01@gmail.com` → "Pago recibido — Pedido #XXXXX" |
| 6 | Aveonline guía | DB shipments → tracking_number real + URL PDF |
| 7 | Email guía | Inbox → "📋 Guía generada — Pedido #XXXXX" |
| 8 | WhatsApp guía | Bot envía 2 mensajes: "Pago confirmado ✅" + "Guía asignada 📋" |
| 9 | Inbox UI | https://kaiu-tenant-console → Inbox → badge "Post-pago" emerald |

---

## Flow DECLINED — Lo que se valida (5 sistemas)

```
Cliente intenta pagar, Wompi rechaza
        ↓
[1] Wompi webhook DECLINED
        ↓
[2] payments.status: pending → declined + wompi_txn_id audit
[3] orders.status: STAYS pending_payment (NO confirma)
[4] stock_reservations: 'active' → 'released' (stock available recupera)
[5] EMAIL "Pago no procesado" (Resend, rev. 109 BRECHA)
[6] Auto-retry: si tenant tiene private_key + amount ≥ $1.500
       → crea NUEVO Wompi link (segundo intento)
       → WhatsApp con nuevo link
       ELSE → WhatsApp "Tu pago no se completó. ¿Te conecto con un especialista?"
[7] Inbox UI: badge → PAYMENT (cliente puede reintentar)
```

### Verificación por sistema

| # | Sistema | Cómo verificar |
|---|---|---|
| 1 | Wompi webhook | Tab Wompi sandbox → ver evento DECLINED enviado |
| 2 | DB payments | DB query: `SELECT status FROM payments WHERE wompi_link_id='XXX'` → declined |
| 3 | DB orders | DB query: `SELECT status FROM orders` → pending_payment (NO confirmed) |
| 4 | DB stock | available_stock RPC vuelve al nivel previo (release exitoso) |
| 5 | **Email pago fallido** (NUEVO) | Inbox `crittan01@gmail.com` → "Pago no procesado — Pedido #XXXXX" |
| 6 | WhatsApp retry | Bot envía nuevo link Wompi O mensaje "Tu pago no se completó" |
| 7 | Inbox UI | Badge sigue PAYMENT, conversación bot_active, no escalada |

---

## Pasos para founder ejecutar

### Pre-requisitos

```bash
# 1. Verificar stack live
make -C /home/ansible/commerce-ops-local status

# 2. Verificar Wompi sandbox tenant en KAIU
# Tenant Console → Integraciones → Wompi → environment=sandbox
# (Si está en production, switchear a sandbox para tests $1.000)

# 3. Verificar email contact
psql ... -c "SELECT email FROM contacts WHERE phone='+573125835649';"
# Debe ser tu email real para recibir notificaciones
```

### Test 1: APPROVED

```
1. Reset:
   python3.11 scripts/wipe_conversation.py --phone +573125835649 --yes

2. WhatsApp al bot:
   "Hola, 1 sérum vit C 30ml, pago online, Bogota, Servientrega"

3. Cuando bot pida consent: "si autorizo"
4. PII: "Cristian Tobon", "CC 1018502222", dirección, email crittan01@gmail.com
5. Bot ofrecerá Wompi link al confirmar.

6. CLICK link Wompi en navegador → pagar con tarjeta de prueba sandbox:
   • Nro tarjeta: 4242 4242 4242 4242
   • Fecha: cualquier futura
   • CVV: cualquier 3 dígitos
   • Wompi sandbox aprueba automáticamente
   (Documentación: https://docs.wompi.co/docs/colombia/ambientes/)

7. Verificar en orden (en este orden):
   [a] WhatsApp del bot: 2 mensajes en ~15-30s
       - "✅ ¡Pago confirmado!"
       - "📋 Guía asignada — Pedido #XXX + tracking + URL"
   [b] Inbox crittan01@gmail.com:
       - Email 1: "Pago recibido — Pedido #XXX"
       - Email 2: "📋 Guía generada — Pedido #XXX"
   [c] Inbox UI (Tenant Console):
       - Conversación con badge "Post-pago" emerald
       - Orden visible en /dashboard/orders con tracking
   [d] Catálogo:
       - Stock del sérum 30ml bajó por 1
```

### Test 2: DECLINED

```
1. Reset (mantén contacto):
   python3.11 scripts/wipe_conversation.py --phone +573125835649 --yes

2. WhatsApp al bot:
   "Hola, 1 jabón coco 100g, pago online, Bogota, Servientrega"

3. Cliente CONOCIDO, datos guardados.
4. Confirmar → Wompi link.

5. CLICK link Wompi → usar tarjeta sandbox DECLINED:
   • Nro tarjeta: 4111 1111 1111 1111  (tarjeta sandbox declined)
   • O en sandbox: usar amount < $1.500 (rechazo automático por monto)
   (Docs: https://docs.wompi.co/docs/colombia/ambientes/#sandbox)

6. Verificar en orden:
   [a] WhatsApp del bot:
       - Si retry exitoso: nuevo link Wompi
       - Si retry falla: "Tu pago no se completó. ¿Te conecto con
                          un especialista?"
   [b] Inbox crittan01@gmail.com:
       - Email: "Pago no procesado — Pedido #XXX"
       - Copy empático invitando a reintentar
   [c] Inbox UI: conversación sigue bot_active, no escalada
   [d] DB:
       - payments.status = declined
       - orders.status = pending_payment (NO confirmed)
       - stock_reservations status = released
       - shipments = empty (NO se generó guía)
```

---

## Criterios certificación

### APPROVED — Todo PASS

- [ ] WhatsApp mensaje "Pago confirmado" llegó
- [ ] WhatsApp mensaje "Guía asignada" con tracking llegó
- [ ] Email "Pago recibido" llegó al inbox
- [ ] Email "Guía generada" llegó al inbox (cuando aplique)
- [ ] DB orders.status = confirmed
- [ ] DB payments.status = approved + wompi_txn_id persistido
- [ ] DB stock_quantity decremented por qty exacta
- [ ] DB stock_movements audit row con reason='reservation_consumed'
- [ ] Inbox UI badge "Post-pago" emerald visible

### DECLINED — Todo PASS

- [ ] WhatsApp mensaje rechazo (con o sin nuevo link según retry)
- [ ] Email "Pago no procesado" llegó al inbox (rev. 109 NUEVO)
- [ ] DB orders.status = pending_payment (NO confirmed)
- [ ] DB payments.status = declined
- [ ] DB stock_reservations status = released (todas las del cart)
- [ ] DB available_stock recupera nivel previo
- [ ] DB shipments empty
- [ ] Inbox UI bot_active

---

## Si algo falla — Cómo diagnosticar

| Problema | Comando |
|---|---|
| WhatsApp no llega | `tail -100 /home/ansible/commerce-ops-local/logs/orchestrator.log \| grep WOMPI` |
| Email no llega | `grep RESEND /home/ansible/commerce-ops-local/logs/orchestrator.log` |
| Stock no decremented | `SELECT * FROM stock_movements WHERE order_id='XXX'` |
| Inbox no actualiza | Refresh manual del Inbox |

---

## Brecha rev. 109 cerrada

**Email DECLINED** (template_mode="payment_failed"):
- Renderiza HTML con desglose pedido + total + carrier + tenant
- Copy empático sin culpar cliente, invita reintentar
- Subject: "Pago no procesado — Pedido #XXXXX"
- 12 tests unitarios PASS (`tests/test_wompi_email_failed.py`)
- Dispatched al inicio del retry flow para garantizar envío inmediato
- Best-effort: si Resend falla, el flow continúa (logs warning)

Antes de rev. 109 — cliente solo recibía WhatsApp del rechazo.
Post rev. 109 — cliente recibe WhatsApp + Email simultáneos.

---

## Próximos validations (post-Wompi)

1. **1 audio WhatsApp** — Gemini Flash transcribe español Colombia
2. **1 foto WhatsApp** — Gemini describe imagen (recibo/etiqueta)
3. **1 cancelación post-orden** — Pendiente diseño (no implementado aún)

Total UAT live final founder: ~30-40 min para autorizar merge a `develop`/`main`.
