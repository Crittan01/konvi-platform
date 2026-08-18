# Contrato tipo Tenant ↔ Konvi — Borrador Cláusulas

**Estado:** BORRADOR para revisión legal externa.
**Audiencia:** abogado comercial colombiano contratado por founder.
**Objetivo:** plantilla base de cláusulas que el abogado convertirá en contrato definitivo + adaptará a contexto persona natural Konvi → SAS Konvi (Fase 3 estrategia).

> ⚠️ **Este documento NO es un contrato firmable.** Es un punto de partida con cláusulas críticas que el founder debe llevar al abogado para revisión y formalización. NO usar tal cual con tenants.
>
> Rev. 2026-08-02: corregido operador logístico (Envia→Aveonline). Pendiente revisión de abogado antes de firma con tenants (ítem B3 del PLAN).

---

## Contexto operativo

- **Konvi** (hoy persona natural founder; en Fase 3 estrategia → SAS Konvi) presta servicio SaaS de comercio conversacional WhatsApp + integraciones (Wompi, Aveonline, MeLi, Telegram) a tenants B2B.
- **Tenant** = pyme/empresa colombiana que contrata Konvi para operar su canal de venta vía WhatsApp + integraciones.
- **Relación legal**: Konvi presta SERVICIO DE SOFTWARE (SaaS). NO es intermediario financiero, NO procesa pagos a nombre del tenant, NO actúa como agregador. El tenant configura sus propias credenciales Wompi (key-per-tenant). Konvi cobra suscripción mensual SaaS al tenant — esto es pago por servicio prestado, NO recaudo a terceros.

---

## Cláusulas críticas (las que NO deben faltar)

### 1. Objeto y naturaleza del servicio

**Propósito:** delimitar que Konvi presta software, no intermediación.

> El presente contrato tiene por objeto la prestación, por parte de KONVI al CLIENTE, del servicio de software como servicio ("SaaS") denominado "Konvi", consistente en una plataforma tecnológica que automatiza la atención conversacional vía WhatsApp y canales integrados, facilita la gestión de catálogo de productos, conversaciones con clientes finales del CLIENTE, generación de órdenes y enlaces de pago hacia las pasarelas de pago que el propio CLIENTE configure con sus credenciales.
>
> **KONVI NO actúa como intermediario financiero, agregador de pagos, recaudador a nombre de terceros, ni gestor de cobros de transacciones del CLIENTE con sus clientes finales.** Los pagos efectuados por los clientes finales del CLIENTE son procesados directamente por las pasarelas de pago contratadas por el CLIENTE bajo sus propias credenciales y términos comerciales, ingresando directamente a la cuenta bancaria del CLIENTE sin paso por cuentas de KONVI.
>
> La presente contratación NO constituye sociedad, joint venture, mandato, agencia comercial, distribución, franquicia, ni representación legal de ningún tipo.

### 2. Suscripción, vigencia y renovación

> **Plan contratado:** [Starter / Pro / Enterprise — definir]
>
> **Valor mensual:** $[X] COP + IVA si aplica.
>
> **Vigencia inicial:** [12] meses contados a partir de la fecha de firma o activación efectiva del servicio (lo posterior).
>
> **Renovación:** el contrato se renovará automáticamente por periodos sucesivos de [12] meses, salvo notificación escrita de no renovación enviada con al menos [30] días calendario de anticipación al vencimiento del periodo en curso.
>
> **Reajuste anual:** KONVI podrá ajustar el valor de la suscripción anualmente con base en el IPC certificado por el DANE del año inmediatamente anterior, sin que el incremento supere el IPC + 3 puntos porcentuales. Cualquier ajuste se notificará con [60] días de anticipación.

### 3. Limitación de responsabilidad (CRÍTICA)

**Propósito:** tope tu exposición patrimonial. Sin esto, demanda civil = patrimonio personal completo.

> En la máxima medida permitida por la legislación colombiana aplicable, la responsabilidad total y agregada de KONVI frente al CLIENTE por cualquier reclamo derivado o relacionado con este contrato, independientemente de la causa (incumplimiento contractual, hecho ilícito, responsabilidad estricta o cualquier otra), estará limitada a la suma de las CONTRAPRESTACIONES PAGADAS EFECTIVAMENTE por el CLIENTE a KONVI durante los DOCE (12) meses inmediatamente anteriores al hecho generador del reclamo.
>
> En ningún caso la responsabilidad total agregada de KONVI excederá la suma de [TOPE FIJO, ej. $50.000.000 COP] independientemente del número de reclamos o causas.
>
> Esta limitación NO aplica para: (i) dolo o culpa grave debidamente probados; (ii) violación de obligaciones expresas de confidencialidad sobre datos del CLIENTE; (iii) sanciones impuestas por autoridades por infracciones imputables a KONVI a la Ley 1581 de 2012 (Habeas Data) específicamente respecto a obligaciones que correspondan a KONVI como Encargado del Tratamiento.

