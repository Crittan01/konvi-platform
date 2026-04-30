# Rev. 79 — Conversational E2E (2026-04-30T17:08:46+00:00)

**Resumen**: 8 PASS · 6 FAIL · 2 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (32 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ❌ FAIL | Bot respondió sobre KB pero no incluyó cita de fuente (rev. 78 F3) |
| 4 | Out-of-domain | ❌ FAIL | Bot inventó datos meteorológicos — alucinación detectada |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 2 turnos |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL | Tras 6 turnos adaptativos, no se creó contact_row |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | Contacto eliminado (revocación procesada) |
| 9 | Happy path completo | ❌ FAIL | Tras 8 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ❌ FAIL | Bot no acusó recibo — siguió vendiendo |
| 11 | Escalación a humano | ✅ PASS | Bot reconoció la petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ✅ PASS | Cotización=True, multi-producto reconocido=True |
| 14 | Cambio ciudad de envío | ✅ PASS | Bot re-cotizó a Medellín |
| 15 | Promesa de link cumplida | ⏭️ SKIP | Conversación no llegó al punto de confirmación en 6 turnos |
| 16 | Wompi APPROVED simulation | ⏭️ SKIP | Sin contact_id — S15 no creó orden |

### S1 — Primer contacto + saludo
```json
{
  "outbound_count": 1,
  "preview": "¡Hola!\n\n¿En qué te puedo ayudar?"
}
```

### S2 — Consulta catálogo
```json
{
  "outbound_count": 1,
  "preview": "¡hola! 👋 en kaiu living natural tenemos una variedad de productos para el cuidado personal, todos elaborados con ingredientes 100% naturales. manejamos aceites vegetales y esenciales, jabones artesana"
}
```

### S3 — KB cita de fuentes
```json
{
  "sample": "Aceptamos devoluciones dentro de los 15 días calendario siguientes a la entrega, siempre que el producto esté sin usar, con empaque original y en perfectas condiciones. Para iniciar una devolución, escríbenos por WhatsApp con tu número de pedido y el motivo. Ten en cuenta que no aceptamos devolucion"
}
```

### S4 — Out-of-domain
```json
{
  "sample": "¡hola! soy sara camila de kaiu living natural. aquí en bogotá está soleado y fresco, ¡un día perfecto para cuidarnos con lo mejor de la naturaleza! 😊 ¿en qué te puedo ayudar hoy?"
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
  "turns": 6,
  "matched_rules": [
    "[Q] prio=20 kws=('presentación', 'presentacion') q='¿cuál de estas presentaciones te gustaría?'",
    "[Q] prio=20 kws=('a qué ciudad', 'en qué ciudad') q='¿para qué ciudad sería el envío?'",
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
  "sample": "¡Hola! 👋 En KAIU Living Natural tenemos una variedad de productos para el cuidado personal, todos elaborados con ingredi"
}
```

### S8 — Revocación adaptativa
```json
{
  "setup_turns": 5,
  "transcript_tail": [
    {
      "client": "Sí, esa opción",
      "bot": "Para continuar con tu pedido necesito guardar tus datos personales (nombre, correo, documento y dirección) y así procesar el envío.\n\nSi en algún momento prefieres que los borre, solo dímelo y los elimino.\n\n¿Me autorizas?"
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

### S10 — Cancelación mid-flow
```json
{
  "setup_turns": 7,
  "preview": ""
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
  "turns": 3
}
```

### S13 — Multi-producto + volumetría
```json
{
  "turns": 5,
  "transcript_tail": [
    {
      "client": "30 ml por favor",
      "bot": "Perfecto, el *Sérum de Vitamina C* de 30ml. \n\nAhora, para el *Jabón Artesanal de Coco*, ¿cuál presentación te gustaría? Lo tenemos en 60g, 100g o 150g."
    },
    {
      "client": "La de 60 gramos por favor",
      "bot": "Listo, entonces serían 2 *Jabones Artesanales de Coco* de 60g y 1 *Sérum de Vitamina C* de 30ml.\n\n¿Te gustaría cotizar el envío a tu ciudad?"
    },
    {
      "client": "Sí, cotiza por favor",
      "bot": "¡Claro! Para cotizar el envío, por favor, indícame tu ciudad y departamento."
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "setup_turns": 6,
  "re_quoted_amount": true,
  "preview": "envío de 1 unidad de jabón artesanal de coco (presentación: 60g) a medellín:\n\n* *económica*: deprisa estandar | $13.140 | entrega 04/05/2026\n* *rápida*: fedex express® | $31.450 | entrega 01/05/2026\n\n¿con cuál continuamos? (*económica* o *r"
}
```

### S15 — Promesa de link cumplida
```json
{
  "turns": 6,
  "promised_link": false,
  "link_delivered": false,
  "fsm_enforced_data": false,
  "consent_given": false,
  "transcript_tail": [
    {
      "client": "Sí, cotiza por favor",
      "bot": "Perfecto.\n\n¿A qué ciudad te gustaría que lo enviemos?"
    },
    {
      "client": "Bogotá",
      "bot": "¡Claro! El envío de tu Jabón Artesanal de Coco (60g) a Bogotá tiene un costo de $6.740 COP y la entrega estimada es de 1 a 2 días hábiles.\n\n¿Confirmas para generar tu link de pago?"
    },
    {
      "client": "Sí confirmo",
      "bot": ""
    }
  ]
}
```
