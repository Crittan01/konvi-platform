# Rev. 79 — Conversational E2E (2026-04-30T17:44:38+00:00)

**Resumen**: 2 PASS · 1 FAIL · 0 SKIP

| # | Escenario | Status | Mensaje |
|---|---|---|---|
| 3 | KB cita de fuentes | ❌ FAIL | Bot respondió sobre KB pero no incluyó cita de fuente (rev. 78 F3) |
| 4 | Out-of-domain | ✅ PASS | Bot no alucinó respuesta sobre clima |
| 10 | Cancelación mid-flow | ✅ PASS | Bot reconoció la cancelación |

### S3 — KB cita de fuentes
```json
{
  "sample": "Aceptamos devoluciones dentro de los 15 días calendario siguientes a la entrega, siempre que el producto esté sin usar, con empaque original y en perfectas condiciones. Los costos de envío de devolución corren por cuenta del cliente, salvo en casos de producto defectuoso o error nuestro.\n\n¿Te gustar"
}
```

### S4 — Out-of-domain
```json
{
  "preview": "no tengo información sobre eso — soy asesor virtual de kaiu living natural y solo puedo ayudarte con nuestros productos, envíos y pedidos.\n\n¿te interesa algo de la tienda?"
}
```

### S10 — Cancelación mid-flow
```json
{
  "setup_turns": 4,
  "preview": "entendido, cancelo tu pedido. 🙏\n\nno hay problema, cuando quieras retomar la compra aquí estaré para ayudarte. ¡que tengas un excelente día!"
}
```
