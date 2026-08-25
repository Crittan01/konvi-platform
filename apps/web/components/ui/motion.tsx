'use client'

// Primitivos de motion del DS (Kaiu) — wrappers finos sobre framer-motion.
// REGLA: toda animación del producto pasa por aquí para que el respeto a
// `prefers-reduced-motion` sea uniforme (useReducedMotionDS hidratación-seguro
// en los wrappers de entrada; useReducedMotion directo donde aplica),
// alineado con el patrón CSS ya usado en globals.css (card-hover).
// Aplicado desde Track 7: escena auth (T7.1), topbar (T7.5), chat inbox (T7.2).

import * as React from 'react'
import {
  motion,
  useReducedMotion,
  type HTMLMotionProps,
  type Variants,
} from 'framer-motion'

const EASE_OUT = [0.16, 1, 0.3, 1] as const

/**
 * useReducedMotionDS — `useReducedMotion` hidratación-seguro.
 * framer-motion lee la media query REAL ya en la primera pintura cliente,
 * pero el SSR no puede conocerla y siempre renderiza la rama "sin reduce"
 * (estilos de entrada opacity:0/translateY) → hydration mismatch para
 * usuarios con prefers-reduced-motion (expuesto por la verificación live
 * de T7.2 en chromium con reduce emulado). Aquí SSR e hidratación coinciden
 * (false) y el valor real aplica tras montar: el contenido aparece ESTÁTICO
 * en el primer frame post-hidratación — exactamente lo que pide §4.1.1.
 * Uso: wrappers de ENTRADA con estilo SSR-visible (FadeIn/StaggerList/
 * StaggerItem) y Pressable (framer añade `tabindex="0"` al SSR cuando hay
 * `whileTap` — atributo SSR-visible que también diverge, expuesto por la
 * verificación live T7.4). BubbleIn no lo necesita (superficie client-only
 * tras auth: lee el valor real directo).
 */
function useReducedMotionDS(): boolean {
  const reduce = useReducedMotion()
  const [hydrated, setHydrated] = React.useState(false)
  React.useEffect(() => setHydrated(true), [])
  return hydrated ? reduce === true : false
}

/**
 * FadeIn — entrada suave (fade + translateY corto) al montar. Con
 * prefers-reduced-motion: `initial={false}` → aparece directo, sin animación.
 */
export function FadeIn({ children, ...props }: HTMLMotionProps<'div'>) {
  const reduce = useReducedMotionDS()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0 } : { duration: 0.25, ease: EASE_OUT }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

const listVariants = (stagger: number): Variants => ({
  hidden: {},
  show: { transition: { staggerChildren: stagger } },
})

const itemVariants: Variants = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2, ease: EASE_OUT } },
}

// Variante reduced-motion de StaggerItem: MISMOS valores finales con snap
// instantáneo (duration 0). NUNCA `variants={undefined}` para reduced: al
// quitar las variantes framer NO resetea los valores en vuelo y el contenido
// quedaba congelado en `opacity: 0` (bug real expuesto por la verificación
// live T7.3: usuarios con prefers-reduced-motion veían las listas con
// StaggerList VACÍAS). Con la variante duration-0, el flip post-hidratación
// (useReducedMotionDS) re-targets a `show` y todo encaja en el mismo frame.
const itemVariantsReduced: Variants = {
  hidden: {},
  show: { opacity: 1, y: 0, transition: { duration: 0 } },
}

/**
 * StaggerList — contenedor de listas: los <StaggerItem> hijos entran en
 * cascada. Con prefers-reduced-motion no hay stagger ni item animation.
 * `stagger` = delay entre ítems (default 0.05s; listas operativas usan
 * 0.02-0.03s — Spec WOW §4.1.5 micro-interacciones cortas).
 */
export function StaggerList({
  children,
  stagger = 0.05,
  ...props
}: HTMLMotionProps<'div'> & { stagger?: number }) {
  const reduce = useReducedMotionDS()
  return (
    <motion.div
      variants={listVariants(stagger)}
      initial={reduce ? false : 'hidden'}
      animate="show"
      {...props}
    >
      {children}
    </motion.div>
  )
}

/** StaggerItem — ítem de un <StaggerList> (hereda el timing del contenedor). */
export function StaggerItem({ children, ...props }: HTMLMotionProps<'div'>) {
  const reduce = useReducedMotionDS()
  return (
    <motion.div variants={reduce ? itemVariantsReduced : itemVariants} {...props}>
      {children}
    </motion.div>
  )
}

