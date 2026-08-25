# UX/UI — Documento Maestro de Experiencia y Diseño

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Documento canónico pre-producción del Tenant Console (`apps/web/`). Regla de oro aplicada: **cero suposición** — cada afirmación cita el archivo (y línea) que la respalda. Lo no verificable desde el código está marcado explícitamente como **[DECLARADO]** en §7.

---

## 0. Stack real verificado (manda el código, no los docs viejos)

| Capa | Real verificado | Evidencia |
|---|---|---|
| Next.js | **16.2.11** | `apps/web/package.json` (`"next": "16.2.11"`) |
| React | **^19** | `apps/web/package.json` |
| Tailwind CSS | **4.3.3** — sin `tailwind.config`; tokens en `@theme inline` | `apps/web/package.json`, `app/globals.css:11` |
| Animación CSS | `tw-animate-css` ^1.4.0 (reemplazo de `tailwindcss-animate`) | `app/globals.css:2-5` |
| Componentes | 20 en `components/ui/` (shadcn/ui sobre Radix) | `ls apps/web/components/ui/` §1.9 |
| Tipografía | Inter self-hosted vía `next/font` | `app/layout.tsx:18-22` |
| Feedback | sonner ^2.0.7 | `app/layout.tsx:4`, §3.3 |
| Gráficos | recharts ^3.9.2 | `apps/web/package.json` |
| Tests | Vitest 4 + Testing Library | `apps/web/package.json`, §6.5 |

> Nota: `AGENTS.md` y `.context/00-product.md` declaran Next 14.2.35 / 15.5.20, React 18 y Tailwind 3.3 — **desactualizados** frente al `package.json` real (coincide con hallazgo A7 de `.audit/findings/2026-08-02-consolidated-audit.md`).

---

## 1. Design System "Kaiu"

### 1.1 Arquitectura de tokens (Tailwind 4, `@theme inline`)

Los tokens semánticos se declaran en `app/globals.css:11-67` dentro de `@theme inline` y mapean `hsl(var(--token))`. El modificador `inline` es **obligatorio** (comentario en `globals.css:9-10`): sin él, Tailwind 4 congela el valor y el swap de tokens de `.dark` deja de reaccionar — dark mode roto.

Tokens semánticos (`globals.css:17-46`):

- Superficies: `--background`, `--card`, `--popover`, `--secondary`, `--muted`, `--accent`
- Texto: `--foreground`, `--card-foreground`, `--popover-foreground`, `--secondary-foreground`, `--muted-foreground`, `--accent-foreground`
- Marca/acción: `--primary` + `--primary-foreground`, `--destructive` + `--destructive-foreground`
- Formularios: `--border`, `--input`, `--ring`
- Radio: `--radius: 0.75rem` (+ derivados `--radius-lg/md/sm`, `globals.css:44-46`, 177)

Compatibilidad v3→v4: capa base que fija `border-color` a `--color-gray-200` (`globals.css:77-85`) y regla global `* { @apply border-border }` (`globals.css:255-258`).

### 1.2 Tema claro — "Kaiu Organic"

Definido en `:root, .light` (`globals.css:136-192`). Filosofía declarada en el propio archivo (`globals.css:140-145`): diseño orgánico, natural y elegante.

| Token | Valor HSL | Hex / descripción |
|---|---|---|
| `--background` | `30 25% 96%` | `#F8F5F1` — "Kaiu Cream", crema cálido |
| `--card` / `--popover` | `30 20% 98%` | `#FBFAF6` — elevación natural sobre el fondo |
| `--foreground` | `156 33% 20%` | `#224438` — verde bosque profundo (contraste sin negro) |
| `--muted-foreground` | `156 22% 34%` | `#44695A` — ≥4.5:1 AA sobre el crema (ajustado desde 40%, `globals.css:160`) |
| `--primary` | `156 33% 27%` | `#2E5C4A` — verde corporativo Kaiu |
| `--accent` / `--amber` | `43 65% 53%` | "Kaiu Gold" |
| `--border` / `--input` | `30 25% 85%` | `#DCD6CD` — arena/beige |
| `--destructive` | `0 84% 60%` | rojo |
| `color-scheme` | `light` | `globals.css:191` |

La clase `.light` recibe los **mismos** tokens que `:root` sin duplicarlos (`globals.css:132-137`): permite forzar tema claro en un subárbol aunque `<html>` tenga `.dark` (páginas de auth con card clara hardcodeada).

### 1.3 Tema oscuro — "Kaiu Evening Forest"

Definido en `.dark` (`globals.css:202-232`). El comentario rector (`globals.css:194-201`) lo dice explícito: **NO es una inversión naïve** — es la versión nocturna del look orgánico.

| Token | Valor HSL | Descripción |
|---|---|---|
| `--background` | `165 14% 11%` | charcoal verde-bosque profundo |
| `--card` / `--popover` | `165 13% 15%` | superficie elevada |
| `--foreground` | `40 30% 92%` | crema cálido — contraste alto |
| `--muted-foreground` | `150 12% 64%` | sage-gris ≥4.5:1 AA |
| `--primary` | `156 42% 55%` | verde Kaiu **más brillante** para resaltar en oscuro |
| `--amber` / `--accent` | `43 70% 60%` | dorado que conserva calidez |
| `--border` / `--input` | `165 12% 22%` | sutil pero visible |
| `color-scheme` | `dark` | `globals.css:231` |