### 4. Exclusión de daños indirectos (CRÍTICA)

> Bajo ninguna circunstancia KONVI será responsable frente al CLIENTE por daños indirectos, incidentales, consecuenciales, especiales, punitivos o ejemplarizantes, incluyendo pero no limitado a:
>
> - Lucro cesante o pérdida de utilidades esperadas;
> - Pérdida de oportunidades comerciales o reputacionales;
> - Pérdida de datos consecuencial a fallas no atribuibles a dolo o culpa grave de KONVI;
> - Daño moral;
> - Costos de procurar bienes o servicios sustitutos;
> - Interrupciones de negocio.
>
> Esta exclusión aplica incluso si KONVI hubiera sido advertido de la posibilidad de tales daños.

### 5. Indemnidad recíproca

> **5.1 El CLIENTE mantendrá indemne a KONVI** y a sus representantes, contra cualquier reclamo, demanda, acción, sanción, multa, costo o gasto (incluyendo honorarios razonables de abogado) que se derive de: (i) el contenido, productos, servicios, ofertas, promociones, precios, condiciones de venta y comunicaciones que el CLIENTE distribuya, publique o procese a través de la plataforma KONVI; (ii) el uso indebido de la plataforma por el CLIENTE o por terceros bajo su responsabilidad; (iii) la falta de obtención por parte del CLIENTE de las autorizaciones requeridas a sus propios clientes finales para el tratamiento de datos personales conforme a la Ley 1581 de 2012; (iv) la veracidad y legalidad de la información comercial del CLIENTE.
>
> **5.2 KONVI mantendrá indemne al CLIENTE** únicamente respecto a reclamos por infracción de derechos de propiedad intelectual de terceros causados directamente por el código fuente propietario de la plataforma KONVI (excluyendo componentes open-source de terceros y configuraciones del CLIENTE).

### 6. Tratamiento de datos personales — Habeas Data Ley 1581 de 2012

**Propósito:** clarificar roles legales y obligaciones recíprocas según marco colombiano.

> **6.1 Roles legales:** las partes reconocen y aceptan que, respecto a los datos personales de los CLIENTES FINALES del CLIENTE que se traten en la plataforma KONVI:
>
> - El **CLIENTE** actúa como **Responsable del Tratamiento** conforme a la Ley 1581 de 2012, en tanto determina las finalidades del tratamiento, recolecta las autorizaciones de los titulares y mantiene la relación comercial primaria.
> - **KONVI** actúa como **Encargado del Tratamiento**, en tanto procesa los datos por cuenta y según instrucciones del CLIENTE para prestar el servicio.
>
> **6.2 Obligaciones de KONVI como Encargado:**
>
> - Tratar los datos personales únicamente con la finalidad de prestar el servicio contratado;
> - Implementar medidas técnicas y organizativas razonables para proteger los datos, incluyendo cifrado en tránsito (TLS) y en reposo, control de accesos por roles, registro de auditoría;
> - Notificar al CLIENTE en un plazo no superior a [72] horas tras tomar conocimiento de cualquier incidente de seguridad que afecte datos personales bajo tratamiento;
> - Permitir al CLIENTE ejercer sus derechos de información, acceso, rectificación, supresión y revocación respecto a los titulares;
> - Devolver o destruir los datos al término del contrato según instrucciones documentadas del CLIENTE, conservando solo lo legalmente exigible.
>
> **6.3 Obligaciones del CLIENTE como Responsable:**
>
> - Obtener autorización expresa, previa e informada de los titulares conforme al artículo 9 de la Ley 1581 de 2012 antes de incorporar sus datos a la plataforma;
> - Mantener política de tratamiento de datos publicada y vigente;
> - Atender consultas y reclamos de titulares en los términos del artículo 14 y 15 de la Ley 1581 de 2012;
> - Comunicar a KONVI las solicitudes de los titulares que requieran acción de KONVI como Encargado.
>
> **6.4 Subprocesadores:** KONVI podrá subcontratar tratamiento a los subprocesadores listados en [`docs/legal/subprocessors.md`](subprocessors.md) (Supabase, Render, Resend, Google Gemini, Meta/WhatsApp, Wompi, Aveonline, etc.). Cualquier nuevo subprocesador será notificado al CLIENTE con [30] días de anticipación.

### 7. Force majeure y caso fortuito

> Ninguna de las partes será responsable por incumplimiento o demora derivado de eventos de fuerza mayor o caso fortuito, incluyendo sin limitación: catástrofes naturales, pandemias declaradas por autoridad sanitaria, conflictos armados, decisiones gubernamentales o regulatorias sobrevinientes, ataques cibernéticos masivos a infraestructura nacional, interrupciones prolongadas de servicios de terceros esenciales para la operación (proveedores cloud como Supabase, Render, Google Cloud; pasarelas Wompi; APIs Meta/WhatsApp Business; redes de telecomunicaciones).
>
> La parte afectada notificará a la otra dentro de [5] días hábiles tras conocer el evento e implementará esfuerzos razonables para mitigar el impacto.

