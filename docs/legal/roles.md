# Roles legales — Responsable vs Encargado del Tratamiento

**Aplicable a:** Commerce Ops Platform (rev. ≥ 99)
**Marco legal:** Ley 1581/2012 Colombia (Habeas Data) + Decreto 1377/2013

---

## 1. Definiciones

| Rol | Descripción legal | En esta plataforma |
|---|---|---|
| **Titular** | Persona natural cuyos datos son objeto de tratamiento | El cliente final que interactúa con el negocio del tenant vía WhatsApp |
| **Responsable** | Decide sobre la finalidad y tratamiento de los datos | **El tenant** (e.g., KAIU) — recibe consent del titular, define qué hacer con sus datos |
| **Encargado** | Realiza el tratamiento por cuenta del Responsable | **Commerce Ops Platform** — procesa datos siguiendo instrucciones del tenant |

---

## 2. Obligaciones del Tenant (Responsable)

1. Obtener consentimiento previo, expreso e informado (Art. 9).
2. Informar al titular sobre la finalidad y derechos (Art. 12).
3. Atender solicitudes de acceso, rectificación, supresión y portabilidad (Arts. 14, 16, 17, 19).
4. Notificar incidentes de seguridad a la SIC y al titular cuando aplique (Art. 18).
5. Aceptar el DPA con la plataforma antes de operar.
6. Mantener actualizada la política de privacidad publicada al titular.

## 3. Obligaciones de la Plataforma (Encargado)

1. Procesar datos solo siguiendo instrucciones del tenant.
2. Mantener confidencialidad y seguridad técnica (cifrado, RLS, audit).
3. Proveer herramientas para que el tenant ejerza sus obligaciones (audit log, SAR endpoint, retention policies, anonimización al revocar).
4. No transferir datos a subprocesadores no aprobados.
5. Soportar al tenant en respuestas a la SIC con evidencia documentada.
6. Eliminar / devolver datos al fin de la relación contractual.

## 4. Cadena de subprocesadores

Cada subprocesador (ver `subprocessors.md`) opera bajo su propio acuerdo
de tratamiento con la plataforma. La plataforma es responsable de su
diligencia debida.

## 5. Implicancias técnicas

- `tenant_id` en cada tabla = atribuye datos al Responsable correcto.
- `consent_audit_log` = trazabilidad para que el tenant responda a SIC.
- `notification_settings` = canal para que la plataforma alerte al tenant
  de eventos relevantes (revocaciones, SARs).
- `tenant_legal_acceptance` (rev. 99) = registro de aceptación del DPA.

---

## 6. Si la SIC notifica al tenant

1. La plataforma facilita evidencia (audit logs, fechas de consent, cadena de PII access).
2. El tenant es quien firma respuestas y compromisos con la SIC.
3. La plataforma puede aportar peritaje técnico si se solicita.

> **Nota:** este documento es un resumen operativo. La interpretación
> jurídica vinculante requiere asesoría legal con abogado calificado en
> protección de datos en Colombia.
