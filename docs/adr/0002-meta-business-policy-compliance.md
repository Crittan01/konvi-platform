# ADR-0002: Cumplimiento Meta Business Policy + UX (rev. 84/85)

## 1. Status

**Accepted** · 2026-04-30 (rev. 84/85)
Próxima revisión: cuando WhatsApp Business Policy publique cambios
relevantes (anti-spam, healthcare, datos personales) o se incorpore un
tenant en sector regulado (alcohol, tabaco, OTC medicines).

## 2. Context

### Detonante

Audit oficial de https://business.whatsapp.com/policy + observación
del usuario sobre 2 escenarios de UX/cumplimiento:

1. **Salud delicada**: el bot puede recibir preguntas como
   *"¿este jabón cura mi acné?"* o *"tengo dermatitis"*. Sin guardrail,
   el LLM podría dar consejo médico → riesgo legal y violación Meta
   Healthcare policy.
2. **Datos sensibles inadvertidos**: cliente envía número de tarjeta
   completo o CVV en el chat — riesgo PCI + Meta Personal Data policy.
3. **Mensajes consecutivos rápidos**: cliente envía 2-3 mensajes
   seguidos; el bot procesa cada uno aislado, último msg domina la
   respuesta del LLM, contexto previo se pierde.

### Cita oficial Meta Business Policy

> "Healthcare: Telemedicine and health data prohibited in non-compliant
> systems"
>
> "Personal data: Cannot collect/share full payment card numbers, bank
> accounts, ID documents"
>
> "Solo puedes contactar a personas por WhatsApp si: (a) te dieron su
> número de teléfono celular; y (b) obtuviste el consentimiento
> explícito."

### Categorías relevantes para KAIU (cosmética artesanal)

- ✅ NO son productos prohibidos (cosmética natural).
- ⚠️ Cliente puede preguntar sobre uso medicinal de productos →
  cae en zona healthcare.
- ⚠️ Datos sensibles deben quedar en el widget Wompi cifrado.
- ⚠️ Menores de edad: no procesamiento de pedido.

## 3. Decisión

> **Implementar guardrails determinísticos PRE-LLM** para casos críticos
> (salud mental, datos sensibles), **reglas en system prompt** para
> casos blandos (consejos médicos/legales/financieros) y **message
> coalescing** en worker para preservar contexto multi-turno.

## 4. Implementación (rev. 84 + 85)

### Rev. 84 — Guardrails de cumplimiento

| Detector | Tipo | Acción |
|---|---|---|
| `_detect_mental_health_crisis` (suicidio/autolesión) | PRE-LLM determinístico | P0 — escala inmediato a humano + mensaje de seguridad con líneas de ayuda (106/123 Colombia). Status conv → `human_takeover`. |
| `_detect_sensitive_payment_data` (tarjeta CC, CVV) | PRE-LLM regex | Advertencia + descarta del contexto. Bot guía al widget Wompi seguro. |
| Reglas system prompt — Salud / Medicina | LLM-guided | NO recomendar tratamientos. Plantilla canned: "Consulta con un dermatólogo". Si insiste 2+ → escalar. |
| Reglas system prompt — Legal / Financiero | LLM-guided | "Consulta con un abogado / asesor financiero certificado". |
| Reglas system prompt — Menores | LLM-guided | Pedir adulto autorizado para procesar la compra. |

Tests: [tests/test_rev84_meta_compliance.py](tests/test_rev84_meta_compliance.py) — 19 escenarios cubiertos:
- Crisis salud mental: 8 (incluido falsos positivos / negativos).
- Datos sensibles: 9 (CC con espacios, hyphens, sin separador, CVV
  explícito, código de seguridad, falsos positivos cédula/teléfono).
- Boundary: 2 (dolor de cabeza menor NO crisis; doc 12 dígitos NO card).

### Rev. 85 — Message coalescing

`OrchestratorWorker._coalesce_pending_by_conversation`:
- Agrupa mensajes pendientes por `conversation_id`.
- Si el mensaje más reciente tiene <5s de edad, espera la ventana
  restante (`MESSAGE_COALESCE_WINDOW_SECONDS=5` por default).
