# Golden corpus — transcripts dorados del harness B-3

Fixtures canónicos de conversaciones reales para evaluación de calidad del bot
(LLM-judge: `scripts/uat/llm_judge.py`) y como referencia de escenarios del
harness de coherencia.

**Regla innegociable: PII siempre enmascarada.** Nombres `[CLIENTE]`, teléfonos
`[TEL]`, emails `[EMAIL]`, documentos `[DOC]`, direcciones `[DIR]`. Nunca entra
al repo un transcript con PII real.

## Fixtures

| Archivo | Qué es |
|---|---|
| `prd_4d608efd.json` | Conversación REAL de PRD anonimizada (66 turns `{ts, dir, text}`, 2026-08-09→20). Es la conversación del audit `.audit/findings/2026-08-21-bot-deep-audit.md` — incluye `fallos_conocidos` (F1-F9: totales alucinados, cupón sin código, loop de repetición, gate pisando contenido, preguntas ignoradas, escalación contradictoria, takeover zombi…). |
| `stg_e2e_2026-08-23.json` | E2E real de STG post-B-1 (20 turns `{n, inbound, outbound, veredicto, nota}`). Transcrito del run log `scripts/uat/runs/bot_e2e_stg_2026-08-23.md` — dinero exacto verificado en DB + hallazgos H1-H5. Los textos son resúmenes del run log, no literales. |

## Cómo se regenera

- **`prd_4d608efd.json`**: extracción READ-only de la conversación `4d608efd…`
  desde PRD (`messages` ordenadas por `created_at`, solo `direction`/`content`),
  seguida de anonimización manual (PII → placeholders). No hay script
  automatizado: la anonimización se revisa a ojo antes de commitear.
- **`stg_e2e_2026-08-23.json`**: transcripción manual de la tabla del run log
  correspondiente en `scripts/uat/runs/`, enmascarando formatos de PII aunque
  sean datos ficticios de prueba.

## Uso

```bash
python3.11 scripts/uat/llm_judge.py scripts/uat/golden_corpus/prd_4d608efd.json
python3.11 scripts/uat/llm_judge.py scripts/uat/golden_corpus/stg_e2e_2026-08-23.json
```
