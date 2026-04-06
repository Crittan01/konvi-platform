# AI Orchestrator: Guardrails y Seguridad de Contexto

Los Guardrails son aserciones evaluadas post-output del modelo o pre-envío a WhatsApp. Si fallan, el mensaje no se entrega y se fuerza la ejecución de `request_human_handoff` o en su defecto un *Safe Fallback Message*.

## 1. Reglas Pre-Meta (Anti-Spam / Regulación)
WhatsApp prohibe flujos en bucle infinito o spam explícito.
- **Rate-Limit Guardrail:** Un bot tiene prohibido por el backend responder más de X veces en un slide temporal.
- **Opt-in Guardrail:** Si no hay un `opt_in=True` en la base de datos de marketing para ese cliente, el LLM no puede generar calls-to-action proactivos no relacionados con la compra en curso.
- **Template Mismatch:** Solo podemos usar *Template Messages* para abrir 24h Windows. La orquestación IA en crudo no puede hacerlo.

## 2. Reglas Transaccionales (E-Commerce)
### 2.1 "No Alucinarás Inventario"
- Si el LLM escribe o confirma la existencia de un producto PERO la Tool `stock_verify_lock` NO fue llamada en su array de Tool Calls del Turno anterior, la respuesta del LLM **se descarta** y se inyecta un *System Message Correctivo* devolviéndola al modelo para regeneración.

### 2.2 Promesa de Facturación Segura
- El Orquestador no tiene acceso directo a procesamiento de pagos (Stripe, Mercado Pago).
- Consecuentemente, el bot **no puede confirmar un pago existoso**. Esa confirmación ocurre Out-Of-Band de una capa asíncrona dedicada que lee el webhook del pasarela. El LLM, vía system prompt y guardrails, debe limitarse a facilitar el Payment Link.