# Run UAT — Guía REAL Aveonline (B1) — 2026-08-03/04

**Resultado: GUÍA REAL GENERADA Y VERIFICADA EN AVEONLINE ✅ — `numguia 86732771636` (COORDINADORA MERCANTIL), estado `GENERADA`. Anulación vía API NO soportada por Aveonline ⚠️ → anular manual en panel (ver §5).**

| Campo | Valor |
|---|---|
| Fecha | 2026-08-03 ~23:50 → 2026-08-04 00:20 UTC |
| Autorización | Founder — 1 guía real facturable (B1) |
| Stack | API local uvicorn `:8011` (código `develop` + fix) con env de **prod** (`.env.prod`) + `AVEONLINE_GENERATE_REAL_GUIDES=true` solo en este proceso |
| Tenant | `KAIU Living Natural` = `0fb0777e-f3e4-48c7-89bf-a25aa201c0c9` (konvi-prod, pre-launch) |
| Ruta | Bogotá D.C. → Bogotá D.C. (envío local al propio `shipping_origin`, práctica estándar de certificación con carrier) |
| Endpoint | `POST /api/v1/integrations/aveonline/guide-dry-run` con `{"simulate": false}` |
| Guía | **86732771636** · COORDINADORA MERCANTIL (rate_id 1009, Mensajería, $7.530 COP) · `simulated: false` (REAL) |
| Costo en riesgo | $7.530 COP (1 guía) |

## 1. El endpoint estaba roto contra el schema actual — fix previo obligatorio

`aveonline_guide_dry_run` pedía a `tenants` columnas planas `shipping_origin_city/state/dane/address/nit/phone/email` + `idagente` que **no existen** (PostgREST 400). El origen vive en `tenants.shipping_origin` (jsonb) y el `idagente` en las credenciales de la integración.

Cambios (mínimos, alineados al flujo real `wompi_webhook._generate_shipping_guide_async`):

| Archivo | Cambio |
|---|---|
| `services/api/routers/integrations.py:668-707` | Select → `name, shipping_origin, telefono_contacto, email_contacto, nit`; validación "origin completo" (city+street → 422, espejo de `wompi_webhook.py:1886-1892`); `origin` desde jsonb con `to_aveonline_city_format` + `dane_code`; `sender` desde jsonb + columnas planas; `idagente` desde `client._load_credentials()` (`idagente \|\| asesor_logistico`, patrón `aveonline_client.py:422`) solo para diagnostics |
| `services/api/routers/integrations.py:596-603` | Deps dual-auth (A0.2c): `get_tenant_id_internal_or_user` / `get_role_internal_or_user` / `get_service_client_internal_or_user` — antes JWT-only, la UAT service-to-service no podía autenticar |
| `services/api/main.py:281-294` | Router `integrations`: gate MFA → `enforce_mfa_internal_or_user` (NO-OP para internal-secret; para JWT de usuario exige AAL2 igual que antes). Sin esto el gate router-level rechazaba la llamada interna con 401 |
| `tests/test_aveonline_guide_dry_run.py` | **Nuevo** — 5 tests: select pide jsonb (regresión), payload sender/origin como flujo real, 422 sin origin completo, fail-safe simulate, NO_CARRIER_SELECTED |

Verificación: `pytest tests/test_aveonline_guide_dry_run.py` → **5 passed**; suites relacionadas (`test_whatsapp_credentials_endpoint`, `test_meli_oauth_state`, `test_wompi_webhook_money_paths`, `test_m15_rate_limit_wiring`, `test_b0_mfa_gateway_enforce`, `test_mfa_gate_asgi_401`, `test_b0_mfa_mandatory_enrollment`) → **158 passed**; `ruff check` del endpoint sin errores nuevos (C901 preexistente baja 14→13); `py_compile` OK.

## 2. Seed UAT en prod (filas marcadas, conservadas como evidencia)

Script: `scripts/uat/_seed_aveonline_guia_real.py` (lee `.env.prod` sin imprimir; `env_guard` → `prelaunch`, aviso auditable).

- **Cotización REAL** (cotizarDoble) origen=destino=shipping_origin KAIU — 5 opciones:

  | Carrier | rate_id | Precio |
  |---|---|---|
  | **COORDINADORA MERCANTIL** | **1009** | **$7.530** ← elegida (más barata) |
  | SERVIENTREGA | 33 | $8.600 |
  | ENVIA | 29 | $8.750 |
  | INTERRAPIDISIMO | 1016 | $9.500 |
  | TCC SA | 1010 | $16.400 |

- `conversations` `07ce3483-…` (closed+archivada) · `contacts` `53eb8f30-…` "UAT Guía Real 2026-08-03" (dirección = shipping_origin, CC 999888777 de prueba) · `orders` `1d2dadbe-…` (confirmed, $15.000, notes 'UAT guía real — eliminar') · `conversation_carts` `60f8a76b-…` (converted → orden, `shipping_meta` canónico con rate_id 1009 + weight_inputs + quoted_options).
- `tenant_shipping_provider_config.real_guides_enabled`: estaba **false** → subido a **true** temporalmente (techo per-tenant BLOQUE B) y **revertido a false en cleanup** (verificado).

## 3. Llamada al endpoint (guía real)

```
POST :8011/api/v1/integrations/aveonline/guide-dry-run
Headers: X-Internal-Service-Secret: *** + X-Tenant-Id: 0fb0777e…
Body: {"order_id": "1d2dadbe-0ddb-4749-a148-530b7f2926a5", "simulate": false}
```

**Intento 1 → error de validación Aveonline (sin cargo):** `status=error — "El campo dsnit es inválido. Debe ser numérico, tener al menos 5 dígitos y ser mayor a 10000."` — el contact UAT no tenía `document_number`. Se corrigió el dato (CC 999888777) y se reintentó. *Observación:* el endpoint valida name/phone pero no documento; Aveonline lo exige. No se cambió código por esto (el flujo real lo recolecta en PII_COLLECTION), queda anotado en §6.

