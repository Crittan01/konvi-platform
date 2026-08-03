"use client"

import * as React from "react"
import useEmblaCarousel, { type UseEmblaCarouselType } from "embla-carousel-react"

import { cn } from "@/lib/utils"

// Carousel — wrapper DS (Kaiu) sobre embla-carousel-react (Spec WOW §4.5;
// deuda §1.10). Versión acotada al uso del producto: viewport + items + dots
// con aria-label (sin flechas — el swipe/drag es la interacción móvil).
// El gesto de drag es dirigido por el usuario (exento de prefers-reduced-motion).

type CarouselApi = UseEmblaCarouselType[1]
type CarouselOptions = NonNullable<Parameters<typeof useEmblaCarousel>[0]>

interface CarouselContextValue {
  carouselRef: ReturnType<typeof useEmblaCarousel>[0]
  api: CarouselApi
}

const CarouselContext = React.createContext<CarouselContextValue | null>(null)

function useCarousel(): CarouselContextValue {
  const ctx = React.useContext(CarouselContext)
  if (!ctx) throw new Error("useCarousel requiere <Carousel> en el árbol.")
  return ctx
}

const Carousel = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement> & { opts?: CarouselOptions }
>(({ opts, className, children, ...props }, ref) => {
  const [carouselRef, api] = useEmblaCarousel(opts)
  return (
    <CarouselContext.Provider value={{ carouselRef, api }}>
      <div
        ref={ref}
        className={cn("relative", className)}
        role="region"
        aria-roledescription="carrusel"
        {...props}
      >
        {children}
      </div>
    </CarouselContext.Provider>
  )
})
Carousel.displayName = "Carousel"

const CarouselContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => {
  const { carouselRef } = useCarousel()
  return (
    <div ref={carouselRef} className="overflow-hidden">
      <div ref={ref} className={cn("flex", className)} {...props} />
    </div>
  )
})
CarouselContent.displayName = "CarouselContent"

const CarouselItem = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    role="group"
    aria-roledescription="diapositiva"
    className={cn("min-w-0 shrink-0 grow-0", className)}
    {...props}
  />
))
CarouselItem.displayName = "CarouselItem"

/** Dots indicadores de posición con navegación por tap y aria-label. */
function CarouselDots({ className, labels }: { className?: string; labels?: string[] }) {
  const { api } = useCarousel()
  const [selected, setSelected] = React.useState(0)
  const [count, setCount] = React.useState(0)

  React.useEffect(() => {
    if (!api) return
    const onSelect = () => setSelected(api.selectedScrollSnap())
    const onReInit = () => {
      setCount(api.scrollSnapList().length)
      onSelect()
    }
    onReInit()
    api.on("select", onSelect)
    api.on("reInit", onReInit)
    return () => {
      api.off("select", onSelect)
      api.off("reInit", onReInit)
    }
  }, [api])

  if (count <= 1) return null

  return (
    <div className={cn("flex justify-center gap-1.5 pt-3", className)}>
      {Array.from({ length: count }).map((_, i) => (
        <button
          key={i}
          type="button"
          aria-label={labels?.[i] ? `Ir a ${labels[i]}` : `Ir a la tarjeta ${i + 1} de ${count}`}
          aria-current={i === selected ? "true" : undefined}
          onClick={() => api?.scrollTo(i)}
          className={cn(
            "h-1.5 rounded-full transition-all",
            i === selected
              ? "w-4 bg-primary"
              : "w-1.5 bg-muted-foreground/30 hover:bg-muted-foreground/50",
          )}
        />
      ))}
    </div>
  )
}
CarouselDots.displayName = "CarouselDots"

export { Carousel, CarouselContent, CarouselItem, CarouselDots, useCarousel, type CarouselApi, type CarouselOptions }
