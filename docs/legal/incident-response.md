# Plan de Respuesta a Incidentes

**Aplicable a:** Konvi Platform (rev. ≥ 98)
**Marco legal:** Ley 1581/2012 Art. 18 + Decreto 1377/2013

---

## 1. Definición de incidente

Cualquier evento que comprometa o pueda comprometer la
confidencialidad, integridad o disponibilidad de datos personales:

- Acceso no autorizado a la DB.
- Filtración de credenciales (Vault, JWT, service_role).
- Pérdida de datos (corrupción, borrado accidental).
- Compromiso de un subprocesador.
- Ransomware / malware en infraestructura.
- Exfiltración por bug de aplicación (e.g., RLS bypass).

## 2. Severidades

| Nivel | Criterio | Plazo notificación |
|---|---|---|
| **P0** | PII de >100 titulares expuesta o accesible públicamente | ≤ 24 h SIC + tenant + titular |
| **P1** | PII de <100 titulares; o brecha de control sin evidencia de exfiltración | ≤ 72 h SIC + tenant |
| **P2** | Vulnerabilidad detectada sin exposición | Ciclo normal de release |
| **P3** | Misconfiguración menor sin riesgo PII | Backlog |

## 3. Roles

| Rol | Responsable | Responsabilidad |
|---|---|---|
| Incident Commander | Responsable técnico de la Plataforma | Coordina respuesta end-to-end |
| Comms Lead | Comms / Legal | Comunicaciones a tenants, SIC, titulares |
| Tech Lead | Ingeniería | Contención + remediación |
| Legal | Asesor legal | Plazos legales, contenido de notificaciones |

## 4. Pasos de respuesta

### 4.1 Detección
- Alertas de Supabase (audit_log, query patterns).
- Alertas de Render (errors 5xx, latencia).
- Reporte de tenant o titular.
- Reporte de subprocesador.

### 4.2 Contención
- Revocar credenciales comprometidas (Supabase service_role rotation).
- Aislar el componente afectado (suspender service en Render).
- Cerrar acceso del subprocesador comprometido.

### 4.3 Evaluación
- Determinar alcance: ¿qué datos? ¿cuántos titulares? ¿qué tenants?
- Consultar `consent_audit_log` y `pii_access_log` para cadena de custodia.
- Decidir severidad y plazo legal aplicable.

### 4.4 Notificación

#### A la SIC (Superintendencia de Industria y Comercio)
- Plazo: ≤ 72 h (P1+).
- Canal: formulario oficial SIC + email a notificacionesjudiciales@sic.gov.co.
- Contenido mínimo: naturaleza del incidente, categorías de datos,
  número aproximado de titulares, medidas adoptadas.

#### Al Tenant (Responsable)
- Plazo: inmediato (≤ 24 h, P0/P1).
- Canal: email vía Resend + Telegram bot.
- Contenido: alcance, acciones requeridas del tenant, cadena de
  evidencia.

#### Al Titular
- Plazo: cuando aplica (P0 con riesgo material).
- Canal: WhatsApp (template aprobado) + email registrado.
- Contenido: qué datos, qué riesgo, qué acciones puede tomar
  (cambiar contraseñas, monitorear cuentas).

### 4.5 Remediación
- Parche de la vulnerabilidad raíz.
- Tests de regresión.
- Migración / rotación de tokens si aplica.

### 4.6 Postmortem
- Reporte interno en `docs/reports/incident-YYYY-MM-DD.md`.
- ADR si introduce cambio arquitectónico.
- Lecciones aprendidas + acciones preventivas.

## 5. Drills

Simulacros trimestrales de:

- Exposición accidental de Vault token.
- RLS bypass en query custom.
- Compromiso de Supabase service_role.

## 6. Contactos clave

- **Supabase support:** support@supabase.com
- **Meta security:** business-security@meta.com
- **Wompi support:** soporte@wompi.co
- **SIC notificación:** notificacionesjudiciales@sic.gov.co

> Mantener este archivo sincronizado con `subprocessors.md` y revisar
> tras cada incidente.
