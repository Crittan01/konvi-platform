import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// F1 2026-07-04: el harness ahora TAMBIÉN cubre components/** (antes la carpeta
// estaba fuera del include → testear el design system era imposible). El plugin
// de React habilita JSX/TSX en los tests de componentes; default node, los
// tests de componentes declaran su entorno con `// @vitest-environment jsdom`
// (vitest 4 removió environmentMatchGlobs). El ex-huérfano tests/*.test.mjs
// (node:test) se migró a lib/marketplace-badges.test.ts.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname),
    },
  },
  test: {
    include: [
      'app/**/*.test.{ts,tsx}',
      'lib/**/*.test.{ts,tsx}',
      'components/**/*.test.{ts,tsx}',
    ],
    environment: 'node',
    setupFiles: ['./vitest.setup.ts'],
  },
})
