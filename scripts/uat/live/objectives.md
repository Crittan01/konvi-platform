# UAT Live — Catálogo de OBJETIVOS

Esta lista reemplaza el directorio `scripts/uat/scenarios/` (eliminado en
rev. 107 2026-05-24). Cada entrada describe **el objetivo a validar**, no
un script ejecutable. La validación se hace dialógicamente turn-a-turn
con `scripts/uat/live/helpers.py` — el agente envía mensajes, lee la
respuesta REAL del bot, formula el siguiente turn en base a esa respuesta
y evalúa coherencia global.

## Por qué no scripts estáticos

Decisión founder 2026-05-24 (ver `feedback_no_static_uat.md` en memoria):
los scripts estáticos pasaban PASS aunque el bot generara texto
incoherente o robotizado en turns posteriores — solo verificaban patrones
aislados, no calidad real de conversación. La validación real es
dialógica: la respuesta del cliente en turn N+1 depende de lo que el
bot dijo en turn N. Como un humano.

## Catálogo (referencia)

### Onboarding + saludo
- **O1 — Primer contacto + saludo (cliente NUEVO)**  
  Bot saluda con patrón B/C según #categorías; ofrece consent.
- **O2 — Primer contacto + saludo (cliente CONOCIDO)**  
  Bot saluda por nombre, patrón A; salta menú; pregunta directo "¿En qué te ayudo?".
- **O3 — Saludo casual / colombiano coloquial**  
  "Quihubo", "buenas, pa", "qué más", "regálame info" — bot mantiene tono natural.

### Catálogo + KB
- **C1 — Consulta de catálogo general** — "qué tienes / qué venden".
- **C2 — Consulta de categoría específica** — "muéstrame los jabones".
- **C3 — KB cita de fuentes** — "los jabones son hipoalergénicos?" → KB query + cita doc.
- **C4 — Off-domain rechazo** — "tienes paracetamol?" → bot rechaza + redirige.

### Multi-producto + variantes
- **M1 — Multi-producto en un mensaje** — "Dame 2 jabones coco 100g y 1 sérum vit C".
- **M2 — Multi-producto SIN variante** — "Quiero jabón y sérum" → bot pide variantes (cuál + cuántos).
- **M3 — Multi-unit del mismo producto** — "Llévame 3 jabones coco 100g".
- **M4 — Cambio de cantidad en cart existente** — "Mejor que sean 5".
- **M5 — Eliminar item del cart** — "Quita el sérum".

### Foto + KB
- **F1 — Petición de foto** — "Mándame la foto del jabón" → `send_product_image`.
- **F2 — Petición foto producto inexistente** — bot disculpa + ofrece alternativas.

### Datos desordenados
- **D1 — Volcado de PII en un solo mensaje** — "Soy Cristian, cédula 1023456789,
  vivo en calle 100 Bogotá, email cristian@x.com" → bot parsea + save_* secuencial.
- **D2 — Datos parciales** — "Soy Cristian" → bot pide siguiente campo, no rechaza.

### Envío
- **E1 — Cotización envío post-cart** — "Envíalo a Bogotá" → `quote_shipping`
  → presenta opciones con rate_id.
- **E2 — Cambio de ciudad mid-flow** — Bogotá → Medellín, bot re-cotiza.
- **E3 — Selección carrier por nombre natural** — "El de Servientrega"
  → `select_carrier(carrier_name=...)`.
- **E4 — Shipping phone alterno** — "Recíbelo en este otro número: 300..."
  → `save_shipping_phone`.

### Resumen + pago
- **P1 — Resumen explícito 📋** antes del link de pago.
- **P2 — Link de pago Wompi** generado tras confirmación.
- **P3 — Cancelación mid-flow** — "Mejor no quiero" → bot cancela + cierra educado.
- **P4 — Confirmación de pago aprobado** (simular wompi APPROVED webhook).
- **P5 — Pago rechazado (DECLINED)** — bot ofrece retry sin perder cart.

### Habeas Data (Ley 1581)
- **H1 — Revocar consentimiento** — "Quita mis datos" → anonimización completa
  + conv cerrada + audit log.
- **H2 — Consent gating** — contact sin consent NO recibe link de pago; bot pide
  consent activamente.
- **H3 — Renewed consent post-anonimización** — cliente vuelve después de revocar,
  flow desde cero.
- **H4 — Operator delete deja audit inmutable** — operador borra contact en UI;
  audit log persiste.

### Cross-canal
- **X1 — Match phone MeLi ↔ WhatsApp** — buyer importado vía MeLi escribe a WA
  → mismo contact (no duplicado), consent preservado.

### Cart + cliente conocido
- **K1 — Cliente conocido happy path completo** — saludo → cart → cotización
  → confirma datos guardados (no re-pide) → resumen → link → pago.
- **K2 — Cliente conocido modifica cart después de payment link** — invalida
  link previo + re-cotiza.
- **K3 — Cliente conocido cambia ciudad mid-flow** — re-cotiza con address
  nuevo, no usa el guardado.

### Cupones (objetivo futuro — backlog)
- **U1 — Aplicar cupón válido**
- **U2 — Código inválido / expirado**
- **U3 — Remover cupón aplicado**
- **U4 — Cupón rechazado post-payment-link**

### Escalación
- **S1 — Cliente pide humano** — "Quiero hablar con una persona" → escalate +
  conv human_takeover.
- **S2 — Bot escalation silenciosa** — Gemini falla N veces → escalación auto
  con notif Telegram, mensaje natural al cliente.

## Cómo correr una validación

```python
# Desde python3.11 REPL del agente:
import sys
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform")
from scripts.uat.live import helpers

# Objetivo K1: cliente conocido happy path completo
conv = helpers.reset_known_customer(city="Bogotá")

helpers.turn(conv, "Hola")
# LEER respuesta → "Buenas, Cristian. Qué bueno verte en KAIU..."
# Formular siguiente turn en base a lo leído.

helpers.turn(conv, "Quiero 2 jabones coco 100g y 1 sérum vit C")
# LEER → bot pide variante del sérum (presentaciones 15/30 ml)

helpers.turn(conv, "30ml")
# LEER → bot confirma cart + pregunta envío

helpers.turn(conv, "Envíalo a Bogotá por favor")
# LEER → bot cotiza, debe presentar opciones reales (no "un momento")

# ... iterar hasta cierre. Si algo falla:
helpers.diagnose(conv, last_n=2)  # tool_call_log + invariantes
helpers.cart_state(conv)           # cart real DB
```

## Reglas para el agente

1. **NUNCA hardcodear lo que esperas que diga el bot** — eso es estático.
   Si vas a verificar "el bot mencionó Medellín", léelo del output real.
2. **Si el bot responde algo raro, NO uses workaround conversacional**.
   Reporta el bug y arregla el root cause (system_prompt o invariant).
3. **Cada objetivo se testea como cliente real**, no como script.
4. **Diagnose siempre con `helpers.diagnose(conv)` cuando algo no encaja**.
