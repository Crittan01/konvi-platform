# CI hardening + seguridad + test MFA — normalización 2026-07-24

Consolidación de una sesión de mantenimiento (Dependabot + endurecimiento de CI +
parche de seguridad + cobertura del gate MFA). Estado de deploy al cierre:
**`production` = `develop` = `1bfd5436`** (los 4 servicios Render live, health OK).

---

## 1. Dependabot — resuelto por completo

7 PRs abiertos + 1 que apareció durante el trabajo. Criterio: **mergear lo que se
autovalida o pasa el pipeline real; cerrar con justificación técnica lo que no es un
bump sino un proyecto**.

**Mergeados (4):** `#135` acciones CI (checkout v7.0.1, setup-python v7), `#136`
`@supabase/ssr`+`supabase-js`, `#132`/`#133` `sentry-sdk` 2.65 (api + orchestrator).

**Cerrados con justificación (5):** son **3 proyectos, no bumps**:
- `#137` eslint 8→10 + `#138` eslint-config-next 15→16 → **upgrade de Next 15→16**
  (eslint 10 rompe el lint sobre `.eslintrc.json`: `Invalid Options: useEslintrc`;
  eslint-config-next 16 apunta a Next 16).
- `#139` tailwindcss 3→4 → **migración Tailwind 4** (requiere `@tailwindcss/postcss` +
  migrar config + revisión visual de ~30 módulos; encaja con el barrido UX).
- `#140` @types/node 20→26 → **upgrade de runtime Node** (los tipos adelantarían al
  runtime Node 20 → footgun de runtime).
- `#134` grupo python-connector (fastapi 0.128.8→0.139.0 + supabase 2.31) → **rompe 4
  tests de `services/api`** por el venv compartido del CI (ver §4).

> Los "verdes" de los 4 majors JS eran **falsos**: ninguno corría lint ni tipos por el
> hueco de CI de §2.

---

## 2. Hallazgos — 3 huecos de CI (latentes, ninguno regresión nuestra)

**H1 — deps JS no se escaneaban en PRs de solo-lockfile.** El gate `osv-scanner` vivía
dentro de `validate.sh`, gateado por `backend`. Un cambio solo del lockfile (el 99% de
los PRs Dependabot JS) no lo ejecutaba. Cerrado en **#142**: paso `osv-scanner`
standalone (~2s) cuando cambia el frente JS y no el backend + `package.json`/
`osv-scanner.toml` agregados al filtro de paths.

**H2 — lint/tipos/tests de frontend no corrían en PRs de solo-frontend.** `validate.sh`
(que contiene TypeScript+ESLint+Vitest) estaba gateado por `backend`; un cambio solo de
`apps/web` los saltaba los tres — quedaba solo `next build`, que **degrada el fallo de
ESLint a mensaje no fatal**. Detectado con el PR de eslint 8→10 que pasó en verde en
2m34s imprimiendo `⨯ ESLint: Invalid Options`. Cerrado en **#144**: los 3 checks pasan
al job `build-web` (gateado por `frontend`, ya con Node+deps → sin arrastrar la suite
Python). Además `validate.sh` ahora falla ante un error de HERRAMIENTA de ESLint (no
solo de reglas): antes `|| true` + grep de errores-de-regla dejaba pasar `Invalid
Options` como "Lint OK".

**H3 — el escaneo osv ignora por ID de advisory, no por paquete.** Un GHSA nuevo del
mismo paquete pone el CI en rojo aunque el paquete ya esté allowlisteado. Pasó dos veces
esta sesión (§3). Regla: si osv dice "can be fixed", **corregir con `pnpm.overrides`**
(verificando que la versión exista en el registry), no allowlistear.

---

## 3. Seguridad — advisories publicados en el día

