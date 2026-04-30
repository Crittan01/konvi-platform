# Rev. 79 — Conversational E2E (2026-04-30T19:59:15+00:00)

**Resumen**: 10 PASS · 5 FAIL · 1 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (119 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ✅ PASS | Respuesta KB incluye cita explícita |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 2 turnos |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL | Tras 9 turnos adaptativos, no se creó contact_row |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | Contacto eliminado (revocación procesada) |
| 9 | Happy path completo | ❌ FAIL | Tras 12 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |
| 11 | Escalación a humano | ❌ FAIL | Sin respuesta tras petición de asesor |
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
    "[Q] prio=1 kws=('?', '¿') q='cuéntame,  ¿para qué lo quieres usar?'",
    "[Q] prio=15 kws=('cuántos', 'cuantos') q='000 cop*  ¿cuál te gustaría llevar y cuántos?'",
    "[Q] prio=20 kws=('presentación', 'presentacion') q='perfecto, ¿cuál presentación del *jabón artesanal de coco* t'",
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
      "bot": "Perfecto, Cristian. Te genero tu link de pago."
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
      "client": "crittan01@gmail.com",
      "bot": "Entendido, crittan01@gmail.com. \n\nAhora, ¿cuál es tu número de documento de identidad y qué tipo es (CC, CE, TI, etc.)?"
    },
    {
      "client": "CC 1032414179",
      "bot": "📋 *Resumen de tu pedido:*\n\n*Productos:*\n* 1x Jabón Artesanal de Coco (60g): *$18.000 COP*\n\nSubtotal: *$18.000 COP*\nEnvío: *$6.740 COP*\n*TOTAL: $24.740 COP*\n\n*Datos de envío:*\n> Calle 3 sur # 70-84 — barrio Olaya, Bogotá (casa)\n* Nombre: *Cristian Garzón*\n* Correo: crittan01@gmail"
    },
    {
      "client": "Olaya",
      "bot": "Entendido, Cristian. El barrio es Olaya.\n\n¿Confirmas que los datos están correctos para generar tu link de pago?"
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
      "client": "Sí, esa opción",
      "bot": "Para continuar con tu pedido necesito guardar tus datos personales (nombre, correo, documento y dirección) y así procesar el envío.\n\nSi en algún momento prefieres que los borre, solo dímelo y los elimino.\n\n¿Me autorizas?"
    },
    {
      "client": "Sí acepto, guarden mis datos",
      "bot": "¡Perfecto!\n\n¿Cuál es tu correo electrónico?"
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": ""
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "setup_turns": 7,
  "re_quoted_amount": false,
  "preview": "entendido. para poder seguir con la compra y generar tu pedido, necesito que me digas tu correo electrónico, por favor."
}
```

### S15 — Promesa de link cumplida
```json
{
  "turns": 7,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": true,
  "consent_given": false,
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
      "client": "crittan01@gmail.com",
      "bot": ""
    }
  ]
}
```
