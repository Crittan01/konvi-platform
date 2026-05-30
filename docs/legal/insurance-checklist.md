# Checklist Seguros — Konvi como persona natural

**Estado:** ACTIVO — usar para cotizar antes de primer tenant pagador.
**Audiencia:** founder, corredor de seguros.
**Objetivo:** cotizar y contratar pólizas RC Profesional E&O + Cyber Risk que mitiguen ~80% del riesgo patrimonial sin requerir constituir SAS.

> Lectura previa: [`ADR-0022`](../adr/0022-legal-entity-billing-rails-risk-mitigation.md) — explica por qué seguro es Capa 2 de la mitigación (Capa 1 = contratos, Capa 3 = SAS futura).

---

## ¿Por qué seguro y no solo SAS?

| Mecanismo | Costo | Cuándo protege | Limitaciones |
|---|---|---|---|
| **Contratos bien redactados** (Capa 1) | $1-2M COP one-shot abogado | Ante demandas civiles de tenants | No cubre multas regulatorias ni terceros distintos al tenant |
| **Seguro RC + Cyber** (Capa 2 — este doc) | $3-5M COP/año | Daños civiles a terceros, defensa jurídica, costos de brecha | NO cubre multas SIC ni sanciones DIAN |
| **Migrar a SAS** (Capa 3, Fase 3 estrategia) | $1.5-2.5M COP setup + $500-800 USD/mes operativo | Separación patrimonial real (velo societario) | Setup demora, requiere migración Wompi nueva |

**Conclusión**: las 3 capas son complementarias, no excluyentes. Seguros + contratos hoy compran ~6-12 meses de tranquilidad mientras se construye SaaS rentable que justifique SAS.

---

## Qué pólizas contratar (orden de prioridad)

### 1. 🔴 RC Profesional / Errores y Omisiones (E&O) — OBLIGATORIA

**Qué cubre:**
- Demandas civiles de terceros (especialmente tenants) por errores u omisiones en la prestación del servicio SaaS
- Defensa jurídica (honorarios abogados, costos procesales)
- Indemnizaciones a terceros derivadas de fallas técnicas u operativas

**Qué NO cubre:**
- Multas SIC, DIAN o sanciones de cualquier autoridad
- Reclamos por incumplimiento contractual deliberado
- Lucro cesante de KONVI

**Cobertura recomendada inicial:**
- Límite agregado anual: **$500.000.000 - $1.000.000.000 COP**
- Límite por siniestro: **$300.000.000 - $500.000.000 COP**
- Deducible: **$5.000.000 - $20.000.000 COP** por siniestro (a menor deducible, mayor prima)
- Vigencia: **anual renovable**

**Prima estimada anual (2026 Colombia):** $1.500.000 - $3.000.000 COP

### 2. 🔴 Cyber Risk (CRC) — OBLIGATORIA

**Qué cubre:**
- Brechas de datos personales (especialmente relevante con Ley 1581/2012 ya implementada en rev 93-99)
- Costos de notificación a titulares afectados
- Forensics post-incidente
- Restauración de sistemas
- Business interruption (interrupción de negocio)
- Algunas pólizas: ransomware payment (verificar caso por caso, controversial)
- Reclamos de terceros derivados del breach (NO la multa SIC, pero sí el daño a los titulares)

**Qué NO cubre:**
- Multa SIC por incumplimiento Habeas Data (no asegurable)
- Pérdidas propias derivadas del incidente
- Brechas anteriores a la vigencia de la póliza

**Cobertura recomendada inicial:**
- Límite agregado anual: **$500.000.000 - $2.000.000.000 COP**
- Límite por siniestro: **$300.000.000 - $1.000.000.000 COP**
- Deducible: **$10.000.000 - $30.000.000 COP**

**Prima estimada anual (2026 Colombia):** $2.000.000 - $5.000.000 COP

### 3. 🟡 RC General — OPCIONAL (suele venir en bundle)

**Qué cubre:**
- Daños a terceros por operación general (no específica del servicio software)
- Útil si Konvi tiene oficina física, recibe visitas, eventos

**Prima estimada anual:** $300.000 - $600.000 COP

**Recomendación:** pedir en bundle con E&O + Cyber. Suelen incluirla gratis o con cargo mínimo.

---

## Aseguradoras colombianas con productos para tech/SaaS

> ⚠️ NO cotizar directo con aseguradora. **Usar corredor**. Los corredores cotizan en N aseguradoras simultáneamente, negocian precio, y la asesoría es pagada por la aseguradora (no por vos). Hay diferencias de hasta 40% en prima por mismo riesgo entre corredores.

### Corredores recomendados (por especialización tech/SaaS)

