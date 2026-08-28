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

### 1.9 Inventario real de componentes (`components/ui/` — 27)

Verificado con `ls apps/web/components/ui/` (2026-08-25; 36 archivos: 27 componentes + 9 `.test.tsx` — badge, motion, page-header + los 6 de T7.8 §6.5):

`alert` · `badge` · `button` · `card` · `carousel` · `checkbox` · `command` · `confirm-dialog` · `dialog` · `drawer` · `dropdown-menu` · `empty-state` · `input` · `label` · `motion` · `page-header` · `responsive-dialog` · `select` · `sheet` · `skeleton` · `sonner` · `submit-button` · `switch` · `table` · `tabs` · `textarea` · `tooltip`

Fuera de `ui/` pero parte del DS aplicado: `components/command-palette.tsx` (⌘K, §4.3) · `components/auth/auth-scene.tsx` (escena de auth T7.1: `AuthScene`/`AuthBrand`/`AuthCardReveal` — grano inline + aurora estática + brand tile degradado + coreografía stagger, usada por login/mfa/forgot/set-password/logout) · `components/route-error.tsx` (T7.6: boundary de error compartido por módulo — 23 `error.tsx` lo consumen) · `components/pwa/` · `components/theme/`.

Primitivos Radix instalados (`package.json`): accordion, checkbox, dialog, dropdown-menu, select, slot, switch, tabs, tooltip. Nota: `@radix-ui/react-accordion` es dependencia y sus keyframes viven en `globals.css:48-66`, pero **no existe `ui/accordion.tsx`** — primitive instalado sin wrapper del DS.

