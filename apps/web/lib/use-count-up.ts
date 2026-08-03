'use client'

/**
 * useCountUp — count-up animado para KPIs (Spec WOW §4.7).
 *
 * rAF + easeOutCubic; continúa desde el valor mostrado si el target cambia a
 * mitad de animación (realtime refresh). Con prefers-reduced-motion devuelve
 * el valor final DIRECTO en render (useReducedMotion de framer-motion, la
 * misma fuente que los wrappers de components/ui/motion.tsx).
 */
import { useEffect, useRef, useState } from 'react'
import { useReducedMotion } from 'framer-motion'

export function useCountUp(target: number, duration = 700): number {
  const reduce = useReducedMotion()
  const [value, setValue] = useState(target)
  // valueRef y value se actualizan SIEMPRE en par dentro del loop de rAF →
  // al re-entrar al effect, valueRef tiene el último valor realmente mostrado.
  const valueRef = useRef(target)
  const firstRun = useRef(true)

  useEffect(() => {
    // reduce: el return de abajo ya da `target` directo; no hay nada que animar.
    if (reduce) return
    const from = firstRun.current ? 0 : valueRef.current
    firstRun.current = false
    if (from === target) return
    const start = performance.now()
    let raf = 0
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - t, 3)
      const current = from + (target - from) * eased
      valueRef.current = current
      setValue(current)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, duration, reduce])

  return reduce ? target : value
}