| Corredor | Tipo | Cuándo elegir |
|---|---|---|
| **Aon Colombia** | Multinacional grande | Si futuro plan es crecer >$500M facturación o levantar capital |
| **Marsh Colombia** | Multinacional grande | Similar a Aon, ambos sirven enterprise |
| **DelCorral & Mejía** | Local, especializado tech/cyber | Mejor relación PYME — atención más personal |
| **MAS Seguros** | Local, PYMES | Más barato pero menos especialización tech |
| **Willis Towers Watson Colombia** | Multinacional | Buena cobertura cyber |

**Recomendación pragmática:** contactar 2-3 corredores en paralelo (ej. DelCorral + Aon + MAS) y comparar propuestas.

### Aseguradoras que el corredor probablemente cotizará

| Aseguradora | Productos tech/cyber | Notas |
|---|---|---|
| **Sura** | E&O + Cyber + RC | Líder mercado CO, suele tener mejor cobertura local |
| **Liberty Seguros** | E&O + Cyber | Buena para PYME tech |
| **Chubb** | Cyber Risk fuerte | Producto cyber premium |
| **AXA Colpatria** | E&O + Cyber + RC | Bundle competitivo |
| **Bolívar** | E&O + RC | Menos enfocado cyber |
| **Allianz** | Cyber Risk | Buena para enterprise |

---

## Información que el corredor pedirá (preparar antes de la llamada)

### Datos básicos KONVI

| Campo | Valor |
|---|---|
| **Razón social / Nombre** | [Founder nombre completo persona natural Konvi] |
| **Cédula / NIT** | [Cédula con dígito verificación] |
| **Actividad económica CIIU** | 6201 (Desarrollo de sistemas informáticos) — principal · 6202 (Actividades de consultoría informática) — secundaria |
| **Régimen tributario** | Persona natural — [Régimen Simplificado / RST si se inscribe / Responsable IVA si supera 3.500 UVT] |
| **Domicilio** | [Ciudad, Colombia] |
| **Antigüedad operativa** | [Fecha primera factura emitida] |
| **Empleados / colaboradores** | [0 hoy si es solo founder; mencionar si hay contratistas/freelance] |

### Datos del servicio prestado

| Campo | Valor |
|---|---|
| **Tipo de servicio** | SaaS — comercio conversacional WhatsApp + integraciones (Wompi, Aveonline/Envia, MercadoLibre, Telegram) |
| **Modelo de negocio** | B2B suscripción mensual + flat fee tier (no per-transaction) |
| **Mercado objetivo** | PYMES Colombia (verticales: eCommerce, cosmética, moda, alimentos) |
| **Volumen proyectado año 1** | Ingresos brutos: $[X] COP · Tenants activos: [N] · Conversaciones procesadas mes: [Y] |
| **Stack técnico principal** | Render (hosting), Supabase (DB + Auth), Wompi (pagos), Meta WhatsApp Business API, Google Gemini (LLM), Resend (email), Sentry (observability) |
| **¿Procesás pagos?** | NO procesa pagos directamente. Las pasarelas Wompi son configuradas con credenciales del tenant (key-per-tenant). Konvi NO es agregador ni recauda a nombre de terceros. |
| **¿Manejás datos personales?** | SÍ — actúa como Encargado del Tratamiento conforme Ley 1581/2012. Responsable = tenant. |
| **¿Datos sensibles?** | NO — no se manejan datos sensibles según art. 5 Ley 1581 (salud, biométricos, vida sexual, política, religión, etc.) |
| **¿Datos de menores?** | NO esperado en B2B; verificar con tenants |
| **Volumen titulares procesados** | Estimado año 1: [N tenants × M clientes finales promedio = ~X.000 titulares activos] |

### Compliance ya implementada

> Compartir esto con el corredor MEJORA significativamente la prima — demuestra postura de riesgo madura.

- ✅ **Habeas Data Ley 1581/2012:** Audit log append-only, SAR endpoint, retention policies pg_cron, anonimización, click-wrap acceptance, política de tratamiento publicada (`docs/legal/privacy-policy.md`), DPA con tenants (`docs/legal/dpa.md`), lista subprocesadores (`docs/legal/subprocessors.md`), incident response playbook (`docs/legal/incident-response.md`).
- ✅ **Seguridad técnica:** TLS en tránsito (Render gestiona), encriptación at-rest (Supabase Postgres), RLS multi-tenant, RBAC owner/manager/operator, MFA TOTP para owner/manager (J.2.4.3), tenant offboarding workflow con grace period 30d + hard delete (J.2.4.4), Sentry tracing E2E (J.2.7.4).
- ✅ **Auditoría operativa:** suite tests 2783+ pass, validate.sh CI strict, GitHub Actions pre-merge, código abierto al equipo (no hay shadow operations).

### Información de incidentes previos

| Pregunta | Respuesta |
|---|---|
| ¿Has tenido reclamo previo asegurado? | NO |
| ¿Has tenido brecha de datos? | NO |
| ¿Has tenido demanda civil? | NO |
| ¿Tienes auditorías externas? | NO actualmente. Penetration testing pendiente (V.5 plan) — informar cuando esté hecho, baja la prima futura. |

