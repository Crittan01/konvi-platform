# ADR-0022 — Estrategia entidad legal, rails de cobro y mitigación patrimonial

**Estado:** ACTIVO (Fase 0 blindaje fiscal en ejecución).
**Fecha:** 2026-05-30.
**Branch:** `develop` (vía PR docs-only).
**Audiencia:** founder, contador, abogado comercial.

## Contexto

Konvi opera hoy como SaaS B2B de comercio conversacional WhatsApp. Plan K llegó a 16/18 (89%) consolidado en `develop` tras sesión 2026-05-29/30. Tres preguntas estratégicas surgieron del founder en esta sesión 2026-05-30:

1. **¿Puede founder usar Konvi para 1-2 verticales propias** (cosmética, zapatos, ropa) además de servir tenants externos SaaS?
2. **¿Cómo manejar Wompi** con constraint duro de "1 cuenta persona natural por correo, correo locked"?
3. **¿Cómo cobrar suscripción SaaS** a futuros tenants externos?

Workflow adversarial 4-agentes (legal/fiscal · Wompi capabilities · estratégico · síntesis) integró las 3 dimensiones. Este ADR cristaliza la decisión.

### Hechos confirmados

- Founder es **persona natural** con **una cuenta Wompi actual** (correo inmutable).
- Wompi NO ofrece API marketplace/splits/sub-cuentas/subscriptions REST. Modelo canónico: **una cuenta merchant por comercio** (key-per-tenant — ya implementado correctamente en repo).
- Wompi: una cuenta = un nombre comercial en extracto bancario del cliente final. No hay statement_descriptor per-transaction.
- DIAN UVT 2026: $52.374. Umbral responsable IVA persona natural = 3.500 UVT = $183.309.000 ingresos brutos anuales. Por debajo: NO responsable IVA.
- Exclusión IVA cloud computing (art. 476 num. 21 ET + Concepto DIAN 017056/2017): aplica a SaaS si cumple 5 características NIST — Konvi califica. Requiere autodiagnóstico documentado.
- RST 2026 Grupo 3 (servicios profesionales / desarrollo software CIIU 6201/6202): tarifas 5.9%-7.3%. **Ventana inscripción 2026 cerró 28-feb-2026. Próxima ventana: 28-feb-2027.**
- Persona natural responde patrimonio personal ilimitado ante multas SIC (Habeas Data, hasta ~$2.847M COP 2026 = 2.000 SMMLV), demandas civiles tenants, chargebacks no cubiertos.
- Lucams (eCommerce esposa) está en memoria `project_lucams_camino_d.md` para Sem 14+ como tenant Konvi — encaja como tenant externo en el modelo per-tenant.
- Memoria `feedback_product_first.md`: trámites externos solo cuando bloqueen producción real.
- Memoria `feedback_dx_over_cost_optimization.md`: founder prefiere DX simple + arquitectura proactiva sobre ahorros marginales.

## Decisión

Adoptar estrategia **"Defer-Smart"** = persona natural HOY + SAS futura por triggers objetivos + mitigación patrimonial multi-capa **HOY**.

### Núcleo de la decisión

```
HOY  →  Persona natural Konvi (1 cuenta Wompi actual)
         │
         ├─ Rail OPERATIVO: cobros tenant→cliente-final usan credenciales Wompi DEL TENANT
         │  (key-per-tenant, Konvi NO toca ese dinero)
         │
         └─ Rail SUSCRIPCIÓN: cobros tenant→Konvi por servicio SaaS usan
            la cuenta Wompi de Konvi persona natural (= mismo founder)
            └─ Las verticales propias (KAIU, futura cosmética/zapatos)
               cobran clientes finales a la MISMA cuenta como product_sale

FUTURO (trigger-driven, NO fecha fija)  →  SAS Konvi
         │
         ├─ Nueva cuenta Wompi SAS (KYC nuevo Bancolombia)
         │  → exclusivamente rail SUSCRIPCIÓN SaaS
         │
         └─ Cuenta persona natural Wompi se queda para
            verticales propias del founder (KAIU + cosmética/zapatos)
```