### 8. Servicios de terceros (disclaimer)

> El CLIENTE reconoce y acepta que la plataforma KONVI integra servicios de terceros (Meta/WhatsApp Business API, Wompi como pasarela de pagos, Aveonline como operador logístico, Mercado Libre como marketplace, Telegram, Resend, etc.). **KONVI NO controla ni responde por:**
>
> - Caídas o degradación de servicio de los proveedores terceros;
> - Cambios en los términos comerciales, precios, comisiones o políticas de los proveedores terceros;
> - Decisiones de los proveedores terceros respecto a la habilitación, suspensión o cancelación de cuentas del CLIENTE en sus plataformas (ej. baneo Meta Business, suspensión Wompi por compliance, etc.);
> - Sanciones impuestas al CLIENTE por los proveedores terceros derivadas del uso que el CLIENTE haga del servicio.
>
> El CLIENTE contrata directamente con los proveedores terceros (especialmente Meta WhatsApp Business y Wompi) bajo sus propios términos comerciales, los cuales prevalecen sobre cualquier disposición de este contrato respecto a esa relación bilateral.

### 9. Confidencialidad

> Cada parte se obliga a mantener confidencial toda información comercial, técnica, financiera y operativa de la otra parte a la que tenga acceso con ocasión de la ejecución del contrato, durante la vigencia del mismo y por [3] años posteriores a su terminación.
>
> No se considerará confidencial la información que: (i) sea de dominio público sin culpa de la parte receptora; (ii) sea desarrollada independientemente sin uso de información de la otra parte; (iii) deba ser revelada por orden de autoridad competente.

### 10. Terminación

> **10.1 Por mutuo acuerdo** en cualquier momento.
>
> **10.2 Unilateral con preaviso:** cualquiera de las partes podrá terminar el contrato sin causa con [60] días calendario de preaviso escrito. En tal caso, las contraprestaciones ya pagadas no son reembolsables (excepto pagos anticipados anuales, los cuales se reembolsan prorrateados).
>
> **10.3 Por incumplimiento:** la parte cumplida podrá terminar el contrato con efecto inmediato si la parte incumplida no subsana el incumplimiento dentro de [30] días calendario tras notificación escrita detallando el incumplimiento.
>
> **10.4 Causales automáticas:** se declara terminado el contrato sin necesidad de declaración judicial ante:
> - Mora superior a [60] días en el pago de la suscripción;
> - Apertura de proceso de insolvencia, liquidación judicial o quiebra de cualquiera de las partes;
> - Uso de la plataforma para actividades ilegales, fraudulentas, o que violen las políticas de uso de los proveedores terceros (especialmente Meta Business Policy y Habeas Data).
>
> **10.5 Efectos de la terminación:**
> - KONVI suspenderá el acceso a la plataforma dentro de [5] días hábiles;
> - Los datos del CLIENTE se conservan por [30] días en estado read-only para permitir exportación; tras ese plazo se eliminan de forma irreversible conforme a `tenant_offboarding_workflow` (J.2.4.4 ya implementado en el repo);
> - Sobreviven a la terminación: cláusulas 3 (limitación responsabilidad), 4 (daños indirectos), 5 (indemnidad), 6 (Habeas Data residual), 9 (confidencialidad), 11 (resolución conflictos).

### 11. Resolución de conflictos

> Las controversias derivadas de este contrato se intentarán resolver primero de buena fe mediante negociación directa entre representantes autorizados por [30] días.
>
> Si no hay acuerdo, las partes podrán acudir a:
>
> **Opción A — Centro de Arbitraje Cámara de Comercio de Bogotá:** arbitraje en derecho, tribunal de [3] árbitros, en idioma español, según el reglamento del Centro de Arbitraje y Conciliación de la Cámara de Comercio de Bogotá. El laudo será definitivo, inapelable y obliga a las partes. Aplicable cuando el monto en discusión sea superior a [200] SMMLV.
>
> **Opción B — Jurisdicción ordinaria:** jueces civiles del domicilio del demandado. Aplicable a controversias menores o cuando ambas partes lo prefieran.
>
> **Ley aplicable:** legislación colombiana.

### 12. Notificaciones

> Las notificaciones formales se cursarán por correo electrónico a:
>
> - **A KONVI:** [correo legal/contractual permanente] (recomendado: distinto del correo Wompi locked, para flexibilidad futura — ej. `legal@konvi.co` cuando exista dominio propio)
> - **AL CLIENTE:** [correo registrado al momento de la firma]
>
> Las notificaciones se entenderán recibidas al día siguiente hábil de su envío, salvo prueba de rebote o no entrega.

