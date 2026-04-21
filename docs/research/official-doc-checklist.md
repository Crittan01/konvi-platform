# Checklist de Validación Oficial

Última actualización: 2026-04-21

Antes de cambios en integraciones o infraestructura productiva, validar en documentación oficial vigente.

## Validaciones críticas pendientes

- Render pricing/límites vigentes para plan objetivo.
- Política de retries y timeouts de webhooks Meta.
- Rate limits actuales de Envia por plan.
- Límites Realtime/Queues de Supabase para escala objetivo.
- Límites/costos del proveedor SMTP sender para alertas productivas.
- Contrato oficial Wompi (ambientes/llaves, eventos por ambiente, tokens de aceptacion).

## Validaciones ya aplicadas en código

- WhatsApp Cloud API oficial + HMAC webhook.
- OAuth MeLi endurecido con state firmado y anti-replay.
- `google-genai` como SDK oficial activo.