### Triggers SAS (cualquiera de ellos activa migración)

| Trigger | Detalle | Acción |
|---|---|---|
| **Ingresos** | Ingresos brutos founder ≥ $10M COP/mes sostenidos 3 meses consecutivos | Constituir SAS Konvi en próximos 60 días |
| **Tenant Enterprise** | Tenant exige contrato con sociedad (compliance interno) | Adelantar SAS aunque ingresos no lo justifiquen |
| **Capital externo** | Inversión, deuda institucional, ronda angel | SAS obligatoria pre-cierre |
| **Tope IVA persona natural** | Ingresos consolidados founder cruzan 3.500 UVT (~$183M COP año) | SAS recomendada para separar contabilidad y limitar exposure IVA personal |
| **Vertical >$5M/mes** | Una vertical propia (cosmética/zapatos) escala sostenida | Evaluar SAS o aportar a SAS Konvi |

## Alternativas consideradas (rechazadas)

### A. SAS Konvi desde día 1 (RECHAZADA)
**Por qué no:** consume bandwidth founder ($1.5-2.5M setup + ~$500-800 USD/mes operativo) cuando aún no hay ingresos validados. Memoria `feedback_product_first.md`: trámites externos solo cuando bloqueen producción real. SAS hoy NO bloquea producto — solo paga overhead. Ventana RST persona natural 2026 ya cerró → SAS arrancaría sin RST hasta 28-feb-2027.

### B. Múltiples cuentas Wompi persona natural (RECHAZADA hasta validar)
**Por qué no:** no está confirmado oficialmente que persona natural puede tener N cuentas Wompi (correos distintos). Founder reportó "1 cuenta por persona". Esperar a Fase 2 (cuando arranque 2da vertical real) y validar con Wompi soporte antes de asumir.

### C. SAS Konvi pura + verticales propias en SAS separadas (RECHAZADA hoy)
**Por qué no:** triplica overhead operativo (3 SAS = 3 contadores, 3 RUT, 3 facturaciones). Solo justificable cuando cada vertical facture >$50M/mes sostenida. Considerar en Fase 4 si tracción lo amerita.

### D. Konvi como agregador de pagos (FUERTEMENTE RECHAZADA)
**Por qué no:** recibir pagos de clientes finales de los tenants en cuenta Konvi y dispersar a tenants = intermediación financiera regulada por Superintendencia Financiera. Requiere licencia SEDPE (Sociedad Especializada en Depósitos y Pagos Electrónicos). Fuera de alcance Konvi. Modelo actual key-per-tenant preserva a Konvi fuera de esa zona regulada.

## Mitigación patrimonial — 3 capas complementarias

### Capa 1 — Contractual (esta semana, $1-2M COP one-shot)

Cláusulas críticas en contrato tipo tenant (detalle en [`docs/legal/contract-template-tenant.md`](../legal/contract-template-tenant.md)):

- **Limitación de responsabilidad** a 12 meses de fee pagado, con tope absoluto $50M COP
- **Exclusión daños indirectos** (lucro cesante, daño moral, consecuenciales)
- **Indemnidad recíproca** con cláusula explícita: tenant indemniza a Konvi por su contenido
- **Habeas Data**: Konvi = Encargado; tenant = Responsable del Tratamiento
- **Force majeure** cubriendo caídas proveedores (Render, Supabase, Wompi, Meta)
- **Cesión** explícita permitida para reorganización persona natural → SAS
- **Servicios de terceros disclaimer** — Konvi no responde por baneos Meta, Wompi, etc.

Mitiga: demandas civiles de tenants. Costo: abogado comercial $1-2M COP one-shot revisión + plantilla.

### Capa 2 — Seguros (próximas 2-4 semanas, $3-5M COP/año)

Detalle en [`docs/legal/insurance-checklist.md`](../legal/insurance-checklist.md).

| Póliza | Cobertura | Prima anual |
|---|---|---|
| **RC Profesional / E&O** | Demandas civiles + defensa jurídica | $1.5-3M COP |
| **Cyber Risk** | Brechas datos + notification + forensics | $2-5M COP |
| **RC General** (opcional bundle) | Daños generales a terceros | $300-600K COP |

