# Política de Documentación — Konvi Platform

**Este archivo define cómo se gobierna la documentación de este repositorio.**
Todo agente y desarrollador debe respetar estas normas antes de crear, modificar o eliminar archivos de documentación.

---

## Jerarquía de Fuentes de Verdad

| Nivel | Archivo | Propósito | Quién puede actualizarlo |
|---|---|---|---|
| **L1** | `.context/00-product.md` | Tree funcional, dominios, clasificación de módulos | Solo con decisión arquitectónica formal aprobada |
| **L1** | `.context/01-state.md` | Estado real de implementación verificado en código | Cada sesión de trabajo (al cierre) |
| **L2** | `.context/02-stack.md` | Stack real con versiones | Solo cuando cambia una versión real en el repo |
| **L2** | `.context/03-rules.md` | Reglas de implementación quick | Cuando cambia un principio del proyecto |
| **L2** | `.context/04-next-steps.md` | Próximos pasos y deuda técnica | Cada sesión de trabajo (al cierre) |
| **L3** | `docs/architecture/` | Decisiones técnicas de arquitectura | Con cambios de arquitectura real |
| **L3** | `docs/integrations/` | Diseño de conectores externos | Con nuevas integraciones o cambios de fase |
| **L3** | `docs/HANDOFF.md` | Estado operativo, credenciales, lecciones | Con cambios de infra o credenciales |
| **L3** | `docs/tech/` | Matrices técnicas, hardening y validaciones | Con cambios de contratos runtime |
| **L1** | `.context/06-contracts.md` | Contratos runtime (FSM, Wompi, Aveonline, fuentes que consume el bot) | Con cambios en runtime/contracts |
| **L1** | `.context/07-schema-canonical.md` | Snapshot del schema DB live (rev. 72+) | Regenerable con `scripts/dump_schema_canonical.py` |
| **L1** | `.context/08-domain-coherence-matrix.md` | Matriz Front↔API↔DB↔Tests↔Docs por dominio | Con cualquier rev. que cierre/abra drift arquitectural |
| **L1** | `.context/09-bot-flowchart.md` | Flowchart canónico del bot conversacional (FSM + tools + guards + async). | Con cualquier cambio en FSM/tools/guards |
| **L4** | `docs/roadmap/` | Fases de implementación y estado | Con avance formal de fases |
| **L4** | `docs/risks/` | Preguntas abiertas y registro de riesgos | Con nuevas decisiones o riesgos detectados |
| **L5** | `AGENTS.md` | Índice rápido y quick context para agentes IA | Solo si L1 o L2 cambian significativamente |
| **L5** | `CLAUDE.md` | Quick context para desarrollo | Solo si stack o reglas cambian |
| **L5** | `README.md` | Visión general para humanos | Con cambios de estado mayor o de estructura |

---

## Reglas de Consistencia

### Regla 1 — Una fuente por tema
Nunca duplicar el mismo estado en dos archivos.
Si el estado de un módulo cambia, actualizar **únicamente** `.context/01-state.md`.
No replicar ese estado en `AGENTS.md`, `README.md` ni `HANDOFF.md`.

### Regla 2 — Referencias, no duplicaciones
Los archivos de nivel L5 deben referenciar a L1/L2, no copiar su contenido.
Si `AGENTS.md` menciona el estado de implementación, debe apuntar a `.context/01-state.md`, no repetirlo.

### Regla 3 — Actualización obligatoria al cierre
Cada sesión de trabajo debe cerrar con:
1. `.context/01-state.md` actualizado con el estado real final
2. `.context/04-next-steps.md` actualizado con lo que queda pendiente
3. Si se tomó una decisión arquitectónica → `.context/00-product.md` actualizado

### Regla 4 — Sin placeholders como módulos
No documentar como "Próximo" o "🔒" en fuentes L1/L2 algo que no tiene caso de uso definido.
Los módulos sin implementación real van a `docs/roadmap/`, no al tree funcional.

### Regla 5 — Platform Console es frontera futura
No crear documentación de implementación para Platform Console.
Solo puede mencionarse como frontera futura bloqueante por OQ-P01.

### Regla 6 — Archivos sin contenido real deben eliminarse
Un archivo con < 200 bytes efectivos (stubs, placeholders) no es documentación —
es ruido que confunde a agentes. Eliminar o completar.

### Regla 7 — Los docs eliminados no deben reaparecer en referencias
Al eliminar un archivo, buscar y actualizar todas las referencias a él en el repo.

### Regla 8 — Frescura verificada (L1/L2)
Todo archivo L1/L2 (`.context/*.md`) lleva en su cabecera una línea
**"Verificado contra repo: YYYY-MM-DD @ commit"**.
Esa fecha se actualiza en **cada PR que cambie algo que el archivo declara**
(versiones, estados FSM, conteos, rutas, tablas). Un L1/L2 con fecha vieja es
sospechoso: verificar antes de confiar en él.

---

## Qué Archivos Existen y Para Qué

