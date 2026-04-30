# Rev. 79 — Conversational E2E (2026-04-30T13:08:34+00:00)

**Resumen**: 7 PASS · 5 FAIL · 2 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 1 | Primer contacto + saludo | ✅ PASS | Bot respondió en 1 mensaje(s) (34 chars) |
| 2 | Consulta catálogo | ✅ PASS | Bot listó productos en 1 mensaje(s) |
| 3 | KB cita de fuentes | ✅ PASS | Respuesta KB incluye cita explícita |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 5 | Foto producto | ✅ PASS | Bot fallback explicativo tras 1 turnos |
| 6 | Datos desordenados (turn-by-turn) | ❌ FAIL | Tras 2 turnos adaptativos, no se creó contact_row |
| 7 | Formato canónico WhatsApp | ✅ PASS | Outbound sin `**` ni `• ` (rev. 77 normaliza al canon) |
| 8 | Revocación adaptativa | ✅ PASS | Contacto eliminado (revocación procesada) |
| 9 | Happy path completo | ❌ FAIL | Tras 5 turnos, contact_row no creado |
| 10 | Cancelación mid-flow | ⏭️ SKIP | Setup avanzó solo 1 turnos — no llegó a estado pre-cancelación |
| 11 | Escalación a humano | ❌ FAIL | Sin respuesta tras petición de asesor |
| 12 | Address conjunto residencial | ❌ FAIL | Bot no preguntó por torre/apto y no se registraron |
| 13 | Multi-producto + volumetría | ❌ FAIL | Cotización=False, multi-producto reconocido=False |
| 14 | Cambio ciudad de envío | ⏭️ SKIP | Setup paró en turn 1 — sin contexto de cotización previa |

### S1 — Primer contacto + saludo
```json
{
  "outbound_count": 1,
  "preview": "Cuéntame, ¿en qué te puedo ayudar?"
}
```

### S2 — Consulta catálogo
```json
{
  "outbound_count": 1,
  "preview": "¡buenos días! 👋 en kaiu living natural tenemos una variedad de productos naturales para tu cuidado personal. manejamos aceites vegetales, aceites esenciales, sérums faciales y jabones artesanales.\n\n¿h"
}
```

### S3 — KB cita de fuentes
```json
{
  "preview": "¡Hola! Con gusto te cuento sobre nuestra política de devoluciones.\n\nAceptamos devoluciones y cambios dentro de los *15 días calendario* después de la entrega, siempre que el producto esté sin usar, co"
}
```

### S4 — Out-of-domain
```json
{
  "preview": "¿de cuál producto te gustaría ver foto? cuéntame su nombre y te muestro la que tengo cargada."
}
```

### S5 — Foto producto
```json
{
  "image_sent": false,
  "turns": 1,
  "matched_rules": []
}
```

### S6 — Datos desordenados (turn-by-turn)
```json
{
  "turns": 2,
  "matched_rules": [
    "prio=1 kws=('?', '¿') q='000*  ¿Cuál te gustaría llevar?'"
  ],
  "transcript_tail": [
    {
      "client": "Hola, quiero comprar un jabón artesanal de coco",
      "bot": "¡Buenos días! 👋\n\nClaro, el *Jabón Artesanal de Coco* lo tenemos en varias presentaciones:\n* 60g por *$18.000*\n* 100g por *$24.000*\n* 150g por *$32.000*\n\n¿Cuál te gustaría llevar?"
    },
    {
      "client": "Sigamos con la compra por favor",
      "bot": ""
    }
  ]
}
```

### S7 — Formato canónico WhatsApp
```json
{
  "sample": "¡Hola! Soy Sara Camila de KAIU Living Natural. Tenemos una variedad de productos naturales para el cuidado personal.\n\nCo"
}
```

### S8 — Revocación adaptativa
```json
{
  "setup_turns": 5,
  "transcript_tail": [
    {
      "client": "Sí, cotiza por favor",
      "bot": "Claro, ¿para qué ciudad sería el envío?"
    },
    {
      "client": "Bogotá",
      "bot": "No pude cotizar el envio ahora mismo. Te apoyo con un asesor experto."
    }
  ],
  "outbound_after_revoke": 0
}
```

### S9 — Happy path completo
```json
{
  "transcript_tail": [
    {
      "client": "La de 60 gramos por favor",
      "bot": "Listo, el Jabón Artesanal de Coco de 60g tiene un costo de *$18.000*.\n\n¿Te gustaría cotizar el envío a tu ciudad?"
    },
    {
      "client": "Sí, cotiza por favor",
      "bot": "Perfecto.\n\n📋 *Resumen de tu pedido:*\n\n*Productos:*\n* 1x Jabón Artesanal de Coco (Presentación: 60g): *$18.000 COP*\n\nSubtotal: *$18.000 COP*\n\n¿Quieres agregar algo más a tu pedido o seguimos con el envío? Si es así, cuéntame para qué ciudad sería."
    },
    {
      "client": "No, eso es todo",
      "bot": ""
    }
  ]
}
```

### S10 — Cancelación mid-flow
```json
{
  "transcript_tail": [
    {
      "client": "Hola, quiero comprar un jabón artesanal de coco",
      "bot": ""
    }
  ]
}
```

### S12 — Address conjunto residencial
```json
{
  "asked_tower": false,
  "address_db": {},
  "turns": 1
}
```

### S13 — Multi-producto + volumetría
```json
{
  "turns": 1,
  "transcript_tail": [
    {
      "client": "Hola, quiero comprar 2 jabones artesanales de coco y 1 sérum de vitamina C",
      "bot": ""
    }
  ]
}
```

### S14 — Cambio ciudad de envío
```json
{
  "transcript_tail": [
    {
      "client": "Hola, quiero comprar un jabón artesanal de coco",
      "bot": ""
    }
  ]
}
```
