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
   horas — validator.ts, xdist, enums DB, reinicio de servicios, make deps).
4. Los documentos del trabajo en curso que el estado señale (hoy Track 7 —
   UX/UI de la consola contra Kaiu DS: `docs/ux/UX-UI.md`; brief T7.1-T7.12 en
   `.context/04-next-steps.md` §"Track 7 — brief de implementación").
5. `docs/PLAN.md` §E — bitácoras de ejecución (cómo se cerró cada fase, con
   evidencia y lecciones).

Reglas vigentes (sin cambios): STG-first · nada a PRD sin certificar en STG +
visto bueno founder · cero suposiciones (verificar contra código y docs
oficiales con fetch live) · python3.11 explícito · comentarios en español · no
commitear sin suite verde · Supabase CLI pineada 2.90.0 (NO actualizar) · tras
cada replay de migraciones restaurar STG con `scratch/track9_backup_secrets.py`
(decrypted_secret, NO secret) + `track9_restore_stg.sh` + `track9_restore_stg.py`
· PII enmascarada en evidencias · FIX ARQUITECTÓNICO no parche · CALIDAD sin
importar tiempo/esfuerzo · NO tocar el bot (dispatcher, prompts, resolvers,
invariants, tools, libs del orchestrator) fuera del bloque bot — sus espejos
congelados se adoptan en B-2/M3 defendidos por tests de paridad · la
certificación de dinero la hace el harness turno a turno en STG
(`scripts/uat/coherence_scenarios.py`).

La tarea inmediata es la que el plan marque como siguiente en
`.context/01-state.md` ("En curso / sigue") — si tiene brief de implementación
en `04-next-steps.md`, léelo primero y no re-derives nada sin verificar que
siga vigente contra el código. Al cerrarla (con la barra de cierre completa:
suite + dbharness + harness B-3 si el path lo toca + live STG +
`validate.sh --ci` con el web detenido + commits temáticos + push + CI 5/5 +
bitácora `PLAN.md` §E + `01-state.md`/`04-next-steps.md` al día), continúa con
la siguiente del §Orden sin esperar instrucción, y actualiza los documentos
vivos para que la próxima sesión encuentre el plan actualizado.

Stack STG local: `export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock"
&& make -C .local deps && make -C .local db && make -C .local up` · certificar:
`bash scripts/certify_stg.sh` (18/18) · validate: `make -C .local stop-web &&
bash scripts/validate.sh --ci` (luego `start-web` + certify para dejar STG
completo).
