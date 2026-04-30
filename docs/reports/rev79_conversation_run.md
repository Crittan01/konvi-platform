# Rev. 79 — Conversational E2E (2026-04-30T19:06:00+00:00)

**Resumen**: 10 PASS · 4 FAIL · 2 SKIP

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
| 9 | Happy path completo | ❌ FAIL | Tras 10 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |
| 11 | Escalación a humano | ✅ PASS | Bot reconoció la petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ✅ PASS | Cotización=True, multi-producto reconocido=True |
| 14 | Cambio ciudad de envío | ❌ FAIL | Bot no reconoció el cambio de ciudad |
| 15 | Promesa de link cumplida | ⏭️ SKIP | Conversación no llegó al punto de confirmación en 2 turnos |
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
    "[Q] prio=1 kws=('?', '¿') q='¿es para el rostro, el cuerpo, o tienes alguna necesidad esp'",
    "[Q+ctx] prio=20 kws=('presentación', 'presentacion') q='000 cop*  ¿cuál te gustaría llevar?'",
    "[Q] prio=15 kws=('¿deseas cotizar', 'deseas cotizar') q='¿te gustaría cotizar el envío a tu ciudad?'",
    "[Q] prio=20 kws=('a qué ciudad', 'en qué ciudad') q='claro, ¿para qué ciudad sería el envío?'",
    "[Q] prio=15 kws=('servientrega', 'transportadora') q='740 | entrega 30/04/2026  ¿continuamos con la opción *económ'",
    "[Q] prio=25 kws=('aceptas', 'tratamiento de datos') q='¿me autorizas?'",
    "[Q] prio=50 kws=('correo', 'email') q='¿cuál es tu correo electrónico?'"
  ],
  "transcript_tail": [
    {
      "client": "Sí, esa opción",
      "bot": "Para continuar con tu pedido necesito guardar tus datos personales (nombre, correo, documento y dirección) y así procesar el envío.\n\nSi en algún momento prefieres que los borre, solo dímelo y los elimino.\n\n¿Me autorizas?"
    },
    {
      "client": "Sí acepto, guarden mis datos",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
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
  "sample": "¡Hola! 👋 Soy Sara Camila de KAIU Living Natural. Trabajamos cosmética artesanal 100% natural.\n\n*Aceites vegetales:*\n* Al"
}
```

### S8 — Revocación adaptativa
```json
{
  "setup_turns": 8,
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
      "client": "crittan01@gmail.com",
      "bot": "¡Genial, crittan01@gmail.com!\n\nAhora, para finalizar tu pedido, ¿me podrías confirmar tu nombre completo y tipo y número de documento, por favor?"
    },
    {
      "client": "Cristian Garzón",
      "bot": "¡Perfecto, Cristian! Ya tengo tu nombre y correo: crittan01@gmail.com.\n\nPara finalizar tu pedido, ¿me podrías confirmar tu tipo y número de documento, por favor?"
    },
    {
      "client": "CC 1032414179",
      "bot": "¡Perfecto, Cristian! Ya tengo tu nombre y correo: crittan01@gmail.com.\n\nPara finalizar tu pedido, ¿me podrías confirmar tu tipo y número de documento, por favor?"
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
  "turns": 5,
  "transcript_tail": [
    {
      "client": "Sigamos con la compra por favor",
      "bot": "Listo, entonces serían 2 *Jabones Artesanales de Coco* de 60g.\n\n¿Qué presentación del *Sérum de Vitamina C* te gustaría llevar, el de 15ml o el de 30ml?"
    },
    {
      "client": "30 ml por favor",
      "bot": "Perfecto, entonces serían 2 *Jabones Artesanales de Coco* de 60g y 1 *Sérum de Vitamina C* de 30ml.\n\n¿Para qué ciudad sería el envío y así te cotizo el costo?"
    },
    {
      "client": "Bogotá",
      "bot": "Para cotizar envío con precisión, confirma el producto: Sérum de Vitamina C / Jabón Artesanal de Coco. Con eso te paso de inmediato la opción más económica y la más rápida."
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "setup_turns": 3,
  "re_quoted_amount": false,
  "preview": "¡claro!\n\n¿a qué ciudad necesitas que te lo envíe para cotizar el envío?"
}
```

### S15 — Promesa de link cumplida
```json
{
  "turns": 2,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": false,
  "consent_given": false,
  "transcript_tail": [
    {
      "client": "Hola, quiero comprar un jabón artesanal de coco",
      "bot": "¡Hola! 👋 Soy Sara Camila de KAIU Living Natural. Trabajamos cosmética artesanal 100% natural.\n\nClaro, tenemos el Jabón Artesanal de Coco.\n\n¿Lo quieres para el rostro o el cuerpo?\n\n¿Y tu piel es seca, grasa o sensible?"
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": "¡Hola! 👋 Soy Sara Camila de KAIU Living Natural. Trabajamos cosmética artesanal 100% natural.\n\nClaro, tenemos el *Jabón Artesanal de Coco*.\n\n¿Lo quieres para el rostro o el cuerpo?\n\n¿Y tu piel es seca, grasa o sensible?"
    }
  ]
}
```
