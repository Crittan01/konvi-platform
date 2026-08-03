'use client'

// Primitivos de motion del DS (Kaiu) — wrappers finos sobre framer-motion.
// REGLA: toda animación del producto pasa por aquí para que el respeto a
// `prefers-reduced-motion` sea uniforme (useReducedMotion en cada wrapper),
// alineado con el patrón CSS ya usado en globals.css (card-hover).
// Aún no aplicado a pantallas — fundación para las siguientes oleadas UX.

import * as React from 'react'
import {
  motion,
  useReducedMotion,
  type HTMLMotionProps,
  type Variants,
} from 'framer-motion'

const EASE_OUT = [0.16, 1, 0.3, 1] as const

/**
 * FadeIn — entrada suave (fade + translateY corto) al montar. Con
 * prefers-reduced-motion: `initial={false}` → aparece directo, sin animación.
 */
export function FadeIn({ children, ...props }: HTMLMotionProps<'div'>) {
  const reduce = useReducedMotion()
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
  const reduce = useReducedMotion()
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
  const reduce = useReducedMotion()
  return (
    <motion.div variants={reduce ? undefined : itemVariants} {...props}>
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
  const reduce = useReducedMotion()
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
