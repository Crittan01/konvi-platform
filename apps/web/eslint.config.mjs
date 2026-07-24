import next from 'eslint-config-next'

// ESLint 9 Flat Config (Next 16). `next lint` fue removido en Next 16 → el
// script `lint` invoca el CLI de ESLint contra este archivo.
//
// eslint-config-next 16 exporta un flat config array NATIVO (Linter.Config[])
// que ya agrupa @next/eslint-plugin-next + react + react-hooks +
// typescript-eslint + import + jsx-a11y (equivale a next/core-web-vitals +
// next/typescript). Se importa y spreadea directamente — NO via FlatCompat
// (el bridge legacy choca al serializar el plugin react: "circular structure").
//
// NOTA: NO se agrega `js.configs.recommended` (eslint:recommended). El flat
// config de `next` ya es autocontenido — incluye typescript-eslint recommended,
// que apaga `no-undef`/`no-unused-vars` base (redundantes y con falsos positivos
// sobre React/JSX bajo el runtime automático). Es el mismo patrón que genera
// create-next-app 16. Añadir eslint:recommended reintroducía ~190 falsos
// positivos (`'React' is not defined`, etc.).
const eslintConfig = [
  {
    ignores: ['.next/**', 'node_modules/**', 'public/**', 'next-env.d.ts', 'coverage/**'],
  },
  ...next,
  {
    // Overrides scopeados a TS/TSX: es donde `next` registra los plugins
    // react/@next/next/@typescript-eslint. En flat config los plugins se
    // mergean por-archivo, así que referenciar sus reglas en un objeto sin
    // `files` fallaría sobre .js/.mjs (plugin no registrado ahí).
    files: ['**/*.{ts,tsx}'],
    rules: {
      // Reglas heredadas del .eslintrc.json previo (sin cambios de política).
      'react/no-unescaped-entities': 'off',
      '@next/next/no-img-element': 'off',
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',
      // Reglas NUEVAS en eslint-plugin-react-hooks (bundled en Next 16, era
      // React Compiler) — recomendaciones/purity, no bugs. Un bump de deps no
      // debe forzar refactors de código que funciona → warn (visible),
      // follow-up de calidad. `purity` marca Date.now() en render de Server
      // Components (correcto: timestamp por-request); `set-state-in-effect`
      // marca sync setState en useEffect (patrones de hidratación/sync válidos).
      'react-hooks/set-state-in-effect': 'warn',
      'react-hooks/purity': 'warn',
    },
  },
]

export default eslintConfig
