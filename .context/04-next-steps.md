# Próximos Pasos — Estado 2026-04-19

## Pendientes reales (post cierre correctivo)

1. **Envia Fase 2**
- Label generation
- Tracking
- Pickup scheduling

2. **Mercado Libre**
- Sync completo MeLi → Supabase (descripción/precio/atributos en modo pull)
- Cobertura funcional extendida para `shipments` en webhook MeLi

3. **Operación/Infra**
- SMTP propio en Supabase (cuando exista dominio propio)
- Monitoreo operativo (alertas centralizadas por fallos de integración)

## No pendientes (cerrado en esta sesión)

- Contrato único de estados de conversación end-to-end
- Human takeover efectivo (bot silenciado en runtime)
- RBAC runtime unificado (`owner/manager/operator`)
- OAuth MeLi con state firmado + expiración + anti-replay
- Credenciales WhatsApp por tenant como única fuente runtime
- Frontend residual: badge MeLi real + inventory legacy redirigido
- Contrato explícito de procesamiento de mensajes (`processing_status`)
