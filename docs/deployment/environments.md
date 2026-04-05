# Environments

## Ambientes actuales
- local
- production

## Ambiente futuro
- staging

## Local
La VM dedicada del proyecto.
Incluye:
- repo
- tooling
- reglas del agente
- ejecución local
- pruebas
- documentación del proyecto

## Production
Infra desplegada en:
- Render
- Supabase
- canales e integraciones externas

## Staging
Se habilitará cuando:
- existan integraciones reales sensibles
- se requieran pruebas previas de despliegue
- se necesite validar webhooks, RLS o sync sin tocar producción

## Regla
No introducir staging antes de que aporte valor real.
Pero sí dejar la arquitectura preparada para agregarlo sin rehacer entornos.