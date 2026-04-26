'use client'

import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'

interface Props {
  hasResult: boolean
}

export function TeamUrlCleaner({ hasResult }: Props) {
  const router   = useRouter()
  const pathname = usePathname()

  useEffect(() => {
    if (!hasResult) return
    const t = setTimeout(() => router.replace(pathname), 4000)
    return () => clearTimeout(t)
  }, [hasResult, router, pathname])

  return null
}
