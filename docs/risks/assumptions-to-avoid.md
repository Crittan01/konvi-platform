# Suposiciones a Evitar — Commerce Ops Platform

Última actualización: 2026-04-09

Estas son suposiciones que han causado o podrían causar problemas reales. No asumirlas.

---

## WhatsApp / Meta

| Suposición a evitar | Realidad |
|---------------------|----------|
| Que se puede enviar marketing masivo por WhatsApp | Viola políticas Anti-Spam de Meta. Puede resultar en baneo de la cuenta. |
| Que el webhook de Meta siempre llega | En Render Free, el cold start de 30-60s puede hacer que Meta abandone el webhook. |
| Que el token temporal META_ACCESS_TOKEN dura más de 24h | Expira en ~24h. Para producción, usar System User Token permanente. |
| Que la librería informal de WhatsApp "funciona igual" que la API oficial | Solo usar WhatsApp Cloud API oficial de Meta. |
| Que el LLM puede generar respuestas transaccionales (stock, precios, pedidos) | El LLM no es fuente de verdad. Siempre consultar la DB real. |

---

## Multi-tenant / Seguridad

| Suposición a evitar | Realidad |
|---------------------|----------|
| Que RLS funciona automáticamente con service_role | service_role bypasea RLS. Workers DEBEN setear `app.current_tenant_id` manualmente. |
| Que el frontend es una barrera de seguridad | El frontend no es seguridad. RLS y API Gateway son las barreras reales. |
| Que un bug en el tenant resolver es menor | Un bug en el resolver puede exponer datos de todos los tenants (riesgo R-13). |
| Que todos los tenants comparten los mismos settings | Cada tenant tiene su propia configuración, integraciones y credenciales. |

---

## Shipping / Envia

| Suposición a evitar | Realidad |
|---------------------|----------|
| Que el LLM puede inventar una cotización de envío | El LLM nunca genera precios ni tiempos de envío. Solo el conector real de Envia. |
| Que Envia siempre responde sin error | Envia puede tener downtime. El conector debe tener manejo de error y fallback a humano. |
| Que la API Key de Envia es la misma para todos los tenants | Pendiente confirmar el modelo de autenticación de Envia por tenant. |
| Que los datos de dirección siempre son válidos | Validar con Queries API de Envia antes de cotizar. |

---

## Infraestructura

| Suposición a evitar | Realidad |
|---------------------|----------|
| Que el plan Free de Render es suficiente para producción | No lo es. Cold starts, sin SLA, 512MB RAM. Usar plan Starter antes de producción real. |
| Que psql directo funciona desde la VM | No funciona (Supavisor bloquea TCP). Usar `supabase db query --linked`. |
| Que `google-generativeai` y `google-genai` son intercambiables | `google-generativeai` está deprecado. Usar solo `google-genai==1.47.0`. |
| Que `gemini-2.0-flash` está disponible en cuentas nuevas con billing | No lo está. Usar `gemini-2.5-flash`. |

---

## Producto / Diseño

| Suposición a evitar | Realidad |
|---------------------|----------|
| Que la UI actual del repo es el producto final | El Tenant Console está completo (13/13 módulos). Platform Console no existe aún (Fase 12). |
| Que la Tenant Console y Platform Console son la misma app | Son superficies completamente separadas. No mezclar. |
| Que implementar primero el backend y luego el frontend es siempre correcto | El orden correcto es: claridad funcional/visual → backend correspondiente. |
| Que un módulo "existe" porque hay un link en el sidebar | El sidebar tiene links a rutas que no existen todavía. Verificar en código. |

---

## Documentos relacionados

- `docs/risks/risk-register.md` — Riesgos activos con severidad
- `docs/risks/open-questions.md` — Preguntas sin resolver
