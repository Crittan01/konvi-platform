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

## 8. Cambios a esta política

Te notificaremos por WhatsApp con 30 días de antelación si la política
cambia materialmente.

---

**Versión:** [v2026-XX]
**Última actualización:** [fecha]
**Aceptación electrónica:** queda registrada al consentir el tratamiento.