---

## Qué pedir explícitamente al corredor

> Copiar este script al correo/WhatsApp con el corredor.

```
Hola [corredor],

Soy [founder] de Konvi, plataforma SaaS B2B de comercio conversacional
WhatsApp. Necesito cotizar:

1. RC Profesional / Errores y Omisiones (E&O) - límite $500M-1.000M COP agregado
2. Cyber Risk - límite $500M-2.000M COP agregado
3. Bundle preferido (RC General incluido si baja prima total)

Detalles:
- Persona natural Colombia, CIIU 6201/6202
- SaaS B2B suscripción mensual, mercado PYMES Colombia
- Año 1 proyectado: [N] tenants, ingresos brutos $[X] COP
- NO procesa pagos (pasarela configurada per-tenant)
- Encargado del Tratamiento Ley 1581/2012 — compliance documentada
- Stack: Render + Supabase + Meta WhatsApp Business + Wompi
- 0 incidentes previos, 0 reclamos previos

Por favor cotizar en 3-4 aseguradoras (Sura, Liberty, Chubb, AXA Colpatria).

Necesito:
- Prima anual neta + IVA
- Deducible por siniestro
- Cobertura defensa jurídica
- Exclusiones específicas
- Tiempo de emisión

Gracias.
```

---

## Comparativa propuestas — plantilla decisión

> Cuando recibas 2-3 propuestas, llenar esta tabla y decidir.

| Item | Propuesta 1 | Propuesta 2 | Propuesta 3 |
|---|---|---|---|
| Corredor | | | |
| Aseguradora | | | |
| Límite agregado E&O | | | |
| Límite agregado Cyber | | | |
| Deducible E&O | | | |
| Deducible Cyber | | | |
| Prima anual total | | | |
| Cobertura defensa jurídica | | | |
| Tiempo emisión | | | |
| Exclusiones críticas | | | |
| Renovación automática | | | |
| **Score subjetivo (1-10)** | | | |

**Criterios de decisión** (orden):
1. **Cobertura mínima requerida** (E&O ≥$500M, Cyber ≥$500M)
2. **Exclusiones razonables** (rechazar pólizas que excluyan brechas Habeas Data sin justificación)
3. **Prima razonable** (no necesariamente la más barata — la más barata suele excluir cosas importantes)
4. **Reputación pago siniestros** del aseguradora (Sura, Chubb, Allianz tienen mejor track record)

---

## Recomendaciones específicas según etapa

### Etapa A: HOY (pre-primer tenant pagador)

- Contratar **solo E&O + Cyber básico** (límites mínimos: $500M cada uno)
- Prima esperada: **$3-4M COP/año**
- Renovar con upgrades cuando crezcan ingresos

### Etapa B: 5-10 tenants pagando

- Aumentar límites a **$1.000M E&O + $1.000M Cyber**
- Considerar agregar **RC General** si hay oficina física o eventos
- Prima esperada: **$4-6M COP/año**

### Etapa C: 20+ tenants (post-SAS)

- Migrar pólizas a nombre de SAS (mejor protección velo societario)
- Agregar **D&O (Directors & Officers)** para protección administradores
- Considerar **Tech E&O internacional** si tenés tenants fuera Colombia
- Prima esperada: **$8-15M COP/año** (escala con facturación)

---

## Acciones inmediatas

| # | Acción | Cuándo | Cómo |
|---|---|---|---|
| 1 | Contactar 2-3 corredores (DelCorral + Aon + MAS recomendado) | Esta semana | Email con script de arriba |
| 2 | Recibir 2-3 propuestas | Próximas 1-2 semanas | Llenar tabla comparativa |
| 3 | Decidir y firmar | Semana 3-4 | Después de comparar |
| 4 | Pagar prima año 1 | Semana 4 | Pago anual upfront típico |
| 5 | Recibir póliza emitida | Semana 5-6 | Documentar en `docs/legal/policies/` (NO commitear, son confidenciales — solo referencia) |
| 6 | Notificar a primer tenant cuando exista | Pre-contrato | Mencionar póliza en contrato cláusula 3 (limitación) refuerza credibilidad |

**Costo total año 1 estimado:** $3-5M COP en pólizas.

**Retorno esperado:** mitigación ~80% del riesgo patrimonial personal sin necesidad de constituir SAS (que sería ~$2-3M setup + $6-10M/año operativo adicional).

---

## Referencias

- [`ADR-0022`](../adr/0022-legal-entity-billing-rails-risk-mitigation.md) — Estrategia completa entidad legal Konvi
- [`docs/legal/contract-template-tenant.md`](contract-template-tenant.md) — Contrato tipo (cláusulas Capa 1)
- [`docs/legal/incident-response.md`](incident-response.md) — Playbook que el seguro Cyber Risk querrá ver
- [`docs/legal/privacy-policy.md`](privacy-policy.md) — Compliance Habeas Data
