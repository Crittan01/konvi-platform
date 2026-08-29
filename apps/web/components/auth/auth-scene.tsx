'use client'

// Escena compartida de auth (login · mfa · forgot · set-password · logout) —
// Track 7 T7.1; reescrita a split-screen en el PASO 3 (login WOW).
//
// El canvas oscuro fijo del patrón auth (`.light` forzado — NO se toca, §1.8
// del DS) gana el panel visual de marca que la directiva founder pide ("login
// animado y memorable"), sin mover NI UN token:
//   - Layout split ≥lg: columna formulario (minmax(460px,45%)) + panel visual
//     con AuroraCanvas (mesh gradient animado, solo transform/opacity; en <lg
//     NO se monta el DOM — batería/FPS). <lg: banda aurora ESTÁTICA superior
//     + blob dorado estático inferior, cero costo de animación. Pulido v3
//     (feedback founder "plano"): grano global sobre TODA la escena (data URL
//     inline exportada desde aurora-canvas — única fuente), glow radial suave
//     detrás del formulario, hairline lg:border-r entre columnas, headline
//     del panel más grande y chips glass de capacidades.
//   - Entrada del formulario: fade + subida y:20→0 (pedido explícito founder)
//     vía `AuthEntrance`, wrapper LOCAL que replica el patrón FadeIn del DS
//     (mismo EASE_OUT, reduced-motion → initial={false}) sin tocar el FadeIn
//     global.
//   - Storytelling del panel: stagger vía wrappers del DS (StaggerList/
//     StaggerItem — prohibido `motion` crudo en pantallas, §4.1; aquí solo se
//     usa en AuthEntrance, primitivo local de esta misma escena).
//   - Logo real: tile degradado primary→amber con `glow-primary` + letterform
//     K. El wordmark va BLANCO y el acento del headline del panel va en DORADO
//     PLENO (`text-[hsl(var(--amber))]`): en el canvas oscuro el degradado de
//     `text-gradient` (pensado para superficies claras, dashboard-client) no
//     alcanza contraste AA por el extremo primary — violaba la propia regla
//     del DS; corregido en el pulido v4. El degradado vive en el tile, donde
//     sí resalta. El aside gana además el `ProductMock` glass (ancla visual).

import * as React from 'react'
import { motion, type HTMLMotionProps } from 'framer-motion'
import { Check, MessageSquare, ShoppingBag, Truck } from 'lucide-react'
import {
  EASE_OUT,
  FadeIn,
  StaggerItem,
  StaggerList,
  useReducedMotionDS,
} from '@/components/ui/motion'
import { AuroraCanvas, GRAIN_DATA_URL } from './aurora-canvas'

/** Shell split-screen: formulario (izq) + panel visual de marca (der, ≥lg). */
export function AuthScene({ children }: { children: React.ReactNode }) {
  return (
    <div className="light relative min-h-dvh w-full bg-[#0D1211] lg:grid lg:grid-cols-[minmax(460px,45%)_1fr]">
      {/* Decoración ESTÁTICA <lg — cero animación en móvil: banda aurora
          superior + blob dorado inferior (equilibra el tercio bajo, que sin
          él quedaba plano — verificado en capturas v2). El contenedor lleva
          overflow-hidden para que el blob desbordado no genere scroll. */}
      <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden lg:hidden">
        <div className="absolute inset-x-0 top-0 h-56 bg-[radial-gradient(60%_100%_at_50%_0%,hsl(var(--primary)/0.28),transparent_70%)]" />
        <div className="absolute -bottom-40 -right-24 h-96 w-96 rounded-full bg-[hsl(var(--amber))] blur-3xl opacity-15" />
      </div>
      <main className="relative flex min-h-dvh flex-col justify-center px-6 py-10 sm:px-12 md:py-14 lg:min-h-0 lg:px-16 lg:border-r lg:border-white/5">
        {/* Atmósfera de la columna (pulido v3 + v4): glow radial primary detrás
            del formulario + contra-glow ámbar abajo-izquierda. El contenedor
            overflow-hidden evita que el blob desbordado genere scroll. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
          <div className="absolute inset-0 bg-[radial-gradient(50%_50%_at_50%_45%,hsl(var(--primary)/0.14),transparent_70%)]" />
          <div className="absolute -bottom-24 -left-16 h-72 w-72 rounded-full bg-[hsl(var(--amber))]/10 blur-3xl" />
        </div>
        <AuthEntrance className="relative mx-auto w-full max-w-[400px]">
          {children}
        </AuthEntrance>
      </main>
      <aside className="relative hidden overflow-hidden lg:block">
        <AuroraCanvas />
        <div className="relative flex h-full flex-col p-14">
          {/* Ancla visual del panel: mock glass del producto (solo ≥lg — el
              aside ni se monta en <lg, así que el mock nunca cuesta en móvil). */}
          <div className="flex-1 flex items-center justify-center">
            <ProductMock />
          </div>
          <StaggerList stagger={0.12}>
            <StaggerItem>
              <h2 className="text-3xl lg:text-4xl xl:text-5xl font-semibold tracking-tight text-white">
                Tus ventas por WhatsApp,{' '}
                <span className="text-[hsl(var(--amber))]">en piloto automático.</span>
              </h2>
            </StaggerItem>
            <StaggerItem>
              <p className="mt-3 max-w-md text-sm text-white/60">
                Pedidos, pagos y envíos operados desde una sola consola.
              </p>
            </StaggerItem>
            <StaggerItem>
              {/* Chips glass de capacidades — sin animación propia (la vida la
                  da la aurora); vidrio real: border/blur sobre el canvas. */}
              <div className="flex flex-wrap gap-3 mt-8">
                {[
                  { icon: MessageSquare, label: 'Inbox con IA' },
                  { icon: ShoppingBag, label: 'Pedidos' },
                  { icon: Truck, label: 'Envíos' },
                ].map(({ icon: Icon, label }) => (
                  <span
                    key={label}
                    className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 backdrop-blur-md px-4 py-2 text-xs font-medium text-white/70"
                  >
                    <Icon className="h-3.5 w-3.5" aria-hidden />
                    {label}
                  </span>
                ))}
              </div>
            </StaggerItem>
          </StaggerList>
        </div>
      </aside>
      {/* Grano global sobre TODA la escena (todas las resoluciones) — film
          grain de la puerta del producto; última capa, sin eventos. */}
      <div
        aria-hidden
        className="absolute inset-0 opacity-5 mix-blend-overlay pointer-events-none"
        style={{ backgroundImage: `url("${GRAIN_DATA_URL}")` }}
      />
    </div>
  )
}