### `.context/` — Contexto activo del sistema
| Archivo | Contenido |
|---|---|
| `00-product.md` | Tree funcional, dominios, clasificación (L1 — no tocar sin decisión formal) |
| `01-state.md` | Estado de implementación real verificado en código |
| `02-stack.md` | Stack técnico con versiones reales |
| `03-rules.md` | Reglas quick de implementación para agentes |
| `04-next-steps.md` | Puntero a `docs/PLAN.md` + contexto extra no cubierto por el plan |
| `05-doc-policy.md` | Este archivo — gobierno de la documentación |
| `06-contracts.md` | Contratos runtime (FSM, Wompi, Aveonline, Meta, fuentes del bot) |
| `07-schema-canonical.md` | Snapshot del schema DB live (39 tablas CORE; regenerable) |
| `08-domain-coherence-matrix.md` | Matriz Front↔API↔DB↔Tests↔Docs por dominio |
| `09-bot-flowchart.md` | Flowchart canónico del bot agentic (gates, FSM, tools, invariants, async) |

### `docs/` — Documentación técnica detallada
| Carpeta | Contenido |
|---|---|
| `docs/PLAN.md` | **Plan maestro y backlog priorizado pre-producción (backlog de verdad)** |
| `docs/product/PRD.md` | PRD — qué es el producto |
| `docs/tech/TRD.md` | TRD — requisitos técnicos |
| `docs/backend/BACKEND.md` | Backend canónico (servicios, routers, workers) |
| `docs/ux/UX-UI.md` | UX/UI canónica (design system Kaiu) |
| `docs/flows/` | Flujos end-to-end (README + 6 flujos) |
| `docs/HANDOFF.md` | Estado operativo, credenciales activas, lecciones |
| `docs/architecture/` | Decisiones técnicas (front-back sep., multi-tenant, conectores) |
| `docs/integrations/` | Diseño de conectores (README + Wompi, Aveonline, Telegram, MeLi, WhatsApp-Meta) |
| `docs/adr/README.md` | Índice de ADRs |
| `docs/roadmap/` | Fases con estado |
| `docs/risks/` | Preguntas abiertas, riesgos, decisiones pendientes |
| `docs/_archive/` | Histórico superado (cabecera ARCHIVADO + README índice) — no es referencia operativa |

### Archivos raíz
| Archivo | Contenido |
|---|---|
| `AGENTS.md` | Quick context para agentes IA — índice de dónde buscar |
| `CLAUDE.md` | Quick context para desarrollo — stack, reglas, estructura |
| `README.md` | Visión general del proyecto para humanos |

---

## Archivos Deprecados o Eliminados

Los siguientes archivos fueron eliminados en sesiones previas. No recrear ni enlazar como rutas vivas:

| Archivo eliminado | Fecha | Razón |
|---|---|---|
| docs/product/navigation-map.md | 2026-04-14 | Redundante con `.context/00-product.md` |
| docs/product/current-scope.md | 2026-04-14 | Movido y fusionado en `.context/01-state.md` |
| docs/product/admin-ui-modules.md | 2026-04-14 | Redundante con `.context/01-state.md` |
| docs/architecture/nav-architecture.md | 2026-04-14 | Redundante con `.context/00-product.md` |
| .agents/rules/nav-architecture.md | 2026-04-14 | Reemplazado por regla `06-frontend-best-practices.md` |

---

## Las migraciones SQL NO son fuente de verdad (rev. 72)

Los archivos en `supabase/migrations/` son **history reproducible** (necesarios
para replicar el schema en otros entornos), pero NO son la spec viva del
sistema. La fuente de verdad operacional es:

1. **DB live** — vista por `information_schema` en el proyecto Supabase linked.
2. **Contratos en código vivo** — Pydantic models en `services/api/routers/*`,
   types TS en `apps/web/`, server actions, helpers de orchestrator.
3. **`.context/07-schema-canonical.md`** — snapshot regenerable de la DB live.

### Reglas de mantenimiento

- Al detectar divergencia entre cualquiera de estas y una migración antigua,
  **ajustar la canónica viva** y, si aplica, generar una migración nueva
  forward-only que refleje la decisión.
- **Nunca** modificar migraciones aplicadas (otros entornos las re-ejecutan).
- Las migraciones tienen valor histórico (auditoría de evolución del schema)
  y de replicabilidad (un nuevo entorno se levanta corriéndolas en orden).
- Para detectar drift live↔fixture: `python3.11 scripts/dump_schema_canonical.py --diff`.
- Para regenerar fixture tras cambio aprobado: `python3.11 scripts/dump_schema_canonical.py`.

### Tests de coherencia (golden file)

`tests/test_coherence_pact.py` valida que cada Pydantic model de write
(Create/Patch) en routers tenga sus campos como columnas reales en la tabla
correspondiente. Si un agente futuro agrega un campo huérfano (no en DB), el
test rompe con mensaje claro indicando dominio + campo.

---

## Cómo Actuar en Futuras Sesiones

Al iniciar una sesión de trabajo:
1. Leer `.context/00-product.md` (tree funcional + dominios)
2. Leer `.context/01-state.md` (estado real de implementación)
3. Leer `.context/04-next-steps.md` (qué queda por hacer)
4. Revisar `docs/HANDOFF.md` para contexto operativo e infra

Al cerrar una sesión:
1. Actualizar `.context/01-state.md` con estados reales
2. Actualizar `.context/04-next-steps.md` con lo que quedó pendiente
3. Si tomaste una decisión arquitectónica importante → actualizar `.context/00-product.md`
4. Si cambiaron versiones reales → actualizar `.context/02-stack.md`
5. Commit + push (rama `develop`) para triggear autodeploy en Render
