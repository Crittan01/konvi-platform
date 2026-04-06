# AI Orchestrator: Tool Contracts

Las Tool Calls que genera Gemini serán procesadas mediante validadores de esquema Pydantic antes de tocar cualquier fuente de datos (Base de datos o APIs externas).

## Regla de Oro Multi-Tenant
**Ninguna herramienta** tiene un argumento `tenant_id` en el esquema presentado al modelo. El `tenant_id` es insertado mediante Closures o Dependency Injection durante el *Tool Binding* en la ejecución de la función Python.

## 1. Tool: CatalogMatch
Permite buscar si el cliente tiene un producto y traer sus variaciones y stock disponible.

**JSON Schema / Pydantic Model:**
```json
{
  "name": "catalog_match",
  "description": "Busca un producto por termino de usuario. Devuelve nombre real, precio y boolean de existencia. Nunca confirmes stock real sin usar stock_verify.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "Término que usa el cliente" },
      "filters": {
        "type": "object",
        "properties": {
          "color": { "type": "string" },
          "size": { "type": "string" }
        }
      }
    },
    "required": ["query"]
  }
}
```

## 2. Tool: StockVerify & Lock
Verifica el stock a tiempo real basado en la sincro actual (Postgres desde Webhooks de ML) y congela ese stock lógicamente por X minutos para la transacción.

**JSON Schema / Pydantic Model:**
```json
{
  "name": "stock_verify_lock",
  "description": "Invocado justo y únicamente cuando el cliente dice SI QUIERO COMPRAR. Bloquea el stock de un item y retorna un token virtual que debe pasarse al checkout link.",
  "parameters": {
    "type": "object",
    "properties": {
      "internal_variation_id": { "type": "string", "description": "ID que devuelve catalog_match." },
      "quantity": { "type": "integer", "description": "Validado previamente en el chat" }
    },
    "required": ["internal_variation_id", "quantity"]
  }
}
```

## 3. Tool: HandoffRequest
Delega toda la sesión actual al Telegram del Tenant.

**JSON Schema / Pydantic Model:**
```json
{
  "name": "request_human_handoff",
  "description": "Si el cliente pide soporte, está quejoso, o el LLM no sabe resolver el intent. Redirige el control al humano.",
  "parameters": {
    "type": "object",
    "properties": {
      "reason": { "type": "string", "description": "Corto resumen para el humano." },
      "priority": { "type": "string", "enum": ["low", "high", "critical"] }
    },
    "required": ["reason"]
  }
}
```