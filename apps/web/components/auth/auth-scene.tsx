'use client'

// Escena compartida de auth (login · mfa · forgot · set-password) — Track 7 T7.1.
//
// El canvas oscuro fijo del patrón auth (`.light` forzado — NO se toca, §1.8 del
// DS) gana la coreografía de entrada y el ambiente que la directiva founder pide
// ("login animado y memorable"), sin mover NI UN token:
//   - Textura grano SVG INLINE (sin dependencia de terceros en la puerta del
//     producto — el login ya la traía; mfa usaba `grainy-gradients.vercel.app`,
//     vector de supply-chain que esta escena elimina).
//   - Aurora ambiental ESTÁTICA (blobs primary/amber con blur, solo tokens Kaiu;
//     sin animación → reduced-motion trivialmente seguro, §4.1.1).
//   - Coreografía vía wrappers del DS (StaggerList/FadeIn — `useReducedMotion`
//     uniforme; prohibido `motion` crudo, §4.1).
//   - Logo real: tile degradado primary→amber con `glow-primary` + letterform K
//     (reemplaza el "Logo mock / Brand" explícito). El wordmark va BLANCO: en el
//     canvas oscuro el degradado de `text-gradient` (pensado para superficies
//     claras, dashboard-client) no alcanza contraste AA por el extremo primary;
//     el degradado vive en el tile, donde sí resalta.

import * as React from 'react'
import { FadeIn, StaggerItem, StaggerList } from '@/components/ui/motion'

// Misma textura inline que traía el login (feTurbulence, sin red).
const GRAIN_DATA_URL =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E"

/** Canvas oscuro de auth + grano + aurora estática + columna centrada 420px. */
export function AuthScene({ children }: { children: React.ReactNode }) {
  return (
    <div className="light relative flex h-screen w-full items-center justify-center overflow-hidden bg-[#131A19]">
      {/* Textura grano — SVG inline (cero dependencias runtime de terceros). */}
      <div
        aria-hidden="true"
        className="absolute inset-0 opacity-5 mix-blend-overlay pointer-events-none"
        style={{ backgroundImage: `url("${GRAIN_DATA_URL}")` }}
      />
      {/* Aurora ambiental estática (tokens Kaiu, reduced-motion seguro al no animarse). */}
      <div
        aria-hidden="true"
        className="absolute -top-32 left-1/2 h-80 w-[36rem] -translate-x-1/2 rounded-full bg-primary/25 blur-3xl opacity-40 pointer-events-none"
      />
      <div
        aria-hidden="true"
        className="absolute -bottom-40 -right-24 h-96 w-96 rounded-full bg-[hsl(var(--amber))] blur-3xl opacity-15 pointer-events-none"
      />
      <div className="relative w-full max-w-[420px] p-6 sm:p-8">
        {children}
      </div>
    </div>
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
