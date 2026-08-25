# PROMPT DE CONTINUACIÓN — nueva sesión (Track 5 M2.3)

> Copiar tal cual como primer mensaje de la nueva sesión. Está diseñado para que
> el agente continúe el plan sin re-derivar nada: el estado vivo + el brief de
> M2.3 con todas las constraints ya descubiertas están en el repo.

---

Continúa el plan de trabajo de Konvi Platform. Antes de actuar, lee en este orden:

1. `.context/01-state.md` — sección "Estado vivo" + "En curso / sigue". Estado al
   2026-08-25: REORDEN founder vigente (plataforma primero, BLOQUE BOT AL FINAL).
   Track 5 (dominios modulares) en ejecución: M1 ✅ (inventario verificable 11
   dominios) · M2 diseño APROBADO por founder (4/4) · M2.0 ✅ (paquete
   `packages/shared-py/` `konvi_domain` vivo) · M2.1 ✅ (OrdersService
   create/get/list/list_by_contact + `GET /orders/` + consola sobre REST) ·
   M2.2 ✅ (cancelación unificada con pipeline legal completo en consola +
   paridad de outcome bot↔paquete ×11).
2. `.context/04-next-steps.md` §"Track 5 — estado de ejecución" +
   **§"M2.3 — brief de implementación" (OBLIGATORIO: tiene todas las constraints
   de compatibilidad ya descubiertas — tests que pachean el módulo, wiring tests,
   criterio de reuso exacto, dinero, 503/http_status — y las lecciones de
   entorno: validator.ts, xdist/PosixPath, grep -c, enums DB, reinicio de
   servicios, make deps)** + §"M2.4 y resto del Track 5".
3. `docs/architecture/modular-domains-vision.md` (visión destino) +
   `docs/architecture/domain-services-contract.md` (contrato APROBADO — D1-D8,
   pilotos, plan M2.0-M2.4 con lo ya cerrado marcado, criterios de aceptación §7)
   + `docs/architecture/domain-capabilities-inventory.md` (M1 — matriz + backlog
   de 11 domain services con progreso anotado).
4. `docs/PLAN.md` §E — bitácoras de M2.0/M2.1/M2.2 (qué se hizo, con qué se
   certificó, qué bugs destapó la certificación live).

Reglas vigentes (sin cambios): STG-first · nada a PRD sin certificar en STG +
visto bueno founder · cero suposiciones (verificar contra código y docs oficiales
con fetch live) · python3.11 explícito · comentarios en español · no commitear
sin suite verde · Supabase CLI pineada 2.90.0 (NO actualizar) · tras cada replay
de migraciones restaurar STG con `scratch/track9_backup_secrets.py`
(decrypted_secret, NO secret) + `track9_restore_stg.sh` + `track9_restore_stg.py`
· PII enmascarada en evidencias · FIX ARQUITECTÓNICO no parche · CALIDAD sin
importar tiempo/esfuerzo · **NO tocar el bot** (dispatcher, prompts, resolvers,
invariants, tools, libs del orchestrator) fuera del bloque bot — el bot conserva
sus espejos congelados hasta B-2/M3 y la duplicación queda defendida por tests
de paridad con alarma · la certificación de dinero la hace el harness turno a
turno en STG (scripts/uat/coherence_scenarios.py).

Estado certificado de base (no re-verificar salvo que algo falle): suite 4.767
pytest (xdist+SLOW; 4.754 serial) + 316 dbharness + 363 vitest + ruff 198 ≤
baseline 202 y **0 en `packages/shared-py/` (gate nuevo: la capa de dominio no
admite deuda)** + `certify_stg.sh` 18/18 + `validate.sh --ci` 25/25 + CI 5/5 +
harness B-3 (`money_full_flow`, `s11_cancela_preconfirmacion`) verde. Stack STG
local: `export DOCKER_HOST="unix:///run/user/$(id -u)/podman/podman.sock" &&
make -C .local deps && make -C .local db && make -C .local up`. **Tras cambios
de código, reiniciar el servicio afectado antes de certificar live**
(`make -C .local stop-api start-api`). **`validate.sh --ci` se corre con el web
DETENIDO** (`make -C .local stop-web`; luego `start-web` + certify_stg para
dejar STG completo).

Tarea inmediata — **Track 5 fase M2.3 (payment link colapsado)**:
1. Lee el brief de M2.3 en `.context/04-next-steps.md` (OBLIGATORIO — ahí está
   el diseño completo con archivos a crear/tocar y las 9 constraints de
   compatibilidad descubiertas; NO re-derives nada sin verificar que el brief
   siga vigente contra el código).
2. Implementa `payments.get_or_create_link` colapsado: política de reuso/TTL con
   ÚNICA fuente en `konvi_domain.orders.payments` · `wompi_client` del API
   re-exporta el TTL (shim) · router `create_payment_link` delega al servicio
   (puertos con lazy import — constraint #1) · `DomainError` gana `http_status`
   (constraint #6) · wiring tests de TTL actualizados deliberadamente + alarma
   de paridad con la constante del bot · contrato: `implemented=True`.
3. Tests: paridad con el espejo del bot (mismo criterio de reuso sobre las mismas
   filas) + unidad del servicio + TODOS los tests existentes del payment-link
   verdes sin cambiar su semántica.
4. Cierre del paso (la barra completa, como M2.1/M2.2): tests focales → suite →
   dbharness → harness B-3 `money_full_flow` + `s11_cancela_preconfirmacion`
   PASADOS → live STG (reuso de link vigente vía REST: crear orden + link,
   re-llamar, verificar mismo checkout_url sin fila nueva en payments) →
   `validate --ci` (web detenido) → commits temáticos + push + CI 5/5 +
   bitácora `docs/PLAN.md` §E + `.context/01-state.md`.
5. Al cerrar M2.3, continuar con **M2.4 (ClaimsService)** — diseño en
   `domain-services-contract.md` §5 (UN writer con reason cerrado +
   reason_detail, dedup idempotente, titularidad por actor, FSM formalizada,
   reversión delega a RPCs SQL, enums compartidos) con la misma barra y paridad
   bot↔paquete.