- **`brace-expansion` (7.7) + `js-yaml` (7.5)** → `pnpm.overrides` a las versiones
  fijas (#142). El allowlist tenía advisories *anteriores* de esos mismos paquetes.
- **Next.js 15.5.20 → 15.5.21** (#145): **8 advisories, 2× CVSS 8.3**. Es un patch
  DENTRO del minor (no el major 16 cerrado). Dejó el trunk en rojo tras un merge; el
  osv-scanner de `validate.sh` lo detectó. + `postcss`/`sharp` transitivos por override.
  **Ya desplegado a prod** (konvi-web rebuild).

---

## 4. Hallazgo mayor — el venv compartido del CI (deuda estructural)

Del workflow de análisis (8 agentes). **No son 3 servicios, son 2 DOMINIOS DE PINS:**
`api` y `ai-orchestrator` tienen pins **byte-idénticos** (fastapi 0.139.0, pydantic
2.13.4, supabase 2.31.0, …); la única divergencia real es `connector` (0.128.8 / 2.12.5
/ 2.28.3). El CI instala los 3 en UN venv y **gana el último (connector)** →

> **Defecto latente:** el CI hoy testea api/orch bajo fastapi **0.128.8**, pero prod los
> corre en **0.139** (su pin real). El CI NO es fiel a prod para el core. Los tests de
> introspección MFA pasan hoy *por accidente* (bajo 0.128.8); un bump del connector a
> 0.139 (#134) los desenmascara.

### Plan (DIFERIDO a bloque dedicado — decisión founder)

**Split de 2 legs** (no 3 venvs — caro: marcar ~263 tests + residuo cross-service):
- leg `core` (api+orch, resolución coherente por pins idénticos) + leg `connector`
  (aislado).
- `ci.yml` → job matriz 2 legs (borrar el loop `for svc … pip install` compartido);
  `validate.sh` → flag `--service core|connector` + `--py-tests-only` (default sin flag
  = pase único actual, no rompe local); `conftest` root → manifest `CONNECTOR_OWNED`
  (~7-9 archivos) + guard AST anti-drift OBLIGATORIO; marker `connector` en pyproject +
  `--strict-markers`.
- **Fase 0 (prerrequisito, YA ENTREGADA):** el test ASGI de disparo MFA (#146) — porque
  el leg `core`, al correr bajo 0.139 real, desenmascara los 2 tests de introspección
  MFA + 1 de contrato postgrest. Adaptar/de-brittle esos 3 va en el mismo PR del split.

Plan de 8 fases completo en memoria (`reference_ci_shared_venv_dep_coupling`).

---

## 5. Cobertura del gate MFA de dinero (#146, entregado)

El gate MFA sobre payment-link / PATCH orders / generate-shipping-guide / offboarding
export+request-deletion tenía **cableado** probado (introspección) pero **no disparo**.
El forense confirmó: el enforcement en runtime sigue activo bajo 0.139; lo que rompe es
la introspección (lee internos privados de FastAPI por nombre). Se agregó
`tests/test_mfa_gate_asgi_401.py`: monta los **gates reales** en una app mínima y afirma
401 vía ASGI/DI para AAL1+MFA (200 sin MFA). Version-agnóstico, determinista,
probado-el-test (gate no-op → 200 → lo caza).

Efecto colateral: se corrigió una fragilidad **green-by-luck** en
`test_telegram_tenant_isolation` (dependía del orden de import para el secret).

---

## 6. Ideas / backlog

**De esta sesión (priorizado):**
1. **Split de venv (2 legs)** — §4, DIFERIDO. Prerrequisito (#146) ya hecho.
2. **Upgrade de Node runtime** — tiene presión externa: el build ya emite
   `Node.js 20 and below are deprecated … @supabase/supabase-js. Upgrade to 22+`.
   Desbloquea #140.
3. **Upgrade de Next 15→16** — arrastra #137/#138 (flat config de ESLint). Verificar si
   el "Next.js EOL" del audit de julio sigue vigente lo vuelve no-opcional.
4. **Migración Tailwind 4** — encaja con el barrido UX (revisión visual).

**Pre-existente (de sesiones previas — NO verificado hoy, confirmar vigencia antes de
planear):** perf `@audit_log` async-assuming (~54 handlers), barrido UX Tenant Console
(~30 módulos), habilitación MeLi.

---

## Apéndice — PRs de la sesión

Mergeados: #131 (money-path, ya desplegado), #132, #133, #135, #136, #142, #144, #145,
#146, #143, #141. Cerrados con justificación: #134, #137, #138, #139, #140.
