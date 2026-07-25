# ADR-0040 — Comprobante de compra no fiscal

**Estado:** PROPUESTO · 7 decisiones abiertas del founder (§6), una de ellas bloqueante del diseño de datos
**Fecha:** 2026-07-25
**Origen:** bloqueante 12 de `docs/reports/launch_readiness_2026_07_25.md` — *"el comprador no recibe
NINGÚN documento de compra"*.
**Grounding legal (verificado en fuentes primarias, ver §7):** Ley 1480 de 2011 actualizada
(`alcaldiabogota.gov.co/sisjur`), Ley 2439 de 2024 (Diario Oficial 52.975 vía `lector.ramajudicial.gov.co`),
Decreto 1074 de 2015, Estatuto Tributario y Res. DIAN 000165/2023 (`normograma.dian.gov.co`).
**Coordina con:** ADR-0025 (aislamiento multi-tenant), ADR-0003 (Habeas Data), #163 (identidad legal
del tenant), #175 (coherencia del dinero).

---

## 1. El problema no es el que parecía

El planteo inicial fue *"sería bueno darle un recibo al comprador"*. La verificación contra fuente
oficial lo reencuadra: **no es una cortesía de producto, es una obligación con plazo.**

**Ley 1480 art. 50 lit. d)** — vigente, la Ley 2439 de 2024 modificó los literales b, g y h, **no** el
d) — obliga al proveedor en ventas por medios electrónicos a:

- remitir **acuse de recibo del pedido a más tardar el día calendario siguiente**, y
- poner a disposición un **resumen del pedido, imprimible y/o descargable**,

con contenido tasado: tiempo de entrega, precio exacto **con impuestos incluidos**, gastos de envío
**informados por separado** (lit. c) y forma de pago.

Hoy el comprador no recibe nada de eso de forma consistente, y lo que recibe depende del camino:

| Camino a `confirmed` | Qué recibe hoy el comprador |
|---|---|
| Wompi APPROVED | WhatsApp determinista + email con desglose (**el único completo**) |
| Contra entrega (COD) | **Ningún email.** El texto de WhatsApp lo emite el LLM desde `direct_response` |
| Operador (`auto_confirm`) | **Nada** |
| Operador (PATCH → confirmed) | **Nada** |
| MercadoLibre | **Nada** (MeLi emite su propio documento) |

---

## 2. Por qué el documento es el paso 3 y no el paso 1

Un comprobante es un **compromiso público sobre cifras y condiciones legales**. Emitirlo sobre un
modelo que no garantiza ninguna de las dos convierte una brecha cosmética en una sancionable:
**Ley 1480 art. 26** — si al consumidor le aparecen dos precios distintos, solo está obligado al menor.

El diseño destapó que el modelo de dinero **nunca tuvo que satisfacer esa coherencia**:

- **`confirm_rate` actualizaba `shipping_cost` sin recalcular `total_amount`** (que es el que se cobra).
  → **Arreglado en #175.** Era el mismo *"COD quote incoherence"* anotado sin diagnóstico en el UAT de julio.
- **El clamp `max(0, subtotal + envío − descuento)`** puede imprimir `Subtotal 50.000 / Descuento
  −80.000 / Envío 10.000 / TOTAL 0`, que no es aritmética sino una contradicción impresa. #175 lo deja
  registrado; falta decidir si el descuento a imprimir es el **efectivamente aplicado** en vez del nominal.

**Regla de diseño que se adopta:** si las cifras no cuadran, **no se emite comprobante — se emite
alerta**. Es preferible no documentar a documentar una contradicción.

---

## 3. Arquitectura: separar ARMADO, PRESENTACIÓN y ENTREGA

Hoy están fundidos (el texto vive en el mismo lugar que el envío). Separarlos es lo que permite que el
paso 1 no haya que tirarlo para hacer el paso 2.

### 3.1 Armado — `public.order_receipts`

Un **snapshot `jsonb` congelado** en el instante de la confirmación: vendedor, comprador, ítems con su
variante y precios, totales discriminados, forma de pago, entrega, cupón, más `content_hash` sha256.