`confirm-dialog` y `submit-button` son componentes propios (no shadcn estándar): `ConfirmProvider` se monta en el root layout (`app/layout.tsx:5,59`). **`page-header` (T7.11)** es la cabecera de módulo con identidad: tile degradado primary→amber + `glow-primary` + glifo blanco (hermano del brand tile de auth) + título h1 + contexto + slot de acciones, con entrada stagger vía wrappers DS (§4.1); pilotada en settings/security (T7.11) y **aplicada transversal a todos los módulos en T7.12** (2026-08-27 — mapa por pantalla y excepciones en §5).

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
> Estado de dependencias (verificado en `apps/web/package.json`): **5 vigentes** — `tw-animate-css` ^1.4.0 y, agregadas el 2026-08-02: `framer-motion` ^12.43.0, `cmdk` ^1.1.1, `vaul` ^1.1.2, `embla-carousel-react` ^8.6.0. (`@tanstack/react-virtual` se instaló con ese mismo pack pero **nunca tuvo consumidor**: T7.7 midió todas las superficies candidatas — §4.6 — y la retiró el 2026-08-25; no dejar dep muerta). Ya existe además `components/ui/motion.tsx` (wrappers DS sobre framer-motion con reduced-motion uniforme vía `useReducedMotionDS` — hidratación-seguro desde T7.2; aplicado a pantallas desde T7.1). Las secciones 4.2-4.6 quedan como guía de dónde y cómo aplicar cada una.
>
> **Estado de implementación (2026-08-25):** §4.2 parcial (StaggerList en inbox/orders, `useCountUp` + Pressable en home, **chat motion ✅ T7.2** — `BubbleIn`+`AnimatePresence`, solo burbujas nuevas, live-verificado · **pill bottom-nav + layout cards pedidos ✅ T7.3** — `NavPill` layoutId + `LayoutItem`, live-verificado · **micro-celebraciones ✅ T7.4** — `CelebrationCheck` + toast sonner con monto count-up en home y detalle, verificado con dinero sandbox real) · §4.3 ✅ command palette ⌘K con búsqueda federada · §4.4 parcial (drawers en stock móvil y confirmación de pedido) · §4.5 parcial (carrusel OpsCards/KpiCards del home) · **§4.6 ✅ T7.7 (decisión medida live: la virtualización NO paga en ninguna superficie — dep `@tanstack/react-virtual` retirada)**. **Auth con firma propia (T7.1+T7.10 ✅):** `components/auth/auth-scene.tsx` — escena compartida (grano SVG inline sin terceros, aurora estática de tokens, brand tile degradado primary→amber + `glow-primary`, coreografía stagger vía wrappers §4.1) en login/mfa/forgot/set-password + **logout con despedida de marca** (`/logout`, signOut con limpieza G7 de la cookie AAL2); el "Logo mock / Brand" del login murió. **La firma dentro del canvas dashboard (T7.11 ✅):** `components/ui/page-header.tsx` — cabecera de módulo con identidad (tile degradado primary→amber + glow + glifo blanco + h1 + contexto + acciones, entrada stagger §4.1) pilotada en settings/security (cards DS para contraseña/MFA + avisos migrados a variantes de `Alert`); rollout a todos los módulos = T7.12.

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
| **Pedidos** (`orders-manager.tsx`) | ✅ T7.3 (2026-08-25): `LayoutItem` envuelve TODA card — al filtrar/paginar, las sobrevivientes se reubican suave (StaggerItem queda dentro para la entrada de las nuevas) | `layout` en la card; sin animación en carga inicial; reduced-motion sin layout (§4.1.1) |
| **Catálogo móvil** (`catalog-table.tsx` ProductMobileCard) | ✅ T7.9 (2026-08-27): `SwipeActions` del DS (`ui/motion.tsx`) — swipe-right → ajuste rápido de stock (bottom-sheet directo si hay UNA variante; si hay varias, expande la card para elegir), swipe-left → drawer de acciones (editar/desactivar/eliminar con sus confirms propios); hints contextuales revelados bajo la card; supresión del click tras un drag real (no come el tap de expandir) | Umbral 90px con snap al origen (instantáneo en reduced-motion — el drag es dirigido por el usuario); el gesto NUNCA dispara destructivas directas ni es la única vía (botones visibles permanecen) |
| **Pago confirmado / guía generada** (dashboard home + order detail) | ✅ T7.4 (2026-08-25): toast sonner con `CelebrationCheck` (pop spring único) + monto count-up al transicionar a `confirmed`/`delivered` vía realtime; isla `OrderStatusLive` en el detalle (celebra + refresh sin F5); dedupe por orden+estado | Una sola vez por evento; check estático y count-up al valor final en reduced-motion; sin confetti pesado |
| **Bottom-nav** | ✅ T7.3 (2026-08-25): `NavPill` — pill `layoutId` que viaja entre destinos (250ms), respeta `aria-current` y el badge de takeover; estática en reduced-motion | Respeta `aria-current` existente |

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

- **Carrusel KPIs móvil**: KPI bars horizontales con snap en dashboard home (✅ desde 894b7357), catálogo (`products-manager.tsx` KPI bar de 4 cards) y finanzas (`finance-dashboard.tsx`) — ✅ T7.9 (2026-08-27): doble render §2.5 — carrusel con snap + dots en `< sm` (antes se comprimían 2×2 / apilaban 1-col), grid intacto en `≥ sm`. Las cards se construyen UNA vez (array) y se montan en ambos contenedores.
- **Galería de producto**: `product-edit-drawer.tsx` / `image-upload-box.tsx` — navegación swipe entre fotos con thumbnails; reordenable sigue por DnD desktop.
- **Reglas**: `align: 'start'`, `containScroll: 'trimSnaps'`; dots con `aria-label`; loop desactivado en KPIs (son finitos y escaneables).

### 4.6 Listas largas — decisión verificada T7.7 (2026-08-25): la virtualización NO paga hoy

`@tanstack/react-virtual` se instaló con la Spec (2026-08-02) y **nunca tuvo consumidor** (grep: solo `package.json`). T7.7 midió TODAS las superficies candidatas contra el código y en live STG (sonda `scratch/t7_07_visual_verify.py`, 17/17, ambos temas + móvil + reduced-motion, 0 errores de consola):

