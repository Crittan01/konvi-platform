# WhatsApp Connector
Servicio perimetral expuesto públicamente. Dedicado 100% a recibir notificaciones de **Meta Cloud API**.

## Arquitectura
1. **Verificación de Token:** Endpoint GET enlazado al Meta Dashboard.
2. **Recepción Rápida:** Endpoint POST que retorna HTTP 200 Inmediato para evitar baneos o retries, y empuja asíncronamente (BackgroundTasks / Queue) los payloads limpios hacia Postgres/Supabase.\n