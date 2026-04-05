# Commerce Ops Platform

Plataforma operativa de comercio. Este repositorio sigue una estructura de monorepo.

## Estructura del Proyecto

- `apps/`: Aplicaciones web (frontend) y servidores principales que consumen los servicios.
- `services/`: Microservicios, APIs y funciones backend independientes.
- `packages/`: Paquetes, librerías compartidas (ej. UI components, utilities, core configs).
- `infra/`: Infraestructura como código (IaC) para los distintos entornos.
- `scripts/`: Scripts de utilidad, automatización, migraciones o pipelines de CI/CD.
- `tests/`: Pruebas globales e inter-servicio (e2e, integraciones).
- `docs/`: Documentación detallada de arquitectura, APIs y despliegues.
- `.agents/`: Flujos de trabajo (workflows) y configuraciones para agentes de IA que asisten al proyecto.

## Comandos Útiles

Configuración base inicial (requiere gestor de paquetes definido en futuros pasos):
```bash
npm install
```
