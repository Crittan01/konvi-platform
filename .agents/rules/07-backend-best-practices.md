# Regla N-07: Backend Best Practices y Restricciones (Python / FastAPI)

Aplica a `services/api`, `services/connector-whatsapp` y `services/ai-orchestrator`.

## 1. Contratos y validación

- Priorizar Pydantic/FastAPI models en entradas y salidas de API.
- Errores de negocio deben exponerse con `HTTPException` explícita y mensajes operables.
- No delegar verdad transaccional al LLM.

## 2. Estilo y tooling

- `services/api` sí tiene `pyproject.toml` con reglas de lint/format; en otros servicios mantener estilo consistente equivalente.
- Preferir logging estructurado sobre `print()` en rutas de runtime.
- Mantener imports ordenados y tipado claro en código nuevo.

## 3. Multi-tenant

- Nunca ejecutar lecturas/escrituras sensibles sin scoping por `tenant_id`.
- Recordar que `service_role` puede bypassar RLS: el filtro explícito por tenant es obligatorio en capa de aplicación.
