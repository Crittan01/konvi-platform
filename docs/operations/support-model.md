# Modelo de Soporte

Última actualización: 2026-04-21

## Niveles

1. Tenant autoservicio en Tenant Console.
2. Soporte operativo interno (integraciones, estados, permisos).
3. Soporte técnico/DevOps (infra, incidentes, migraciones, colas).

## Estado de canales internos

| Canal | Estado | Uso |
|---|---|---|
| Telegram | Activo | alertas operativas por tenant (`human_takeover`) |
| Render Logs | Activo | diagnóstico de servicios |
| Supabase | Activo | DB/auth/colas/consultas |

## Brecha vigente

Sin Platform Console, parte del soporte avanzado se ejecuta asistido en backend/dashboard.
Todas las acciones deben dejar trazabilidad documental y técnica.