Mitiga: ~80% riesgo patrimonial sin requerir SAS.

**NO cubre:** multas SIC, sanciones DIAN, daños propios.

### Capa 3 — Estructural SAS (trigger-driven, Sem 20+ típico)

Mitigación definitiva vía velo societario. Setup $1.5-2.5M COP + operativo $500-800 USD/mes adicional.

**No es opcional a largo plazo** — toda SaaS profesional debe migrar a sociedad eventualmente. Pero NO es prerequisito para arrancar.

## Fase 0 — Blindaje fiscal inmediato (próximas 2-4 semanas)

> 🔴 **VENTANA CRÍTICA:** acciones que deben pasar en próximas 2 semanas o se posponen 6-12 meses.

### Acciones founder

| # | Acción | Plazo | Costo | Responsable |
|---|---|---|---|---|
| 1 | Contratar contador público titulado especializado SaaS | Semana 1 | $200-300 USD/mes | Founder |
| 2 | Verificar RUT con responsabilidad correcta + CIIU 6201/6202 | Semana 1 | $0 | Contador |
| 3 | Activar facturación electrónica DIAN (Alegra recomendado, $30 USD/mes) | Semana 1-2 | $30 USD/mes | Founder + Contador |
| 4 | Autodiagnóstico exclusión IVA cloud (NIST 5 características + Concepto DIAN 017056/2017) | Semana 2 | $0 (gratis) | Contador |
| 5 | Cotizar pólizas E&O + Cyber con 2-3 corredores (DelCorral + Aon + MAS) | Semana 1-2 | $0 (corredor pagado por aseguradora) | Founder |
| 6 | Contratar pólizas E&O + Cyber | Semana 3-4 | $3-5M COP/año | Founder |
| 7 | Cambiar `Nombre del comercio` Wompi a "KONVI" (descriptor neutro) | Semana 1 | $0 (1-5 días hábiles soporte) | Founder |
| 8 | Contratar abogado comercial revisar contrato tipo tenant | Semana 2-4 | $1-2M COP one-shot | Founder + Abogado |
| 9 | Revisar `docs/legal/dpa.md` + `privacy-policy.md` + `subprocessors.md` confirmar consistencia con persona natural | Semana 2 | $0 | Abogado |

**Costo total Fase 0:** ~$7-10M COP año 1.

### Acciones técnicas (Konvi código, post-implementación J.2.12)

| # | Item Plan K | Descripción |
|---|---|---|
| J.2.12 | **Subscription Billing Engine** (rail Konvi→tenant) | Link Wompi manual mensual + Resend reminder + reconciliación. Suficiente 1-3 tenants iniciales. Implementación posterior a UAT Plan K. |
| J.2.13 | **Two-rail accounting separation** | Ledger interno distingue rail operativo (tenant→cliente) vs rail suscripción (tenant→Konvi). Columna `payment_purpose ∈ ('product_sale', 'saas_subscription')`. |
| J.5.X | **Compliance fiscal tracking** | Cron mensual reporta ingresos brutos founder consolidados vs triggers SAS. Output: dashboard founder visibilidad ventana SAS. |

### Acción de tracking

| # | Tracking | Frecuencia |
|---|---|---|
| 1 | Ingresos brutos founder consolidados (KAIU + suscripción Konvi + verticales futuras) | Mensual |
| 2 | Estado triggers SAS (cuál se está acercando) | Mensual |
| 3 | Compliance Habeas Data (audit log SIC + retention pg_cron + DPA firmados) | Continuo (ya implementado rev 93-99) |
| 4 | Inscripción RST próxima ventana 28-feb-2027 | Recordatorio Q4-2026 |

## Roadmap por fases temporales

### Fase 0 (próximas 2-4 semanas) — Blindaje fiscal
- Acciones founder Fase 0 (ver arriba)
- Cambio nombre comercio Wompi a "KONVI"
- Contratar contador + abogado + 2 pólizas seguros

