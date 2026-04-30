# Rev. 79 — Conversational E2E (2026-04-30T14:38:56+00:00)

**Resumen**: 1 PASS · 0 FAIL · 1 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 15 | Promesa de link cumplida | ✅ PASS | Bot bloqueó link y pidió datos faltantes (FSM enforcement OK) |
| 16 | Wompi APPROVED simulation | ⏭️ SKIP | Sin contact_id — S15 no creó orden |

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