Solo se sobrescriben tokens del **canvas**: sidebar y topbar ya son oscuros y mantienen sus valores en ambos modos (§1.5).

### 1.4 Tokens chart theme-aware

`--chart-opex` y `--chart-beneficio` existen por tema (`globals.css:183-184` light, `228-229` dark): en dark el rojo y el verde suben de brillo (`0 72% 63%` / `152 48% 55%`) porque los literales originales quedaban tenues sobre el canvas oscuro. Consumidos por el P&L de Finanzas.

### 1.5 Superficies oscuras fijas (sidebar / topbar)

Sidebar y topbar son oscuros **en ambos temas** — tokens de fuente única (`globals.css:187-189`):

- `--sidebar-bg: 168 14% 8%` y `--sidebar-bg-end: 168 15% 6%` (gradiente vertical)
- `--topbar-bg: 168 13% 15%` — `#212B2A`, intermedio entre sidebar y canvas

La clase `.sidebar-gradient` sobrescribe tokens internos para forzar texto claro dentro del sidebar (`globals.css:238-244`); `.topbar-bg` fija fondo, texto crema y borde (`globals.css:247-251`).

### 1.6 Utilities custom (`@utility`)

Cinco, todas en `globals.css`:

| Utility | Líneas | Qué hace |
|---|---|---|
| `sidebar-gradient` | 87-94 | Gradiente 180° `--sidebar-bg` → `--sidebar-bg-end` |
| `glow-primary` | 96-99 | Glow verde sutil del logo (`box-shadow` con `--primary` al 25%) |
| `text-gradient` | 101-107 | Texto degradado verde → dorado (`background-clip: text`) |
| `card-hover` | 109-130 | **Opt-in** para cards interactivas: borde primary/20, sombra, `translateY(-2px)`. Transición limitada a propiedades animadas (no `all`) y **respeta `prefers-reduced-motion`** (124-129) |
| `chat-canvas` | 355-358 | Fondo del área de mensajes del Inbox; theme-aware (antes hex fijo `#F3F6F4` que no adaptaba a dark) |

### 1.7 Tipografía

- **Inter self-hosted** vía `next/font/google` (`app/layout.tsx:18-22`): subset `latin`, `display: 'swap'`, variable CSS `--font-inter`. El comentario F1 (`layout.tsx:14-17`) documenta que la fuente estaba declarada en el DS pero jamás se cargaba hasta ese fix — self-host elimina CLS.
- Stack: `var(--font-inter), system-ui, -apple-system, 'Segoe UI', Roboto, ...` (`globals.css:12-15`, `260-267`).
- Fuentes de emoji a color (Apple/Segoe/Noto/Twemoji) incluidas en el stack (`globals.css:260-267`) para que los mensajes de WhatsApp se vean como en el celular del cliente.
- `font-feature-settings: 'cv02', 'cv03', 'cv04', 'cv11'` en body (`globals.css:274`).
- Anti-aliasing: `-webkit-font-smoothing: antialiased` (`globals.css:268-269`).

### 1.8 Dark mode — mecánica

- Variante: `@custom-variant dark (&:is(.dark *))` (`globals.css:7`) — activación por clase `.dark` en `<html>`.
- **ThemeProvider propio, sin next-themes** (`components/theme/theme-provider.tsx`): resuelve guardado (localStorage `konvi-theme`) > sistema (`prefers-color-scheme`); persiste elección; escucha cambios del sistema **solo si el usuario no eligió manualmente** (`theme-provider.tsx:70-82`); aplica también `documentElement.style.colorScheme` (53-57).
- **Anti-FOUC**: script inline síncrono como primer hijo de `<body>` (`app/layout.tsx:12,57`) fija `.dark` antes del primer paint; el provider sincroniza React después — sin flash claro→oscuro.
- `<html suppressHydrationWarning>` (`layout.tsx:54`) por la mutación de clase pre-hidratación.
- `theme-color` por esquema en viewport (`layout.tsx:42-45`): `#F8F5F1` claro / `#1A211F` oscuro.

### 1.9 Inventario real de componentes (`components/ui/` — 26)

Verificado con `ls apps/web/components/ui/` (2026-08-25; 28 archivos: 26 componentes + `badge.test.tsx` + `motion.test.tsx`):

`alert` · `badge` · `button` · `card` · `carousel` · `checkbox` · `command` · `confirm-dialog` · `dialog` · `drawer` · `dropdown-menu` · `empty-state` · `input` · `label` · `motion` · `responsive-dialog` · `select` · `sheet` · `skeleton` · `sonner` · `submit-button` · `switch` · `table` · `tabs` · `textarea` · `tooltip`

