# Restructuring Review — Vuelta 1 (Solo Diagnóstico)

**Fecha**: 2026-04-14  
**Rama**: `develop`  
**Revisión**: Vuelta 1 — diagnóstico, contraste, propuesta objetivo. Sin ejecución de cambios estructurales.  
**No modificar** sin leer `.context/00-product.md` primero.

---

## Objetivo de Esta Revisión

Reconstruir la base funcional ideal del producto desde cero, contrastarla contra el estado real del repo, detectar desalineaciones y dejar el diagnóstico completo listo para una segunda vuelta de ejecución controlada.

---

## Decisiones Preliminares

| Decisión | Descripción |
|---|---|
| **Renombrar `Logística` → `Despachos`** | Más honesto para PYME colombiana. Logística corporativa ≠ despacho de pedidos. |
| **Mover Envíos de Ventas → Despachos** | El despacho ocurre post-pedido — pertenece a operación, no a flujo comercial. |
| **Eliminar Central Ofertas del menú** | No hay caso de uso definido. Agrega ruido sin valor. |
| **Desbloquear `ai-agents`** | El módulo está implementado (DB + router + page). Estaba marcado `locked: true` erróneamente. |
| **Dashboard + Inbox → sección `Inicio` visible** | No como accordeon, sino como sección sin colapso para acceso directo. |
| **Grupos de 1 hijo → hoja directa** | `Compras`, `Finanzas` con 1 hijo no justifican el overhead del accordeon. |
| **Bottom nav mobile** | Los 3 módulos de mayor uso diario (Inbox, Pedidos, Contactos) deben ser accesibles por pulgar en mobile. |
| **Quitar trends hardcodeados** | KpiCard muestra `+12%`, `+5%` sin base real — erosiona confianza del tenant. |
| **Low stock dinámico** | Dashboard hardcodea `<= 5`. La DB tiene `tenants.low_stock_threshold`. Usar el valor real. |

---

## Contradicciones Detectadas

| Contradicción | Detalle |
|---|---|
| `.context/01-state.md` líneas 266-270 | Referencia `docs/product/admin-ui-modules.md`, `navigation-map.md`, `current-scope.md` — todos eliminados en sesión anterior |
| `docs/HANDOFF.md` tabla de referencias | Apunta a `docs/product/current-scope.md` — eliminado |
| `sidebar-client.tsx` marcado `ai-agents` como `locked` | El módulo tiene implementación real en `20260412000000_ai_agents_and_vectors.sql` + router + page |
| `Shipping` en el grupo `Ventas` en sidebar | Era correcto antes de la reestructuración conceptual. Ya no coincide con el nuevo tree funcional. |
| Tendencias en KPIs (`+12%`, `+5%`) | Datos falsos hardcodeados en `dashboard-client.tsx` — sin base en queries reales |
| Stubs vacíos en `packages/` y `docs/` | Generan falsa sensación de estructura sin contenido real |

---

## Propuesta Objetivo (Resumen para Vuelta 2)

### Sidebar nuevo structure (NAV_ITEMS):
```
Inicio (sin accordeon):
  · Dashboard
  · Inbox

Ventas:
  · Pedidos
  · Contactos
  · Reclamos

Productos:
  · Catálogo
  · Inventario
  · Media

Canales:
  · Mercado Libre

Despachos:
  · Cotizaciones (Envia) ✅
  · Órdenes de Envío 🔒

Compras (hoja directa si solo 1 hijo):
  · Órdenes de Compra

Finanzas (hoja directa si solo 1 hijo):
  · P&L / Ingresos & Gastos

IA y Automatización:
  · Base de Conocimiento ✅
  · Agentes IA ✅ (desbloquear)

Analítica:
  · Métricas
  · Auditoría

Configuración:
  · General
  · Equipo
  · WhatsApp
  · Integraciones
  · Notificaciones
```

### UX Mobile:
- Agregar `BottomNav` fijo con: Inbox, Pedidos, Contactos, Más(...)
- Reducir top bar a 40px o eliminar en mobile
- Breadcrumb en top bar para desktop

---

## Pendientes de la Vuelta 2

### Código
- [ ] `sidebar-client.tsx`: Restructurar NAV_ITEMS según propuesta objetivo
- [ ] `layout.tsx`: Agregar breadcrumb en top bar desktop; reducir/eliminar top bar mobile
- [ ] Crear `components/bottom-nav.tsx` para mobile
- [ ] `dashboard/page.tsx`: Usar `low_stock_threshold` dinámico
- [ ] `dashboard-client.tsx`: Eliminar trends hardcodeados

### Documental
- [ ] `.context/01-state.md`: Remover referencias a docs eliminados (líneas 266-270), actualizar sidebar real
- [ ] `docs/HANDOFF.md`: Actualizar tabla "Referencias rápidas"
- [ ] `.context/04-next-steps.md`: Actualizar con contexto de esta revisión

### Limpieza de raíz
- [ ] Mover `find_leaf*.py`, `test_*.py`, scripts de debug a `scripts/debug/` o eliminar
- [ ] Eliminar stubs vacíos: `docs/product/{functional,non-functional}-requirements.md`, `docs/architecture/{async-processing,output-template,realtime}.md`

### Evaluación (no ejecución todavía)
- [ ] Evaluar `packages/{ui,config,shared-types}/` — ¿eliminar dirs vacíos o definir contenido mínimo?
- [ ] Evaluar `packages/db/migrations/` — ¿vaciar o eliminar? La fuente es `supabase/migrations/`

---

## Riesgos Identificados

| Riesgo | Severidad | Mitigación |
|---|---|---|
| Cambiar grupo de `Shipping` en sidebar puede confundir a usuarios actuales que ya tienen esa ruta memorizada | Baja | Las URLs no cambian — solo cambia el grupo visual |
| Bottom nav mobile puede colisionar con el drawer mobile existente | Media | Ocultar drawer toggle cuando bottom nav está visible (`lg:hidden` vs `md:hidden`) |
| Desbloquear `ai-agents` sin verificar que el módulo sea completamente funcional para el tenant de prueba | Media | Revisar la implementación de `ai-agents/page.tsx` antes de exponer |
| Eliminar stubs puede romper imports si hay referencias no detectadas | Baja | Hacer grep exhaustivo antes de eliminar |
