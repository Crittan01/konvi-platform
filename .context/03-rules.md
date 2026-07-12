# Reglas Críticas — No Negociables

## Multi-tenant

- Toda operación atada a `tenant_id` con filtro explícito en queries sensibles
- `app_current_tenant()` resuelve desde JWT (`app_metadata.tenant_id`) o session config
- Workers usan `service_role` + `SET app.current_tenant_id = '<uuid>'`
- `service_role` puede bypassar RLS; por eso el aislamiento runtime depende de filtros de aplicación + RLS donde aplique.
- El frontend no es seguridad.

## LLM (Gemini)

El LLM **nunca es fuente de verdad** de:
stock · precios · pedidos · shipping quotes · tracking · estados transaccionales · permisos

Si faltan datos → solicitar al usuario o escalar a humano. No inventar.

## WhatsApp / Meta

- Solo WhatsApp Cloud API oficial (Meta Graph API v22.0). Sin librerías no oficiales.
- Respuestas al cliente solo con datos reales del backend — nunca inventados.
- Cumplimiento Anti-Spam de Meta.

## Código seguro

- `getUser()` en Server Components — nunca `getSession()` (inseguro JWT)
- Python 3.11.13: tanto `Optional[X]` como `X | None` son válidos. El código existente usa `Optional[X]` — mantener consistencia salvo refactors explícitos.
- Funciones `() => {}` no son serializables como props de RSC — usar props opcionales con default interno
- `.env` nunca al repositorio

## Orden de trabajo

1. Claridad funcional/visual → 2. Backend correspondiente → 3. Implementación
No al revés. No implementar basándose en suposiciones de APIs externas — validar docs oficiales primero.
