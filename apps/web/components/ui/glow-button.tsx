'use client'

// GlowButton — CTA primario magnético/líquido (PASO 3, login WOW).
//   - Magnético: el botón sigue sutilmente al cursor (spring suave) SOLO con
//     pointer fino (ratón) y sin prefers-reduced-motion; táctil → estático.
//   - Líquido: barrido de brillo en hover (span gradiente que cruza la cara;
//     motion-reduce:hidden → sin barrido con reduced-motion).
//   - Tap: compresión scale 0.95 (desactivada con reduced-motion).
// Hidratación segura: useReducedMotionDS — framer añade `tabindex="0"` al SSR
// cuando hay `whileTap` y los estilos magnéticos ramifican por reduce; ambos
// son SSR-visibles → prohibido useReducedMotion directo (regla §4 nota 6,
// documentada en ui/motion.tsx).

import * as React from 'react'
import { motion, useMotionValue, useSpring } from 'framer-motion'
import { cn } from '@/lib/utils'
import { EASE_OUT, useReducedMotionDS } from '@/components/ui/motion'

export function GlowButton({
  className,
  children,
  ...props
}: React.ComponentProps<typeof motion.button>) {
  const reduce = useReducedMotionDS()
  const [magnetic, setMagnetic] = React.useState(false)
  React.useEffect(() => {
    setMagnetic(window.matchMedia('(pointer: fine)').matches && !reduce)
  }, [reduce])

  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const sx = useSpring(x, { stiffness: 180, damping: 16 })
  const sy = useSpring(y, { stiffness: 180, damping: 16 })

  const onMove = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (!magnetic) return
    const r = e.currentTarget.getBoundingClientRect()
    x.set((e.clientX - r.left - r.width / 2) * 0.18)
    y.set((e.clientY - r.top - r.height / 2) * 0.18)
  }

  return (
    <motion.button
      style={magnetic ? { x: sx, y: sy } : undefined}
      onMouseMove={onMove}
      onMouseLeave={() => { x.set(0); y.set(0) }}
      whileTap={reduce ? undefined : { scale: 0.95 }}
      transition={{ duration: 0.15, ease: EASE_OUT }}
      className={cn(
        'group relative inline-flex items-center justify-center overflow-hidden',
        'rounded-xl bg-primary font-medium text-primary-foreground',
        'h-11 px-6 text-sm max-sm:min-h-[44px]',
        'shadow-[0_0_24px_-6px_hsl(var(--primary)/0.6)]',
        'transition-shadow hover:shadow-[0_0_36px_-4px_hsl(var(--primary)/0.8)]',
        'focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring',
        'disabled:pointer-events-none disabled:opacity-50',
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/20 to-transparent transition-transform duration-500 group-hover:translate-x-full motion-reduce:hidden"
      />
      <span className="relative inline-flex items-center">{children}</span>
    </motion.button>
  )
}
