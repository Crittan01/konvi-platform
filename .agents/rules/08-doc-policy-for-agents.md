# Regla N-08: Política Documental y Contexto para Agentes

**Esta regla es vinculante para todo agente que opere en este repositorio.**

---

## Jerarquía de Autoridad Documental

Al iniciar cualquier tarea, consultar en este orden:

1. `.context/00-product.md` — Tree funcional, dominios, qué es módulo (L1 — máxima autoridad)
2. `.context/01-state.md` — Estado real de implementación
3. `.context/04-next-steps.md` — Qué queda por hacer
4. `docs/HANDOFF.md` — Contexto operativo e infra

Si hay contradicción entre un archivo de nivel inferior y uno superior, **el superior gana**.

## Obligaciones al Cierre de Sesión

Todo agente que ejecute cambios debe, antes de hacer commit:

1. Actualizar `.context/01-state.md` con el estado real final del trabajo
2. Actualizar `.context/04-next-steps.md` con lo que quedó pendiente
3. Si se tomó una decisión arquitectónica → actualizar `.context/00-product.md`
4. Si cambiaron versiones reales → actualizar `.context/02-stack.md`
5. Si cambiaron referencias en documentación → actualizar los archivos afectados para no dejar refs rotas

## Prohibiciones Explícitas

- **No duplicar estado** en múltiples archivos. Un tema = una fuente.
- **No crear módulos** sin verificar primero el tree en `.context/00-product.md`.
- **No documentar Platform Console** como alcance activo. Es frontera futura.
- **No dejar referencias a archivos eliminados** en ningún documento vivo.
- **No crear archivos stub vacíos** (< 200 bytes sin contenido real efectivo).
- **No mantener "🔒 Próximo"** en el menú si no hay caso de uso real definido.

## Archivos que No Deben Recrearse

| Archivo | Razón |
|---|---|
| docs/product/navigation-map.md | Fusionado en `.context/00-product.md` |
| docs/product/current-scope.md | Movido a `.context/01-state.md` |
| docs/product/admin-ui-modules.md | Fusionado en `.context/01-state.md` |
| docs/architecture/nav-architecture.md | Redundante con `.context/00-product.md` |
| .agents/rules/nav-architecture.md | Reemplazado por `06-frontend-best-practices.md` |
| docs/product/functional-requirements.md | Stub vacío — eliminado |
| docs/product/non-functional-requirements.md | Stub vacío — eliminado |
| docs/architecture/async-processing.md | Stub vacío — eliminado |
| docs/architecture/output-template.md | Stub vacío — eliminado |
| docs/architecture/realtime.md | Stub vacío — eliminado |
