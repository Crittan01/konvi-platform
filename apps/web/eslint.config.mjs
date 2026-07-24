import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { FlatCompat } from '@eslint/eslintrc'
import js from '@eslint/js'

// Migración a ESLint Flat Config (Next 16 / ESLint 9).
// eslint-config-next 16 requiere ESLint >=9 y `@next/eslint-plugin-next` ya
// defaultea a flat config. `next lint` fue removido en Next 16 → el script
// `lint` invoca el CLI de ESLint directamente contra este archivo.
//
// FlatCompat traduce los presets legacy (`extends`) al formato flat, preservando
// exactamente lo que declaraba el antiguo `.eslintrc.json`:
//   eslint:recommended + next/core-web-vitals + next/typescript (≈ @typescript-eslint/recommended).
const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const compat = new FlatCompat({
  baseDirectory: __dirname,
  recommendedConfig: js.configs.recommended,
})

const eslintConfig = [
  {
    ignores: ['.next/**', 'node_modules/**', 'public/**', 'next-env.d.ts', 'coverage/**'],
  },
  ...compat.extends('eslint:recommended', 'next/core-web-vitals', 'next/typescript'),
  {
    rules: {
      // Reglas heredadas del .eslintrc.json previo (sin cambios de política).
      'react/no-unescaped-entities': 'off',
      '@next/next/no-img-element': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
]

export default eslintConfig