Fuera de `ui/` pero parte del DS aplicado: `components/command-palette.tsx` (⌘K, §4.3) · `components/auth/auth-scene.tsx` (escena de auth T7.1: `AuthScene`/`AuthBrand`/`AuthCardReveal` — grano inline + aurora estática + brand tile degradado + coreografía stagger, usada por login/mfa/forgot/set-password/logout) · `components/pwa/` · `components/theme/`.

Primitivos Radix instalados (`package.json`): accordion, checkbox, dialog, dropdown-menu, select, slot, switch, tabs, tooltip. Nota: `@radix-ui/react-accordion` es dependencia y sus keyframes viven en `globals.css:48-66`, pero **no existe `ui/accordion.tsx`** — primitive instalado sin wrapper del DS.

`confirm-dialog` y `submit-button` son componentes propios (no shadcn estándar): `ConfirmProvider` se monta en el root layout (`app/layout.tsx:5,59`).

### 1.10 Deuda declarada del DS

1. **Remap dark interino** (`globals.css:295-358`): barrido de pares `bg-{color}-50/100` + `text-{color}-700` → tintes oscuros translúcidos por familia (red/amber/orange/emerald/blue/indigo/slate/gray/zinc/cyan/violet/teal). El propio comentario (301-302) lo declara: *"Interino; el fin de juego son tokens danger/warning/success/info"*. Sin `@layer` → ganan por cascada. No toca variantes `/15` `/20` ni páginas `.light`.
2. **Primitivos faltantes** (ausentes del directorio, verificado §1.9): `popover` (el token existe pero no el componente), `command`, `avatar`, `progress`, `calendar`, `carousel`, `scroll-area`, `separator`. La Spec WOW (§4) introduce `command` (cmdk) y `carousel` (embla) — deben crearse como wrappers del DS, no como estilos sueltos.

---

## 2. Sistema responsive / mobile

### 2.1 Bottom-nav móvil

`app/dashboard/bottom-nav.tsx` (verificado completo):

- **5 destinos**: Inbox, Pedidos, Catálogo, Contactos, Métricas (`bottom-nav.tsx:9-15`).
- Visible solo `< lg` (`lg:hidden`, línea 22); fixed bottom, `z-40`, `bg-card/90` + `backdrop-blur-sm`.
- **Safe-area**: `style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}` (línea 23).
- **aria-current="page"** en el destino activo (línea 32); activo por match exacto o prefijo (`pathname.startsWith(href + '/')`, línea 27).
- El contenido del dashboard lleva `pb-24` en móvil para no quedar bajo el bottom-nav (`app/dashboard/layout.tsx:177`).
- **Sin badges** — no recibe `inboxBadge` (gap M1, §6.1).

### 2.2 Sidebar drawer hamburguesa

`app/dashboard/sidebar-client.tsx`:

- Botón hamburguesa fijo `top-3 left-3 z-50`, solo `< lg`, `aria-label="Abrir menú"` (219-226).
- Drawer: `aside` fijo con `transition-transform duration-300`, entra/sale con `translate-x` (237-243); overlay `bg-black/60 backdrop-blur-xs` que cierra al click (229-234); botón cerrar `aria-label="Cerrar menú"` (267-273).
- Se cierra automáticamente al navegar (`useEffect` sobre `pathname`, 192-195).
- En `lg` pasa a sidebar relativo estático (`lg:relative lg:translate-x-0`).

### 2.3 Viewport y PWA

- **viewport-fit cover**: `app/layout.tsx:38-46` (`viewportFit: 'cover'`) — necesario para el safe-area del bottom-nav; `width: device-width`, `initialScale: 1`.
- **PWA instalable**:
  - Manifest generado en `app/manifest.ts`: `display: 'standalone'`, `start_url: '/dashboard'`, `orientation: 'portrait-primary'`, `theme_color: '#2E5C4A'`, `background_color: '#F8F5F1'`, iconos SVG (any + maskable) y apple-icon 180.
  - Service worker conservador `public/sw.js`: cache-first **solo** para `/_next/static/**` (assets con hash, inmutables); nada más se intercepta — sin riesgo de servir contenido stale ni romper auth (comentario cabecera de `sw.js`). Offline real diferido explícitamente.
  - Registro solo en producción, silencioso si falla (`components/pwa/sw-register.tsx`).
  - `appleWebApp` metadata en `app/layout.tsx:28-32`.

### 2.4 Inbox — 3 paneles con máquina de vistas móvil

`app/dashboard/inbox/_components/inbox-manager.tsx`:

- Tres paneles: `ConversationList` + `ChatPanel` + `ContextPanel` (líneas 353-412).
- **Máquina de vistas móvil**: `mobileView: 'list' | 'chat' | 'context'` (línea 58); seleccionar conversación → `'chat'` (192); el panel contextual móvil se cierra a `'chat'` (406) y se activa con `mobileView === 'context'` (409).
- Deep-link accionable `?status=human_takeover` desde las OpsCards del dashboard, one-shot con `history.replaceState` (82-101).
- Si WhatsApp no está conectado → estado vacío con CTA a Integraciones (328-346).

### 2.5 Doble render y cards