| Superficie | Cota real verificada (código) | DOM máx (medido live) |
|---|---|---|
| Auditoría — cambios y accesos PII | Paginación **server-side** 25/pág (`audit/page.tsx` `pageSize=25` + `range()`) | 25 filas — con 68 eventos (3 págs) y 220 accesos (9 págs) reales en STG; navegación p1→p2 trae set distinto |
| Inbox — conversaciones | Ventana cursor 50 + 50 por click **deliberado** (`use-conversations.ts` PAGE_INITIAL/PAGE_STEP); agrupada por teléfono con filas expandibles de altura variable | 3 filas STG; sin scroll infinito; "Ver más" solo si el cursor no se agotó |
| Inbox — chat | Cursor de mensajes (prepend al subir) | acotado |
| Contactos | Ventana 500 + paginación **cliente** 30/pág (`contacts-manager.tsx` ITEMS_PER_PAGE) | 30 |
| Pedidos | REST `per_page=20` (`orders/page.tsx`) | 20 |
| Catálogo | Ventana protectora 1000 con aviso al operador (`catalog/page.tsx` PRODUCT_WINDOW — data-fetching: PostgREST trunca en silencio sin ella) | 7 en STG |
| Despachos / Marketplace / Comprobantes / Compras / Promociones | 50 envíos · páginas de 50 · paginado server · 100 OC+300 selects · redenciones on-demand ≤500 | acotados |

**Conclusión:** ninguna superficie monta miles de nodos hoy; la dep muerta se retiró de `apps/web/package.json` (2026-08-25). El caso borde es el catálogo (única lista sin paginación cliente): si un tenant real se acerca a la ventana de 1000, el fix consistente con el codebase es **paginación cliente estilo contacts** (`ITEMS_PER_PAGE`), NO virtualizar — la tabla tiene filas expandibles de altura variable con `aria-expanded`/teclado, y las filas virtuales romperían esa semántica por un caso borde. **Trigger para revisitar:** tenant con catálogo >500 productos Y pedido de producto de scroll continuo — solo ahí se re-evalúa `@tanstack/react-virtual` con `measureElement`.

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
| `/dashboard/settings/security` ◊ | CONFIG · Seguridad | Todos los roles; MFA TOTP + recovery codes + cambio contraseña · **con la firma (T7.11): PageHeader + stagger + cards DS + Alert variants** |
| `/dashboard/settings/health` ◊ | CONFIG · Salud integraciones | Grid de salud + refresh manual |
| `/dashboard/settings/legal` ◊ | CONFIG · Legal | Aceptación legal + descarga reporte SIC |
| `/dashboard/settings/legal/view/[doc]` ◊ | CONFIG · Legal | Visor de documento legal |
| `/dashboard/settings/retention` ◊ | CONFIG · Retención datos | Políticas de retención per-tenant |
| `/dashboard/settings/account-closure` ◊ | CONFIG · Cerrar cuenta | owner; destructiva con confirm |
| `/dashboard/account` ↪ | — | Redirect → `/dashboard/settings/security` (00-product §5.1) |
| `/dashboard/whatsapp-templates` ↪ | — | Redirect → `/dashboard/integrations/whatsapp?tab=plantillas` (00-product §5.1) |

◊ = ruta huérfana del tree canónico (hallazgo M2 de la auditoría). ↪ = redirect de compatibilidad.