### Fase 1 (Sem 7-13) — Cerrar Plan K + J.2.12 + UAT
- NO abrir cuentas Wompi adicionales
- NO constituir SAS
- Cerrar Plan K 16/18 + UAT
- Implementar J.2.12 Subscription Billing Engine (link Wompi manual)
- Implementar J.2.13 Two-rail accounting
- Implementar J.5.X compliance fiscal tracking
- KAIU como vertical activa usando rail operativo (cuenta Wompi del tenant = la del founder)
- Primer tenant externo SaaS (cuando aparezca) con contrato firmado + factura electrónica

### Fase 2 (Sem 14-20) — Multi-vertical (solo si trigger)
- Solo si arranca 2da vertical propia (cosmética O zapatos) O Lucams
- Validar formalmente con Wompi soporte: ¿persona natural N cuentas?
- Si sí: abrir cuenta Wompi separada para 2da vertical (branding correcto)
- Si no: adelantar trigger SAS para esa vertical
- Lucams (esposa) abre SU PROPIA cuenta Wompi (a su nombre)

### Fase 3 (Sem 20+) — SAS Konvi (cuando trigger se cumpla)
- Constituir SAS Konvi (objeto social SaaS comercio conversacional)
- Inscripción RST SAS antes 28-feb del año correspondiente
- Nueva cuenta Wompi SAS (KYC Bancolombia 2-4 semanas)
- Rail SUSCRIPCIÓN migra a cuenta Wompi SAS
- Cuenta Wompi persona natural se queda con verticales propias
- Migrar costos Konvi (Render, Supabase, Gemini, Claude API) a SAS para deducibilidad
- Actualizar `docs/legal/*` (DPA, privacy, contratos) para reflejar SAS como Encargado
- D&O insurance opcional para administradores SAS

### Fase 4 (Sem 30+) — Consolidación opcional
- Si vertical propia escala >$10M/mes sostenida: SAS hija o línea de negocio en SAS Konvi
- Platform Console (Plan K Fase 12) solo si ≥3 tenants externos pagando
- Business Verification Meta + registro marca SIC + dominios múltiples (solo cuando bloqueen producción)
- Considerar D&O + Tech E&O internacional

## Decisiones que requieren intervención humana del founder

| # | Decisión | Cuándo | Recomendación |
|---|---|---|---|
| 1 | Aprobar Fase 0 completa | Esta semana | SÍ — no negociable, $7-10M COP/año mitiga 80% riesgo |
| 2 | Nombre comercial Wompi: "KONVI" vs "KAIU LIVING NATURAL" | Semana 1 | **"KONVI"** — alinea con marca SaaS futura |
| 3 | Contador y abogado a retener largo plazo | Fase 0 | Buscar especializado SaaS Colombia (nicho). Trabajar 6 meses antes de comprometerse |
| 4 | 2da vertical priorizada (cosmética O zapatos) | Sem 13-14 | Founder decide según margen + mercado |
| 5 | Lucams: persona natural propia O SAS propia (NO bajo tu cédula) | Sem 14+ coordinar con esposa | NO bajo tu cédula |
| 6 | Subscription engine: link manual vs PSP con subscriptions reales | Sem 13-20 | Link manual hasta 3 tenants, después PSP (Bold/dLocal/Stripe LATAM) |
| 7 | Al cumplir trigger SAS: SAS pura solo SaaS vs incluir verticales | Trigger | **SAS pura** — verticales quedan persona natural separadas |
| 8 | RST 2027: inscribir antes 28-feb-2027 | Recordatorio Q4-2026 | SÍ (5.9-7.3% sobre brutos vs 33% renta corporativa) |

## Hard constraints (NO negociables)