- **Catálogo**: doble render real en `catalog-table.tsx` — cards móvil `sm:hidden` (`ProductMobileCard`, 497-524) + tabla desktop `hidden sm:block` (527+); columna categoría solo `≥ md` (535). Además `viewMode: 'list' | 'grid'` (333) con toggle.
- **Pedidos**: lista de cards en `space-y-4` a todos los anchos (`orders-manager.tsx:497`); chips de filtro con scroll horizontal (`overflow-x-auto`, 435); grid principal `grid-cols-1 xl:grid-cols-3` (467) con formulario de nuevo pedido en columna lateral.

### 2.6 Breakpoints en uso

Conteo de variantes de breakpoint en `app/**/*.tsx` (grep 2026-08-02): **sm 243 · lg 55 · md 21 · xl 16** (2xl: 0). Estrategia efectiva: mobile-first con quiebre principal en `sm` (cards↔tabla) y estructural en `lg` (bottom-nav↔sidebar, drawer).

---

## 3. Patrones UX verificados

### 3.1 Skeletons que replican layout

17 rutas con `loading.tsx` bajo `app/dashboard` (verificado con `find`): dashboard root, catalog, categories, media, claims, contacts, orders, promotions, shipping, marketplace, knowledge-base, ai-agents, metrics, audit, integrations, settings, team.

Los skeletons replican la forma del layout real — ej. `orders/loading.tsx`: barra título+botón, 5 chips de filtro (`rounded-full`), 10 filas de cards (`h-16 rounded-xl`), todo con `animate-pulse` + `bg-muted`. El componente `ui/skeleton.tsx` existe pero solo se usa en 4 archivos (grep) — la mayoría de loading states usan divs crudos. **Inbox no tiene `loading.tsx`** (carga client-side con estados propios).

### 3.2 Anti-falso-0 (errores como error+retry, nunca "0")

Patrón verificado, ej. `orders-manager.tsx:403-414`: si la lectura falla se renderiza `Alert variant="destructive"` con el mensaje y botón **Reintentar** (`router.refresh()`) — nunca se pinta una lista vacía o un KPI en 0 ante error de carga. Métricas tiene su propio `metrics-retry.tsx`. El mismo patrón aparece en los hooks del inbox (`conversationsLoadError`, `messagesLoadError`, `contextError` pasados a los paneles).

### 3.3 Toast feedback

sonner montado una vez en root (`app/layout.tsx:60`). **95 llamadas** `toast.success/error/...` en **20 archivos** (grep 2026-08-2). Se usa para feedback de mutaciones (guardado, errores de acción), no para errores de lectura (esos van por el patrón §3.2).

### 3.4 Confirm-dialog para destructivas

`components/ui/confirm-dialog.tsx` con `ConfirmProvider` en root (`app/layout.tsx:59`). **21 archivos** lo consumen (`useConfirm`/ConfirmDialog, grep) — cancelaciones, eliminaciones, cierre de cuenta, desconexiones de integración.

### 3.5 Accesibilidad

- **Focus visible universal**: `:focus-visible { outline: 2px solid hsl(var(--ring)); outline-offset: 2px }` (`globals.css:287-292`) — cubre botones/links crudos que no usan primitivos.
- **Filas operables por teclado**: filas del catálogo expandibles con `onKeyDown` Enter/Espacio + `preventDefault` (`catalog-table.tsx:568,682`).
- **ARIA en controles reales**: `aria-current` (bottom-nav), `aria-pressed` + `aria-label` con conteos en chips de filtro de pedidos (`orders-manager.tsx:444-445`), `aria-label` en búsquedas (386) y botones de menú (sidebar 223,270), `aria-hidden` en iconos decorativos (bottom-nav 37), `aria-label="Navegación principal"` (bottom-nav 21).
- Contraste: tokens ajustados a ≥4.5:1 AA en ambos temas (§1.2/§1.3).

### 3.6 Mutaciones robustas (patrón inbox)

`inbox-manager.tsx`: `Idempotency-Key` con scope canónico por operación (`createIdempotencyKey('conversations.status'|'conversations.send')`, líneas 228,280) reutilizada en reintentos; retry único ante 503 con backoff 1.5s (247-251); `AbortController` con timeout 45s/90s; updates optimistas (mensaje enviado aparece sin esperar Realtime, 299-305; marcar leída, 197-198).

---

## 4. Spec WOW — guía de implementación aprobada