**Cabeceras de módulo con identidad (T7.12, 2026-08-27):** todas las pantallas de módulo llevan `PageHeader` (§1.9) — tile degradado primary→amber + `glow-primary` + glifo blanco junto al h1, línea de contexto verbatim y acciones a la derecha (rollout transversal del piloto settings/security de T7.11; home incluido: el saludo «Bienvenido, {tenant}» ES el header, con `text-gradient` intacto — `PageHeader.title` es ReactNode). **Excepciones documentadas:** **inbox** — el h1 «Inbox AI» vive en el panel angosto (w-80), no en una fila de página → NO PageHeader completo; mini-tile de marca inline (mismo degradado, `h-7 w-7 rounded-lg`) junto al título, chip «Live» intacto · **ramas de error/vacío/gate NO llevan firma** (`ClaimsError` en claims, gate «no conectado» de marketplace — ahí manda el EmptyState) · **detalle comprobante** (`receipts/[id]`) — PageHeader con `print:hidden`: el CSS de impresión oculta todo `<header>` y el artefacto impreso queda byte-idéntico · redirects (inventory, account, whatsapp-templates) y el área auth (ya firmada en T7.1/T7.10) fuera de alcance. **Bug pre-existente cazado por la sonda T7.12:** el visor legal (`legal/view/[doc]`) era `force-static` bajo el layout autenticado → el layout no recibía las cookies de sesión y la ruta redirigía a /login (inalcanzable); quedó `force-dynamic` (verificado live: chain sin redirect).

**RBAC efectivo en navegación** (`sidebar-client.tsx:53-138`): Dashboard/Inbox/Pedidos/Contactos/Cotizador/Reclamos/Comprobantes — todos los roles; Productos/Categorías/Canales/KB/Métricas — owner+manager; Compras/Finanzas/Equipo/General/Cerrar cuenta — owner; Integraciones/Salud/Legal/Retención — owner+manager; Seguridad — todos. Locks visibles con razón (`Lock` icon + title) cuando falta integración o capability de plan (289-303).

---

## 6. Gaps UX conocidos (auditoría 2026-08-02, re-verificados)

> **Estado al 2026-08-25 (Track 7):** §6.1 ✅ (badge takeover vive en bottom-nav desde la rev. M1 — verificado live en T7.3) · §6.2 ✅ (T7.5: topbar con identidad de página + ⌘K) · §6.3 ✅ (T7.6: barrido a `EmptyState` completado) · §6.4 ✅ (T7.6: `RouteError` compartido + 23 boundaries por ruta) · §6.5 ✅ (T7.8: los 6 primitivos con lógica propia tienen cobertura de render).

### 6.1 Badge `human_takeover` ausente en bottom-nav móvil (M1)

El badge rojo con el conteo de conversaciones en `human_takeover` solo se renderiza en el sidebar (`sidebar-client.tsx:319-323`). `bottom-nav.tsx` no recibe `inboxBadge` (verificado: su `ITEMS` no tiene badge y `layout.tsx:183` lo monta sin props). En móvil el sidebar está oculto tras el drawer → el operador no ve la señal de escalaciones pendientes. **Fix sugerido**: dot/badge sobre el destino Inbox del bottom-nav, misma query ya cacheada en el layout.

### 6.2 Topbar móvil casi vacía

`layout.tsx:147-158`: la topbar (`h-12 topbar-bg`) en móvil solo contiene el espacio del hamburguesa + `ThemeToggle` + dot "Live" (oculto `< sm` el texto). No hay título de página, búsqueda ni badge. Es el slot natural para la entrada a la command palette (§4.3) y el badge de takeover (§6.1).

### 6.3 Sin EmptyState compartido

**✅ CERRADO 2026-08-25 (T7.6):** el barrido completó la migración — ~20 sitios ad-hoc en 13 archivos pasaron a `EmptyState` (team, categories, media, whatsapp-quality ×2, product-edit-drawer movimientos, context-panel pedidos/catálogo, metrics-charts ×2, metrics ×5, expenses con CTA, chat-panel ×2, las 4 páginas "Sin acceso", notas del inbox). Quedaron fuera a propósito: micro-notas en dropdowns de búsqueda (layout crítico, `p-3 text-xs`) y la alerta ámbar de proveedores en compras (es guía/alert, no vacío de lista). Verificado live (media light/dark, finance con CTA, barrido 27 rutas sin errores).