- Re-fetch tras la espera.
- Conversaciones con 2+ mensajes pendientes → contents juntados con
  `\n\n` separador, el último msg lleva el contenido combinado, los
  anteriores se marcan `processed` con `skip_reason=coalesced_into_next`.

Configurable via `.env`:
- `MESSAGE_COALESCE_WINDOW_SECONDS` (default 5; el usuario pidió mínimo
  5s "no todos escriben rápido").

Tests: [tests/test_rev85_message_coalescing.py](tests/test_rev85_message_coalescing.py) — 5/5 OK.
- Single mensaje viejo → no coalesce.
- 2 mensajes misma conv → coalesce.
- 3 mensajes secuencia típica del usuario → coalesce.
- 2 mensajes en conversaciones distintas → NO coalesce entre sí.
- Constante `MESSAGE_COALESCE_WINDOW_SECONDS >= 5`.

## 5. Alternativas evaluadas y rechazadas

| Alternativa | Por qué se rechazó |
|---|---|
| Solo system prompt (sin detectores PRE-LLM) | El LLM puede ignorar instrucciones críticas. Para crisis de salud mental el riesgo de falso negativo es inaceptable. |
| Multi-API-key per tenant | Out of scope (ver ADR-0001). |
| Coalescing en el connector WhatsApp | Más complejo (requiere queue persistente). El worker ya procesa de forma asincrónica, agrupar ahí es trivial. |
| Detector de tarjeta vía Luhn checksum | Demasiado strict — pueden haber cards "fake" del cliente que igual queremos descartar del chat. La detección de patrón 13-19 dígitos es suficiente. |

## 6. Consecuencias

### Aceptamos

- **Falsos positivos en crisis salud mental** → escalación innecesaria
  ocasional. **Mitigación**: agente humano evalúa y desbloquea si es
  falsa alarma. Mejor que falsos negativos.
- **Latencia +5s en mensajes muy recientes** por debounce de coalescing.
  **Mitigación**: solo aplica si el mensaje tiene <5s; mensajes que
  esperaron >5s en cola se procesan sin delay.

### Ganamos

- **Cumplimiento Meta** verificable con tests deterministas (19 escenarios).
- **Cero respuestas con consejos médicos del bot** (system prompt
  explícito).
- **Cero datos de tarjeta en logs/history** (descarte PRE-LLM).
- **Bot mantiene contexto multi-turno** ante mensajes consecutivos del
  cliente.
- **Trazabilidad**: cada caso especial loggea con tag `[CRISIS]`,
  `[PCI]`, `[COALESCE]` para audit operativo.

## 7. Triggers para revisitar

| Trigger | Acción |
|---|---|
| Meta publica nueva versión de Business Policy | Re-leer policy, comparar con guardrails actuales, abrir ADR-NNNN si cambia decisión núcleo. |
| Tenant nuevo en sector regulado (alcohol, tabaco, OTC) | Activar requerimientos adicionales (age verification, geo-restriction). |
| Métrica: tasa de falsos positivos `[CRISIS]` > 1% | Refinar `_MENTAL_HEALTH_CRISIS_PHRASES` (más específicas). |
| Tasa de coalescing > 30% de mensajes | Considerar reducir ventana o revisar UX (cliente fragmentando demasiado). |

## 8. Referencias

- WhatsApp Business Policy: https://business.whatsapp.com/policy
- Meta Commerce Policy: https://www.facebook.com/policies_center/commerce
- PCI DSS — datos de tarjeta nunca deben entrar en sistemas no-PCI.
- Implementación rev. 84: [services/ai-orchestrator/orchestrator.py](services/ai-orchestrator/orchestrator.py) (handlers `_detect_mental_health_crisis`, `_detect_sensitive_payment_data`).
- Implementación rev. 85: [services/ai-orchestrator/worker.py:_coalesce_pending_by_conversation](services/ai-orchestrator/worker.py).

## 9. Política de actualización

ADR inmutable. Cualquier cambio núcleo crea ADR-NNNN nuevo. Tunings
menores (agregar phrases a las listas, ajustar regex CC) → mantener
`Accepted` y registrar en sección Changelog abajo.

## Changelog

- 2026-04-30: Creación. rev. 84/85 cerrada con 24 tests nuevos
  (19 compliance + 5 coalescing).
