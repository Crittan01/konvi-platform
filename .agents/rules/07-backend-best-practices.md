# Regla N-07: Backend Best Practices y Restricciones (Python / FastAPI)

Esta regla impone el estándar innegociable de uso en todos los repositorios y contenedores backend (especialmente `services/api` y `services/orchestrator`).

## 1. Validación de Esquemas y Contratos
- **Priorizar Pydantic:** Toda estructura de entrada u salida (Requests, Responses, BaseModels para Base de Datos) debe estar 100% tipada bajo las directrices estrictas de Pydantic v2.
- **Validado Fuerte:** Todo router deberá hacer *raise* explícito `HTTPException(status_code=4XX)` garantizando que solo la data correcta cruce el puente al Orquestador AI o a DB.

## 2. Herramientas de Desarrollo y Estilo (Ruff)
- Tenemos un `pyproject.toml` anclando a **Ruff** en el backend. 
- Todo comando y script Python debe cumplir `line-length = 100`. 
- Se desaconseja por completo `print()` para debugear flujos productivos. En su lugar utilizar estructuración logg o `logger` de la consola de Render.
- Para importaciones, utiliza la separación y orden isort (librerías core nativas -> librerías terceros ej. fastapi -> directy import ej. `routers.X`). Ruff capturará fallos automáticamente (I001).

## 3. Manejo de Tenencia (Multi-Tenant)
- ¡Jamás realizar consultas a DB global sin inyectar explícitamente el `tenant_id`! Toda instancia de DB usa incondicionalmente las dependencias de `/dependencies/auth.py` para asegurar que el `user` o `api_key` se limite al aislamiento RLS que protege la integridad B2B.