1. **Correo Wompi inmutable** — pensá bien correo definitivo
2. **UNA cuenta = UN nombre comercial** en extracto — cliente final ve "KONVI"
3. **Wompi NO tiene API marketplace** — Konvi NO es agregador, key-per-tenant es ley
4. **Persona natural = patrimonio personal ilimitado** — mitigar con Capa 1 + Capa 2 obligatorias
5. **Facturación electrónica DIAN desde primer peso** — sin esto, ingresos no deducibles para tenants enterprise
6. **Habeas Data Ley 1581 aplica igual a persona natural y SAS** — única diferencia operativa: SAS obligada a RNBD (Registro Nacional de Bases de Datos) si activos >100k UVT
7. **Modelo "servicio de software" vs "recaudo a terceros"** — contrato debe ser explícito (cláusula 1 contrato tipo)
8. **Trigger SAS objetivo, no emocional** — ingresos $10M/mes × 3 meses sostenidos O tenant enterprise exige O capital externo

## Consecuencias

### Inmediatas
- Founder gasta ~$7-10M COP año 1 en blindaje (Fase 0)
- ~10h founder semana 1-2 ejecutando acciones Fase 0
- Plan K crece: J.2.12 + J.2.13 + J.5.X agregados
- 2 docs nuevos: `contract-template-tenant.md` + `insurance-checklist.md`

### A mediano plazo
- Konvi tiene capacidad legal y técnica para servir primer tenant externo Sem 8+
- Verticales propias del founder (KAIU + futuras) operan sin friction
- Migración a SAS es decisión informada por triggers objetivos, no emocional
- Documentación legal completa y consistente con realidad operativa

### A largo plazo
- Cuando se cumpla trigger SAS, migración limpia (cláusula cesión contratos + cuenta Wompi SAS adicional)
- Cuenta Wompi persona natural se queda como histórico/vertical mientras SAS opera SaaS
- Founder protegido patrimonialmente desde día 1 (seguros) y estructuralmente Fase 3 (SAS)

## Open questions (las que solo founder o consulta externa puede responder)

1. **Wompi soporte oficial:** ¿persona natural puede ser titular de N cuentas con correos distintos? Escribir consulta formal y guardar respuesta — abre/cierra Fase 2 modelo multi-cuenta.
2. **Contador SaaS Colombia:** identificar 2-3 candidatos en próximas 2 semanas. Trabajar Fase 0-1 con uno antes de comprometer largo plazo.
3. **Abogado comercial SaaS:** ¿quién revisa contrato tipo + DPA + términos? Mismo timing que contador.
4. **Pricing exacto suscripción SaaS:** $80K, $150K, $300K/mes/tenant — definir antes primer tenant pagador.
5. **2da vertical priorizada:** cosmética vs zapatos vs ropa — definir Sem 13-14 antes de Fase 2.
6. **Lucams timing:** ¿esposa arranca Sem 14 confirmado? Coordinar con ella su propia entidad legal.

## Referencias

- [`docs/legal/contract-template-tenant.md`](../legal/contract-template-tenant.md) — Contrato tipo (Capa 1)
- [`docs/legal/insurance-checklist.md`](../legal/insurance-checklist.md) — Checklist seguros (Capa 2)
- [`docs/legal/dpa.md`](../legal/dpa.md) — DPA Habeas Data
- [`docs/legal/privacy-policy.md`](../legal/privacy-policy.md) — Política privacidad
- [`docs/legal/subprocessors.md`](../legal/subprocessors.md) — Lista subprocesadores
- [`docs/legal/incident-response.md`](../legal/incident-response.md) — Incident response playbook
- [`docs/research/wompi-dossier-2026-05-05.md` (histórico)](../_archive/research/wompi-dossier-2026-05-05.md) — Dossier técnico Wompi
- [`docs/refactor/0006-roadmap-pending-sessions.md` (histórico)](../_archive/refactor/0006-roadmap-pending-sessions.md) — Roadmap Plan K
- Workflow adversarial 2026-05-30 transcript: `~/.claude/projects/.../tasks/wgg1t1qm3.output`

## Estado

ACTIVO. Próxima revisión: Sem 13 (verificar Fase 0 cerrada + Fase 1 en ejecución + triggers SAS no activados todavía).

Re-evaluar este ADR si:
- Wompi publica API marketplace/sub-cuentas oficialmente
- Cambio regulatorio Colombia (umbral IVA, RST, intermediación financiera)
- Trigger SAS se cumple antes de Sem 13
- Founder decide constituir SAS por razón no técnica (capital, tenant enterprise)
