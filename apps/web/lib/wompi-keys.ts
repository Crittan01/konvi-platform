/**
 * Validación par llave/ambiente Wompi (S0.2 — plan segregación 2026-08-16).
 *
 * Wompi emite llaves con prefijo por ambiente (doc oficial ambientes-y-llaves,
 * verificada 2026-08-16): sandbox → `prv_test_` / `test_events_`; producción →
 * `prv_prod_` / `prod_events_`. Elegir un ambiente y pegar llaves del otro es
 * un error de configuración posible que mezclaría transacciones de prueba con
 * datos reales — exactamente lo que la doc de Wompi advierte evitar al exigir
 * una URL de eventos distinta por ambiente.
 *
 * Defensa complementaria: en reposo la flaggea scripts/check_env_data_mix.py
 * (meta.environment) y en runtime el webhook (S0.1, environment del payload).
 * Esta validación la corta EN EL ORIGEN: el formulario de guardado.
 */

export type WompiEnvironment = 'sandbox' | 'production'

const EXPECTED_PREFIXES: Record<WompiEnvironment, { privateKey: string; eventsKey: string }> = {
  sandbox: { privateKey: 'prv_test_', eventsKey: 'test_events_' },
  production: { privateKey: 'prv_prod_', eventsKey: 'prod_events_' },
}

export type WompiKeyCheck = { ok: true } | { ok: false; error: string }

/**
 * Verifica que las llaves correspondan al ambiente elegido. Fail-closed por
 * campo: si una llave no trae el prefijo de SU ambiente, se rechaza el guardado
 * completo (un par a medias deja la integración rota de todas formas).
 */
export function wompiKeysMatchEnvironment(
  environment: WompiEnvironment,
  privateKey: string,
  eventsKey: string,
): WompiKeyCheck {
  const expected = EXPECTED_PREFIXES[environment]
  const envLabel = environment === 'production' ? 'producción' : 'sandbox'
  if (!privateKey.startsWith(expected.privateKey)) {
    return {
      ok: false,
      error: `La Llave Privada no es de ${envLabel} (debe empezar con ${expected.privateKey}). Revisa el ambiente seleccionado o la llave pegada.`,
    }
  }
  if (!eventsKey.startsWith(expected.eventsKey)) {
    return {
      ok: false,
      error: `La Llave de Eventos no es de ${envLabel} (debe empezar con ${expected.eventsKey}). Revisa el ambiente seleccionado o la llave pegada.`,
    }
  }
  return { ok: true }
}