### 13. Cesión

> El CLIENTE no podrá ceder este contrato sin autorización previa y escrita de KONVI.
>
> **KONVI sí podrá ceder este contrato como parte de:** (i) reorganización empresarial (constitución de SAS Konvi y aporte del giro ordinario); (ii) fusión, escisión o venta de la empresa; (iii) consolidación corporativa. En tales casos KONVI notificará al CLIENTE con [30] días de anticipación. **Esto es CRÍTICO para la estrategia de migración persona natural → SAS Konvi documentada en `ADR-0022`.**

### 14. Independencia de cláusulas

> Si alguna cláusula se declara nula o inejecutable por autoridad competente, las demás cláusulas mantendrán plena vigencia.

### 15. Acuerdo íntegro

> Este contrato, junto con los anexos: (i) Plan contratado y precio; (ii) Política de Privacidad ([`docs/legal/privacy-policy.md`](privacy-policy.md)); (iii) DPA ([`docs/legal/dpa.md`](dpa.md)); (iv) Lista de subprocesadores ([`docs/legal/subprocessors.md`](subprocessors.md)); (v) Política de Respuesta a Incidentes ([`docs/legal/incident-response.md`](incident-response.md)); constituye el acuerdo íntegro entre las partes y reemplaza cualquier acuerdo previo verbal o escrito.

---

## Cláusulas opcionales según tipo de tenant

### Si el tenant es Gran Contribuyente o Autorretenedor

> El CLIENTE declara su calidad de [Gran Contribuyente / Autorretenedor de renta y/o IVA] y aplicará las retenciones de ley sobre los pagos a KONVI, entregando los certificados respectivos. KONVI ajustará la facturación electrónica reflejando dichas retenciones.

### Si el tenant exige SLA (típico Enterprise)

> KONVI garantiza disponibilidad del servicio del [99.0%] mensual calculada sobre las horas del mes calendario, excluyendo: (i) ventanas de mantenimiento programado notificadas con [48h] de anticipación; (ii) caídas atribuibles a proveedores terceros (Render, Supabase, Meta, Wompi, etc.); (iii) eventos de fuerza mayor.
>
> Incumplimiento del SLA da derecho al CLIENTE a crédito en facturación proporcional al downtime imputable.

### Si el tenant requiere DPA estándar (firma DPA separado)

> Las partes suscriben separadamente el Acuerdo de Procesamiento de Datos (DPA) anexo, que detalla los términos específicos de tratamiento conforme a la Ley 1581 de 2012 y, cuando aplique, GDPR/CCPA para subprocesadores internacionales.

---

## Items que el abogado DEBE revisar y ajustar

1. **Tope de limitación de responsabilidad** (cláusula 3): el monto sugerido $50M COP es referencia. Abogado define según riesgo real + capacidad financiera Konvi + práctica de mercado SaaS Colombia.
2. **Régimen IVA y facturación**: ajustar redacción según si Konvi está en régimen simplificado (no responsable IVA) o responsable IVA tras superar 3.500 UVT (~$183M COP anuales 2026).
3. **Cláusula de cesión** (13): asegurar que la redacción permite la cesión persona natural → SAS sin renegociación con cada tenant.
4. **Subprocesadores** (6.4): mantener actualizado el listado oficial en `docs/legal/subprocessors.md` con cada cambio de proveedor.
5. **Notificaciones a KONVI** (12): usar email permanente (ej. `legal@konvi.co` cuando exista dominio) que NO sea el correo Wompi locked.
6. **Validar consistencia** con DPA y Política de Privacidad existentes en `docs/legal/`.

---

## Próximo paso

Founder: agendar reunión con abogado comercial especializado en tech/SaaS Colombia. Llevarle este documento + repo `docs/legal/*` existente. Costo estimado revisión + ajustes + plantilla firmable: $1-2M COP one-shot.

Tras revisión, el abogado emite versión definitiva firmable que reemplaza este borrador. Mover este `contract-template-tenant.md` a `docs/legal/archive/` y reemplazar por `contract-tenant.md` definitivo.

## Referencias

- [`ADR-0022`](../adr/0022-legal-entity-billing-rails-risk-mitigation.md) — Estrategia entidad legal Konvi
- [`docs/legal/dpa.md`](dpa.md) — Data Processing Agreement
- [`docs/legal/privacy-policy.md`](privacy-policy.md) — Política de privacidad pública
- [`docs/legal/subprocessors.md`](subprocessors.md) — Lista de subprocesadores
- [`docs/legal/incident-response.md`](incident-response.md) — Política de respuesta a incidentes
- [`docs/legal/insurance-checklist.md`](insurance-checklist.md) — Checklist para corredor de seguros (complementa este contrato)
