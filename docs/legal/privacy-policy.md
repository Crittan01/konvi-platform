# Política de Privacidad

> **Template inicial.** Cada tenant debe adaptar este documento a su
> propia operación y publicarlo en su canal/sitio. La Plataforma no
> publica esta política al titular final — eso es obligación del
> Tenant (Responsable).

---

## 1. Identificación del Responsable

**[Nombre del Tenant]**
**NIT:** [XXX]
**Dirección:** [XXX]
**Email contacto Habeas Data:** [habeasdata@tenant.com]

## 2. ¿Qué datos recogemos?

- **Identificación:** nombre, tipo y número de documento (CC, CE, etc.).
- **Contacto:** teléfono celular, email, dirección.
- **Transaccional:** pedidos, pagos, envíos.
- **Conversacional:** mensajes que envías por WhatsApp.

## 3. ¿Para qué los usamos?

- Procesar tu pedido y entregártelo.
- Atender tus consultas vía WhatsApp.
- Cumplir obligaciones tributarias y de logística.
- Notificaciones transaccionales (estado del pedido, pago, envío).

## 4. Tus derechos (Habeas Data Ley 1581/2012)

Como titular puedes:

- **Conocer** los datos que tenemos sobre ti (Art. 14). Escríbenos
  *"qué tienen sobre mí"* en WhatsApp y te respondemos en ≤ 48h.
- **Actualizar / rectificar** datos inexactos (Art. 16).
- **Solicitar supresión** (Art. 15). Escribe *"elimina mis datos"* en
  WhatsApp y se procesa al instante.
- **Portabilidad:** pedirnos tus datos en formato estructurado (Art. 19).
- **Revocar el consentimiento** en cualquier momento.
- **Quejarte ante la SIC** si crees que vulneramos tus derechos.

## 5. ¿Con quién compartimos tus datos?

Subprocesadores aprobados (lista en `subprocessors.md` de la plataforma):

- **Pasarela de pagos** (Wompi) — para procesar tu pago.
- **Mensajería** (Meta WhatsApp) — para entregarte mensajes.
- **Logística** (Envia.com / transportadora) — para el envío.
- **Hosting** (Supabase, Render) — almacenamiento técnico.

NO vendemos tus datos a terceros para publicidad.

## 6. Retención

- Mensajes WhatsApp: 6 meses.
- Conversaciones: 1 año.
- Datos de contacto sin actividad: 2 años (luego soft-delete).
- Audit logs: 5 años (obligación legal).

## 7. Seguridad

Aplicamos:

- Cifrado en tránsito (TLS 1.2+).
- Aislamiento por tenant (Row-Level Security).
- Audit inmutable de accesos a tu PII.
- Tokenización de número de documento (hash + last4 visible).

## 8. Menores de edad

**No procesamos datos de menores de edad sin autorización del representante legal.**

Marco normativo: Ley 1581/2012 + **Decreto 1377/2013 Art. 7** + Sentencia
C-748/2011 de la Corte Constitucional.

Nuestro sistema:

- No acepta el tipo de documento "Tarjeta de Identidad" (TI) en el
  registro de contactos. Los pedidos de menores deben registrarse con
  los datos del representante legal (padre, madre o tutor) como
  contacto principal.
- El bot de WhatsApp detecta cuando el cliente declara ser menor de
  edad ("tengo 14 años", "soy menor", etc.) o lo sugiere por contexto
  ("mi mamá me dijo", "tengo permiso de mis padres") y NO continúa
  el flujo comercial. Pide al representante legal que escriba al
  chat y escala la conversación a un operador humano.
- Si por error se registra a un menor sin autorización, el operador
  humano debe ejecutar Anonimizar (Art. 15) sobre el contacto y
  registrar la decisión en `consent_audit_log` con razón explícita.

Si eres menor de edad: por favor, pide a tu padre, madre o tutor que
nos escriba para gestionar tu compra. No podemos procesar tu solicitud
directamente.

## 9. Cambios a esta política

Te notificaremos por WhatsApp con 30 días de antelación si la política
cambia materialmente.

## 10. Datos importados desde marketplaces

Cuando recibimos órdenes desde marketplaces (Mercado Libre y otros), los
datos del comprador (nombre, teléfono) llegan automáticamente vía webhook
del marketplace y los almacenamos para gestionar la entrega y la atención
post-venta. Cada contacto importado queda marcado con
`consent_source = marketplace_meli` y un audit log inmutable referencia el
`meli_order_id` correspondiente.

El marketplace de origen aplica su propia política de privacidad sobre la
captura inicial del dato; el tenant es responsable del tratamiento posterior
bajo el DPA firmado con la plataforma. Si el titular ejerce sus derechos
Habeas Data, los flujos de SAR (export/portabilidad/anonimización) operan
exactamente igual que para contactos creados por otros canales.

---

**Versión:** [v2026-XX]
**Última actualización:** [fecha]
**Aceptación electrónica:** queda registrada al consentir el tratamiento.
