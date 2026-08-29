# ADR-0001: Estrategia de tier LLM (Gemini AI Studio paid + cascada + router)

## 1. Status

**Accepted** · 2026-04-30 (rev. 81)
Próxima revisión: cuando se cumpla cualquiera de los triggers de la
sección 7.

## 2. Context

### Hechos detonantes

Auditoría de la conversación productiva del 2026-04-30 14:48 (log
`scripts/uat/logs/conversation_57312XXXXXX649_20260430-150617.log`)
expuso 4 problemas operativos:

1. Cliente confirmó pedido y bot prometió enviar link de pago, pero
   el link nunca llegó.
2. Resumen final omitió 2 de 3 productos del carrito (`1x Coco $26.000`
   cuando real era `1x Coco + 2x Lavanda = $93.000`).
3. Cliente reclamó 3 veces sin recibir respuesta del bot.
4. Logs del orchestrator mostraron 503 sostenidos de
   `gemini-2.5-flash` con mensaje literal *"This model is currently
   experiencing high demand. Spikes in demand are usually temporary."*

Sobre el punto 4, durante la discusión emergió una propuesta:
**multi-API-key rotation con tiers comerciales** (Basic / Pro /
Enterprise) — cada tenant con su propia key Gemini.

### Aclaración terminológica (importante)

Tres productos de Google se confunden frecuentemente:

| Producto | Qué es | Para quién |
|---|---|---|
| **Google One Pro / Gemini Advanced** | Suscripción consumidor (~$20/mes) para usar `gemini.google.com` | Usuario final, no devs |
| **AI Studio API key** (`aistudio.google.com`) | Key con prefijo `AIza...`. Free (15 RPM) y Paid (1.500 RPM) | Mayoría de devs |
| **Vertex AI** (Google Cloud Console) | Servicio empresarial, auth con service account JSON | Empresas grandes |

### Stack actual confirmado

`konvi-platform` usa **AI Studio API key en paid tier**, billed
via un GCP project linkeado. Tráfico actual: 1 tenant productivo
con ~50 RPH (0.05% del techo de 90.000 RPH paid).

## 3. Decisión

> Mantener AI Studio paid tier como API LLM.
> Mantener la **cascada `flash → flash-lite → degraded response`**
> implementada en rev. 81 batch 1.
> Mantener el **model router heurístico** (intent simple / transactional
> → modelo correspondiente) implementado en rev. 81 batch 2.
>
> **NO** implementar multi-API-key rotation.
> **NO** migrar a Vertex AI todavía.

## 4. Razones (con datos)

| Argumento contra multi-API-key | Evidencia |
|---|---|
| 503s son capacidad global Google, no quota | El mensaje "high demand" del log aparece **idéntico** en free y paid tier — Google lo emite cuando su capacidad regional para el modelo está saturada, independiente de tu cuota |
| Quota paid no es escasa con escala actual | 1.500 RPM × 60 = 90.000 RPH disponibles. Tráfico real: ~50 RPH. Margen: 1.800x. |
| Costo unitario es por tokens, no por key | Google factura por uso. 50 keys = mismo costo en tokens + N veces el overhead administrativo |
| Operativo es caro | 50 GCP projects × IAM × billing × rotación de keys comprometidas = mucho trabajo sin payoff |
| "Tier por API key" es upsell falso | El cliente Pro pagaría más por algo que no es un recurso escaso. Cuando descubre, churn |
| La cascada YA cubre el caso real | `flash → flash-lite` cambia de modelo en 503; lite tiene capacidad propia distinta |

## 5. Alternativas evaluadas y rechazadas

| Alternativa | Por qué se rechazó |
|---|---|
| Multi-API-key rotation + circuit breaker | No resuelve los 503s globales (todas las keys golpean los mismos servidores Google). Costo operativo > beneficio. |
| Migrar a Vertex AI ahora | Overkill. ~1-2 días de trabajo de migración (SDK, auth, regional endpoints). Solo aporta valor con `provisioned throughput`, que se justifica con tráfico mucho mayor. |
| Subir tier free → paid | Ya estamos en paid tier. |
| No hacer nada | Insuficiente — el log mostró 3 mensajes del cliente sin respuesta. La cascada (rev. 81) es el mínimo defensivo. |

## 6. Consecuencias

### Aceptamos

- **Riesgo de 503 sostenido si Google tiene incidente regional grande**.
  Mitigación: cascada termina en `degraded response` con
  `requires_human=true` → cliente recibe *"Disculpa, tengo dificultades
  técnicas, un asesor humano se pondrá en contacto"* en lugar de
  silencio.
- **Sin aislamiento físico entre tenants en la layer LLM**.
  Mitigación: la cuota AI Studio paid tiene mucho headroom; no hay
  contención observable con escala actual.

### Ganamos

- **Operativo simple**: 1 GCP project, 1 key, 1 facturación, 0 IAM
  diferenciado.
