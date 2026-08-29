'use client'

// AuroraCanvas — mesh gradient animado del panel visual de auth (login WOW;
// pulido v3: presencia subida tras feedback founder — "la aurora es tímida").
// Reglas duras cumplidas:
//   - Solo transform/opacity (thread compositor; sin layout ni paint por frame).
//   - prefers-reduced-motion → blobs ESTÁTICOS (animate=undefined), §4.1.1.
//     Se usa useReducedMotionDS (hidratación-seguro) y no useReducedMotion
//     directo: los estilos de los blobs son SSR-visibles y ramifican por
//     reduce — regla §4 nota 6 del DS.
//   - Se monta SOLO en el aside ≥lg de AuthScene: en <lg ni siquiera existe
//     el DOM (batería/FPS); el móvil lleva una banda aurora estática.
// La textura grano es el mismo SVG inline feTurbulence que la escena auth ya
// traía (cero dependencias de red en la puerta del producto). GRAIN_DATA_URL
// se EXPORTA: es la única fuente — AuthScene la reusa para el grano global.

import { motion } from 'framer-motion'
import { useReducedMotionDS } from '@/components/ui/motion'

// Textura grano inline (única fuente del patrón auth — importada por auth-scene).
export const GRAIN_DATA_URL =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"

const DRIFT = { duration: 26, repeat: Infinity, ease: 'easeInOut' } as const

export function AuroraCanvas() {
  const reduce = useReducedMotionDS()
  return (
    <div aria-hidden className="absolute inset-0 overflow-hidden bg-[#0D1211]">
      <motion.div
        className="absolute -top-1/4 left-1/4 h-[40rem] w-[40rem] rounded-full bg-primary/35 blur-3xl will-change-transform"
        animate={reduce ? undefined : { x: [0, 80, -60, 0], y: [0, -60, 40, 0] }}
        transition={DRIFT}
      />
      <motion.div
        className="absolute bottom-0 right-0 h-[32rem] w-[32rem] rounded-full bg-[hsl(var(--amber))]/20 blur-3xl will-change-transform"
        animate={reduce ? undefined : { x: [0, -70, 50, 0], y: [0, 50, -30, 0] }}
        transition={{ ...DRIFT, duration: 32, delay: -8 }}
      />
      {/* Tercer blob pequeño ámbar arriba-derecha, drift desfasado (v3). */}
      <motion.div
        className="absolute -top-10 right-10 h-[18rem] w-[18rem] rounded-full bg-[hsl(var(--amber))]/12 blur-3xl will-change-transform"
        animate={reduce ? undefined : { x: [0, -40, 30, 0], y: [0, 30, -20, 0] }}
        transition={{ ...DRIFT, duration: 22, delay: -14 }}
      />
      <div
        className="absolute inset-0 opacity-5 mix-blend-overlay"
        style={{ backgroundImage: `url("${GRAIN_DATA_URL}")` }}
      />
    </div>
  )
}