**Congelar es lo que convierte el documento en comprobante.** `order_items` ya congela `title` y
`unit_price` en el INSERT y sobrevive al borrado del catálogo (`ON DELETE SET NULL`) — buena base. Pero
el **vendedor** y las **condiciones legales** hoy se resolverían con un lookup vivo, y un comprobante no
puede cambiar de contenido porque el tenant editó su perfil el mes siguiente.

**El consecutivo va en el comprobante, NO en `orders`.** Razón concreta: `payment_link_tool.py` y
`cart_tool.py` **cancelan la orden `pending_payment` y crean otra** cada vez que el cliente cambia el
carrito o aplica un cupón. Numerar en el INSERT de `orders` haría que un cliente indeciso queme 3-4
números en órdenes que nunca existieron comercialmente, dejando el consecutivo agujereado — y pondría
un `pg_advisory_xact_lock` por tenant en el INSERT de dinero de mayor concurrencia del sistema.
Numerando `order_receipts` (solo lo emitido) el consecutivo queda **denso** y no se toca ese camino.

Idempotente por `UNIQUE(tenant_id, order_id)`. RLS + policies RESTRICTIVE anti-escritura desde
`authenticated`, con el molde de #165/#173.

### 3.2 Presentación

- `render_receipt_html` — imprimible desde la consola (**Cmd+P → PDF**). **Cero dependencias nuevas**:
  es la decisión ya tomada en el repo (`services/api/routers/data_subject_request.py:407-412`).
- `render_receipt_whatsapp_ack` — **acuse corto, ≤10 líneas**.

### 3.3 Entrega

**WhatsApp es el canal primario, por cobertura y no por estética:** `contacts.phone` es `NOT NULL`,
`contacts.email` es opcional — y el email de confirmación **se salta en silencio** cuando no hay correo
(`wompi_webhook.py:1524-1529`). WhatsApp llega al 100% de los compradores; el correo no.

**Pero por WhatsApp va solo el acuse corto, no el documento completo.** Razón técnica, no de gusto:
`messages` alimenta el contexto conversacional del LLM (`dispatcher.py:2149`, `_get_conversation_history`).
Meter 1.100–1.500 caracteres de cifras y cláusulas legales en el hilo (a) cuesta tokens en **cada turno
posterior** y (b) le da al LLM un documento lleno de números para parafrasear o re-citar — colisión
directa con el principio 4 del proyecto (*el LLM no decide verdad transaccional*) y con el hallazgo de
UAT del *"total mentido"*. El detalle completo va por correo y por la consola.

### 3.4 Ciclo de vida — `void_receipt()`

**Lo que separa un documento de un mensaje.** El pipeline de cancelación con reembolso está vivo
(`orders.py:452`, `lib/order_cancellation.py:344`, y un `VOIDED` tardío tras un `APPROVED` ya confirmado
en `wompi_webhook.py:418-430`). Secuencia trivial de reproducir: pedido confirmado → comprobante
entregado → cancelación o reembolso → **el comprador se queda con un documento que afirma una compra que
ya no existe**. Un comprobante es una afirmación pendiente, no un evento de fin de flujo.

---

## 4. Alcance del primer PR

**Dentro:** Wompi APPROVED + COD + los dos caminos de operador.
**Fuera, con motivo:** MercadoLibre — no porque el router no esté montado (lo está), sino porque no hay
canal al comprador y MeLi emite su propio documento.
**Diferido al paso 6:** enlace público firmado, PDF server-side, plantillas HSM, adjuntos.

Se difiere el **endpoint público con token HMAC**: es superficie de red nueva y expuesta, con PII
potencialmente sensible (Ley 1581 art. 5, vertical Salud y Belleza), por un beneficio que el correo y la
consola ya cubren.

**Dependencias nuevas: ninguna.**
**Esfuerzo estimado: 7–8 días**, incluyendo coherencia del dinero y ciclo de vida.

---

## 5. El documento NO puede parecer una factura DIAN

