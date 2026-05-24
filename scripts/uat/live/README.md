# UAT Live — Conversación dialógica turn-a-turn

Este directorio reemplaza el patrón estático `scripts/uat/scenarios/`
(eliminado en rev. 107, 2026-05-24, decisión founder).

## Por qué

Los escenarios estáticos (`sXX_*.py`) tenían respuestas pre-escritas
("quemadas") y daban PASS aunque el bot generara texto incoherente o
robotizado en turns posteriores. Solo validaban patrones aislados, no
calidad real de conversación.

**Pattern correcto:** el agente envía un mensaje, lee la respuesta REAL
del bot, formula el siguiente turn EN BASE a esa respuesta, e itera
turn-a-turn evaluando coherencia global. Como un humano chateando.

## Archivos

| Archivo | Propósito |
|---|---|
| `helpers.py` | Primitivas live: reset, turn, diagnose, cart_state. |
| `objectives.md` | Catálogo de objetivos a probar (NO ejecutables). |
| `__init__.py` | Re-export del módulo helpers. |

## Uso típico

```python
import sys
sys.path.insert(0, "/home/ansible/workspaces/commerce-ops-platform")
from scripts.uat.live import helpers

# Estado limpio
conv = helpers.reset_known_customer(city="Bogotá")
# o:
conv = helpers.reset_new_customer()

# Conversación dialógica
helpers.turn(conv, "Hola")  # imprime bot reply
# → LEER lo que el bot dijo → formular siguiente turn en base a eso
helpers.turn(conv, "...")

# Diagnóstico si algo falla
helpers.diagnose(conv, last_n=2)  # tool_call_log + invariantes
helpers.cart_state(conv)           # cart real DB
helpers.cleanup_conv(conv)         # limpia al terminar
```

## Pre-requisitos

- Orchestrator local corriendo (`make -C /home/ansible/commerce-ops-local start-orchestrator`).
- `apps/web/.env.local` con `NEXT_PUBLIC_SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.
- Conn KAIU productivo (Supabase) — tenant_id default = `0fb0777e-...`,
  phone default = founder. Sobrescribibles vía env `UAT_LIVE_TENANT_ID`
  y `UAT_LIVE_PHONE`.

## Reglas para el agente

1. NUNCA hardcodear respuestas esperadas — léelas del output real.
2. Si el bot responde mal, **fix arquitectónico (system_prompt o invariant)**.
   No workaround conversacional.
3. Reportar bugs detectados con `diagnose()` — root cause antes de paliativo.
4. Memoria: `feedback_no_static_uat.md` documenta esta política.
