# Backlog de mejoras del Inbox — auditoría post-refactor

**Fecha:** 2026-05-29.
**Branch:** `refactor/inbox-components` (post-10/10).
**Disparador:** founder pidió validar "cosas que mejorar, adicionar, que hagan falta".

Auditoría del Inbox tras refactor estructural completo. Examina UX, workflow del operador, gaps funcionales, paridad con productos de soporte modernos (Intercom, Front, Crisp, Help Scout).

## ✅ Recién entregado (esta sesión)

| Item | Estado |
|---|---|
| Refactor estructural 10/10 (page.tsx Server thin + manager Client + 5 componentes + 3 hooks + _lib/) | ✅ |
| Filtros simplificados 7→4 chips canónicos | ✅ |
| Emoji picker en toolbar (35 emojis curados + tip OS picker) | ✅ |
| Build production-ready (3 bugs latentes corregidos en baseline) | ✅ |

## 🎯 Backlog priorizado por valor x esfuerzo

Convención: **P0** bloquea producto · **P1** alto valor · **P2** nice-to-have.

### 🟢 P0 (sin esto el producto sufre)

| Item | Esfuerzo | Por qué |
|---|---|---|
| **Notas privadas del operador** por conv (no enviadas al cliente) | 2-3h | Hoy el operador no puede dejar memos "este cliente pidió cambio talla la próxima vez" — pierde contexto entre sesiones. Tabla `conversation_notes` + UI panel derecho. |
| **Adjuntar imagen/PDF al outbound humano** (factura, foto producto, comprobante) | 3-4h | Operador no puede enviar PDF de factura o foto adicional. Solo texto. Bloquea casos reales (reclamo con foto, ticket recibido). |
| **Re-procesar último turno del bot** (botón "Volver a ejecutar IA") | 2h | Cuando el bot da una respuesta mala, operador toma control + tiene que rehacer. Botón "rerun" envía el último inbound de nuevo al orchestrator para que produzca outbound nuevo (con prompt actualizado o cache busted). |

### 🟡 P1 (productividad operador concreta)

| Item | Esfuerzo | Por qué |
|---|---|---|
| **Templates de respuesta rápida** (canned responses) | 4-5h | "Te confirmo el envío en 24h" / "Gracias por tu compra" / "Te paso el link de seguimiento" — operador tipea lo mismo todos los días. Tabla `tenant_canned_responses` + dropdown en editor + atajo `/saludo` `/envio` etc. |
| **Hotkeys navegación J/K para convs + Enter para abrir** (estilo Gmail) | 2h | Operador con 50 convs activas pierde tiempo con mouse. J/K para next/prev, Enter para focus chat, R para "responder", T para "Tomar control". |
| **Indicador cross-operadores "viéndolo ahora"** (Realtime presence Supabase) | 4-5h | Si 2 operadores abren misma conv, conflicto de takeover. Mostrar "Andrés está viendo esta conv" via Supabase Realtime Presence. |
| **Búsqueda dentro del chat actual** (Ctrl+F en mensajes) | 2h | Cliente menciona pedido viejo, operador busca por SKU/número orden en thread largo. Hoy hay que scrollear manualmente. |
| **Etiquetas/tags por cliente** (VIP, conflictivo, mayorista) | 3h | Tag visible al recorrer lista + filtrable. Tabla `contact_tags` + UI chips editables. |

### 🔵 P2 (valor menor, deferible)

