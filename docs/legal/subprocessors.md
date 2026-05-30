# Subprocesadores

Lista de terceros con quienes la plataforma comparte datos para operar.
Aplicable a tenants que firmaron el DPA. Esta lista forma parte del DPA
por referencia.

**Última actualización:** 2026-05-01 (rev. 98)
**Notificación de cambios:** 30 días antes de incorporar un nuevo
subprocesador (al email registrado en `notification_settings`).

---

## Subprocesadores activos

| Nombre | Rol | Datos compartidos | Jurisdicción | Compliance |
|---|---|---|---|---|
| **Supabase Inc.** | Hospedaje DB + Auth + Realtime | Toda la PII almacenada (con encryption-at-rest del proveedor) | USA / EU | SOC 2 Type II, ISO 27001 |
| **Meta Platforms (WhatsApp Business)** | Mensajería WhatsApp Cloud API v21 | Phone, contenido de mensajes, multimedia | USA / EU | SOC 2, [Meta DPA](https://www.facebook.com/legal/terms/dataprocessing) |
| **Google Cloud (Gemini API)** | LLM generativo (gemini-2.5-flash) | Texto de mensajes inbound (NO PII estructurada) | USA | SOC 1/2/3, ISO 27001/27017/27018 |
| **Wompi (Bancolombia Group)** | Procesamiento de pagos | Phone, doc, name, email, total, currency | Colombia | PCI-DSS L1, vigilado SFC |
| **Aveonline** | Cotización de envíos + generación de guías + tracking | Address, phone, name, document | Colombia | Política propia · Bancolombia partner |
| **Resend** | Envío de email transaccional | Email del operador (tenant), phone hash, contenido del template | USA / EU | SOC 2 in progress |
| **Render Inc.** | Hospedaje de servicios (web, api, orchestrator, connector) | Logs operativos (sin PII directa) | USA | SOC 2 Type II |

---

## Subprocesadores opcionales (per tenant)

| Nombre | Activación | Rol |
|---|---|---|
| **MercadoLibre** | Cuando el tenant conecta su cuenta ML | Catálogo + órdenes |
| **Telegram Bot API** | Cuando el tenant configura canal Telegram | Notificaciones operativas |

---

## Política de aprobación

1. Nuevo subprocesador = evaluación interna (compliance, seguridad, jurisdicción).
2. Notificación 30 días previos a tenants vía email + UI.
3. El tenant puede objetar y proponer alternativa o rescindir el contrato.

## Transferencias internacionales

Los proveedores con jurisdicción USA/EU implican transferencia
internacional. Cada uno tiene cláusulas estándar contractuales (SCCs)
o programa equivalente reconocido por la SIC para Colombia.
