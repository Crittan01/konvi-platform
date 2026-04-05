# Environments

## Ambientes actuales
- local
- production

## Ambiente futuro
- staging

## Definición

### Local
Entorno de desarrollo dentro de una VM dedicada al proyecto.
Incluye:
- repo
- tooling
- variables locales
- ejecución de desarrollo y pruebas
- reglas específicas del agente para este proyecto

### Production
Infra desplegada en:
- Render
- Supabase
- canales e integraciones externas activas

### Staging
No es obligatorio desde el primer día.
Se incorporará cuando el proyecto entre en:
- pruebas seguras de integraciones reales
- endurecimiento previo a clientes
- pruebas de despliegue antes de producción

## Regla
No asumir que local reemplaza staging o production.