> **Principio rector**: el *wow* viene de **motion + command palette + polish móvil** — NO de más tokens ni de cambiar el DS. Todo lo de esta sección consume los tokens Kaiu existentes (§1) y respeta el dark mode (§1.8) sin excepción.
>
> **Directiva founder 2026-08-25 (ampliación, Track 7):** el lenguaje de diseño de auth (escena con grano + aurora + brand tile + coreografía) NO es una referencia aislada — es la **firma diferencial que debe impregnar TODO el front** (logout, cambio de contraseña, módulos y submódulos): no solo "llamativo", sino **diferencial frente a cualquier desarrollo genérico**. Track 7 ejecuta esta ampliación (breakdown T7.1-T7.12 en `.context/04-next-steps.md`).
>
> Estado de dependencias (verificado en `apps/web/package.json`): **las 6 ya están instaladas** — `tw-animate-css` ^1.4.0 y, agregadas el 2026-08-02 (WIP sin commit al cierre de esta verificación): `framer-motion` ^12.43.0, `cmdk` ^1.1.1, `vaul` ^1.1.2, `embla-carousel-react` ^8.6.0, `@tanstack/react-virtual` ^3.14.9. Ya existe además `components/ui/motion.tsx` (wrappers DS sobre framer-motion con reduced-motion uniforme vía `useReducedMotionDS` — hidratación-seguro desde T7.2; aplicado a pantallas desde T7.1). Las secciones 4.2-4.6 quedan como guía de dónde y cómo aplicar cada una.
>
> **Estado de implementación (2026-08-25):** §4.2 parcial (StaggerList en inbox/orders, `useCountUp` + Pressable en home, **chat motion ✅ T7.2** — `BubbleIn`+`AnimatePresence`, solo burbujas nuevas, live-verificado; pendientes pill bottom-nav, layout en cards de pedidos, micro-celebraciones) · §4.3 ✅ command palette ⌘K con búsqueda federada · §4.4 parcial (drawers en stock móvil y confirmación de pedido) · §4.5 parcial (carrusel OpsCards/KpiCards del home) · §4.6 pendiente (react-virtual instalado, sin consumidor aún). **Auth con firma propia (T7.1+T7.10 ✅):** `components/auth/auth-scene.tsx` — escena compartida (grano SVG inline sin terceros, aurora estática de tokens, brand tile degradado primary→amber + `glow-primary`, coreografía stagger vía wrappers §4.1) en login/mfa/forgot/set-password + **logout con despedida de marca** (`/logout`, signOut con limpieza G7 de la cookie AAL2); el "Logo mock / Brand" del login murió.

### 4.1 Reglas transversales de motion (obligatorias)

1. **`prefers-reduced-motion` siempre**. Precedente ya en el DS: `card-hover` anula transición y transform bajo `prefers-reduced-motion: reduce` (`globals.css:124-129`). Todo motion nuevo (framer-motion, CSS) debe tener su variante reducida — para framer-motion usar `useReducedMotion()` y desactivar layout animations/gestos.
2. **Solo tokens Kaiu** (`hsl(var(--token))` o utilities Tailwind semánticas). Prohibido introducir colores literales nuevos; el remap dark interino (§1.10) ya muestra el coste de los literales.
3. **Nada que rompa dark mode**: cualquier superficie nueva (palette, sheet, carousel) usa `bg-card`/`bg-popover` + `border-border` + tokens de texto; se prueba en ambos temas. El anti-FOUC y `.light` forzado de auth no se tocan.
4. **Motion con propósito operativo**: feedback, orientación espacial, celebración de hitos de dinero. Nada decorativo que retrase la tarea (operador en inbox mide segundos).
5. Duraciones cortas: micro-interacción 150-300ms (coherente con `duration-300` del drawer y `0.2s` de los keyframes accordion, `globals.css:48-49`).
6. **Reduced-motion hidratación-seguro** (T7.2): framer-motion `useReducedMotion()` lee la media query REAL en la primera pintura cliente, pero el SSR no puede conocerla → si el wrapper ramifica estilos de entrada en SSR, el usuario con reduce recibe hydration mismatch. Regla: en wrappers de entrada con estilo SSR-visible usar `useReducedMotionDS` (de `ui/motion.tsx`: false en SSR/hidratación, valor real tras montar); en superficies client-only (post-auth, p. ej. chat) el `useReducedMotion` directo es correcto.

### 4.2 framer-motion — layout animations, gestos, micro-celebraciones

Dependencia: `framer-motion` ^12.43.0 (instalada 2026-08-02). Usar preferentemente los wrappers de `components/ui/motion.tsx` (reduced-motion uniforme) en vez de `motion` crudo.

| Dónde | Patrón | Regla |
|---|---|---|
| **Inbox** (`chat-panel.tsx`) | ✅ T7.2 (2026-08-25): `BubbleIn` + `AnimatePresence` del DS — entrada slide-up 200ms SOLO en burbujas nuevas (`useAnimatableMessageIds`: nunca carga inicial, prepend loadMore ni dedupe polling/realtime; verificado live con navegador) | Fade 150ms en reduced-motion; sin `exit` (la UI no borra mensajes) |
| **Pedidos** (`orders-manager.tsx`) | Layout animation al cambiar estado de una card (chips de filtro reordenan la lista) | `layout` en la card; sin animación en carga inicial |
| **Catálogo móvil** (`catalog-table.tsx` ProductMobileCard) | Gesto swipe sobre la card: swipe-right → ajuste rápido de stock, swipe-left → acciones | Umbral con haptic-like snap; gesto nunca como única vía (botones visibles permanecen) |
| **Pago confirmado / guía generada** (dashboard home + order detail) | Micro-celebración: check animado + conteo sutil al llegar realtime un `confirmed`/`delivered` | Una sola vez por evento; desactivada en reduced-motion; sin confetti pesado |
| **Bottom-nav** | Indicador activo con `layoutId` (pill que viaja entre destinos) | Respeta `aria-current` existente |