/**
 * AuthEntrance — entrada del bloque de formulario: fade + subida y:20→0.
 * Replica LOCAL del patrón FadeIn de `ui/motion.tsx` (mismo EASE_OUT,
 * reduced-motion → initial={false} vía useReducedMotionDS hidratación-seguro)
 * con distancia mayor (20px) — el FadeIn global queda intacto (§4.1).
 */
function AuthEntrance({ children, ...props }: HTMLMotionProps<'div'>) {
  const reduce = useReducedMotionDS()
  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={reduce ? { duration: 0 } : { duration: 0.5, ease: EASE_OUT }}
      {...props}
    >
      {children}
    </motion.div>
  )
}

/**
 * ProductMock — mock glass del inbox de Konvi: el ancla visual del panel
 * (pulido v4, pedido founder). Card flotante con rotate sutil + flotación
 * animada (solo transform; 6s easeInOut; reduced-motion → estática vía
 * useReducedMotionDS — sus estilos son SSR-visibles). Las burbujas entran con
 * stagger sutil del DS. Solo se monta ≥lg (vive en el aside).
 * Copy sintético de demostración — no refleja datos reales de ningún tenant.
 */
function ProductMock() {
  const reduce = useReducedMotionDS()
  return (
    <motion.div
      className="will-change-transform"
      animate={reduce ? undefined : { y: [0, -8, 0] }}
      transition={{ duration: 6, repeat: Infinity, ease: 'easeInOut' }}
    >
      <div className="w-[340px] rotate-[-2deg] rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl shadow-2xl p-4 space-y-3">
        {/* Header: presencia del canal + estado del bot. */}
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-400" aria-hidden />
          <span className="text-xs text-white/60">Cliente · WhatsApp</span>
          <span className="ml-auto text-[10px] text-emerald-300 bg-emerald-400/10 rounded-full px-2 py-0.5">
            bot activo
          </span>
        </div>
        <StaggerList stagger={0.15} className="space-y-3">
          <StaggerItem>
            <div className="max-w-[85%] rounded-xl rounded-bl-sm bg-white/10 px-3 py-2 text-xs text-white/80">
              ¿Tienen la camiseta azul en talla M?
            </div>
          </StaggerItem>
          <StaggerItem>
            <div className="ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-primary/80 px-3 py-2 text-xs text-white">
              ¡Sí! Quedan 4 unidades. ¿Te la separo?
            </div>
          </StaggerItem>
          <StaggerItem>
            <div className="flex items-center gap-2 rounded-lg border border-[hsl(var(--amber))]/30 bg-[hsl(var(--amber))]/10 px-3 py-2 text-xs text-[hsl(var(--amber))]">
              <Check className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Pedido #1042 confirmado · $89.900
            </div>
          </StaggerItem>
        </StaggerList>
      </div>
    </motion.div>
  )
}

/** Cabecera de marca animada: tile degradado + glow, wordmark, tagline (stagger). */
export function AuthBrand({ subtitle }: { subtitle: string }) {
  return (
    <StaggerList className="flex flex-col items-center mb-8" stagger={0.09}>
      <StaggerItem>
        <div className="h-14 w-14 rounded-2xl bg-gradient-to-br from-primary to-[hsl(var(--amber))] flex items-center justify-center mb-4 shadow-lg glow-primary ring-1 ring-white/15">
          <span className="text-2xl font-bold tracking-tight text-white" aria-hidden="true">K</span>
        </div>
      </StaggerItem>
      <StaggerItem>
        <h1 className="text-3xl font-bold text-white tracking-tight">Konvi</h1>
      </StaggerItem>
      <StaggerItem>
        <p className="text-white/60 mt-2 text-sm text-center font-medium">{subtitle}</p>
      </StaggerItem>
    </StaggerList>
  )
}

/** Revelado de la card (tras la marca): fade+lift con pequeño delay. */
export function AuthCardReveal({ children }: { children: React.ReactNode }) {
  return (
    <FadeIn
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1], delay: 0.18 }}
    >
      {children}
    </FadeIn>
  )
}
