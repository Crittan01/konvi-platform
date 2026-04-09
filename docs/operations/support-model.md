# Modelo de Soporte — Commerce Ops Platform

Última actualización: 2026-04-09

---

## Niveles de soporte

### Nivel 1 — Autoservicio del Tenant

El tenant resuelve por sí mismo desde la Tenant Console:
- Configuración de catálogo, productos y variantes
- Human takeover de conversaciones
- Cotización de envíos
- Gestión de usuarios del equipo

### Nivel 2 — Soporte operativo interno

El equipo de la plataforma asiste al tenant con:
- Problemas de configuración de WhatsApp (WABA, webhook)
- Integraciones que no sincronizan
- Errores en pedidos o envíos
- Escalamientos desde el Inbox

**Canal previsto**: Telegram interno (cuando esté implementado) + email

### Nivel 3 — Soporte técnico / DevOps

Intervención técnica directa sobre la infraestructura:
- Servicios caídos en Render
- Errores de DB o migraciones
- Renovación de tokens (Meta, Supabase)
- Debugging de AI Orchestrator

---

## Acceso de soporte a datos de tenants

Cuando el equipo de soporte necesita ver datos de un tenant específico:

1. El acceso debe realizarse desde la Platform Console (cuando exista)
2. Toda acción queda registrada en `audit_log` con `action = 'platform.tenant_access'`
3. El tenant puede ver ese acceso en su propia auditoría
4. El acceso de soporte no silencioso ni sin trazabilidad

**Estado actual**: La Platform Console no existe. El acceso de soporte se hace directamente via Supabase Dashboard o CLI. Esto es un gap de trazabilidad (Riesgo R-10).

---

## Canales de alerta internos

| Canal | Estado | Uso |
|-------|--------|-----|
| Telegram Bot | ❌ Pendiente (Fase 8) | Alertas de sistema, conversaciones escaladas |
| Render Logs | ✅ Disponible | Logs de cada servicio en tiempo real |
| Supabase Dashboard | ✅ Disponible | Estado de DB, queries, logs de API |

---

## Intervenciones que siempre requieren humano

Ver `docs/operations/HUMAN_INTERVENTIONS.md` para el listado completo con instrucciones paso a paso.

Resumen de las intervenciones activas:
- Configuración del Webhook en Meta Developers (PASO 6)
- Creación de System User Token permanente (IH-006)
- Test E2E con WhatsApp real (PASO 7)

---

## Documentos relacionados

- `docs/operations/HUMAN_INTERVENTIONS.md` — Intervenciones manuales detalladas
- `docs/operations/runbooks.md` — Procedimientos operacionales
- `docs/operations/onboarding-tenants.md` — Alta de nuevos tenants