### 4.3 cmdk — command palette global ⌘K

Dependencia: `cmdk` ^1.1.1 (instalada 2026-08-02). Crear `components/ui/command.tsx` (wrapper DS estilo shadcn sobre cmdk — cierra parte de la deuda §1.10).

- **Dónde**: global en `app/dashboard/layout.tsx` (atajo ⌘K / Ctrl+K; entrada también desde la topbar — hoy casi vacía en móvil, §6.2).
- **Búsqueda federada**: pedidos (por #id/teléfono/nombre), contactos (nombre/teléfono), productos (título/SKU) — reusando los endpoints existentes; más acciones de navegación a los módulos del sidebar (respetando RBAC e integrations-gating de `NAV_ITEMS`).
- **Reglas**: superficie `bg-popover` + `border-border`; `Dialog` de Radix ya instalado como contenedor; foco atrapado y `Esc` para cerrar (Radix lo da); resultados operables 100% por teclado; en móvil abre como panel full-width bajo la topbar (no modal centrado diminuto).

### 4.4 vaul — bottom-sheet drawers móviles

Dependencia: `vaul` ^1.1.2 (instalada 2026-08-02).

- **Dónde**: acciones rápidas en móvil — detalle de pedido (`orders/[id]`), acciones de conversación en inbox (resolver/etiquetar/notas), ajuste de stock desde `ProductMobileCard`.
- **Patrón**: bottom-sheet con drag-to-dismiss y snap points, reemplazando menús dropdown apretados en pantalla < sm. En `≥ sm` se mantiene `Dialog`/`dropdown-menu` actual (mismo contenido, dos presentaciones — patrón ya usado en catálogo cards↔tabla).
- **Reglas**: respeta `env(safe-area-inset-bottom)` (precedente en bottom-nav:23); superficie `bg-card`; no anidar con el drawer del sidebar (solo un gesto de drawer por pantalla).

### 4.5 embla-carousel-react — carrusel KPIs móvil y galería de producto

Dependencia: `embla-carousel-react` ^8.6.0 (instalada 2026-08-02). Crear wrapper `components/ui/carousel.tsx` (deuda §1.10).

- **Carrusel KPIs móvil**: KPI bars horizontales con snap en dashboard home, catálogo (`products-manager.tsx` KPI bar de 4 cards) y finanzas — hoy se comprimen o hacen overflow-x; el carrusel da snap + indicador de posición.
- **Galería de producto**: `product-edit-drawer.tsx` / `image-upload-box.tsx` — navegación swipe entre fotos con thumbnails; reordenable sigue por DnD desktop.
- **Reglas**: `align: 'start'`, `containScroll: 'trimSnaps'`; dots con `aria-label`; loop desactivado en KPIs (son finitos y escaneables).

### 4.6 @tanstack/react-virtual — listas largas

Dependencia: `@tanstack/react-virtual` ^3.14.9 (instalada 2026-08-02).

- **Dónde**: lista de conversaciones del inbox (`conversation-list.tsx` — hoy pagina con "cargar más"), historial de auditoría (`audit/page.tsx` — exporta CSV, potencialmente miles de filas), tabla de catálogo en tenants con catálogo grande.
- **Reglas**: virtualizar solo cuando la paginación cursor existente no baste (el inbox ya tiene cursor-based pagination — la virtualización es para scroll continuo); mantener los skeletons de fila (§3.1) como placeholders de overscan; filas de altura medida dinámica en conversaciones (preview de texto variable).

### 4.7 tw-animate-css — ya instalado (usar hoy)

`tw-animate-css@^1.4.0` importado en `globals.css:5` — provee `animate-in`, `fade-in-0`, `zoom-in-95`, `slide-in-from-*`. Aplicable sin instalar nada:

- **Transiciones de lista escalonadas**: cards de pedidos y conversaciones entran con `animate-in fade-in-0 slide-in-from-bottom-2` + delay incremental por índice (tope ~5 ítems, sin cascada infinita).
- **KPIs count-up**: hook ligero `useCountUp` (rAF, respeta reduced-motion mostrando el valor final directo) sobre los KPI bars ya renderizados — no requiere librería.
- **Micro-feedback**: `zoom-in-95` en aparición de toasts/badges de estado; `fade-in-0` en alerts del patrón anti-falso-0 (§3.2).
- Regla: estas clases ya respetan el DS (solo animan transform/opacity); el reduced-motion se garantiza añadiendo `motion-reduce:animate-none` (variante estándar Tailwind) donde aplique.

---

## 5. Inventario de pantallas (`app/dashboard` — 37 `page.tsx`)

Verificado con `find apps/web/app/dashboard -name "page.tsx"` (2026-08-02): **37 archivos** (la auditoría cita 38 — ver §7). Route groups `(nombre)` no cambian la URL. Las 17 rutas del tree canónico (`.context/00-product.md` §2) existen todas; 3 páginas son redirects de compatibilidad (marcadas ↪); 9 son rutas "huérfanas" del tree (hallazgo M2, marcadas ◊).

| Ruta | Módulo (tree) | Notas UX verificadas |
|---|---|---|
| `/dashboard` | INICIO · Dashboard | OpsCards con deep-links (p.ej. inbox `?status=human_takeover`); loading skeleton propio |
| `/dashboard/inbox` | INICIO · Inbox | 3 paneles + máquina vistas móvil (§2.4); sin loading.tsx (carga client); estado vacío si WA desconectado |
| `/dashboard/orders` | VENTAS · Pedidos | Cards + chips filtro con counts + aria-pressed; anti-falso-0 con retry; skeleton propio |
| `/dashboard/orders/[id]` | VENTAS · Pedidos | Detalle de pedido (timeline de estados) |
| `/dashboard/contacts` | VENTAS · Contactos | CRM mínimo + acciones Habeas Data (`habeas-data-actions.tsx`); skeleton propio |
| `/dashboard/shipping` | VENTAS · Despachos ("Cotizador" en nav) | Gated por integración shipping; cotizador + timeline (`shipment-timeline.tsx`) |
| `/dashboard/promotions` ◊ | VENTAS · Promociones | owner/manager; skeleton propio |
| `/dashboard/claims` | VENTAS · Reclamos | `reversion-panel.tsx` (refunds); skeleton propio |
| `/dashboard/receipts` ◊ | VENTAS · Comprobantes | Lista comprobantes |
| `/dashboard/receipts/[id]` ◊ | VENTAS · Comprobantes | Detalle comprobante |
| `/dashboard/catalog` | PRODUCTOS | KPI bar 4 cards, doble render cards/tabla + grid, ajuste stock inline; skeleton propio |
| `/dashboard/categories` ◊ | PRODUCTOS · Categorías | Contrato de atributos por categoría; skeleton propio |
| `/dashboard/inventory` ↪ | — | Redirect 301 → `/dashboard/catalog` (00-product §5.1) |
| `/dashboard/media` ◊ | PRODUCTOS · Media | Oculta del menú por decisión (00-product §5.1); skeleton propio |
| `/dashboard/marketplace` | CANALES · Mercado Libre | Badge amber en sidebar; gated integración + capability; skeleton propio |
| `/dashboard/purchases` | COMPRAS | owner only; órdenes de compra + proveedores |
| `/dashboard/finance` | FINANZAS | owner only; P&L con tokens chart theme-aware (§1.4); EmptyState local propio |
| `/dashboard/knowledge-base` | IA Y CONOCIMIENTO · KB | Banners de indexación/migración; skeleton propio |
| `/dashboard/ai-agents` | IA Y CONOCIMIENTO · Agentes IA | owner + capability `ai.agents.configure`; bot-preview; skeleton propio |
| `/dashboard/metrics` | ANALÍTICA · Métricas | Charts + filtros + retry propio; skeleton |
| `/dashboard/audit` | ANALÍTICA · Auditoría | owner + capability `analytics.audit.export`; skeleton |
| `/dashboard/settings` | CONFIGURACIÓN · General | owner; logo, umbral, origen envío, métodos de pago, presencia; skeleton |
| `/dashboard/team` | CONFIGURACIÓN · Usuarios y Acceso | owner only; invite/changeRole/remove; skeleton |
| `/dashboard/integrations` | CONFIGURACIÓN · Integraciones | owner/manager; hub de paneles; skeleton |
| `/dashboard/integrations/whatsapp` | CONFIG · Integraciones | Model B: form 6 credenciales + tabs (plantillas, opt-outs, calidad) |
| `/dashboard/integrations/wompi` | CONFIG · Integraciones | private_key + events_key (Vault) |
| `/dashboard/integrations/aveonline` | CONFIG · Integraciones | usuario/password/empresa + carriers + how-it-works |
| `/dashboard/integrations/telegram` | CONFIG · Integraciones | bot token + chat ID; comandos /resolver · /estado |
| `/dashboard/integrations/mercadolibre` | CONFIG · Integraciones | OAuth MeLi |
| `/dashboard/settings/security` ◊ | CONFIG · Seguridad | Todos los roles; MFA TOTP + recovery codes + cambio contraseña |
| `/dashboard/settings/health` ◊ | CONFIG · Salud integraciones | Grid de salud + refresh manual |
| `/dashboard/settings/legal` ◊ | CONFIG · Legal | Aceptación legal + descarga reporte SIC |
| `/dashboard/settings/legal/view/[doc]` ◊ | CONFIG · Legal | Visor de documento legal |
| `/dashboard/settings/retention` ◊ | CONFIG · Retención datos | Políticas de retención per-tenant |
| `/dashboard/settings/account-closure` ◊ | CONFIG · Cerrar cuenta | owner; destructiva con confirm |
| `/dashboard/account` ↪ | — | Redirect → `/dashboard/settings/security` (00-product §5.1) |
| `/dashboard/whatsapp-templates` ↪ | — | Redirect → `/dashboard/integrations/whatsapp?tab=plantillas` (00-product §5.1) |

◊ = ruta huérfana del tree canónico (hallazgo M2 de la auditoría). ↪ = redirect de compatibilidad.

**RBAC efectivo en navegación** (`sidebar-client.tsx:53-138`): Dashboard/Inbox/Pedidos/Contactos/Cotizador/Reclamos/Comprobantes — todos los roles; Productos/Categorías/Canales/KB/Métricas — owner+manager; Compras/Finanzas/Equipo/General/Cerrar cuenta — owner; Integraciones/Salud/Legal/Retención — owner+manager; Seguridad — todos. Locks visibles con razón (`Lock` icon + title) cuando falta integración o capability de plan (289-303).

---

## 6. Gaps UX conocidos (auditoría 2026-08-02, re-verificados)

### 6.1 Badge `human_takeover` ausente en bottom-nav móvil (M1)

El badge rojo con el conteo de conversaciones en `human_takeover` solo se renderiza en el sidebar (`sidebar-client.tsx:319-323`). `bottom-nav.tsx` no recibe `inboxBadge` (verificado: su `ITEMS` no tiene badge y `layout.tsx:183` lo monta sin props). En móvil el sidebar está oculto tras el drawer → el operador no ve la señal de escalaciones pendientes. **Fix sugerido**: dot/badge sobre el destino Inbox del bottom-nav, misma query ya cacheada en el layout.

### 6.2 Topbar móvil casi vacía

`layout.tsx:147-158`: la topbar (`h-12 topbar-bg`) en móvil solo contiene el espacio del hamburguesa + `ThemeToggle` + dot "Live" (oculto `< sm` el texto). No hay título de página, búsqueda ni badge. Es el slot natural para la entrada a la command palette (§4.3) y el badge de takeover (§6.1).

### 6.3 Sin EmptyState compartido

Al momento de la verificación no existía componente EmptyState en el DS (solo un helper local en `finance-dashboard.tsx`) y los estados vacíos eran ad-hoc: 47 coincidencias de frases tipo "No hay… / Aún no… / Sin resultados" en `app/dashboard` (grep) — cada módulo con su propio markup (ej. `orders-manager.tsx:478-495` con icono + dashed border + "Limpiar filtros"). **En curso (WIP sin commit, 2026-08-02)**: ya se creó `components/ui/empty-state.tsx` (variantes `default` dashed / `plain`, basado en el estilo del EmptyState local de finance) — falta la migración gradual de los ~15+ estados ad-hoc.

### 6.4 Error boundaries solo a nivel sección

En el árbol comprometido solo hay 3 boundaries: `app/global-error.tsx`, `app/error.tsx`, `app/dashboard/error.tsx` (este último: card "Error al cargar el módulo" + botón reintentar, log a consola) — un error en una página tira la sección dashboard completa (M5). **En curso (WIP sin commit, 2026-08-02)**: se agregaron `error.tsx` por ruta en `inbox`, `catalog`, `orders`, `shipping` y `metrics` (verificado con find: 7 `error.tsx` en total bajo `app/`). Cobertura aún parcial — el resto de módulos sigue cayendo al boundary de sección.

### 6.5 Tests de componente: 1 solo

30 archivos de tests Vitest, pero solo **2 son `.tsx`**: `components/ui/badge.test.tsx` (único test de componente UI) y `app/auth/callback/page.test.tsx` (página). Los otros 28 son lógica/lib. El DS de 20 componentes carece de cobertura de render (M5).

---

## 7. Afirmaciones no verificables / discrepancias detectadas

| # | Afirmación del encargo o de docs | Resultado de la verificación |
|---|---|---|
| 1 | "38 páginas bajo app/dashboard" | **37 `page.tsx`** verificados (find, 2026-08-02). Coincide con 34 pantallas funcionales + 3 redirects. No se pudo reproducir el 38. |
| 2 | "loading.tsx en 18 rutas" | **17 `loading.tsx`** verificados bajo `app/dashboard`. |
| 3 | "~15 EmptyState ad-hoc" | No reproducible como cifra: no hay componente EmptyState; hay 47 coincidencias de frases de empty-state en grep (proxy más grueso). |
| 4 | Librerías WOW "ya aprobadas por el founder" | La aprobación es **[DECLARADO]** — no verificable desde código. Lo verificado: al inicio de esta sesión solo `tw-animate-css` estaba instalado; **durante la sesión (2026-08-02, WIP sin commit) se agregaron a `package.json`** `framer-motion` ^12.43.0, `cmdk` ^1.1.1, `vaul` ^1.1.2, `embla-carousel-react` ^8.6.0 y `@tanstack/react-virtual` ^3.14.9, junto a `components/ui/motion.tsx`, `components/ui/empty-state.tsx` y 5 `error.tsx` por ruta (ver §4, §6.3, §6.4). |
| 5 | "FSM 9 estados" (docs de flujo) | **10 constantes de estado** en `services/ai-orchestrator/fsm/states.py` (ver `docs/flows/venta-conversacional.md`). |
| 6 | Stack AGENTS.md (Next 14 / React 18 / Tailwind 3) | Desactualizado (A7): real es Next 16.2.11 / React 19 / Tailwind 4.3.3 (§0). |
