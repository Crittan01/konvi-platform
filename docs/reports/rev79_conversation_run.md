# Rev. 79 — Conversational E2E (2026-04-30T22:07:30+00:00)

**Resumen**: 11 PASS · 3 FAIL · 2 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (119 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ✅ PASS | Respuesta KB incluye cita explícita |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 2 turnos |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL | Tras 7 turnos adaptativos, no se creó contact_row |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | Contacto eliminado (revocación procesada) |
| 9 | Happy path completo | ❌ FAIL | Tras 7 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |
| 11 | Escalación a humano | ✅ PASS | Bot reconoció la petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ✅ PASS | Cotización=True, multi-producto reconocido=True |
| 14 | Cambio ciudad de envío | ✅ PASS | Bot re-cotizó a Medellín |
| 15 | Promesa de link cumplida | ⏭️ SKIP | Conversación no llegó al punto de confirmación en 7 turnos |
| 16 | Wompi APPROVED simulation | ⏭️ SKIP | Sin contact_id — S15 no creó orden |

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
  "preview": "¡hola! 👋 soy sara camila de kaiu living natural. trabajamos cosmética artesanal 100% natural.\n\n*aceites vegetales:*\n* aceite de almendras dulces\n* aceite de argán\n* aceite de coco virgen\n* aceite de r"
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
  "turns": 7,
  "matched_rules": [
    "[Q] prio=1 kws=('?', '¿') q='000 cop*  ¿cuál te gustaría llevar?'",
    "[Q] prio=20 kws=('presentación', 'presentacion') q='¿cuál presentación del *jabón artesanal de coco* te gustaría'",
    "[Q] prio=10 kws=('agregar otro', 'algo más') q='¿te ayudo con algo más?'",
    "[Q] prio=20 kws=('a qué ciudad', 'en qué ciudad') q='¿para qué ciudad sería el envío?'",
    "[Q] prio=15 kws=('servientrega', 'transportadora') q='740 | entrega 30/04/2026  ¿continuamos con la opción *económ'",
    "[Q+ctx] prio=50 kws=('correo', 'email') q='🙏  ¿estás de acuerdo?'"
  ],
  "transcript_tail": [
    {
      "client": "Bogotá",
      "bot": "Envío de 1 unidad de Jabón Artesanal de Coco (Presentación: 60g) a Bogotá D.C.:\n\n* *Económica*: Cabify Express | $6.740 | entrega 30/04/2026\n\n¿Continuamos con la opción *Económica*?"
    },
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo?"
    },
    {
      "client": "Soy Cristian Garzón, correo crittan01@gmail.com, CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
      "bot": ""
    }
  ]
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
  "setup_turns": 7,
  "transcript_tail": [
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo?"
    },
    {
      "client": "Sí acepto, guarden mis datos",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    }
  ],
  "outbound_after_revoke": 1
}
```

### S9 — Happy path completo
```json
{
  "transcript_tail": [
    {
      "client": "Bogotá",
      "bot": "Envío de 1 unidad de Jabón Artesanal de Coco (Presentación: 60g) a Bogotá D.C.:\n\n* *Económica*: Cabify Express | $6.740 | entrega 30/04/2026\n\n¿Continuamos con la opción *Económica*?"
    },
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo?"
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": ""
    }
  ]
}
```

### S10 — Cancelación mid-flow
```json
{
  "setup_turns": 4,
  "preview": "entendido, cancelo tu pedido. 🙏\n\nno hay problema, cuando quieras retomar la compra aquí estaré para ayudarte. ¡que tengas un excelente día!"
}
```

### S11 — Escalación a humano
```json
{
  "preview": "claro, te paso con un asesor que te ayudará de inmediato."
}
```

### S12 — Address conjunto residencial
```json
{
  "asked_tower": false,
  "address_db": {},
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
      "bot": "Claro, para Bogotá el envío tiene un costo de $6.740 COP y la entrega estimada es de 1 a 2 días hábiles.\n\n¿Confirmas para generar tu link de pago?"
    },
    {
      "client": "Sí confirmo",
      "bot": "Listo, para continuar con tu compra y generar el link de pago, necesito tu consentimiento para procesar tus datos personales (nombre, dirección, email, teléfono) con el fin de gestionar tu pedido y envío.\n\n¿Estás de acuerdo?"
    },
    {
      "client": "Sí acepto, guarden mis datos",
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
  "turns": 7,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": false,
  "consent_given": false,
  "transcript_tail": [
    {
      "client": "Bogotá",
      "bot": "Envío de 1 unidad de Jabón Artesanal de Coco (Presentación: 60g) a Bogotá D.C.:\n\n* *Económica*: Cabify Express | $6.740 | entrega 30/04/2026\n\n¿Continuamos con la opción *Económica*?"
    },
    {
      "client": "Sí, esa opción",
      "bot": "¡Perfecto! Voy a continuar con tu pedido. Con tu autorización te pediré algunos datos (nombre, dirección, etc.) para esta compra y futuros pedidos.\n\nSi en algún momento quieres que los borre, solo dímelo. 🙏\n\n¿Estás de acuerdo?"
    },
    {
      "client": "Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
      "bot": ""
    }
  ]
}
```
