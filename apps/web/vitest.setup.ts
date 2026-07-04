// F1 2026-07-04: matchers de @testing-library/jest-dom para los tests de
// componentes (toBeInTheDocument, toHaveClass, etc.). Solo tiene efecto en
// tests jsdom; los de node lo cargan sin costo.
import '@testing-library/jest-dom/vitest'
