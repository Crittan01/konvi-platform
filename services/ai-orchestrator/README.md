# Asíncrono AI Orchestrator

Patrón Arquitectónico del Orquestador de la plataforma conversacional.
Este módulo corre un *Background Worker* en Python / FastAPI desacoplado totalmente de las interfaces públicas, protegiéndose así contra caídas de LLM latencias usando Supabase Queues o PGMQ como amortiguador.

## Arquitectura del Servicio

1. **El Worker Loop:** Un poller / listen thread de Postgres recuperando JSON payloads generados por los webhooks públicos.
2. **Context Manager Middleware:** Encapsula el `tenant_id` y las credenciales firmadas. El modelo carece del ID.
3. **Structured Pydantic Calling:** Cada Tool es dictada e inyectada bajo validación robusta (usando Instructor o LangChain con Pydantic JSON Schema strict mode).
4. **Guardrail Evaluator Middleware:** Antes del broadcast al servicio conector de Telegram / Meta, valida la salubridad y fidelidad del output.

## Deployments
- Render Background Worker Profile (No HTTP entry point).
- En caso de necesitar scaling horizontal, escalar las réplicas del deployment.
- Requiere acceso total a credenciales de `Vertex AI` o `Gemini API` en Secrets.
