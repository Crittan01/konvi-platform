import { defineConfig } from 'vitest/config'

// Vitest cubre los tests unitarios co-locados en app/ (lógica pura, p.ej. ADR-0029
// contrato de atributos). Los tests bajo tests/*.mjs usan el runner nativo `node:test`
// (otra convención) y NO los ejecuta vitest.
export default defineConfig({
  test: {
    include: ['app/**/*.test.{ts,tsx}', 'lib/**/*.test.{ts,tsx}'],
    environment: 'node',
  },
})
