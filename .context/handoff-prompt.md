# PROMPT DE CONTINUACIÓN — durable (vale para cualquier sesión del plan)

> Copiar tal cual como primer mensaje de una sesión nueva. NO duplica el plan:
> lo ANCLA al repo, que es la fuente de verdad viva (si el plan avanza, este
> prompt no queda stale — siempre apunta a los mismos documentos vivos).

---

Continúa el plan de trabajo de Konvi Platform. El plan vive en el repo — léelo
en este orden antes de actuar:

1. `.context/01-state.md` — sección "Estado vivo" + "En curso / sigue" (qué se
   quiere, en qué punto va, qué sigue).
2. `docs/PLAN-CIERRE.md` §"Orden de ejecución vigente" — el orden exacto y la
   razón (REORDEN founder 2026-08-24: la plataforma primero, el BLOQUE BOT AL
   FINAL — núcleo + GUI + API + métricas TODO el bot).
3. `.context/04-next-steps.md` — lo que queda pendiente + briefs de
   implementación + lecciones de entorno (léelas ANTES de certificar: ahorran
   horas — validator.ts, xdist, enums DB, reinicio de servicios, make deps,
   **sondas visuales playwright en `scratch/` (venv `scratch/venv-visual`,
   chromium ya cacheado — `localhost` NO `127.0.0.1`), reglas reduced-motion
   del DS (`useReducedMotionDS`/`itemVariantsReduced`), dbharness asume
   `order_receipts` prístina — las sondas de dinero se auto-limpian**, jsdom:
   `afterEach(cleanup)` explícito en TODO test .tsx + stubs matchMedia/observers
   para embla y matchMedia-getter para use-media-query · **NUEVO 2026-08-28:**
   verificar el estado del lado proveedor (panel/API), no solo el response "ok"
   del flujo propio (bug Aveonline HS256/RS256 — la doc fetch no prueba el auth;
   errores JWT "Incorrect key for this algorithm" → decodificar el header `alg`
   primero)).
4. Los documentos del trabajo en curso que el estado señale (hoy: **BLOQUE BOT
   INICIADO 2026-08-28 — paso 6 del §Orden ejecutado**: los dos inventarios del
   brief preservado ya corrieron con evidencia `archivo:línea` — INV-A
   (`.audit/findings/2026-08-28-bot-patch-inventory-outbound.md`: 70% de la
   política transversal vive fuera del embudo OutputValidator, 5 canales lo
   saltan) + INV-B (`.audit/findings/2026-08-28-bot-resolvers-radiography.md`:
   34 bloques/turno, lecturas DB duplicadas medidas, 15 parches, plan de
   extracción por riesgo Fase 0→3) → **la formulación arquitectónica está en
   `docs/architecture/bot-dispatcher-reengineering.md` — PENDIENTE DE VALIDACIÓN
   founder (6 decisiones con opción recomendada en su §4)**. Si el founder la
   valida: arranca la Fase 0 de B-2 (gratis, sin cambio de comportamiento —
   TurnContext v0 + resolver estado al inicio + transitions.py muerto +
   constantes muertas). HASTA ESA VALIDACIÓN, el código del bot sigue intacto.
   Los pasos de consola del founder viven en
   `docs/operations/runbooks/founder-console-steps.md` (Track 1/2 [F] + Track 4).
5. `docs/PLAN.md` §E — bitácoras de ejecución (cómo se cerró cada fase, con
   evidencia y lecciones — incl. el deploy PRD `d82d714c` de 2026-08-27 con las
   7 migraciones aplicadas por protocolo).

Reglas vigentes (sin cambios): STG-first · nada a PRD sin certificar en STG +
visto bueno founder · cero suposiciones (verificar contra código y docs
oficiales con fetch live) · python3.11 explícito · comentarios en español · no
commitear sin suite verde · Supabase CLI pineada 2.90.0 (NO actualizar) · tras
cada replay de migraciones restaurar STG con `scratch/track9_backup_secrets.py`
(decrypted_secret, NO secret) + `track9_restore_stg.sh` + `track9_restore_stg.py`
· PII enmascarada en evidencias · FIX ARQUITECTÓNICO no parche · CALIDAD sin
importar tiempo/esfuerzo · el bot (dispatcher, prompts, resolvers, invariants,
tools, libs del orchestrator) SOLO se toca dentro del bloque bot — y el bloque
bot arranca su Fase 0 solo tras la validación founder de
`docs/architecture/bot-dispatcher-reengineering.md` §4 — sus espejos congelados
se adoptan en B-2/M3 defendidos por tests de paridad (ej. el cliente Aveonline
duplicado api↔orchestrator, byte-equal por `test_aveonline_client_parity.py` —
si editas uno, re-sincroniza el otro con `cp` y el test te lo exige) · la
certificación de dinero la hace el harness turno a turno en STG
(`scripts/uat/coherence_scenarios.py` — corre además en CI nocturno 02:23 COL
con STG efímero en el runner; secrets ya registrados).

La tarea inmediata es la que el plan marque como siguiente en
`.context/01-state.md` ("En curso / sigue") — si tiene brief de implementación
en `04-next-steps.md`, léelo primero y no re-derives nada sin verificar que
siga vigente contra el código. Al cerrarla (con la barra de cierre completa:
suite + dbharness + harness B-3 si el path lo toca + live STG +
**verificación visual con navegador real si es front (sonda playwright en
`scratch/`, ambos temas + móvil + reduced-motion emulado + 0 errores de
consola)** + `validate.sh --ci` con el web detenido + commits temáticos + push
+ CI verde + bitácora `PLAN.md` §E + `01-state.md`/`04-next-steps.md` al día),
continúa con la siguiente del §Orden sin esperar instrucción, y actualiza los
documentos vivos para que la próxima sesión encuentre el plan actualizado.

Stack STG local: `export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
&& make -C .local deps && make -C .local db && make -C .local up` · certificar:
`bash scripts/certify_stg.sh` (18/18) · validate: `make -C .local stop-web &&
bash scripts/validate.sh --ci` (luego `start-web` + certify para dejar STG
completo).
