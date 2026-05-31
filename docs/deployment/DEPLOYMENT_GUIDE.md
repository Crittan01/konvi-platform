# Guía de Deployment (vigente)

Última actualización: 2026-04-21

Esta guía reemplaza instructivos legacy y refleja el runtime actual del repositorio.

## 1) Modelo activo

- Infra IaC: `render.yaml` (raíz del repo)
- Servicios activos:
  - `konvi-web`
  - `konvi-connector`
  - `konvi-api`
  - `konvi-orchestrator` (modo `web` en Free)
- Base de datos: Supabase (`supabase/migrations` como fuente canónica)

## 2) Principios operativos

1. No subir `.env` al repositorio.
2. Variables sensibles se cargan en Render Dashboard (`sync: false`).
3. Migraciones SQL solo desde `supabase/migrations/` con `supabase db query --linked`.
4. Credenciales WhatsApp outbound son por tenant en DB (`tenant_integrations`), no por env global en API/Orchestrator.

## 3) Paso a paso de despliegue

1. Push a rama de despliegue (`develop` en flujo actual).
2. Render aplica blueprint desde `render.yaml`.
3. Verificar health checks:

```bash
curl https://konvi-web.onrender.com
curl https://konvi-connector.onrender.com/health
curl https://konvi-api.onrender.com/health
curl https://konvi-orchestrator.onrender.com/health
```

4. Verificar contratos críticos:
- Inbox carga conversaciones
- envío humano encola outbound (`whatsapp_outbound_messages`)
- orchestrator consume cola y actualiza `messages.processing_status`

## 4) Variables requeridas (resumen)

Ver lista completa en `render.yaml` y `docs/deployment/secrets-and-config.md`.

## 5) Upgrade a plan pago (decisión vigente)

Sí: la transición a Render/Supabase/canales pagos debe ocurrir cuando estemos cerca de salida productiva o cuando exista bloqueante operacional real en Free.

Criterio mínimo recomendado:
1. certificación funcional cerrada
2. tenant real listo para operar
3. o evidencia de cold starts/limitaciones afectando operación
4. cierre por fases de Inbox (A: catalogo variantes, B: pedidos/shipping, C: pagos)

Referencias de criterio funcional:
- `docs/operations/inbox-intents-matrix.md`
- `docs/integrations/wompi-prep.md` (pagos en fase posterior)

Detalle y riesgos: `docs/deployment/render-upgrade-path.md`.
Gate formal de aprobación: `docs/deployment/production-readiness-gate.md`.
