# AI Orchestrator — Guardrails (estado real)

Última actualización: 2026-04-19

Los guardrails validan la salida antes de enviar respuesta automática.
Si fallan, el inbound se marca `skipped` con `skip_reason=guardrail_rejected`.

---

## Reglas vigentes

1. No inventar datos transaccionales
- No confirmar stock, precio, pagos o estados sin datos reales del backend.

2. Respuesta segura y corta para canal WhatsApp
- Mensajes breves y sin comportamiento spam.

3. Escalación cuando falta certeza operativa
- Si el caso no es resoluble de forma segura, se evita auto-respuesta y se deriva a manejo humano.

---

## Interacción con takeover

- Si la conversación está en `human_takeover` o `closed`, no se ejecuta auto-respuesta.
- Si el inbound es no-texto, se fuerza `human_takeover` y se omite respuesta automática.

---

## Referencias

- `services/ai-orchestrator/orchestrator.py`
- `services/ai-orchestrator/guardrails.py`
- `services/ai-orchestrator/conversation_contract.py`
