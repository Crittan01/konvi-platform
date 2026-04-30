# Rev. 79 — Conversational E2E (2026-04-30T21:11:03+00:00)

**Resumen**: 11 PASS · 4 FAIL · 1 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (119 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ✅ PASS | Respuesta KB incluye cita explícita |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 2 turnos |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL | Tras 8 turnos adaptativos, no se creó contact_row |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | Contacto eliminado (revocación procesada) |
| 9 | Happy path completo | ❌ FAIL | Tras 5 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |
| 11 | Escalación a humano | ✅ PASS | Bot reconoció la petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ✅ PASS | Cotización=True, multi-producto reconocido=True |
| 14 | Cambio ciudad de envío | ❌ FAIL | Bot no reconoció el cambio de ciudad |
| 15 | Promesa de link cumplida | ✅ PASS | Bot bloqueó link y pidió datos faltantes (FSM enforcement OK) |
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
  "preview": "¡hola! 👋 soy sara camila de kaiu living natural. trabajamos cosmética artesanal 100% natural.\n\n*aceites vegetales:*\n* almendras dulces\n* argán\n* coco virgen\n* rosa mosqueta\n\n*aceites esenciales:*\n* ár"
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
  "turns": 8,
  "matched_rules": [
    "[Q] prio=20 kws=('presentación', 'presentacion') q='000*  ¿cuál presentación te gustaría llevar?'",
    "[Q] prio=10 kws=('agregar otro', 'algo más') q='¿te ayudo con algo más?'",
    "[Q] prio=20 kws=('a qué ciudad', 'en qué ciudad') q='¿para qué ciudad sería el envío?'",
    "[Q] prio=15 kws=('servientrega', 'transportadora') q='740 | entrega 30/04/2026  ¿continuamos con la opción *económ'",
    "[Q] prio=25 kws=('aceptas', 'tratamiento de datos') q='¿me autorizas?'",
    "[Q] prio=50 kws=('correo', 'email') q='¿cuál es tu correo electrónico?'",
    "[Q] prio=20 kws=('¿confirmas', 'confirmas que') q='com * celular: +57 312 583 5649 * documento: cc 1032414179 *'"
  ],
  "transcript_tail": [
    {
      "client": "Sí acepto, guarden mis datos",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "Soy Cristian Garzón, correo crittan01@gmail.com, CC 1032414179, dirección Calle 3 sur 70-84, barrio Olaya, casa, Bogotá",
      "bot": "📋 *Resumen de tu pedido:*\n\n*Productos:*\n* 1x Jabón Artesanal de Coco: $18.000 COP\n\nSubtotal: $18.000 COP\nEnvío: $6.740 COP\n*TOTAL: $24.740 COP*\n\n*Datos de envío:*\n* Nombre: Cristian Garzón\n* Correo: crittan01@gmail.com\n* Celular: +57 312 583 5649\n* Documento: CC 1032414179\n* Dire"
    },
    {
      "client": "Sí confirmo",
      "bot": "Perfecto, *Cristian*. Te genero tu link de pago."
    }
  ]
}
```

### S7 — Formato canónico WhatsApp
```json
{
  "sample": "¡Hola! 👋 Soy Sara Camila de KAIU Living Natural. Trabajamos cosmética artesanal 100% natural.\n\n*Aceites vegetales:*\n* Al"
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
      "client": "Sigamos con la compra por favor",
      "bot": "Perfecto.\n\n¿Cuál presentación del *Jabón Artesanal de Coco* te gustaría llevar? (60g, 100g o 150g)"
    },
    {
      "client": "La de 60 gramos por favor",
      "bot": "Listo, *1x Jabón Artesanal de Coco (60g)* por *$18.000 COP*.\n\n¿Te ayudo con algo más?\n* Asesoría sobre el producto (si tienes dudas)\n* Agregar más productos al carrito\n* Cotizar envío\n\nO dime si prefieres avanzar directo."
    },
    {
      "client": "No, eso es todo",
      "bot": "Tienes *1x Jabón Artesanal de Coco (60g)* por *$18.000 COP*.\n\n¿Quieres agregar algo más a tu pedido o seguimos con el envío?"
    }
  ]
}
```

### S10 — Cancelación mid-flow
```json
{
  "setup_turns": 8,
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
      "client": "Sigamos con la compra por favor",
      "bot": "Perfecto, entonces sería:\n* 2x *Jabón Artesanal de Coco* (60g): *$36.000 COP*\n* 1x *Sérum de Vitamina C* (30ml): *$85.000 COP*\n\nSubtotal: *$121.000 COP*\n\n¿Quieres agregar algo más a tu pedido o te cotizo el envío?"
    },
    {
      "client": "Sí, cotiza por favor",
      "bot": "Claro, ¿a qué ciudad necesitas que te cotice el envío?"
    },
    {
      "client": "Bogotá",
      "bot": "Para cotizar envío con precisión, confirma el producto: Jabón Artesanal de Coco / Sérum de Vitamina C. Con eso te paso de inmediato la opción más económica y la más rápida."
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "setup_turns": 7,
  "re_quoted_amount": false,
  "preview": "¡perfecto!\n\n¿cuál es tu correo electrónico?"
}
```

### S15 — Promesa de link cumplida
```json
{
  "turns": 9,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": true,
  "consent_given": false,
  "transcript_tail": [
    {
      "client": "Sí acepto, guarden mis datos",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "crittan01@gmail.com",
      "bot": "Gracias. Para continuar, compárteme tu nombre completo."
    },
    {
      "client": "Cristian Garzón",
      "bot": ""
    }
  ]
}
```
