# `_archive/` — Documentación histórica de Konvi Platform

Esta carpeta contiene documentación **histórica superada**, conservada únicamente como registro de decisiones y contexto de auditoría. **No usar como referencia operativa.**

- Estado vigente del sistema: `.context/01-state.md`
- Backlog vigente: `docs/PLAN.md`
- Handoff operativo: `docs/HANDOFF.md`

**Fecha de la depuración:** 2026-08-02 (movimientos con `mv` simple; git detecta renames al stagear). Segunda pasada 2026-08-02: +3 a `integrations/` (nueva), +6 a `reports/`, +2 a `research/` (total 75).

Cada archivo archivado lleva una cabecera `⚠️ ARCHIVADO — 2026-08-02` como primera línea. Los 3 `.json` crudos (salidas de herramientas) no llevan cabecera para no corromper su formato.

Existe además `docs/research/_archive/` (9 archivos, creado antes de esta depuración) que sigue el mismo patrón y se mantiene en su ubicación original como precedente.

## Contenido archivado por directorio

| Directorio | Archivos | Contenido | Motivo |
|---|---|---|---|
| `integrations/` | 3 | `whatsapp.md` (supersedido por `whatsapp-meta.md`), `meta-suite.md` (diseño no implementado), `wompi-prep.md` (prep superada por `wompi.md` live) | superseded |
| `reports/` | 27 | Reportes de certificación rev78–rev109 + cierres puntuales (coherencia conversacional @6f2455fe, h31 Wompi, UAT replay DEV 2026-07-20) (25 `.md` + 2 `.json` crudos de runs e2e) | histórico superado |
| `research/` | 35 | 10 dossiers de mayo; 11 de la serie `inbox-*` (incl. 1 `.json`); auditorías puntuales (finiquito, fullstack, validation-and-plan, fullstack-review, f1-f2-meta-gap, plan-90plus 2026-07-16); planes y propuestas (nextjs15-upgrade, production-roadmap, ecosystem-master-plan, vertical-templates, dashboard-completeness, tenant-ecosystem, meta-app-architecture, kaiu-attribute-contract) | histórico superado / auditoría superseded |
| `refactor/` | 6 | Serie 0001–0006 del refactor Inbox y backlog de sesiones (0005 cubre Platform Console, iniciativa cancelada/bloqueada por OQ-P01) | histórico superado / plan cancelado |
| `sessions/` | 1 | Bitácora de sesión 2026-05-06 (sem4 P0 integraciones) | sesión cerrada |
| `quality/` | 1 | `bugs-pending-rev106.md` — pendientes de calidad a rev106 | histórico superado |
| `deployment/` | 1 | `FASE7_RENDER_DEPLOY.md` — despliegue Fase 7 ya ejecutado | histórico superado |
| `uat/` | 1 | `sem2-checkpoint-uat-plan.md` — plan UAT semana 2 ya ejecutado | histórico superado |
| **Total** | **75** | | |

## Qué NO está aquí (vigente)

- `docs/reports/`: certificaciones de julio (`launch_readiness`, `revalidacion_legal`, `next16`, `ci_sec`) y cierres recientes.
- `docs/research/`: `aveonline-dossier`, `changelog-watch`, `meli-*`, `validated-decisions.md`, `pending-validations.md`, `mcp-and-skills.md`, `official-doc-checklist.md` y su propio `_archive/`.
- Resto de `docs/`: ADRs, legal, runbooks, architecture, integrations, etc.
