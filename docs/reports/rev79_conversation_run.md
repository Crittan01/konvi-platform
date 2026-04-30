# Rev. 79 — Conversational E2E (2026-04-30T18:27:25+00:00)

**Resumen**: 10 PASS · 4 FAIL · 2 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (182 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ✅ PASS | Respuesta KB incluye cita explícita |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 2 turnos |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL | Tras 9 turnos adaptativos, no se creó contact_row |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | Contacto eliminado (revocación procesada) |
| 9 | Happy path completo | ❌ FAIL | Tras 9 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |
| 11 | Escalación a humano | ✅ PASS | Bot reconoció la petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ✅ PASS | Cotización=True, multi-producto reconocido=True |
| 14 | Cambio ciudad de envío | ❌ FAIL | Bot no reconoció el cambio de ciudad |
| 15 | Promesa de link cumplida | ⏭️ SKIP | Conversación no llegó al punto de confirmación en 3 turnos |
| 16 | Wompi APPROVED simulation | ⏭️ SKIP | Sin contact_id — S15 no creó orden |

### S1 — Primer contacto + saludo
```json
{
  "outbound_count": 1,
  "preview": "¡Hola! Buenas tardes. Soy Sara Camila de KAIU Living Natural. Puedo ayudarte con nuestros productos naturales para el cu"
}
```

### S2 — Consulta catálogo
```json
{
  "outbound_count": 1,
  "preview": "¡hola! 👋 claro que sí. en kaiu living natural tenemos una línea de cuidado personal con ingredientes 100% naturales. \n\nofrecemos aceites vegetales como almendras dulces, argán, coco virgen y rosa mosq"
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
    "[Q] prio=5 kws=('para qué tipo de piel', 'tipo de piel') q='¿y qué tipo de piel tienes?'",
    "[Q] prio=1 kws=('?', '¿') q='¿y qué tipo de piel tienes?'",
    "[Q] prio=15 kws=('¿deseas cotizar', 'deseas cotizar') q='¿te gustaría cotizar el envío?'",
    "[Q] prio=20 kws=('a qué ciudad', 'en qué ciudad') q='claro, ¿a qué ciudad y departamento necesitas que te lo envi'",
    "[Q] prio=18 kws=('continuemos con tu pedido', 'continuemos con la compra') q='¿te gustaría continuar con la compra?'",
    "[Q] prio=50 kws=('correo', 'email') q='para continuar, ¿me podrías confirmar tu nombre completo, po'",
    "[Q] prio=20 kws=('¿confirmas', 'confirmas que') q='¿confirmas que los datos están correctos para generar tu lin'",
    "[Q+ctx] prio=20 kws=('presentación', 'presentacion') q='¿confirmas para generar tu link de pago?'"
  ],
  "transcript_tail": [
    {
      "client": "Soy Cristian Garzón, correo crittan01@gmail.com, CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
      "bot": "¡Claro, Cristian! Ya tengo tus datos: Cristian, correo crittan01@gmail.com, CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, casa, en Bogotá. El envío tiene un costo de $6.740 COP.\n\n¿Confirmas que los datos están correctos para generar tu link de pago?"
    },
    {
      "client": "Sí confirmo",
      "bot": "¡Genial, Cristian! Tu pedido está listo para generarse. El total es de $24.740 COP (Jabón Artesanal de Coco 60g: $18.000 + Envío: $6.740).\n\n¿Confirmas para generar tu link de pago?"
    },
    {
      "client": "La de 60 gramos por favor",
      "bot": "¡Genial, Cristian! Tu pedido está listo para generarse. El total es de $24.740 COP (Jabón Artesanal de Coco 60g: $18.000 + Envío: $6.740).\n\n¿Confirmas para generar tu link de pago?"
    }
  ]
}
```

### S7 — Formato canónico WhatsApp
```json
{
  "sample": "¡Hola! 👋\n\nEn KAIU Living Natural tenemos una variedad de productos para el cuidado de tu piel y bienestar. Manejamos ace"
}
```

### S8 — Revocación adaptativa
```json
{
  "setup_turns": 7,
  "transcript_tail": [
    {
      "client": "Sí acepto, guarden mis datos",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": ""
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
      "client": "Sí confirmo",
      "bot": "Perfecto. Para generar tu link de pago, necesito algunos datos.\n\n📋 *Resumen de tu pedido:*\n\n*Productos:*\n* 1x Jabón Artesanal de Coco (Presentación: 60g): $18.000 COP\n\nSubtotal: $18.000 COP\nEnvío a Bogotá: $6.740 COP\n*TOTAL: $24.740 COP*\n\n¿Cuál es tu nombre completo, por favor?"
    },
    {
      "client": "Cristian Garzón",
      "bot": "Listo, Cristian.\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "crittan01@gmail.com",
      "bot": "Perfecto, crittan01@gmail.com.\n\n¿Y cuál es tu número de celular, por favor?"
    }
  ]
}
```

### S10 — Cancelación mid-flow
```json
{
  "setup_turns": 6,
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
  "turns": 6,
  "transcript_tail": [
    {
      "client": "Sí, cotiza por favor",
      "bot": "Claro, Para, ¿me podrías decir a qué ciudad iría tu pedido?"
    },
    {
      "client": "Bogotá",
      "bot": "Perfecto, tu pedido sería:\n\n* 2x Jabón Artesanal de Coco (60g): $36.000 COP\n* 1x Sérum de Vitamina C (30ml): $85.000 COP\n\nEl envío a Bogotá tiene un costo de $7.000 COP y tarda de 1 a 2 días hábiles en llegar.\n\n¿Confirmas para generar tu link de pago?"
    },
    {
      "client": "Sí confirmo",
      "bot": "¡Genial! Ya confirmo tu pedido. En un momento te envío el link de pago para que puedas finalizar tu compra."
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "setup_turns": 7,
  "re_quoted_amount": false,
  "preview": ""
}
```

### S15 — Promesa de link cumplida
```json
{
  "turns": 3,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": false,
  "consent_given": false,
  "transcript_tail": [
    {
      "client": "Hola, quiero comprar un jabón artesanal de coco",
      "bot": "¡Buenas tardes! Qué chévere que te interese nuestro Jabón Artesanal de Coco. 😊\n\nCuéntame, ¿para qué tipo de piel lo buscas o qué uso le quieres dar? Así te puedo ayudar a elegir la presentación ideal.\n\nLo tenemos en:\n* 60g por *$18.000*\n* 100g por *$24.000*\n* 150g por *$32.000*\n\n"
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": "¡Claro! Para continuar con la compra, necesito que me confirmes la ciudad a la que debemos enviar tu Jabón Artesanal de Coco. Así puedo cotizarte el envío."
    },
    {
      "client": "Sí, continuemos por favor",
      "bot": "Perfecto, para cotizarte el envío y seguir con la compra, por favor, dime la ciudad a la que quieres que enviemos tu Jabón Artesanal de Coco. 😊"
    }
  ]
}
```
