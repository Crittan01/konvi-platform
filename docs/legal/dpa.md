# Acuerdo de Tratamiento de Datos (DPA)

> **Template inicial — requiere revisión legal antes de firma vinculante.**
> Este documento sirve como punto de partida del acuerdo entre el Tenant
> (Responsable) y Commerce Ops Platform (Encargado) bajo Ley 1581/2012.

---

## 1. Partes

- **Responsable del Tratamiento:** el Tenant que opera el negocio
  comercial. Identificado por `tenant_id` en la plataforma.
- **Encargado del Tratamiento:** Commerce Ops Platform (la "Plataforma").

## 2. Objeto

Regular el tratamiento de datos personales que el Encargado realiza por
cuenta del Responsable para operar:

- Atención al cliente vía WhatsApp y otros canales.
- Procesamiento de pedidos y pagos.
- Logística y envíos.
- Comunicaciones transaccionales y notificaciones.

## 3. Datos tratados

| Categoría | Ejemplos | Finalidad |
|---|---|---|
| Identificación | Nombre, tipo y número de documento | Facturación, envío |
| Contacto | Phone, email, dirección | Operativa de pedido |
| Transaccional | Pedidos, pagos, tracking | Cumplimiento del servicio |
| Conversacional | Mensajes WhatsApp, audio, multimedia | Atención al cliente |
| Audit | Consent, accesos PII, eventos SAR | Cumplimiento Habeas Data |

## 4. Finalidades autorizadas

El Encargado solo trata datos para:

1. Operar el servicio contratado por el Responsable.
2. Cumplir obligaciones legales (Ley 1581 Arts. 14, 15, 16, 19, 9, 18).
3. Soporte técnico y mantenimiento.
4. Mejora del servicio en datos agregados/anonimizados.

NO se usan para venta, publicidad de terceros, ni cesión no autorizada.

## 5. Obligaciones del Encargado

- Procesar siguiendo instrucciones del Responsable.
- Confidencialidad del personal con acceso (NDA).
- Medidas de seguridad: cifrado en tránsito (TLS 1.2+) y en reposo,
  RLS por tenant, audit log inmutable, retention policies.
- Atender solicitudes del titular vía herramientas SAR proveídas al Tenant.
- Informar al Responsable de incidentes de seguridad en ≤ 72 horas
  (ver `incident-response.md`).
- Eliminar o devolver datos al término del contrato.

## 6. Subprocesadores

Listados en `subprocessors.md`. Cambios notificados con 30 días previos.
El Responsable puede objetar.

## 7. Derechos del Titular

El Encargado provee al Responsable:

- Endpoint `/api/v1/contacts/{id}/data-subject-request` (export, rectify, erase, portability).
- Audit log inmutable `consent_audit_log`.
- Retención automática vía `retention_policies` configurable per-tenant.
- Self-service vía WhatsApp (cliente pide "envíame mis datos").

## 8. Transferencias internacionales

Algunos subprocesadores operan en USA/EU. Se aplican Cláusulas
Contractuales Tipo (SCCs) y mecanismos equivalentes reconocidos.

## 9. Terminación

- Al fin del contrato: anonimización completa de PII en 30 días o
  devolución al Responsable, a elección.
- Audit logs se conservan por 5 años (obligación legal).

## 10. Responsabilidad

Cada parte responde por su rol. La Plataforma no es solidariamente
responsable por instrucciones ilegales del Tenant.

## 11. Auditoría

El Responsable puede solicitar evidencia de cumplimiento (logs,
certificaciones de subprocesadores) con 30 días de antelación, hasta
una vez por año, a costo del Responsable.

## 12. Vigencia

Acuerdo vigente mientras dure el contrato comercial principal.

---

> **Cláusula técnica:** la aceptación electrónica del DPA queda registrada
> en `tenant_legal_acceptance` con timestamp y versión del documento.