- **Optimización por tipo de turno** (router rev. 81 batch 2): lite
  para FAQ/saludos, flash para transaccional → reducción esperada
  ~50-60% en costos LLM cuando Platform Console valide la mezcla.
- **Resiliencia ante 503s individuales** sin agregar complejidad
  arquitectónica.

## 7. Triggers para revisitar este ADR

Abrir nueva rev y reconsiderar la decisión cuando ocurra **cualquiera**
de estos:

| Trigger | Acción a evaluar |
|---|---|
| Tasa de cascada activada `flash → flash-lite` > **10%** sostenido durante 1 semana | Saturación real. Migrar a Vertex AI con provisioned throughput. |
| Tasa de respuestas degradadas (`requires_human=true` por timeout) > **1%** | Revisar reintentos + abrir ticket Google sobre disponibilidad regional. |
| Tráfico cruza **500 RPM** en un tenant | Pedir aumento de cuota a Google (botón en AI Studio). |
| Más de **5 tenants productivos** con SLAs distintos | Considerar pool de GCP projects (uno por tier comercial), NO multi-key. |
| Necesidad regulatoria de aislamiento físico entre tenants | Migrar a Vertex AI multi-project. |

Las métricas para evaluar estos triggers vienen del Platform Console
(rev. 85 sugerida). Hasta entonces, lectura manual de logs:

```bash
# % de cascada activada en últimos N días:
grep "\[LLM_CASCADE\]" logs/orchestrator.log | \
  awk '/attempts=/ {n=substr($0,index($0,"attempts="));
                    split(n,a,"=");split(a[2],b," ");print b[1]}' | \
  awk '{if ($1>1) cascade++; total++} END {print cascade/total*100"%"}'

# Tasa de degraded:
grep "system_degraded" logs/orchestrator.log | wc -l
```

## 8. Lo que sí se debe hacer ahora (en lugar de multi-key)

Ordenado por ROI:

| Mejora | Rev sugerida | Ahorro estimado | Esfuerzo |
|---|---|---|---|
| Context caching (system prompt + catálogo + KB con `cachedContent`) | rev. 82 | 5-10x en input tokens cacheados | 1-2 días |
| Token compaction del history (últimos N turnos íntegros + resumen comprimido) | rev. 83 | 30-50% en input tokens | 1 día |
| Rate limiting per-tenant en API gateway | rev. 84 | UX (protege tenants chicos) + anti-abuso | 1 día |
| Platform Console con métricas: tokens/msg, costo/venta, tasa cascada, % simple/transactional | rev. 85 | Habilita decisiones data-driven sobre los triggers de §7 | 3-5 días |

## 9. Referencias

### Implementación actual rev. 81

- Cascada: [services/ai-orchestrator/llm_invoke.py](../../services/ai-orchestrator/llm_invoke.py)
- Router: [services/ai-orchestrator/llm_router.py](../../services/ai-orchestrator/llm_router.py)
- Cableo en orchestrator: [services/ai-orchestrator/orchestrator.py](../../services/ai-orchestrator/orchestrator.py) (call site principal post-rev. 81)
- Configuración: `.env` keys
  - `GEMINI_API_KEY` (AI Studio paid key)
  - `GEMINI_MODEL=gemini-2.5-flash`
  - `GEMINI_FALLBACK_MODEL=gemini-2.5-flash-lite`
  - `GEMINI_MAX_RETRIES=8`
  - `GEMINI_FALLBACK_AFTER=4`

### Reportes detallados de implementación

- [docs/reports/rev80_cart_sot_implementation.md (histórico)](../_archive/reports/rev80_cart_sot_implementation.md)
- [docs/reports/rev81_pendientes_cierre.md (histórico)](../_archive/reports/rev81_pendientes_cierre.md)
- [docs/reports/rev81_router_y_regression.md (histórico)](../_archive/reports/rev81_router_y_regression.md)

### Log fuente

`scripts/uat/logs/conversation_57312XXXXXX649_20260430-150617.log`

### Documentación oficial Google

- AI Studio rate limits: https://ai.google.dev/gemini-api/docs/rate-limits
- Vertex AI provisioned throughput: https://cloud.google.com/vertex-ai/generative-ai/docs/provisioned-throughput
- Gemini context caching: https://ai.google.dev/gemini-api/docs/caching

## 10. Política de actualización

- **Inmutable**: este ADR no se reescribe. Si la decisión cambia, se
  crea ADR-NNNN nuevo y este pasa a `Superseded by ADR-NNNN`.
- **Cambios menores que NO alteran la decisión núcleo** (tunings de
  retry-counts, ajustes en heurística del router, agregar modelo a la
  cascada): mantener `Accepted` y registrar en sección
  "Changelog" abajo.

## Changelog

- 2026-04-30: Creación. rev. 81 cerrada con cascada + router cableados.