/**
 * Pressable — feedback físico en cards/elementos interactivos (lift en hover,
 * compresión en tap). Con prefers-reduced-motion: sin transforms, el feedback
 * visual queda a cargo de los estilos CSS (card-hover, etc.).
 */
export function Pressable({ children, ...props }: HTMLMotionProps<'div'>) {
  const reduce = useReducedMotionDS()
  return (
    <motion.div
      whileHover={reduce ? undefined : { y: -2 }}
      whileTap={reduce ? undefined : { scale: 0.98 }}
      transition={{ duration: 0.15, ease: EASE_OUT }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * AnimatePresence — re-export del DS para que las pantallas no importen
 * framer-motion directo (§4.1). Usar con `initial={false}` cuando la primera
 * pintura de la lista NO debe animar entrada (p. ej. historial de chat).
 */
export { AnimatePresence } from 'framer-motion'

/**
 * BubbleIn — entrada de burbuja de chat (Track 7 · T7.2, Spec §4.2 inbox):
 * slide-up 200ms con el easing del DS + `layout` SOLO en la burbuja nueva
 * (sus hermanas no se re-animan cuando polling/realtime re-emite el mismo id
 * — el padre decide con `enter`). Sin `exit`: la UI no borra mensajes y el
 * cambio de conversación reemplaza la lista entera (100 exits en paralelo
 * serían ruido, §4.1.4 motion con propósito operativo).
 * `enter={false}` → `initial={false}`: aparece directo (carga inicial,
 * prepend histórico de loadMore, dedupe). Con prefers-reduced-motion:
 * fade 150ms, sin desplazamiento ni layout (§4.1.1).
 */
export function BubbleIn({
  enter = true,
  children,
  ...props
}: HTMLMotionProps<'div'> & { enter?: boolean }) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      layout={enter && !reduce}
      initial={!enter ? false : reduce ? { opacity: 0 } : { opacity: 0, y: 12 }}
      animate={reduce ? { opacity: 1 } : { opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0.15 } : { duration: 0.2, ease: EASE_OUT }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * NavPill — indicador de destino activo que VIAJA entre ítems (T7.3, Spec
 * §4.2 bottom-nav). Se renderiza UNA vez por ítem con `active`; solo la del
 * destino activo se pinta. El `layoutId` compartido hace que la pill se
 * desplace al nuevo destino (250ms, easing del DS) en vez de aparecer de
 * golpe. Con prefers-reduced-motion se pinta estática (span sin layoutId →
 * sin viaje, §4.1.1). `aria-hidden`: el estado activo lo anuncia
 * `aria-current` en el link padre — la pill es solo refuerzo visual.
 * Sin estilos de entrada en SSR → no hay hydration mismatch (no aplica
 * useReducedMotionDS: el span de la pill no lleva `initial`).
 */
export function NavPill({
  active,
  layoutId,
  className,
}: {
  active: boolean
  layoutId: string
  className?: string
}) {
  const reduce = useReducedMotion()
  if (!active) return null
  if (reduce) return <span aria-hidden className={className} />
  return (
    <motion.span
      aria-hidden
      layoutId={layoutId}
      className={className}
      transition={{ duration: 0.25, ease: EASE_OUT }}
    />
  )
}

/**
 * LayoutItem — ítem de colección que se REUBICA suave cuando sus hermanos
 * cambian (chips de filtro, reorden; T7.3, Spec §4.2 pedidos). NO anima
 * entrada — eso es de FadeIn/StaggerItem (se anidan: LayoutItem por fuera,
 * StaggerItem dentro, para que el layout mida la caja del ítem de lista).
 * Con prefers-reduced-motion: sin layout (§4.1.1).
 */
export function LayoutItem({ children, ...props }: HTMLMotionProps<'div'>) {
  const reduce = useReducedMotion()
  return (
    <motion.div
      layout={!reduce}
      transition={{ duration: 0.25, ease: EASE_OUT }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * CelebrationCheck — check de hito de dinero (T7.4, Spec §4.2): UN pop con
 * spring (scale 0.3→1 + fade) al montar, sin confetti pesado ni loops. Con
 * prefers-reduced-motion: estático (`initial={false}`, §4.1.1).
 * Pensado para el toast de money events (`money-celebration.tsx`).
 */
export function CelebrationCheck({ children, ...props }: HTMLMotionProps<'span'>) {
  const reduce = useReducedMotion()
  return (
    <motion.span
      initial={reduce ? false : { scale: 0.3, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 14 }}
      {...props}
    >
      {children}
    </motion.span>
  )
}