Riesgo real de **publicidad engañosa** (art. 30, exequible por C-592/2012): inducir a error o confusión.
Se adopta un **test de contrato**: el HTML y el texto **fallan el build** si contienen `factura de venta`,
`CUFE`, `Documento validado por la DIAN` o un QR.

---

## 6. Decisiones del founder (no del implementador)

> Cada una viene con recomendación, como corresponde.

1. **🔴 BLOQUEANTE — ¿el comprobante sobrevive a una supresión de Habeas Data?**
   Conflicto normativo real: **Ley 1480 art. 50 lit. e** obliga a conservar prueba de la operación *"por
   el mismo tiempo que se deben guardar los documentos de comercio"*; **Ley 1581** obliga a suprimir.
   Hoy `contact_cleanup.py:385-392` **preserva** `orders`/`order_items` cuando hay pedidos, pero borra
   `messages` **siempre e incondicionalmente**.
   *Recomendación: ser consistente con el precedente ya existente — el comprobante sigue la suerte de
   `orders` (se preserva), no la de `messages`. Es la interpretación que ya está en producción y no
   inventa semántica nueva. **Requiere concepto de abogado colombiano para cerrarla.***

2. **¿Se emite con identidad legal incompleta?** Hoy `razon_social`, `tipo_persona`, `doc_tipo`,
   `doc_dv`, `regimen_iva` y `domicilio_*` están NULL para todos los tenants (#163 solo backfilleó
   `doc_numero := nit`).
   *Recomendación: SÍ, degradado, con WARN estructurado + banner en la consola. El acuse tiene plazo
   legal (día calendario siguiente); no emitir cambia un incumplimiento cosmético por uno cierto.*

3. **¿Quién responde por el texto legal?** Si Konvi redacta el bloque de derechos del consumidor y está
   mal, ¿la exposición es de Konvi o del tenant? Define si el texto es de plataforma, per-tenant
   editable, o mixto. **Requiere asesor legal.**

4. **¿El comprador se entera de la anulación?** Cuando un pedido se cancela o reembolsa después de
   enviado el comprobante.
   *Recomendación: sí, mensaje corto y determinista. Enterarse por un cargo que no llega es peor.*

5. **El número de pedido cambia de forma en la UI** — hoy operadores y clientes citan el hex corto del
   UUID. Hay que anunciarlo y decidir si se numeran retroactivamente los pedidos históricos.

6. **MercadoLibre dentro o fuera** (ver §4 para el motivo correcto).

7. **Art. 616-1 ET** — *"las plataformas de comercio electrónico deberán poner a disposición un servicio
   que permita la expedición y entrega de la factura electrónica de venta por parte de sus usuarios al
   consumidor final"*. Obligación **de la plataforma**, no del tenant, y **distinta** del comprobante no
   fiscal de este ADR. **Verificar aplicabilidad y plazo con el contador.**

---

## 7. Nota de método sobre las fuentes legales

La verificación se hizo con un agente adversarial **instruido a refutar**, no a confirmar. Es relevante
que reportó sus propias limitaciones en vez de taparlas: `funcionpublica.gov.co` falló con error de
certificado y `secretariasenado.gov.co` con conexión rechazada, así que **ninguna** de las URLs citadas
en la primera pasada pudo abrirse en su origen. Lo confirmado se ancló en Diario Oficial 52.975 (vía
`lector.ramajudicial.gov.co`), `alcaldiabogota.gov.co/sisjur` y `normograma.dian.gov.co`.

Correcciones que produjo esa segunda pasada, y que muestran por qué hacía falta:

- La devolución de dinero por retracto es de **30 días calendario**, no hábiles — varias fuentes
  secundarias lo dicen mal.
- En comercio electrónico la Ley 2439/2024 art. 3 la acota a **15 días calendario**.
- **Obligación de FACTURAR (DIAN)** y **obligación de INFORMAR al consumidor (SIC / Ley 1480)** son
  cosas distintas y se mezclan con frecuencia. Este ADR trata solo la segunda.

Todo lo que no pudo anclarse en fuente oficial quedó marcado como no verificado y **no** se usó para
justificar decisiones de diseño.