| Item | Esfuerzo | Por qué |
|---|---|---|
| **Notificaciones browser** (nuevo mensaje cuando Inbox no es la pestaña activa) | 1-2h | `Notification.requestPermission()` + dispatch en Realtime handler. Operador atendiendo y trabajando en otra pestaña no se entera. |
| **Estado "ya viste" cross-operadores** (read receipt en team) | 3h | Hoy `last_read_at` es per-operador (A2). Si operador A abre y luego B abre, ambos ven la conv "como nueva". Agregar `team_last_read_at` global. |
| **Resumen LLM auto del thread** (botón "Resume" al inicio del chat) | 3h | Conv de 200 mensajes → operador nuevo entra → quiere contexto en 3 segundos. Llamar a Gemini con prompt "resume esto en 3 líneas". |
| **Snippet de catálogo en el editor** (autocompletar /producto al tipear) | 4h | `@producto` muestra dropdown de catálogo → click inserta link + nombre. Reduce errores de typing por SKU largo. |
| **Onboarding tour al primer login** (highlights cada panel) | 4h | Operador nuevo abre Inbox y se pierde. Tour con react-joyride o similar. Solo dispara primera vez. |
| **Métricas per-conv visibles** (# turns, tiempo total, valor del pedido) | 2h | Mostrar mini-bar en panel contextual con KPIs de la conv. Útil para operador junior. |
| **Re-render formato WhatsApp en preview del editor** | 0.5h | Ya está implementado parcialmente (`renderWhatsAppFormat(replyText)` ya pinta el preview). Verificar paridad 1-1 con cómo se ve en WhatsApp real. |
| **Indicador "typing..." del operador hacia el cliente** (Meta API soporta) | 3h | Cliente ve "Sara está escribiendo..." mientras operador escribe. UX premium pero requiere endpoint Meta `typing_indicator`. |
| **Eliminar mensaje outbound** (Meta API delete con timestamp <15min) | 2-3h | Operador envió mensaje con typo. Hoy queda permanente. Meta API permite delete dentro de 15 min de enviado. |

### 🟣 Investigación / experimental

| Item | Razón |
|---|---|
| **Multi-canal en el mismo Inbox** (WA + MeLi + Instagram Direct) | Cuando se agreguen otros connectors, decidir si vivir todo en un solo Inbox o por pestañas. |
| **AI assist al operador** ("sugerencia de respuesta" al tipear) | Cuando Gemini Flash sea estable, sugerir reply al operador con un botón "Aceptar IA". |
| **Hand-off offline → online** | Si operador cierra laptop, ¿qué pasa con convs abiertas? Auto-vuelve al bot tras 5min inactividad del operador. |

## 🎨 UX / micro-improvements detectados

Cosas pequeñas que mejoran la experiencia sin ser features nuevos:

1. **Editor textarea: auto-grow** — hoy es `rows={2}` fijo. Si el operador escribe párrafo largo se vuelve scroll interno. Mejor `field-sizing: content` o useEffect que ajuste rows según content.

2. **Phone formatting copy-to-clipboard** — click en el número del cliente en header copia el phone sin formato (útil para CRMs externos).

3. **SLA timer visual cuando expira** — hoy es solo color. Agregar progressbar circular sutil debajo del badge: "12:34 restantes" countdown live.

4. **Filtro Activas: contador per-status dentro del label** — "Activas (12 Bot · 3 Agente)" para que de un vistazo se vea distribución.

5. **Quick toggle "Solo mías" del operador actual** — checkbox que filtra convs donde el operador actual hizo el último outbound. "Mi cola" personal.

6. **Empty states más cálidos** — "Selecciona una conversación" es seco. Sugerir acción: "No hay convs activas. Tu bot está descansando 🌙".

7. **Banner de instalación PWA** — Inbox como PWA en mobile mejora UX considerable. Detectar si está en mobile + sugerir Add to Home Screen.

8. **Validación que el operador no haya empezado a escribir antes de cambiar de conv** — si el editor tiene texto y operador clica otra conv, confirmar "Tienes una respuesta sin enviar. ¿Descartar?".

## 🐛 Bugs latentes / improvements técnicos

| Item | Severidad |
|---|---|
| **`pendingConvRestore.current` no se limpia tras URL restore** | Bajo — solo el primer mount lo usa, después siempre `null` |
| **Race entre Realtime conv INSERT + `loadConversations()` re-fetch** podría duplicar | Bajo — el dedupe por `id` lo absorbe |
| **`syncUrlParam` con `router.replace` reduce history** que para "atrás del browser" puede sorprender | Bajo — comportamiento intencional pero documentar |
| **Auto-refresh 5s del contexto puede ser pesado** con 50 convs simultáneas | Medio — considerar Realtime channel en `conversation_carts` en vez de polling |
| **`messagesContainerRef` scroll restoration** durante `loadMore` puede fallar en mobile con momentum scroll iOS | Medio — testear en dispositivo real |

## 📊 Métricas para decidir prioridad real

Antes de hacer estos items, recolectar:

- ¿Cuántos operadores activos tiene KAIU hoy? (1-3 esperado).
- ¿Qué % del tiempo el operador escribe vs lee? (si 80% lee, hotkeys J/K son menos críticos).
- ¿Cuántas conversaciones promedio en human_takeover por día? (si <5, multi-operador presence es overkill).
- ¿Cuáles son las 3 frases más típicas que el operador escribe? (esos son los canned responses).

**Recomendación**: agregar logging anónimo cliente-side (event tracking) para 2 semanas antes de priorizar finamente.

## Mi recomendación firme — orden de implementación

Si tienes 1 sprint (~1 semana), atacar en este orden:

1. **Adjuntar imagen/PDF outbound** (P0) — desbloqueo de casos reales hoy.
2. **Notas privadas del operador** (P0) — cero costo arquitectónico, alto valor mantener contexto.
3. **Hotkeys J/K + R + T** (P1) — productividad operador inmediata.
4. **Templates canned responses** (P1) — payoff alto si KAIU tiene operador escribiendo lo mismo.
5. **Búsqueda Ctrl+F en chat** (P1) — bajo costo, alto uso real.

Los demás (P1 restantes + P2) cuando llegue tracción suficiente para justificarlo.