Al momento de la verificación no existía componente EmptyState en el DS (solo un helper local en `finance-dashboard.tsx`) y los estados vacíos eran ad-hoc: 47 coincidencias de frases tipo "No hay… / Aún no… / Sin resultados" en `app/dashboard` (grep) — cada módulo con su propio markup (ej. `orders-manager.tsx:478-495` con icono + dashed border + "Limpiar filtros"). **En curso (WIP sin commit, 2026-08-02)**: ya se creó `components/ui/empty-state.tsx` (variantes `default` dashed / `plain`, basado en el estilo del EmptyState local de finance) — falta la migración gradual de los ~15+ estados ad-hoc.

### 6.4 Error boundaries solo a nivel sección

**✅ CERRADO 2026-08-25 (T7.6):** `components/route-error.tsx` NUEVO (superficie única: card + retry + link inicio + digest, log con tag de módulo — extraído de los 6 idénticos) + **23 `error.tsx` por ruta** (17 nuevos: contacts, purchases, finance, claims, team, integrations (cubre los 5 providers), settings (cubre security/retention/health/legal/account-closure), marketplace, ai-agents, categories, promotions, receipts, inventory, audit, knowledge-base, media, account; + los 6 existentes migrados al compartido). Un error en una página ya no tira la sección completa.

En el árbol comprometido solo hay 3 boundaries: `app/global-error.tsx`, `app/error.tsx`, `app/dashboard/error.tsx` (este último: card "Error al cargar el módulo" + botón reintentar, log a consola) — un error en una página tira la sección dashboard completa (M5). **En curso (WIP sin commit, 2026-08-02)**: se agregaron `error.tsx` por ruta en `inbox`, `catalog`, `orders`, `shipping` y `metrics` (verificado con find: 7 `error.tsx` en total bajo `app/`). Cobertura aún parcial — el resto de módulos sigue cayendo al boundary de sección.

### 6.5 Tests de componente

**✅ CERRADO 2026-08-25 (T7.8):** los 6 primitivos del DS con lógica propia tienen cobertura de render — `empty-state` ×5 (variantes default/plain, icono aria-hidden, slot action, margen condicional) · `skeleton` ×2 (tokens base + merge de className) · `confirm-dialog` ×5 (error sin provider, resuelve true/false por botón, destructive, labels por defecto) · `responsive-dialog` ×2 (ambas ramas ≥lg Dialog / <lg bottom-sheet vía stub de `matchMedia` con getter — el mql queda cacheado por query) · `drawer` ×3 (portal, superficie tokens + handle + safe-area, cerrado no renderiza) · `carousel` ×3 (roles carrusel/diapositiva, guard de dots con ≤1 snap, error fuera de contexto). **20 tests nuevos** (vitest 406→426, 52 archivos). Lección de entorno: embla 8.6 exige stub de `matchMedia` + `IntersectionObserver` + `ResizeObserver` en jsdom (mismo patrón que `motion.test.tsx`). Verificado live en navegador real (`scratch/t7_08_visual_verify.py` 19/19: dots del carrusel home móvil, ResponsiveDialog bottom-sheet/dialog en pedidos, ConfirmDialog global abre/cancela sin redirect, EmptyState media ×2 temas, skeletons del inbox durante fetch demorado, reduced-motion, 0 errores consola). Los demás primitivos son wrappers finos Radix/shadcn sin lógica propia — cobertura incremental solo si ganan lógica.

Estado previo (auditoría 2026-08-02): 30 archivos de tests Vitest, pero solo **2 eran `.tsx`**: `components/ui/badge.test.tsx` (único test de componente UI) y `app/auth/callback/page.test.tsx` (página). Los otros 28 eran lógica/lib. El DS de 20 componentes carecía de cobertura de render (M5).

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
