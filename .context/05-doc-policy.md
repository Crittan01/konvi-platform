# Política de Documentación — Commerce Ops Platform

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

---

## Qué Archivos Existen y Para Qué

### `.context/` — Contexto activo del sistema
| Archivo | Contenido |
|---|---|
| `00-product.md` | Tree funcional, dominios, clasificación (L1 — no tocar sin decisión formal) |
| `01-state.md` | Estado de implementación real verificado en código |
| `02-stack.md` | Stack técnico con versiones reales |
| `03-rules.md` | Reglas quick de implementación para agentes |
| `04-next-steps.md` | Próximos pasos y deuda técnica |

### `docs/` — Documentación técnica detallada
| Carpeta | Contenido |
|---|---|
| `docs/HANDOFF.md` | Estado operativo, credenciales activas, lecciones |
| `docs/architecture/` | Decisiones técnicas (front-back sep., multi-tenant, conectores) |
| `docs/integrations/` | Diseño de conectores (Envia, MeLi) |
| `docs/roadmap/` | Fases con estado |
| `docs/risks/` | Preguntas abiertas, riesgos, decisiones pendientes |

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
