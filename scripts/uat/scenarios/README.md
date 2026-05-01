# E2E Conversational Scenarios — Catálogo reviewable

Cada escenario es un archivo **self-contained** ejecutable directamente:

```bash
python3.11 scripts/uat/scenarios/s06_disordered_data.py
python3.11 scripts/uat/scenarios/s06_disordered_data.py --phone +573125835649 --tenant-id ...
python3.11 scripts/uat/scenarios/s06_disordered_data.py --json     # salida JSON
```

Para correr todos en secuencia con cool-down:

```bash
python3.11 scripts/uat/rev79_conversation_scenarios.py
python3.11 scripts/uat/rev79_conversation_scenarios.py --only 6 9 12
```

## Arquitectura

```
scripts/uat/
├── lib/harness.py              ← infra compartida: driver, rules, send/wait
├── scenarios/
│   ├── sNN_<name>.py           ← lógica del escenario + main standalone
│   └── README.md               ← este archivo
├── rev79_conversation_scenarios.py  ← wrapper para correr todos juntos
└── e2e_chat.py                 ← cliente HTTP existente (no se toca)
```

Cada `sNN_*.py` puede revisarse aislado: docstring + flow esperado +
criterio PASS/FAIL/SKIP visibles al abrir el archivo.

---

## Catálogo

| # | Archivo | Categoría | Flow esperado (síntesis) |
|---|---|---|---|
| 1 | `s01_first_contact.py` | Smoke | C: "Hola" → B: saludo (≥5 chars) |
| 2 | `s02_catalog_query.py` | Catálogo | C: "¿Qué productos tienes?" → B: lista con $/COP/jabón |
| 3 | `s03_kb_citation.py` | KB / regulatorio | C: "política devoluciones" → B: respuesta + cita "Fuente:" |
| 4 | `s04_out_of_domain.py` | Anti-alucinación | C: "¿clima en Bogotá?" → B: NO inventa datos meteo |
| 5 | `s05_photo_request.py` | Multimedia | C: "¿foto del jabón?" → B: imagen O fallback explicativo |
| 6 | `s06_disordered_data.py` | **Captura — dump** | Cliente vuelca nombre+email+CC+dirección en 1 mensaje, debe extraer ≥2/4 |
| 7 | `s07_format_canonical.py` | Formato output | Outbound sin `**` ni `• ` |
| 8 | `s08_revoke.py` | Habeas Data | "elimina mis datos" → contact eliminado o consent_given=False |
| 9 | `s09_happy_path_full.py` | **Compra E2E** | Saludo→producto→ciudad→consent→datos→resumen→orden pending_payment |
| 10 | `s10_cancel_midflow.py` | Abandono | "Cancela" mid-flow → bot acuse cordial, no escala |
| 11 | `s11_human_escalation.py` | Escalación | "asesor humano" → bot escala (no sigue vendiendo) |
| 12 | `s12_address_conjunto.py` | **Address conjunto** | Cliente menciona "conjunto" → bot pide torre/apto |
| 13 | `s13_multi_product.py` | Multi + volumetría | 2 jabones + 1 sérum → cotización por TOTAL |
| 14 | `s14_change_shipping.py` | **Cambio ciudad** | Cotiza Bogotá → "mejor a Medellín" → re-cotiza |
| 15 | `s15_payment_link_delivery.py` | **Anti-alucinación TX** | Bot promete link → debe entregar URL Wompi real |
| 16 | `s16_wompi_approved_simulation.py` | Webhook sandbox | Sim APPROVED firmado → orden=confirmed + stock decrement |

**Críticos (rev. 91)**: S6, S9, S12, S15. Estos validan la captura de datos
y el cierre transaccional. Si fallan, hay regresión arquitectónica.

---

## Flow detallado por escenario crítico

### S6 — Datos desordenados (volcado)

```
T1  C: "Hola, quiero comprar un jabón artesanal de coco"
    B: "¿Cuál presentación te gustaría llevar?"
T2  C: "La de 60 gramos por favor"
    B: "Listo, 1x Jabón... ¿Te ayudo con algo más?"
T3  C: "No, eso es todo"
    B: "¿Para qué ciudad sería el envío?"
T4  C: "Bogotá"
    B: "Envío a Bogotá: * Económica $... ¿Continuamos?"
T5  C: "Sí, esa opción"
    B: "¡Perfecto! Voy a continuar... ¿Estás de acuerdo? Responde *SÍ* o *NO*."
T6  C: "Sí, acepto"   ← rule prio 60 (rev. 91)
    B: "¿Cuál es tu correo electrónico?"
T7  C: VOLCADO COMPLETO: "Soy Cristian Garzón, correo crittan01@gmail.com,
       CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá"
    B: 📋 Resumen del pedido con los 4 campos llenos.

PASS: contact.consent_given=True + ≥2 de 4 campos persistidos.
```

### S9 — Happy path completo (compra fluida)

```
Mismo flow que S6 pero el cliente responde UN dato a la vez (no dump).
T6  C: "Sí, acepto"
T7  C: "crittan01@gmail.com"
T8  C: "Cristian Garzón"
T9  C: "CC 1032414179"
T10 C: "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá"
T11 C: "Sí, confirmo"
    B: link Wompi.

PASS: orden con status pending_payment/confirmed creada en DB.
```

### S12 — Address en conjunto

```
... flow normal hasta address ...
T_n  C: "Conjunto Torres del Parque, Carrera 5 #25-40, Bogotá"
T_n+1 B: detecta conjunto via _detect_building_type_from_text + cross-cutting
        reconciliation rev. 91 → pide torre/apto.
T_n+2 C: "Torre 3, apartamento 401, Conjunto Torres del Parque, ..."

PASS: bot pidió torre/apto OR DB tiene tower+apartment persistidos.
```

### S15 — Promesa de link cumplida

```
Mismo flow que S9. Verifica los outbounds finales:
  • Si hay URL Wompi `checkout.wompi.co/l/...` → PASS.
  • Si bot pidió datos faltantes (FSM enforcement) → PASS.
  • Si bot prometió link en lenguaje natural pero NO entregó URL → FAIL
    (alucinación transaccional, observada en log productivo 2026-04-30 14:10).
```

---

## Cómo revisar un escenario para evaluar si el flow es óptimo

1. Abrir `scenarios/sNN_*.py`.
2. Leer el docstring (FLOW + criterio).
3. Ver las reglas `default_response_rules` en
   [`lib/harness.py`](../lib/harness.py) y los overrides del escenario.
4. Correr aislado: `python3.11 scripts/uat/scenarios/sNN_*.py --json`.
5. Inspeccionar `transcript_tail` en evidencia para ver el diálogo real.
6. Si la secuencia de pregunta→respuesta del HARNESS no es realista, ajustar
   las rules. Si es el BOT que se desvía, ajustar orchestrator.

## Cómo agregar un escenario nuevo

1. Crear `scenarios/sXX_<name>.py` siguiendo la plantilla de S01.
2. Agregarlo al import + tupla `SCENARIOS` en
   [`rev79_conversation_scenarios.py`](../rev79_conversation_scenarios.py).
3. Documentarlo en este README.
4. Correr aislado para verificar que no se interfiere con otros.