**Intento 2 → HTTP 200, guía REAL generada** (respuesta resumida; `raw` completo incluye rótulo PDF en base64 y URLs de impresión, omitidos aquí; ningún token/secret en la respuesta):

```json
{
  "ok": true,
  "result": {
    "ok": true,
    "tracking_number": "86732771636",
    "label_url": "https://app.aveonline.co/.../imprimir.rotulo.envia_110_120v2.php?...",
    "tracking_url": "https://app.aveonline.co/assets/data/coordinadora/rotulos/RotuloCoordinadora-86732771636.pdf",
    "carrier_name": "COORDINADORA MERCANTIL",
    "simulated": false,
    "raw": {"status": "ok", "message": "proceso correcto",
            "resultado": {"guia": {"codigo": "0", "mensaje": "Guia 86732771636 Generada",
                                   "numguia": "86732771636", "idtransportador": 1009, …}}}
  },
  "diagnostics": {
    "tenant_idagente": "6135",
    "carrier_selected": "COORDINADORA MERCANTIL",
    "rate_id": "1009",
    "origin": {"dane": "11001", "city": "BOGOTA(CUNDINAMARCA)"},
    "destination": {"dane": "11001", "city": "Bogotá D.C."},
    "simulate": false, "simulate_requested": false,
    "warning_idagente_missing": false
  }
}
```

## 4. Verificación en Aveonline

`obtenerEstadoAuth` (`AveonlineClient.get_estado`, guía 86732771636):

```json
{"ok": true, "message": "registros encontrados", "guias": [{"estado": "GENERADA"}]}
```

La guía existe en el sistema Aveonline, estado `GENERADA`, nunca recogida.

## 5. Anulación — NO soportada vía API (diagnóstico exacto)

`AveonlineClient.cancel_guide` (`tipo=cancelarGuia` al endpoint nal v1.0) falló, y todas las variantes documentadas/intuibles también:

| Intento | Resultado |
|---|---|
| `cancelarGuia` v1.0 (impl. actual: `idempresa`+`numguia`) | `{"status":"error","message":"parametro incorrecto"}` |
| Variante `id`+`guia` / `idempresa`+`guia` | idem `"parametro incorrecto"` |
| `POST https://api.aveonline.co/api/v2.0/guias/cancelarGuia` (URL del sketch del dossier) | **HTTP 404** — la ruta no existe |
| `eliminarRelacionEnvios` nal **v2.0** (`Authorization: <jwt v1>`) | **HTTP 401** `"Token no valido" / "Incorrect key for this algorithm"` — el endpoint v2 existe pero exige token v2 que la plataforma no implementa |

Esto **confirma el dossier §8.2** (`docs/research/aveonline-dossier.md:692`): *"NO existe endpoint público para anular una guía individual ya generada"* y el docstring del cliente (`aveonline_client.py:846-860`): cancelación best-effort → **escalar a operador**. Además no tenemos `numeroRelacionEnvios` (generarGuia2 no lo retorna) ni auth v2.

**Acción pendiente (founder/operador):** anular la guía **86732771636** desde el panel Aveonline (app.aveonline.co) o con el asesor, para revertir el cargo de $7.530. La guía quedó en `GENERADA`, sin recoger — según §8.2 una guía no manifestada/recogida no se despacha, pero el cobro depende del ciclo de facturación semanal: **confirmar la anulación manual**.

## 6. Limpieza ejecutada

- Orden `1d2dadbe-…` → `status=cancelled`, `cancelled_at` estampado, notes: *"UAT guía real 2026-08-03 — guía 86732771636 (COORDINADORA) generada OK; anulación vía API NO soportada → anular manual en panel Aveonline."* (filas UAT conservadas como evidencia, contacto marcado "no contactar").
- `real_guides_enabled` → **false** (valor previo, verificado con SELECT).
- uvicorn local :8011 terminado. `render.yaml` **sin tocar** (el flip en Render lo aplica el orquestador).

## 7. Conclusión sobre el flip `AVEONLINE_GENERATE_REAL_GUIDES`

**El flip es SEGURO de aplicar.** Evidencia:

1. El path completo de producción funciona contra el schema real: auth Aveonline (JWT refresh via Vault RPC), cotización real con 5 carriers, generación de guía **real** con payload canónico (DANE 11001, city `BOGOTA(CUNDINAMARCA)`, sender desde jsonb, idagente 6135 desde credenciales), y verificación de estado.
2. El doble fail-safe opera como fue diseñado: con el master off el endpoint forzó `simulate=True` en tests; para la guía real se necesitaron AMBOS toggles (master env + `real_guides_enabled` per-tenant) — ninguno quedó activo en prod tras la UAT (master nunca se tocó en Render; el flag per-tenant se revirtió).
3. La respuesta de Aveonline es parseada correctamente por el cliente (`ok/tracking_number/label_url/tracking_url/carrier_name/simulated`).

**Caveats conocidos (no bloquean el flip, conviene anotarlos):**

- **Anulación de guías es manual** (panel/asesor) — el dossier ya lo sabía; hoy quedó *probado en vivo*. Si se habilitan guías reales, toda cancelación de orden con guía `labeled` escalará a `manual_operator_call` (path ya implementado en `order_cancellation.py:819`).
- El endpoint dry-run no valida `document_number` del contact antes de llamar a Aveonline (error `dsnit` claro y sin cargo, pero cuesta un round-trip). Mejora opcional, no hecha aquí (cambio mínimo).
- La guía de esta UAT (`86732771636`) debe anularse manual (§5).
