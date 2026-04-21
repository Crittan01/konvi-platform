# Dominios y Subdominios

Última actualización: 2026-04-21

## Estado actual

- Dominio por defecto Render para web/API/connector/orchestrator.
- No hay dominio custom productivo aún.

## Cuándo mover a dominio propio

1. Antes de salida productiva pública.
2. Antes de habilitar SMTP real con dominio propio.
3. Cuando se requiera política de marca/SSL final.

## Consideraciones

- Mantener `APP_URL` alineado al dominio activo.
- Revisar `ALLOWED_ORIGINS` en API/connector tras cualquier cambio de dominio.
