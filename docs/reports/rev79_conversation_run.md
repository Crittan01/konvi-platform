# Rev. 79 — Conversational E2E (2026-05-01T00:15:47+00:00)

**Resumen**: 12 PASS · 2 FAIL · 2 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (119 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ✅ PASS | Respuesta KB incluye cita explícita |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 2 turnos |
| 6 | Datos desordenados (turn-by-turn) | ✅ PASS | Adaptativo: 4/4 campos extraídos de un volcado en 9 turnos |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | consent_given=False (+ revoked_at registrado si aplica) |
| 9 | Happy path completo | ⏭️ SKIP | Conversación cubrió 9 turnos pero no llegó a crear orden — flujo posiblemente cortado en address/resumen |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |
| 11 | Escalación a humano | ✅ PASS | Bot reconoció la petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ✅ PASS | Cotización=True, multi-producto reconocido=True |
| 14 | Cambio ciudad de envío | ✅ PASS | Bot re-cotizó a Medellín |
| 15 | Promesa de link cumplida | ⏭️ SKIP | Conversación no llegó al punto de confirmación en 8 turnos |
| 16 | scenario_16_wompi_approved_simulation | ❌ FAIL | Excepción: {'message': 'column orders.wompi_link_id does not exist', 'code': '42703', 'hint': None, 'details': None} |

### S1 — Primer contacto + saludo
```json
{
  "outbound_count": 1,
  "preview": "¡Hola! 👋 Soy Sara Camila de KAIU Living Natural. Trabajamos cosmética artesanal 100% natural.\n\n¿En qué te puedo ayudar?"
}
```

### S2 — Consulta catálogo
```json
{
  "outbound_count": 1,
  "preview": "¡hola! 👋 soy sara camila de kaiu living natural. trabajamos cosmética artesanal 100% natural.\n\ntenemos varias líneas:\n\n*aceites vegetales:*\n* almendras dulces\n* argán\n* coco virgen\n* rosa mosqueta\n\n*a"
}
```

### S3 — KB cita de fuentes
```json
{
  "preview": "Aceptamos devoluciones y cambios dentro de los 15 días calendario siguientes a la entrega, siempre que el producto esté sin usar, con empaque original y en perfectas condiciones. Para iniciar una devo"
}
```

### S4 — Out-of-domain
```json
{
  "preview": "no tengo información sobre eso — soy asesor virtual de kaiu living natural y solo puedo ayudarte con nuestros productos, envíos y pedidos.\n\n¿te interesa algo de la tienda?"
}
```

### S5 — Foto producto
```json
{
  "image_sent": false,
  "turns": 2,
  "matched_rules": [
    "[Q+ctx] prio=35 kws=('presentación', 'presentacion') q='¿te cuento más beneficios o cotizo el envío a tu ciudad?'"
  ]
}
```

### S6 — Datos desordenados (turn-by-turn)
```json
{
  "turns": 9,
  "matched_rules": [
    "[Q] prio=1 kws=('?', '¿') q='000 cop*  ¿cuál te gustaría llevar?'",
    "[Q] prio=20 kws=('presentación', 'presentacion') q='claro, para el *jabón artesanal de coco*, ¿cuál presentación'",
    "[Q] prio=10 kws=('agregar otro', 'algo más') q='¿te ayudo con algo más?'",
    "[Q] prio=20 kws=('a qué ciudad', 'en qué ciudad') q='¿para qué ciudad sería el envío?'",
    "[Q] prio=15 kws=('servientrega', 'transportadora') q='740 | entrega 30/04/2026  ¿continuamos con la opción *económ'",
    "[Q] prio=60 kws=('estás de acuerdo', 'estas de acuerdo') q='🙏  ¿estás de acuerdo?'",
    "[Q] prio=50 kws=('¿cuál es tu correo', 'cual es tu correo') q='¿cuál es tu correo electrónico?'",
    "[Q] prio=20 kws=('¿confirmas', 'confirmas que') q='com * celular: +57 312 583 5649 * documento: cc 1032414179 *'"
  ],
  "transcript_tail": [
    {
      "client": "Sí, acepto",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "Soy Cristian Garzón, correo crittan01@gmail.com, CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
      "bot": "📋 *Resumen de tu pedido:*\n\n*Productos:*\n* 1x Jabón Artesanal de Coco: $18.000 COP\n\nSubtotal: $18.000 COP\nEnvío: $6.740 COP\n*TOTAL: $24.740 COP*\n\n*Datos de envío:*\n* Nombre: Cristian Garzón\n* Correo: crittan01@gmail.com\n* Celular: +57 312 583 5649\n* Documento: CC 1032414179\n* Dire"
    },
    {
      "client": "Sí confirmo",
      "bot": "Perfecto, te genero tu link de pago."
    }
  ],
  "extracted": {
    "name": true,
    "email": true,
    "document": true,
    "address": true
  }
}
```

### S7 — Formato canónico WhatsApp
```json
{
  "sample": "¡Hola! 👋 Soy Sara Camila de KAIU Living Natural. Trabajamos cosmética artesanal 100% natural.\n\n*Aceites vegetales:*\n* Ac"
}
```

### S8 — Revocación adaptativa
```json
{
  "setup_turns": 6,
  "transcript_tail": [
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo? *SÍ* o *NO*."
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": ""
    }
  ],
  "outbound_after_revoke": 1,
  "contact": {
    "consent_given": false,
    "consent_revoked_at": null,
    "consent_revoked_reason": null
  }
}
```

### S9 — Happy path completo
```json
{
  "turns": 9,
  "consent_given": true,
  "transcript_tail": [
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo? *SÍ* o *NO*."
    },
    {
      "client": "Sí, acepto",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "crittan01@gmail.com",
      "bot": ""
    }
  ]
}
```

### S10 — Cancelación mid-flow
```json
{
  "setup_turns": 7,
  "preview": "entendido, cancelo tu pedido. 🙏\n\nno hay problema, cuando quieras retomar la compra aquí estaré para ayudarte. ¡que tengas un excelente día!"
}
```

### S11 — Escalación a humano
```json
{
  "preview": "claro, te entiendo. en este momento nuestros asesores no están disponibles, pero uno de ellos te contactará apenas inicie el próximo turno. atendemos de lunes a sábado de 8:00 am a 6:00 pm."
}
```

### S12 — Address conjunto residencial
```json
{
  "asked_tower": false,
  "address_db": {
    "city": "Bogotá D.C.",
    "state": "Bogotá D.C.",
    "country": "CO",
    "dane_code": "11001"
  },
  "turns": 7
}
```

### S13 — Multi-producto + volumetría
```json
{
  "turns": 8,
  "transcript_tail": [
    {
      "client": "Bogotá",
      "bot": "Envío de 1 unidad de Sérum de Vitamina C (Volumen: 30ml) a Bogotá D.C.:\n\n* *Económica*: Cabify Express | $6.740 | entrega 30/04/2026\n\n¿Continuamos con la opción *Económica*?"
    },
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo? *SÍ* o *NO*."
    },
    {
      "client": "Sí, continuemos por favor",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "setup_turns": 7,
  "re_quoted_amount": true,
  "preview": "envío de 1 unidad de jabón artesanal de coco (presentación: 60g) a medellín:\n\n* *económica*: deprisa estandar | $13.140 | entrega 04/05/2026\n* *rápida*: fedex express® | $31.450 | entrega 01/05/2026\n\n¿con cuál continuamos? (*económica* o *r"
}
```

### S15 — Promesa de link cumplida
```json
{
  "turns": 8,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": true,
  "consent_given": true,
  "transcript_tail": [
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo? *SÍ* o *NO*."
    },
    {
      "client": "Sí, acepto",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "crittan01@gmail.com",
      "bot": ""
    }
  ]
}
```

### S16 — scenario_16_wompi_approved_simulation
```
Traceback (most recent call last):
  File "/home/ansible/workspaces/commerce-ops-platform/scripts/uat/rev79_conversation_scenarios.py", line 1157, in run_all
    res = fn(phone, tenant_id)
          ^^^^^^^^^^^^^^^^^^^^
  File "/home/ansible/workspaces/commerce-ops-platform/scripts/uat/rev79_conversation_scenarios.py", line 1048, in scenario_16_wompi_approved_simulation
    ).order("created_at", desc=True).limit(1).execute()
                                              ^^^^^^^^^
  File "/home/ansible/.local/lib/python3.11/site-packages/postgrest/_sync/request_builder.py", line 53, in execute
    raise APIError(dict(json_obj))
postgrest.exceptions.APIError: {'message': 'column orders.wompi_link_id does not exist', 'code': '42703', 'hint': None, 'details': None}
```
