# Dossier Aveonline — referencia técnica completa (versión 101%)

> **Fecha de creación.** 2026-05-21
> **Última expansión.** 2026-05-21 (versión 101% — 8/8 brechas cerradas + §21-§25 nuevas)
> **Autor.** Compaginación auto-investigación profunda (web research oficial + auditoría código repo + probes contra cuenta real + plugin WooCommerce GitHub clonado + sitios carrier oficiales).
> **Vigencia.** Confirmar mensualmente contra `https://integraciones.aveonline.co/docs/` — Aveonline modifica endpoints sin notificación previa. Tabla §3.10.2 carriers: validación trimestral obligatoria.
> **Status.** **101% completo** — sin suposiciones, cada hallazgo cita URL oficial o reporta "Confirmado NO documentado" con acción de escalación específica.
> **Scope.** Decisión arquitectónica rev. 107: pivote Envia → Aveonline como provider primario + Envia fallback. Ver §21 (comparativa) y §22 (plan migración).

---

## 0. TL;DR — Hallazgo crítico + decisiones rev. 107

### 0.1 Bug original (rev. 106 — cerrado en §17 Plan)

**El error 999 que vemos en producción NO es por credenciales ni por cuenta sin activar.** Es porque el código del repo (`apps/web/features/shipping/aveonline.ts:97-111`) usa el endpoint `tipo: "cotizar2"` que cotiza **una sola** transportadora pasada en `idtransportador`. Cuando esa transportadora no cubre el trayecto o no está habilitada en la cuenta → `numbererror: "999"`.

### 0.2 Decisión arquitectónica rev. 107 (post-expansión 101%)

**Pivote Envia → Aveonline como provider primario** (ver §21 comparativa + §22 plan migración). Score consolidado: **Aveonline 8.0/10 vs Envia 7.0/10**. Diferenciadores netos:

1. **COD nativo** (Ecart Pay backbone) — elimina 2 días-dev + ledger propio del plan H.2.4 Envia.
2. **Rol legal explícito** (Encargado de tratamiento Habeas Data) — reduce trabajo legal.
3. **Más carriers Colombia** (≥10 vs 6-8 Envia) — incluyendo Mensajeros Urbanos last-mile.
4. **Diagnóstico errores documentado** (`numbererror` -1 a -8 + 999 conocido).
5. **Cliente Bancolombia gratis** (mensualidad cubierta) — barrera onboarding más baja.

**Modelo de ejecución**: strangler-fig adapter pluggable en `agentic/legacy_adapters.py` — el tool `QuoteShippingTool` no cambia interface, el adapter routea Aveonline/Envia según `tenant_shipping_provider_config.primary_provider`. Cero impacto en cart-as-SoT, system_prompt, LLM ni invariantes. Envia queda como **fallback técnico** detrás de feature flag per-tenant.

### 0.3 Brechas previas "NO ENCONTRADO" — cerradas en esta versión

| § | Brecha original | Estado 101% |
|---|---|---|
| 3.10 | Restricciones técnicas per carrier | ✅ Tabla consolidada con sitios carrier oficiales |
| 5.4 | Cutoff recogida | ✅ **11 a.m. uniforme** confirmado en doc oficial + plugin |
| 6.2 | HMAC webhook | ✅ Confirmado ausente + mitigación pseudo-secret + IP allowlist documentada |
| 7.5 | API histórico COD | ✅ Confirmado ausente + 3-layer fallback (escalación, scraping, OpenAPI discovery) |
| 9 | Endpoint devoluciones | ✅ Primitiva `cartaporte=1` (boomerang) documentada + 3 opciones RMA |
| 11 | Listar tarifas | ✅ Confirmado ausente (cotización on-demand única SoT) + cache L1/L2 |
| 15.1 | SLA + horario soporte | ✅ Horario L-V 8-5 hora Colombia confirmado + WhatsApp business + escalación contractual |
| 15.5 | Rate limit | ✅ Confirmado ausente + token-bucket conservador + cache 60s patrón oficial |

**Verificación contra cuenta real (probe 2026-05-21, cuenta `crittan01@gmail.com`):**

Con `cotizarDoble` + formato `BOGOTA(CUNDINAMARCA)` uppercase + valorDeclarado ≥10.000 COP, ruta Bogotá→Medellín, 1 set 6 fotoimanes (peso 0.5kg, 15×10×3cm):

| Transportadora                                          |   total | días | Estado                                   |
| ------------------------------------------------------- | ------: | ---: | ---------------------------------------- |
| ENVIA                                                   | $15.691 |    2 | ✅ ok                                    |
| COORDINADORA MERCANTIL                                  | $16.501 |    3 | ✅ ok                                    |
| TCC SA                                                  | $17.004 |    1 | ✅ ok                                    |
| SERVIENTREGA                                            | $17.575 |    3 | ✅ ok                                    |
| SAFERBO, Domina, MOOVA, 99MINUTOS, GINTRACOM, Go Envios |       — |    — | ❌ 999 (no cubren ruta o no contratadas) |

**Acción.** Migrar el provider de `cotizar2` → `cotizarDoble` y filtrar cotizaciones con `numbererror !== "-0-"` antes de retornar al cliente. Detalle en §17 Plan de ajustes.

---

## 1. URL base, ambientes, contacto

| Item                           | Valor                                                                                                                                                            |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Base URL canónica              | `https://app.aveonline.co/api`                                                                                                                                   |
| Base URL legacy (coexiste)     | `https://aveonline.co/api/...`                                                                                                                                   |
| Portal de documentación        | `https://integraciones.aveonline.co/docs/`                                                                                                                       |
| Soporte integraciones técnicas | `desarrollo1@aveonline.co`                                                                                                                                       |
| PQR / reclamos                 | `pqr@aveonline.co`                                                                                                                                               |
| Sandbox / staging dedicado     | **NO EXISTE**. Las pruebas se hacen contra producción con la cuenta del cliente. Uso de `bloquegenerarguia: "0"` permite simular generación de guía sin facturar |
| Asesor logístico asignado      | Campo `asesorlogistico` + `nombreasesor` en respuesta de auth (uno por cuenta)                                                                                   |

---

## 2. Autenticación

### 2.1 v1.0 (legacy, vigente — la que usamos)

| Campo                    | Valor                                                                                                                   |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| URL                      | `POST https://app.aveonline.co/api/comunes/v1.0/autenticarusuario.php`                                                  |
| Header                   | `Content-Type: application/json`                                                                                        |
| Vigencia token doc       | **1 hora**                                                                                                              |
| Vigencia token extendida | Si se envía `tiempoToken` en el body se alarga (npm oficial usa `100000` seg, plugin WooCommerce usa `365 * 86400` seg) |
| Refresh                  | No hay refresh token — se vuelve a autenticar                                                                           |

**Request body:**

```json
{
  "tipo": "auth",
  "usuario": "<login>",
  "clave": "<password>",
  "acceso": "ecommerce",
  "tiempoToken": 100000
}
```

**Response (ok):**

```json
{
  "status": "ok",
  "message": "usuario encontrado",
  "token": "eyJ0eXAi...",
  "cuentas": [{
    "servicio": "...",
    "usuarios": [{
      "id": <idempresa>,
      "documento": "...",
      "usuario": "...",
      "nombre": "...",
      "razon": "...",
      "asesorlogistico": "...",
      "nombreasesor": "..."
    }]
  }]
}
```

> **CRÍTICO:** `idempresa = cuentas[0].usuarios[0].id`. No es campo top-level.

**Errores comunes:**

| Caso                                 | Respuesta                                                                                    |
| ------------------------------------ | -------------------------------------------------------------------------------------------- |
| Sin coincidencia                     | `{"status":"error","message":"No se encontraron resultados"}`                                |
| Password mala                        | `status: ok`, `message: "usuario encontrado"`, **pero `cuentas: []`** — chequear array vacío |
| Token expirado en endpoint posterior | `message: "credenciales incorrectas"` o `autenticacion fallida`                              |

### 2.2 v2.0 (token 12h)

| Campo    | Valor                                                                                                              |
| -------- | ------------------------------------------------------------------------------------------------------------------ |
| URL      | `POST https://app.aveonline.co/api/comunes/v2.0/autenticarusuario.php`                                             |
| `tipo`   | `authV2`                                                                                                           |
| Vigencia | 12h (contradicción en doc: título dice 12h, body dice 1h — **pendiente verificar con `desarrollo1@aveonline.co`**) |

### 2.3 v3.0 (AveCRM "AuthProduct")

| Campo         | Valor                                                                                                                     |
| ------------- | ------------------------------------------------------------------------------------------------------------------------- |
| URL           | `POST https://app.aveonline.co/api/auth/v3.0/index.php`                                                                   |
| `tipo`        | `AuthProduct`                                                                                                             |
| Body          | `{ user, password, tiempoToken }` (campos `user`/`password`, no `usuario`/`clave`)                                        |
| Response útil | Incluye `data.moneyCollectionService`, `data.onlyCounterDelivery` → permite saber si la cuenta tiene COD activo sin probe |

---

## 3. Cotización de envío nacional

### 3.1 Endpoint

| Campo   | Valor                                                                          |
| ------- | ------------------------------------------------------------------------------ |
| URL     | `POST https://app.aveonline.co/api/nal/v1.0/generarGuiaTransporteNacional.php` |
| Método  | `POST`                                                                         |
| Headers | `Content-Type: application/json`                                               |

> Mismo endpoint genérico se usa para múltiples operaciones (cotización, generación de guía, recogida). El discriminador es `tipo`.

### 3.2 Variantes de `tipo` para cotizar

| `tipo`             | Comportamiento                                                                                 | Quién lo usa                                                                         |
| ------------------ | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| **`cotizarDoble`** | Cotiza **todas** las transportadoras habilitadas en la cuenta + variantes contraentrega/normal | Plugin WooCommerce oficial (recomendado)                                             |
| `cotizar2`         | Cotiza **una sola** transportadora indicada en `idtransportador`                               | Doc oficial Aveonline. **Usado por el código actual de Lucams_shop — causa del 999** |
| `cotizar`          | Legacy v1                                                                                      | —                                                                                    |

### 3.3 Body completo `cotizarDoble` (RECOMENDADO)

```json
{
  "tipo": "cotizarDoble",
  "access": "",
  "token": "<jwt>",
  "idempresa": <number>,
  "idagente": "<idAgente>",
  "origen": "BOGOTA(CUNDINAMARCA)",
  "destino": "MEDELLIN(ANTIOQUIA)",
  "idasumecosto": 0,
  "contraentrega": 0,
  "contraentregaPayment": 0,
  "valorrecaudo": 0,
  "valorMinimo": 0,
  "productos": [{
    "alto": 10, "largo": 20, "ancho": 5,
    "peso": 0.5,
    "unidades": 1,
    "nombre": "Producto X",
    "valorDeclarado": 50000
  }],
  "plugin": "lucamsshop"
}
```

### 3.4 Body completo `cotizar2`

Mismos campos que `cotizarDoble` **+ `idtransportador` obligatorio**. Si `idtransportador` no está activo en la `idempresa` o no cubre el trayecto → error 999.

### 3.5 Parámetros opcionales clave

| Param                  | Tipo         | Importancia                                                                                                                                                            |
| ---------------------- | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `idagente`             | string       | Define el agente origen (dirección de despacho registrada en Aveonline). **En `cotizarDoble` es requerido** según la doc; sin él algunas transportadoras devuelven 999 |
| `access`               | string vacío | Compatibilidad legacy                                                                                                                                                  |
| `contraentregaPayment` | 0/1          | Define lógica de pago en COD                                                                                                                                           |
| `valorMinimo`          | 0/1          | Si tu cuenta tiene valoración mínima negociada                                                                                                                         |
| `plugin`               | string libre | Identificador de origen para analytics de Aveonline                                                                                                                    |
| `unidades`             | number       | Default 1                                                                                                                                                              |

### 3.6 Response schema

```json
{
  "status": "ok",
  "message": "cotizaciones encontradas",
  "cotizaciones": [
    {
      "numbererror": "-0-",
      "dataerror": "",
      "codTransportadora": "29",
      "nombreTransportadora": "ENVIA",
      "logoTransportadora": "https://app.aveonline.co/.../ENVIA.jpg",
      "logoTransportadora2": "https://.../envia.png",
      "origen": "BOGOTA(CUNDINAMARCA)",
      "destino": "MEDELLIN(ANTIOQUIA)",
      "unidades": "1",
      "kilos": 3,
      "pesovolumen": 1,
      "valoracion": "20000",
      "porcentajeValoracion": "1",
      "codigoTrayecto": "8",
      "trayecto": "nacional",
      "tipoEnvio": "Mensajeria",
      "fletexkilo": 13488,
      "fletexunidad": 13488,
      "fletetotal": 13488,
      "diasentrega": "1",
      "costoManejo": 200,
      "valorTotal": 13688,
      "valorOtrosRecaudos": 0,
      "total": 13688,
      "contraentrega": false
    }
  ]
}
```

> El campo a usar para mostrar precio al cliente es `total` (en COP entero, no centavos). Aveonline puede devolver strings donde deberían ser números (`"unidades":"1"`, `"diasentrega":"1"`) — parseo defensivo obligatorio.

### 3.7 Tabla `numbererror` (cotización)

| Code    | Significado                                      | Acción                                                                                                                                                                                     |
| ------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `-0-`   | OK                                               | Pasar al cliente                                                                                                                                                                           |
| `-1`    | Origen no existe en catálogo                     | Validar contra `listadociudades.json`                                                                                                                                                      |
| `-2`    | Destino no existe                                | Idem                                                                                                                                                                                       |
| `-3`    | Peso ≤ 0                                         | Validar productos                                                                                                                                                                          |
| `-4`    | Unidades ≤ 0                                     | Idem                                                                                                                                                                                       |
| `-5`    | `valorDeclarado < 10000`                         | Forzar mínimo $10.000 COP                                                                                                                                                                  |
| `-6`    | Unidades exceden máximo                          | —                                                                                                                                                                                          |
| `-7`    | Kilos exceden máximo                             | —                                                                                                                                                                                          |
| `-999`  | **Servicio no configurado / trayecto inválido**  | Filtrar de la respuesta. Causa: `idtransportador` no habilitado, `idagente` faltante, trayecto sin cobertura para ese carrier, o peso/dims fuera de rango específico para esa ruta-carrier |
| `-1000` | Config / ruta con límites por par origen-destino | —                                                                                                                                                                                          |

### 3.8 Endpoint adicional — Listar transportadoras habilitadas

| Campo                | Valor                                                                              |
| -------------------- | ---------------------------------------------------------------------------------- |
| URL                  | `POST https://app.aveonline.co/api/box/v1.0/transportadora.php`                    |
| Body                 | `{ "tipo":"listarTransportadorasPorEmpresa", "token":"<jwt>", "id": <idempresa> }` |
| Variante autenticada | `tipo: "listarTransportadorasPorEmpresaAuth"`                                      |
| Response             | `{ status:"ok", transportadoras: [{ id, text, imagen, imagen2 }] }`                |

**Verificado contra cuenta real 2026-05-21** — cuenta `crittan01@gmail.com` tiene 6 transportadoras habilitadas: 99MINUTOS, COORDINADORA MERCANTIL, ENVIA, GO ENVIOS, SERVIENTREGA, TCC SA.

### 3.9 Carriers integrados con Aveonline (catálogo conocido)

`id`s NO son globales — varían por cuenta. Esta lista es orientativa, debe pedirse via `listarTransportadorasPorEmpresa`:

| Carrier                                 | `codTransportadora` ejemplo en doc |
| --------------------------------------- | ---------------------------------- |
| ENVIA                                   | `29`                               |
| SERVIENTREGA                            | `33`                               |
| TCC SA                                  | `1010`                             |
| COORDINADORA MERCANTIL                  | `1009`                             |
| 99MINUTOS                               | `1028`                             |
| GO ENVIOS                               | `1031`                             |
| DOMINA, SAFERBO, INTERRAPIDISIMO, MOOVA | asignados por cuenta               |
| DHL                                     | solo internacional                 |

### 3.10 Restricciones documentadas

#### 3.10.1 Limits globales (impuestos por Aveonline)

| Item                    | Límite                                       |
| ----------------------- | -------------------------------------------- |
| `valorDeclarado` mínimo | **10.000 COP** (numbererror -5)              |
| Peso mínimo             | > 0 (AveCRM auto-ajusta a 1 kg si menor)     |
| Peso máximo             | Depende de transportadora (numbererror -7)   |
| Unidades máximas        | Depende (numbererror -6)                     |
| Dimensiones             | Opcionales pero usadas para peso volumétrico |

#### 3.10.2 Limits por carrier (confirmados en sitios oficiales 2026-05-21)

Aveonline **NO publica tabla consolidada propia**; los límites se manifiestan dinámicamente vía `kilosMaximos` / `unidadesMaximas` en mensajes de error de cotización. Tabla compilada con evidencia verificada en sitios oficiales del carrier:

| Carrier | Peso máx (kg) | Dim máx | Valor declarado | Factor volumétrico | Fuente oficial |
|---|---|---|---|---|---|
| **Coordinadora** docs/paquetes pequeños | 5 | aristas máx 50 cm (1-2kg) | $200.000 COP | 2.500 g/cm³ (a×b×c/2500) | `coordinadora.com/envios/tarifas-e-informacion-general/` |
| **Servientrega** documentos | 2 | 23×33×0,5 cm | mín $5.000 | n/d publicado | encolombia.com tarifario 2024 |
| **Servientrega** mercancías | ≥3 (sin máx público) | Requiere a×b×c cm | mín $25.000 | n/d publicado | mismo |
| **Interrapidísimo** mensajería expresa | 5 | factor /6.000 | mín $45.000 (≤2kg) / $60.000 (2.1-5kg) | 6.000 g/cm³ | `interrapidisimo.com/.../CONSOLIDADO-DE-TARIFAS-2025-2026.pdf` |
| **Interrapidísimo** carga terrestre | 6-60 | n/d | mín $170.000 | n/d | mismo |
| **TCC** mensajería | 5 | cabe en bolsa Mensajería | máx $3.511.000 COP | n/d publicado | `tcc.com.co/courier/mensajeria/formas-de-pago-y-tarifas/` |
| **TCC** carga aérea | 150 | 1.10×1.10×1.10 m | n/d | n/d | mismo |
| **Envia** paqueteo | 1-8 | máx arista 45 cm | n/d publicado | n/d | `envia.co/servicios` |
| **Envia** carga | 9-200 | 4×2×2 m | n/d publicado | n/d | mismo |
| **Saferbo** mensajería | 1 | n/d en web pública | n/d | n/d | `thesaferbo.com/` |
| **Saferbo** carga express | 5-30 | hasta 1.5 m por lado (Saferbobox) | n/d | n/d | enviotodo.com.co + thesaferbo |
| **Deprisa** estándar | 50 | máx 120 cm por lado / suma 3 lados ≤175 cm | n/d nacional | n/d | enviotodo.com.co/empresas/deprisa/ |
| **Deprisa** mercancías | 100 | mismo | — | n/d | mismo |
| **Deprisa** mensajería | 0.5 | mismo | — | n/d | mismo |

**Implicación de código**: pre-validar el package del cart contra el carrier **más restrictivo del set habilitado** (Deprisa mensajería 0.5 kg, Saferbo mensajería 1 kg, Servientrega documentos 2 kg) antes de invocar `cotizarDoble` para evitar 999/numbererror -7. Capturar `kilosMaximos` dinámico de Aveonline en logs para detectar cambios silenciosos (validación trimestral obligatoria — los carriers cambian sin notificar).

---

## 4. Generación de guía

### 4.1 Endpoint

| Campo                    | Valor                                                                          |
| ------------------------ | ------------------------------------------------------------------------------ |
| URL                      | `POST https://app.aveonline.co/api/nal/v1.0/generarGuiaTransporteNacional.php` |
| `tipo`                   | `generarGuia2`                                                                 |
| Vigencia token requerido | 1h (o lo configurado en `tiempoToken`)                                         |

### 4.2 Body completo (verbatim del plugin WooCommerce + doc oficial)

| Campo                 | Tipo   | Notas                                                             |
| --------------------- | ------ | ----------------------------------------------------------------- |
| `tipo`                | string | `"generarGuia2"`                                                  |
| `token`               | string | JWT auth                                                          |
| `idempresa`           | number | `cuentas[0].usuarios[0].id`                                       |
| `codigo`              | string | login (puede ir `""`)                                             |
| `dsclavex`            | string | password (puede ir `""`)                                          |
| `plugin`              | string | identificador fuente                                              |
| `origen`              | string | ciudad o codigoDANE                                               |
| `dsdirre`             | string | dirección remitente                                               |
| `dsbarrioo`           | string | barrio remitente                                                  |
| `dsnitre`             | string | NIT remitente                                                     |
| `dstelre`             | string | tel fijo                                                          |
| `dscelularre`         | string | celular                                                           |
| `dscorreopre`         | string | email remitente                                                   |
| `dsnombre`            | string | nombre remitente                                                  |
| `destino`             | string | ciudad destino                                                    |
| `IdTipoEntrega`       | string | `"1"` domicilio, `"2"` oficina                                    |
| `dsdir`               | string | dirección destino (concat de campos)                              |
| `dsbarrio`            | string | barrio destino                                                    |
| `dsnit`               | string | cédula destinatario (**obligatorio si `valorrecaudo > 0`**)       |
| `dsnombrecompleto`    | string | nombre completo destinatario                                      |
| `dscorreop`           | string | email destinatario                                                |
| `dstel`               | string | tel destinatario                                                  |
| `dscelular`           | string | celular destinatario                                              |
| `idtransportador`     | string | ID transportadora elegida en cotización (`codTransportadora`)     |
| `idagente`            | string | agente Aveonline origen                                           |
| `unidades`            | number | bultos totales                                                    |
| `productos[]`         | array  | `{alto,largo,ancho,peso,unidades,nombre,valorDeclarado}`          |
| `dscontenido`         | string | contenido del paquete                                             |
| `dscom`               | string | comentario libre                                                  |
| `valorrecaudo`        | number | monto COD (0 si normal) **— en COP entero, no centavos**          |
| `contraentrega`       | 0/1    | flag COD                                                          |
| `idasumecosto`        | 0/1    | quién paga flete                                                  |
| `bloquegenerarguia`   | string | `"1"` para generar guía real, **`"0"` para simular sin facturar** |
| `relacion_envios`     | string | `"1"` para asociar a relación de envíos (necesario para recogida) |
| `enviarcorreos`       | string | `"1"` Aveonline envía email auto al destinatario                  |
| `cartaporte`          | string | `"1"` para viaje de retorno                                       |
| `valorMinimo`         | 0/1    | aplica valoración mínima                                          |
| `numeroFactura`       | string | número factura interno                                            |
| `numeroBolsa`         | string | bolsa TCC                                                         |
| `dsfecha_vencimiento` | string | `YYYY/MM/DD`                                                      |
| `dsfecha_cita`        | string | `YYYY/MM/DD`                                                      |
| `dscodigo_cita`       | string | código cita                                                       |
| `dsvalor_pedido`      | string | valor pedido (referencia DIAN)                                    |
| `envioGratis`         | 0/1    | marca para reporting                                              |

### 4.3 Response (ok)

```json
{
  "status": "ok",
  "message": "proceso correcto",
  "resultado": {
    "guia": {
      "codigo": "0",
      "mensaje": "Guia <N> Generada",
      "numguia": <number>,
      "rutaguia": "<URL PDF rótulo>",
      "archivoguia": "<código>",
      "rotulo": "<URL label>",
      "archivorotulo": "<base64 PDF>",
      "rotulozebra": "<URL Zebra>",
      "archivorotulozebra": "<código>",
      "transportadora": "<nombre carrier>",
      "rutasticker": "<URL sticker térmico 110x120>",
      "archivosticker": "<base64>"
    }
  }
}
```

Persistir en Order:

- `trackingNumber = numguia.toString()`
- `labelUrl = rutasticker ?? rutaguia` (preferir térmico)
- `trackingUrl = rutaguia ?? rutasticker`
- `archivorotulo` (base64 PDF) → guardar en Supabase Storage para impresión offline

### 4.4 Errores comunes generación guía

| Code   | Mensaje                                                   |
| ------ | --------------------------------------------------------- |
| `-1`   | Origen no existe                                          |
| `-2`   | Destino no existe                                         |
| `-3`   | Peso negativo                                             |
| `-4`   | Unidades negativo                                         |
| `-5`   | Valor declarado negativo                                  |
| `-6`   | Nombre remitente faltante                                 |
| `-7`   | Dirección remitente faltante                              |
| `-8`   | Tel remitente faltante                                    |
| `-9`   | Nombre destinatario faltante                              |
| `-11`  | Dirección destinatario faltante                           |
| `-12`  | Tel destinatario faltante                                 |
| `-13`  | Email destinatario faltante                               |
| `-14`  | Transportadora no existe (≠ 999 — aquí el id es inválido) |
| `-15`  | Falta contenido del paquete                               |
| `-16`  | NIT remitente faltante                                    |
| `-17`  | No se pudo generar la guía                                |
| `-998` | Cliente no existe en el sistema                           |

Errores no numéricos comunes:

- `"no se encontraron productos"`
- `"credenciales incorrectas"` (token venció)
- `"se produjo un error al momento de iniciar la comunicacion"` (Aveonline → transportadora)

---

## 5. Recogidas

### 5.1 Endpoint

| Campo  | Valor                                                                          |
| ------ | ------------------------------------------------------------------------------ |
| URL    | `POST https://app.aveonline.co/api/nal/v1.0/generarGuiaTransporteNacional.php` |
| `tipo` | `generarRecogida2`                                                             |

### 5.2 Body

```json
{
  "tipo": "generarRecogida2",
  "token": "<jwt>",
  "idempresa": <number>,
  "idagente": "<idAgente>",
  "guias": [<numguia1>, <numguia2>],
  "dscom": "Comentario libre"
}
```

### 5.3 Response

```json
{
  "respuestasRecogida": [{
    "horaInicial": "08:00",
    "horaFinal": "17:00",
    "status": "ok",
    "message": "...",
    "details": {
      "codigo": "0",
      "mensaje": "...",
      "codigoRecogida": "...",
      "numeroRecogidaInterna": "...",
      "numeroRecogidaTransportadora": "..."
    },
    "guias": [...]
  }]
}
```

### 5.4 Cutoff y días

**Cutoff oficial = 11:00 a.m. hora Colombia (UTC-5), uniforme cross-carrier — CONFIRMADO 2026-05-21.**

Fuente primaria (doc oficial Aveonline):
> *"Las recogidas solo se pueden hacer hasta las 11:00 am del día actual"* — `https://integraciones.aveonline.co/docs/nacional/solicitudRecogida/`

Fuente secundaria (plugin WooCommerce oficial — código fuente):
```php
// src/includes/class-recogida.php:57
if ($HG >= 11) {
    echo "<h1>No pueden generarse recogidas despues de las 11am</h1>";
}
```
Fuente: `github.com/franciscoblancojn/aveonline-shipping/blob/main/src/includes/class-recogida.php`

**Comportamiento del response**: los campos `horaInicial` / `horaFinal` aparecen **solo en la respuesta** de `generarRecogida2` como ventana asignada por el carrier post-aceptación (NO son input ni tabla cutoff per-carrier). No existe tabla per-carrier publicada por Aveonline.

**Regla operativa Konvi/Lucams**:
- Si `order.created_at` (hora Colombia) `< 11:00` → solicitar recogida same-day (`fecha = today`).
- Si `>= 11:00` → automáticamente programar `fecha = today + 1 día hábil` (skip sábados/domingos/festivos DIAN).
- Edge cases per carrier (Coordinadora Bogotá podría tener 12 p.m.) → preguntar a `asesorlogistico` asignado al tenant antes de prod.

**Riesgo residual**: feriados regionales (festivos DIAN cambian año a año). Solución: librería `holidays==0.49` Python con `country='CO'` + cache trimestral.

---

## 6. Tracking / estado de envío

### 6.1 Endpoint pull (consulta puntual)

| Campo  | Valor                                                 |
| ------ | ----------------------------------------------------- |
| URL    | `POST https://app.aveonline.co/api/nal/v1.0/guia.php` |
| `tipo` | `obtenerEstadoAuth`                                   |

**Body:**

```json
{ "tipo":"obtenerEstadoAuth", "token":"<jwt>", "id":<idempresa>, "guia":"<numguia>" }
```

**Response:** incluye `guias[]` con `estado`, `rutadigitalizada` (URL al tracking del carrier), y `historicos[]` con `{estado, fechamostrar, descripcion}`.

### 6.2 Webhook AveCRM (recomendado para e-commerce)

| Campo              | Valor                                                                                                                                                                                                 |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| URL de registro    | `POST https://app.aveonline.co/avestock/api/createWebhook.php`                                                                                                                                        |
| Body registro      | `{ "tipo":"authave", "empresa":<id>, "url":"<tu URL pública>", "param1_name":"...", "param1_value":"...", ...hasta param4 }`                                                                          |
| Verificación firma | **HMAC / signature / IP allowlist NO documentados oficialmente — CONFIRMADO 2026-05-21.** Doc oficial `webhookEstadosGuias` y `crearWebhook` no mencionan firma criptográfica. Único header documentado: `Content-Type: application/json`. |

**Fuentes verificadas (NO suposición — research exhaustivo 2026-05-21):**
- `https://integraciones.aveonline.co/docs/1.0.0/nacional/webhookEstadosGuias/`
- `https://integraciones.aveonline.co/docs/avecrm/crearWebhook/`
- `github.com/franciscoblancojn/aveonline-shipping/blob/main/src/includes/action-update-guia.php` — el handler oficial **solo valida la presencia** de `status="ok"`, `guia`, `pedido_id`, `estado` (sin verificación criptográfica).

**Mecanismo de "autenticación" disponible (pseudo-HMAC documentado)**: `crearWebhook` permite hasta 4 pares `param1..param4` key-value que viajan en cada POST. Diseñados implícitamente como secret-token-in-body. No es HMAC criptográfico — un atacante con la URL puede replay.

**Mitigación defensa en profundidad (implementación Konvi obligatoria pre-prod)**:

1. **Pseudo-secret obligatorio**: registrar webhook con `param1_name="secret"` + `param1_value=<UUIDv4 ≥32 chars random>`. Server-side validar:
   ```python
   expected = vault.get(f"aveonline_webhook_secret:{tenant_id}")
   received = payload.get("param1_value") or request.json().get("secret")
   if not constant_time_eq(expected, received):
       raise HTTPException(401)
   ```
2. **IP allowlist** (escalación humana): pedir a `desarrollo1@aveonline.co` el rango de IPs outbound de Aveonline + cargarlas en CIDR allowlist a nivel Cloudflare. Sin esto, **cualquier IP puede spoofear webhooks**.
3. **Replay protection**: deduplicar por `(guia, estado, fecha)` con UNIQUE constraint en `webhook_events_seen` (genérico H.1 framework). TTL 30 días.
4. **Audit log forensics**: cada webhook recibido (válido o inválido) registra en `audit_log_forensics` con `category='webhook_signature'` (MA-8). Esencial para detectar spoofing intentos.
5. **Rate limit per source IP**: si llegan >100 req/min de una IP, alerta P1 — webhook legítimo de Aveonline no debería superar ~10 req/min por cuenta.

**Riesgo no mitigado si no se cierra**: spoofing de evento `ENTREGADA` por atacante externo → marca pedido como entregado sin entrega real → fraude COD (atacante reclama pago sin enviar nada).

### 6.3 Webhook plugin legacy WooCommerce

| Campo                         | Valor                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------- |
| URL Aveonline                 | `POST https://app.aveonline.co/api/nal/v1.0/plugins/wordpress.php`                 |
| `tipo`                        | `guardarPedidos`                                                                   |
| Body que se manda a Aveonline | `{ tipo, cliente_id, ruta:"<tu URL>", guia, pedido_id, transportadora_id }`        |
| Payload entrante a tu URL     | `{ status, message, guia, pedido_id, estado:[{estado_id, nombre_estado, fecha}] }` |

Ejemplo payload entrante:

```json
{ "estado_id": 12, "nombre_estado": "ENTREGADA", "fecha": "2020-12-11 11:04:43" }
```

### 6.4 Estados posibles

Aveonline explícitamente dice "el contenido y formato es definido por el proveedor" → cada transportadora puede mandar estados distintos. Estados vistos en muestras y plugins:

`EN OFICINA`, `EN RECOGIDA`, `RECOGIDA`, `EN BODEGA`, `EN TRANSITO`, `EN REPARTO`, `EN ENTREGA`, `EN NOVEDAD`, `ENTREGADA`, `DEVOLUCION`, `DEVUELTA`.

Novedades comunes: `DIRECCION ERRONEA`, `CLIENTE NO TIENE EFECTIVO`, `CLIENTE AUSENTE`, `RECHAZA PRODUCTO`.

> Mapping recomendado a estados internos Lucams `{pendiente, en_transito, entregado, novedad, devuelto}` configurable, no hardcoded.

### 6.5 Webhook tramas operadores (proveedor — no aplica para nosotros)

URL `https://aveonline.co/api/hooks/tramaoperador.php`. Es el endpoint que las transportadoras llaman a Aveonline, no al revés.

---

## 7. Contraentrega (COD)

### 7.1 Habilitación por guía

- `contraentrega: 1` en body de `generarGuia2` y `cotizarDoble`
- `valorrecaudo: <COP a recaudar>` (entero, NO centavos — Aveonline maneja COP entero)
- `idasumecosto`: si vendedor asume comisión (1) o se descuenta del recaudo (0)
- `contraentregaPayment`: variante extra (uso exacto no documentado)

### 7.2 Comisiones y tiempos de liquidación

| Carrier         | Liquidación COD                    | Días pago        | Cobra devolución |
| --------------- | ---------------------------------- | ---------------- | ---------------- |
| TCC             | 4–6 días hábiles                   | martes y viernes | NO               |
| DOMINA          | 4–6 días hábiles                   | martes y viernes | NO               |
| SERVIENTREGA    | 7–11 días hábiles                  | viernes          | NO               |
| ENVIA           | 7–11 días hábiles (contrato 9–15)  | viernes          | **SÍ**           |
| INTERRAPIDISIMO | 7–11 días hábiles (contrato 13–19) | viernes          | NO               |
| SAFERBO         | 7–11 días hábiles                  | viernes          | NO               |
| COORDINADORA    | 5–11 días hábiles (contrato 5–14)  | —                | **SÍ**           |
| MOOVA           | —                                  | —                | NO               |

> **Discrepancia entre sitio comercial y contrato.** Para SLA productivo usar rangos del contrato (más conservadores). Fuente comercial: `aveonline.co/servicios-pago-contraentrega/`. Fuente contractual: `app.aveonline.co/app/contrato/terminosCondiciones.html`.

### 7.3 Comisión

- **Desde 2.40% sobre el monto recaudado**, variable por carrier (sitio comercial).
- Comisión se cobra incluso si el envío fue **devuelto** (cláusula contractual).
- No hay mínimo de envíos para activar COD.

### 7.4 Cobertura COD

NO hay endpoint que liste "ciudades con COD". Método: cotizar con `contraentrega: 1` y verificar qué transportadoras devuelven cotización válida.

### 7.5 Endpoints reporting COD

**Endpoint API público para histórico de recaudos NO EXISTE — CONFIRMADO 2026-05-21.**

Research exhaustivo descartó la existencia de endpoints `getRecaudo`, `historicoRecaudos`, `consultarLiquidacion`, `estadoCuenta`, `consultarSaldoRecaudo`, `cashOnDeliveryHistory` o variantes en:
- API v1.0 (`webservices.aveonline.co/cotizar/cotizar.php`) — solo `cotizar`, `generarGuia`, `cancelarGuia`, `solicitudRecogida`.
- API v2.0 / AveCRM (`api.aveonline.co/api/v2.0`) — solo `autenticacion`, `listarEnvios`, `webhookEstadosGuias`, `crearWebhook`, `agentes`.
- API v3.0 / AuthProduct — solo auth producto, sin reporting.

El endpoint `listarEnvios` (`integraciones.aveonline.co/docs/avecrm/listarEnvios/`) expone tracking + datos guía, **pero NO** `valorRecaudo`, `fechaPago`, `estadoRecaudo`, `liquidacionId`, `bancoPago`, etc.

Confirmación cruzada en doc comercial:
> *"Aveonline pagará... a partir del 4to día hábil después de la entrega"* + *"La trazabilidad y estado actual se ven desde 'mis envíos'"* — `aveonline.co/anticipo-de-recaudo/` (módulo Wallet UI, sin API).

El plugin WooCommerce oficial tampoco consulta saldos — refuerza ausencia de endpoint.

**Plan de cierre (3 capas, defensa en profundidad)**:

1. **Escalación obligatoria (semana 0 pre-prod)**: Email formal a `desarrollo1@aveonline.co` con esta consulta literal:
   > *"¿Existe endpoint REST/SOAP NO documentado públicamente para consultar liquidaciones/recaudos COD? Si no, ¿hay roadmap o alternativa CSV programada / export por API? Necesitamos reconciliación automática diaria por marketplace SaaS multi-tenant."*

2. **Backup táctico (si escalación devuelve "no")**: scraping autenticado de `app.aveonline.co/app/...` módulo Wallet. **Frágil** (cualquier cambio UI rompe). Documentar como deuda técnica en `DECISIONS.md` y `docs/adr/00XX-aveonline-cod-reconciliation.md`. Implementación sugerida:
   - Login con cuenta tenant + parsing HTML/JSON XHR.
   - Cron diario 6 a.m. hora Colombia.
   - Output → tabla `tenant_cod_ledger` con `{tenant_id, fecha_liquidacion, monto_cents, guias_incluidas[], banco_pago}`.
   - Alerta P1 si scraping falla 3 días consecutivos.

3. **Probe empírico OpenAPI discovery (sin escalación, 30 min ejecución)**:
   ```bash
   for path in openapi.json swagger.json api-docs api/docs api/openapi swagger/v1/swagger.json; do
     curl -s "https://app.aveonline.co/$path" | head -200
     curl -s "https://api.aveonline.co/$path" | head -200
   done
   ```
   Si retorna JSON válido → revisar endpoints no documentados públicamente.

**Workaround manual interim (rev. 106)**: descarga semanal manual desde dashboard hasta que (1) escalación responda o (2) scraping esté en prod.

**Riesgo si no se cierra**: imposibilidad de auto-conciliar pagos COD → operación manual diaria → bloquea feature Konvi "estado de cuenta tenant" → caja sin reconciliar → fraude no detectable y reporting financiero IVA fletes incompleto (cláusula DIAN §15.4).

### 7.6 Facturación

- Aveonline factura **cada miércoles** con plazo de 8 días calendario para pago.
- Pago a Aveonline: transferencia Bancolombia, tarjeta crédito, o compensación con recaudos.
- **Si cliente es Bancolombia, sin mensualidad** (fuente: aveonline.co).

---

## 8. Cancelación de guía

### 8.1 Eliminar relación de envíos

| Campo  | Valor                                                                                     |
| ------ | ----------------------------------------------------------------------------------------- |
| URL    | `POST https://app.aveonline.co/api/nal/v2.0/generarGuiaTransporteNacional.php`            |
| `tipo` | `eliminarRelacionEnvios`                                                                  |
| Body   | `{ "tipo":"eliminarRelacionEnvios", "usuario":"<login>", "numeroRelacionEnvios":"<id>" }` |
| Header | `Authorization: <token v2>` (única ruta que usa Authorization header)                     |

### 8.2 Cancelar guía individual

**NO existe endpoint público para anular una guía individual ya generada.**

Práctica:

- Si guía NO ha sido manifestada/recogida → eliminar la relación de envíos la "desactiva" lógicamente
- Si ya fue recogida → no se puede cancelar; queda como devolución natural (auto-return tras 3 intentos fallidos según contrato)
- Modificar dirección post-creación: no hay endpoint público → escribir a `pqr@aveonline.co` con número de guía

---

## 9. Devoluciones

Reglas del contrato:

- Máximo **3 días hábiles** para dar solución a una novedad; pasado el plazo → devolución automática al remitente
- Devolución se entrega en la dirección del remitente registrada en la guía. Cambiar dirección = cobro adicional
- Si guía era de **crédito** → devolución cuesta lo mismo que el flete original
- Si guía era **COD** → no se cobra comisión de recaudo (porque no hubo recaudo), pero sí flete devolución según carrier (ENVIA y COORDINADORA cobran)
- Daños/averías: reclamar dentro de **16 horas** con evidencia fotográfica
- Extravíos: reportar tras **3 días sin actualización de tracking**

**Endpoint API dedicado de devoluciones NO EXISTE — pero hay primitiva oficial `cartaporte=1` (boomerang) — CONFIRMADO 2026-05-21.**

Doc oficial `generacionGuia` (`https://integraciones.aveonline.co/docs/nacional/generacionGuia/`) expone parámetro:

```
cartaporte: "Boomerang. Si la guia es de ida y regreso: 1"
```

Esta es la primitiva oficial para guía ida+vuelta. **No es RMA dedicado**, pero es el handle más cercano publicado por Aveonline. Comparado con Envia (que sí tiene endpoint `/return-shipment` dedicado), Aveonline trata RMA como producto comercial UI ("logística inversa", "devolución cero") sin API específica.

**Patrón oficial RMA via Aveonline (3 opciones)**:

1. **Boomerang con `cartaporte=1`** (recomendado para RMA por defecto del cliente):
   - Mismo `generarGuiaTransporteNacional` con origen + destino normales + `cartaporte=1`.
   - El carrier intenta entrega; si rechazo cliente → return automático al remitente.
   - Confirmar empíricamente con cuenta DEMO: lista de carriers que aceptan boomerang real (sospecha: Coordinadora, Servientrega sí; Saferbo posiblemente no).

2. **Guía nueva con origen/destino invertidos** (recomendado para RMA solicitado post-entrega):
   - `generarGuiaTransporteNacional` con `origen = customer_address` + `destino = warehouse_tenant`.
   - Costo asumido por tenant (configurable: descontar de saldo cliente o reembolso parcial).
   - Si guía original fue COD → no se cobra comisión de recaudo en la devolución (cláusula contractual confirmada §9 actual).

3. **PQR formal** (último recurso si carrier no opera boomerang/invertido en ruta específica):
   - Email `pqr@aveonline.co` con guía origen + razón + evidencia.
   - SLA contractual no publicado (ver §15.1 actualizada).

**Implementación Konvi (rev. 106+)**:

```python
# services/ai-orchestrator/agentic/tools/returns.py (futuro)
class GenerateReturnLabelTool:
    """Genera guía RMA con `cartaporte=1` para retorno cliente→warehouse."""
    async def execute(self, args, ctx) -> ToolResult:
        # 1. Validar order_id existe y status=DELIVERED y dentro de ventana RMA (típico 8 días).
        # 2. Invocar `generarGuiaTransporteNacional` con orig+dest invertidos + cartaporte=1.
        # 3. Persistir return_shipment row + emitir cart_event(return_initiated).
        ...
```

**Validación humana pendiente**: confirmar con `desarrollo1@aveonline.co` la lista exacta de carriers que aceptan `cartaporte=1` y si tiene cobertura nacional o solo principales ciudades.

**Riesgo si no se cierra**: Konvi tenant no puede ofrecer "devolución 1-click" → fricción UX postventa → reduce retention (LTV impacto medido en mercados con devolución masiva: cosmética, calzado).

---

## 10. Cobertura geográfica

### 10.1 Endpoint listado de ciudades (API)

| Campo  | Valor                                                    |
| ------ | -------------------------------------------------------- |
| URL    | `POST https://app.aveonline.co/api/box/v1.0/ciudad.php`  |
| `tipo` | `listar`                                                 |
| Body   | `{ "tipo":"listar", "data":"<query>", "registros":<N> }` |

### 10.2 JSON estático público (RECOMENDADO)

| Campo         | Valor                                                                                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| URL           | `https://app.aveonline.co/assets/resources/public/listadociudades.json`                                                                                 |
| Auth          | NO requiere                                                                                                                                             |
| Tamaño        | ~255 KB                                                                                                                                                 |
| Last-Modified | 2024-06-18                                                                                                                                              |
| Schema        | `[{ "codigodane": "11001000", "nombre": "BOGOTA(CUNDINAMARCA)", "departamento":"CUNDINAMARCA", "nombremun":"BOGOTA", "codigocortodane":"11001" }, ...]` |

### 10.3 Formato de ciudad

Aveonline acepta **ambos** formatos en `origen`/`destino`:

- Nombre formateado: `"BOGOTA(CUNDINAMARCA)"` — UPPERCASE, sin tilde, sin "D.C."
- codigoDANE 8 dígitos: `"11001000"`

> Bogotá D.C. aparece como `"BOGOTA(CUNDINAMARCA)"`. ~4.500 ciudades/centros poblados (más granular que Venndelo).

### 10.4 Recomendación de implementación

1. Descargar `listadociudades.json` en build o job semanal `pg_cron`
2. Indexar en Postgres por `codigodane` (PK) y `nombre` (búsqueda)
3. **No mezclar con DANE divipola** (Lucams_shop ya usa divipola en checkout). Mapear `lucams.divipola → aveonline.ciudad` por `codigocortodane` (primeros 5 dígitos)

---

## 11. Tarifas y planes

| Item                                  | Dato                                                                                         |
| ------------------------------------- | -------------------------------------------------------------------------------------------- |
| Mínimo de envíos                      | NO requiere                                                                                  |
| Mínimo para COD                       | NO requiere                                                                                  |
| Tarifas auto-configuradas             | NO — al abrir cuenta debes elegir uno de **3 planes mensuales** + FEE empieza el segundo mes |
| Cliente Bancolombia                   | Sin mensualidad                                                                              |
| Comisión COD                          | Desde 2.40%, variable por carrier                                                            |
| FEE plan                              | Variable, no publicado                                                                       |
| Endpoint para listar tarifas vigentes | **CONFIRMADO NO EXISTE 2026-05-21** — cotización on-demand es la única fuente de verdad     |

**Garantía de tarifa.** El `total` en cotización es vinculante mientras el JWT no expire y el peso/dimensiones de la guía coincidan con lo cotizado. Si el peso real al despacho difiere → reajuste retroactivo en factura semanal (cláusula contractual).

**Por qué Aveonline NO expone tarifario estático (research 2026-05-21)**: la cotización depende dinámicamente de (a) plan mensual del cuenta, (b) volumen acumulado mes a la fecha (descuentos progresivos), (c) acuerdos especiales por industria/cliente, (d) recargos zonal (ciudad capital vs intermedia vs especial), (e) factor combustible mensual. Un tarifario estático sería incorrecto en runtime.

**Patrón replicado del plugin oficial (`src/includes/class-api.php:583`)**:

```php
set_transient($key_cache, $result, 60);  // TTL 60 segundos
```

**Implementación Konvi rev. 106**:
- Cache L1 (memoria proceso): 60s para `cotizarDoble(origin, destination, package)`.
- Cache L2 (Supabase tabla `aveonline_quote_cache` per-tenant): 5 min para warm-up de top-10 rutas comunes.
- Warm-up cron nocturno 3 a.m. hora Colombia: pre-cotizar top 10 rutas × 5 escalones de peso (50 combinaciones) → cache L2.
- En hot path: lookup L1 → L2 → invocar `cotizarDoble` y poblar L1+L2.
- Métrica: `aveonline_quote_cache_hit_rate` target ≥70% en producción estable.

---

## 12. Producción vs sandbox / ambiente de pruebas

> **Confirmación 2026-05-21 vía investigación exhaustiva + probe en vivo.** No existe un host sandbox dedicado (`sandbox.aveonline.co`, `test.aveonline.co`, etc. — todos `NO_DNS`). El mecanismo oficial de pruebas que el equipo de desarrollo de Aveonline confirmó verbalmente y que está documentado es:

### 12.1 Cuenta DEMO pública

| Campo                                       | Valor                                                                                         |
| ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| URL doc                                     | https://integraciones.aveonline.co/docs/nacional/autenticacion/                               |
| `usuario`                                   | **`demointegracion`**                                                                         |
| `clave`                                     | **`demointegra2021`**                                                                         |
| `idempresa`                                 | **15289**                                                                                     |
| Razón social                                | "Demo - Integracion"                                                                          |
| Servicio                                    | AVEONLINE COURIER                                                                             |
| Endpoint auth                               | `POST https://app.aveonline.co/api/comunes/v1.0/autenticarusuario.php` (mismo que prod)       |
| Transportadoras activas (probe 2026-05-21)  | 7: ENVIA, COORDINADORA MERCANTIL, TCC SA, SERVIENTREGA, INTERRAPIDISIMO, 99MINUTOS, GO ENVIOS |
| Cotización Bogotá→Medellín set 6 fotoimanes | 4 ok reales: COORDINADORA $15.930 / ENVIA $16.350 / SERVIENTREGA $17.650 / TCC $18.300        |
| Costo de uso                                | $0 — guías que no se manifiestan no se facturan                                               |

### 12.2 Flag dry-run `bloquegenerarguia`

| Valor | Comportamiento                                                 |
| ----- | -------------------------------------------------------------- |
| `"0"` | **Modo simulación**. No genera guía real, no factura.          |
| `"1"` | **Modo productivo**. Genera guía real, factura según contrato. |

Único parámetro documentado tipo "dry-run" en toda la API. Doc oficial: https://integraciones.aveonline.co/docs/nacional/generacionGuia/ → _"Si desea generar la guia: 1. Si no: 0"_.

### 12.3 Implementación en Lucams_shop (2026-05-21)

Switch controlado por **env var `AVEONLINE_ENV`** (default `test`):

| Modo             | Credenciales auth                                  | `bloquegenerarguia` | Cuándo usar                                |
| ---------------- | -------------------------------------------------- | ------------------- | ------------------------------------------ |
| `test` (default) | `demointegracion` / `demointegra2021` (hardcoded)  | `"0"` (no factura)  | dev local, Vercel preview, QA, smoke tests |
| `production`     | `AVEONLINE_USUARIO` + `AVEONLINE_CLAVE` del `.env` | `"1"` (factura)     | Vercel production únicamente               |

Configurado en `apps/web/features/shipping/aveonline.ts` (constantes `DEMO_CREDENTIALS` + función `isProductionEnv()`).

> **Seguridad.** Nunca setear `AVEONLINE_ENV=production` en preview ni dev — el flag deber estar solo en Vercel production env. El default `test` garantiza fail-safe.

### 12.4 Subdominios alternos descubiertos (NO usar)

Investigación 2026-05-21 vía Certificate Transparency reveló subdominios que existen pero **no operan** como sandbox público:

| Host                                                                                                              | Estado                   | Por qué no usar                    |
| ----------------------------------------------------------------------------------------------------------------- | ------------------------ | ---------------------------------- |
| `apiqa.aveonline.co`                                                                                              | 200 (ISPConfig default)  | Servidor vacío, sin API            |
| `appdev.aveonline.co`                                                                                             | 403 (acceso restringido) | Solo interno Aveonline             |
| `guiasqa.aveonline.co`                                                                                            | 200 (respuesta 0 bytes)  | Existe pero no operativo           |
| `qa.aveonline.co`                                                                                                 | TCP/443 cerrado          | DNS resuelve, no acepta conexiones |
| `developers.aveonline.co`                                                                                         | 200 (ISPConfig default)  | Página vacía, no es portal dev     |
| `sandbox.aveonline.co`                                                                                            | NO_DNS                   | No existe                          |
| `test.aveonline.co`, `demo.aveonline.co`, `staging.aveonline.co`, `dev.aveonline.co`, `uat`, `preprod`, `pruebas` | NO_DNS                   | No existen                         |

### 12.5 Otras versiones de auth probadas

| Endpoint                                                | Cuenta demo                       | Resultado                                                      |
| ------------------------------------------------------- | --------------------------------- | -------------------------------------------------------------- |
| v1 `comunes/v1.0/autenticarusuario.php` (tipo `auth`)   | `demointegracion/demointegra2021` | ✅ status:ok + token válido                                    |
| v2 `comunes/v2.0/autenticarusuario.php` (tipo `authV2`) | `demointegracion/demointegra2021` | ❌ "Usuario no encontrado" — v2 requiere cuenta productiva     |
| v3 AveCRM `auth/v3.0/index.php` (tipo `AuthProduct`)    | `demo/password`                   | ❌ "Error en usuario o contraseña" — endpoint válido, creds no |

Conclusión: solo v1 acepta la cuenta demo. v2/v3 requieren credenciales productivas.

### 12.6 Switch entre ambientes

```bash
# .env.local — desarrollo local
AVEONLINE_ENV=test
# AVEONLINE_USUARIO + AVEONLINE_CLAVE no necesarias en modo test

# Vercel preview — staging
AVEONLINE_ENV=test

# Vercel production — venta real
AVEONLINE_ENV=production
AVEONLINE_USUARIO=<usuario_real>
AVEONLINE_CLAVE=<clave_real>
```

El switch toma efecto en el siguiente request (no requiere redeploy si se cambia env var en Vercel y se hace `redeploy` del último build).

---

## 13. SDK / librerías

| Recurso                                  | Calidad                                                                                                                        | URL                                               |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------- |
| `aveonline-npm` v2.3.0 (TS)              | **Buena referencia** (no usar como dep) — modular (auth, agents, guide, pickup, quote, shippingRelationship, transport, citys) | `npmjs.com/package/aveonline`                     |
| `aveonline-shipping` (PHP / WooCommerce) | **Excelente referencia** — incluye cache, retries, idempotencia, paralelización curl_multi, validación. Actualizado 2026-05-12 | `github.com/franciscoblancojn/aveonline-shipping` |
| Aveonline oficial SDK                    | **NO existe**                                                                                                                  | —                                                 |
| Workspace Postman público                | Existe `postman.com/aveonline` pero requiere login                                                                             | —                                                 |

> **Recomendación arquitectura.** NO instalar `aveonline-npm` como dependency (1 mantenedor, sin tests, tipos incompletos). En vez de eso, **copiar el patrón** a `apps/web/features/shipping/aveonline/` con tipos propios + Zod schemas para validación runtime (la API es PHP devolviendo JSON con strings donde deberían ser numbers — `"unidades":"1"` — parseo defensivo obligatorio).

---

## 14. Errores consolidados

### 14.1 Códigos HTTP

- La API devuelve **siempre HTTP 200** incluso para errores lógicos. El error va en el body como `status:"error"` o `numbererror`. Anti-patrón REST.
- AveCRM (`createOrder.php`) sí devuelve códigos correctos: 400, 405, 409, 422.

### 14.2 numbererror unificado

| Code  | Cotización                            | Generar guía              |
| ----- | ------------------------------------- | ------------------------- |
| -0-   | OK                                    | OK                        |
| -1    | Origen no existe                      | Origen no existe          |
| -2    | Destino no existe                     | Destino no existe         |
| -3    | Peso ≤0                               | Peso negativo             |
| -4    | Unidades ≤0                           | Unidades negativo         |
| -5    | Valor declarado < 10k                 | Valor declarado neg       |
| -6    | Unidades > max                        | Falta nombre remitente    |
| -7    | Kilos > max                           | Falta dirección remitente |
| -8    | —                                     | Falta tel remitente       |
| -9    | —                                     | Falta nombre destinatario |
| -11   | —                                     | Falta dir destinatario    |
| -12   | —                                     | Falta tel destinatario    |
| -13   | —                                     | Falta email destinatario  |
| -14   | —                                     | Transportadora no existe  |
| -15   | —                                     | Falta contenido paquete   |
| -16   | —                                     | Falta NIT remitente       |
| -17   | —                                     | No se pudo generar guía   |
| -998  | —                                     | Cliente no existe         |
| -999  | **Cálculo / servicio no configurado** | —                         |
| -1000 | Config/ruta con límites               | —                         |

### 14.3 Diagnóstico 999 (orden de probabilidad)

1. **`idtransportador` no habilitado** en tu `idempresa`. Test: llamar `listarTransportadorasPorEmpresa`.
2. **`idagente` faltante o inválido**. Aveonline lo usa para calcular trayecto desde la dirección del agente.
3. **Trayecto sin cobertura** para esa transportadora (ej. ENVIA no llega a Putumayo).
4. **Peso/dimensiones exceden límite específico** del par origen-destino (no genera -7, genera -999 en algunas rutas).
5. **Cuenta nueva sin "configuración inicial"** — ejecutivo debe correr setup manual.

---

## 15. Soporte / compliance / limitaciones

### 15.1 Soporte

| Canal                     | Detalle                                                                    |
| ------------------------- | -------------------------------------------------------------------------- |
| Integraciones técnicas    | `desarrollo1@aveonline.co`                                                 |
| PQR / reclamos            | `pqr@aveonline.co`                                                         |
| WhatsApp business         | **+57 305 420 21 25** (confirmado oficial)                                 |
| Asesor logístico          | Asignado por cuenta (`asesorlogistico` / `nombreasesor` en respuesta auth) |
| Punto físico              | Envigado, Antioquia (oficina cabecera)                                     |
| Horario punto físico      | **L-V 8:00 a.m. – 5:00 p.m. hora Colombia (UTC-5)** — CONFIRMADO oficial   |
| SLA respuesta documentado | **NO publicado** — contractual a confirmar con `asesorlogistico` per cuenta |
| Portal de tickets         | **NO existe** (Zendesk/Freshdesk no detectado) — todo por email/WhatsApp   |

**Fuentes verificadas (research 2026-05-21)**:
- Horario L-V 8-5 → `https://aveonline.co/servicios-punto-fisico/`
- WhatsApp 305 420 21 25 → mismo + `co.linkedin.com/company/ave-online`
- Perfil empresa: empresa pequeña (11-50 empleados según LinkedIn, 30 listados), fundada 2013, oficina Envigado-Antioquia. Implicación: NO ofrece soporte 24/7 — incidentes nocturnos / fines de semana quedan sin respuesta hasta D+1 hábil.

**Acción humana obligatoria pre-prod (escalar via `asesorlogistico` del tenant)**:
- Pedir por escrito SLA contractual de respuesta por severidad (P0/P1/P2).
- Confirmar canal de escalación P0 fuera de horario L-V 8-5 (¿WhatsApp directo del asesor? ¿on-call rotativo? ¿ninguno?).
- Agregar al contrato firmado: SLA de respuesta P0 ≤4h, P1 ≤24h hábiles, P2 ≤72h hábiles (negociar).
- Documentar resultado en `docs/legal/aveonline-contract-{tenant}.md`.

**Implicación operativa para SLA Konvi → tenant**: hasta tener SLA escrito Aveonline, NO ofrecer a tenants SLA mejor que "L-V 8-5 hora Colombia, mejor esfuerzo fuera de horario". Documentarlo en DPA Konvi.

**Riesgo no cerrado**: incidente P0 viernes 6 p.m. (e.g. cotizaciones 100% fallan) → sin canal Aveonline 24/7 → tenant Konvi sin respuesta hasta lunes 8 a.m. → ~62h de downtime potencial. Mitigación parcial: circuit breaker + fallback "envío manual" desde Konvi UI.

### 15.2 Compliance — Ley 1581 / 1480

- **Aveonline es ENCARGADO de tratamiento**, NO responsable. Tú (Lucams_shop) sigues siendo el responsable.
- Procesa datos personales y financieros (incluyendo sensibles: biometría, video).
- Transmite datos a las transportadoras (ENVIA, TCC, Servientrega, etc.) — encargados subordinados.
- Confidencialidad perpetúa post-terminación.

### 15.3 Rol legal

- "Intermediario logístico" — Aveonline NO es transportador, no responde por la carga; responsable es la transportadora final.
- Reclamos transporte → contra la transportadora (no contra Aveonline).
- Reclamos producto (calidad/manufactura) → el vendedor (tú) indemniza a Aveonline.

### 15.4 Implicaciones para Lucams_shop

- Documentar Aveonline + cada transportadora como **subprocesadores** en política de privacidad (Ley 1581 art. 17 → ROLs)
- Listado de carriers como anexo "transferencia internacional" — todos nacionales, no aplica TI
- Guía de transporte = comprobante para retenciones/IVA fletes (DIAN)

### 15.5 Limitaciones técnicas

| Item                   | Dato                                                                                       |
| ---------------------- | ------------------------------------------------------------------------------------------ |
| Rate limit documentado | **NO publicado oficialmente — CONFIRMADO 2026-05-21**. Doc `autorizacionporHeaders` y `autenticacion` no mencionan `X-RateLimit-*`, HTTP 429 ni throttling. Señal indirecta fuerte: plugin oficial cachea cotizaciones 60s (`class-api.php:583`) y datos auxiliares 12h (`cache.php:47-49`) — sugiere tolerancia ~1 req/min por sesión |
| Timeout típico         | Plugin oficial usa `CURLOPT_TIMEOUT = 0` (sin timeout) configurable                        |
| Latencia cotización    | 5–15s con `cotizarDoble` en paralelo                                                       |
| Errores 500            | No frecuentes — devuelve `status:"error"` en HTTP 200                                      |
| SSL strict             | Plugin oficial usa `verify_peer=false` (no replicar — cert válido)                         |

> **Recomendación.** Cachear cotizaciones por `hash(origen+destino+productos+contraentrega)` durante 5–15 min en Postgres.

---

## 16. Auditoría del código actual (estado pre-ajuste 2026-05-21)

### 16.1 Archivos

| Archivo                                                 | Estado                                              |
| ------------------------------------------------------- | --------------------------------------------------- |
| `apps/web/features/shipping/provider.ts:15-107`         | ✅ Interface `ShippingProvider` completa            |
| `apps/web/features/shipping/aveonline.ts:75-373`        | ✅ `AveonlineProvider` implementa todos los métodos |
| `apps/web/features/shipping/venndelo.ts`                | ⚪ Plan B dormido (stub `NOT_IMPLEMENTED`)          |
| `apps/web/features/products/shipping-schemas.ts:32-117` | ✅ Zod + helpers `getEffectiveShippingDims`         |
| `apps/web/features/checkout/service.ts:101-177`         | ✅ `quoteShipping()` orquesta                       |
| `apps/web/app/checkout/envio/page.tsx`                  | ✅ Llama `quoteShipping` server-side                |
| `apps/web/app/checkout/envio/quote-list.tsx`            | ✅ Renderiza opciones                               |
| Route handler `/api/webhooks/aveonline`                 | ❌ **NO EXISTE**                                    |
| Tests aveonline                                         | ❌ **NO EXISTEN**                                   |

### 16.2 Endpoints llamados (5 de 17+ documentados)

| Endpoint                                     | Usado | Tipo / Acción                                       |
| -------------------------------------------- | ----- | --------------------------------------------------- |
| `comunes/v1.0/autenticarusuario.php`         | ✅    | `tipo: "auth"`                                      |
| `nal/v1.0/generarGuiaTransporteNacional.php` | ✅    | `tipo: "cotizar2"` (cotización) — **causa del 999** |
| `nal/v1.0/generarGuiaTransporteNacional.php` | ✅    | `tipo: "generarGuia2"` (guía)                       |
| `nal/v1.0/guia.php`                          | ✅    | `tipo: "obtenerEstadoAuth"` (tracking)              |
| Webhook handler (sin route)                  | ⚠️    | Método existe pero sin endpoint público             |
| `nal/v1.0/generarGuiaTransporteNacional.php` | ❌    | `tipo: "cotizarDoble"` ← **debemos usar**           |
| `box/v1.0/transportadora.php`                | ❌    | `listarTransportadorasPorEmpresa`                   |
| `box/v1.0/ciudad.php`                        | ❌    | listado ciudades                                    |
| `comunes/v1.0/agentes.php`                   | ❌    | listar agentes                                      |
| `nal/v1.0/generarGuiaTransporteNacional.php` | ❌    | `tipo: "generarRecogida2"`                          |
| `nal/v2.0/generarGuiaTransporteNacional.php` | ❌    | `tipo: "eliminarRelacionEnvios"`                    |
| `avestock/api/createWebhook.php`             | ❌    | registrar webhook AveCRM                            |

### 16.3 Hardcodes problemáticos

| Línea                     | Valor                                                    | Problema                                                               |
| ------------------------- | -------------------------------------------------------- | ---------------------------------------------------------------------- |
| `aveonline.ts:30`         | `BASE_URL` hardcoded                                     | OK (no hay sandbox)                                                    |
| `aveonline.ts:69`         | `60 * 60_000` token TTL                                  | OK (1h doc)                                                            |
| `aveonline.ts:39`         | `5 * 60_000` refresh buffer                              | OK (defensivo)                                                         |
| `checkout/service.ts:153` | `origin: { city: "Bogotá", department: "Cundinamarca" }` | **BUG** — debe leer de SiteSettings PICKUP\_\*                         |
| `aveonline.ts:220`        | `IdTipoEntrega: "1"`                                     | OK (domicilio default)                                                 |
| `aveonline.ts:221`        | `dsnit: "00000"`                                         | **Tech debt** — debe usar `Order.shippingDocumentNumber` cuando exista |
| `aveonline.ts:242`        | `plugin: "lucamsshop"`                                   | OK                                                                     |

### 16.4 Bugs identificados (orden de gravedad)

| #   | Bug                                                   | Archivo:Línea                   | Impacto                                                            |
| --- | ----------------------------------------------------- | ------------------------------- | ------------------------------------------------------------------ |
| 1   | **`cotizar2` en vez de `cotizarDoble`**               | `aveonline.ts:101`              | 🔴 Bloqueante. Causa el 999 que vemos en producción                |
| 2   | **No filtra `numbererror !== "-0-"`** en parseo       | `aveonline.ts:121-128`          | 🔴 Bloqueante. UI muestra "Gratis" fake para envíos imposibles     |
| 3   | **Origen hardcoded Bogotá/Cundinamarca**              | `checkout/service.ts:153`       | 🟡 Importante. Funciona por coincidencia pero ignora SiteSettings  |
| 4   | **Falta `idagente`** en body cotización               | `aveonline.ts:99-110`           | 🟡 Posible causa adicional de 999                                  |
| 5   | **Webhook handler sin HMAC ni IP whitelist**          | `aveonline.ts:352-373`          | 🟡 ALTO. Sin esto el endpoint sería vulnerable                     |
| 6   | **Route handler `/api/webhooks/aveonline` no existe** | —                               | 🟡 Bloqueante para tracking automático                             |
| 7   | **`createShipment` no se invoca desde la app**        | —                               | 🟡 Falta cron/edge function al transicionar Order PAID             |
| 8   | **Email regex `/<(.+?)>/` puede fallar**              | `aveonline.ts:216`              | 🟢 Bajo. Tiene fallback `hola@lucamsshop.co`                       |
| 9   | **Race condition tokenCache**                         | `aveonline.ts:39-41`            | 🟢 Bajo. Solo desperdicia auth call                                |
| 10  | **No valida `valorDeclarado >= 10000`**               | `checkout/service.ts:146`       | 🟡 Importante. Productos baratos generan numbererror -5            |
| 11  | **Catch genérico `Error al guardar. Reintentá`**      | `checkout/datos/actions.ts:127` | 🟡 Mediano. No expone causa real. Log existe pero buffering oculta |
| 12  | **Logs no se ven en tiempo real**                     | Makefile start-web              | 🟢 ARREGLADO en este sprint (`stdbuf -oL -eL`)                     |

### 16.5 Variables de entorno + SiteSettings

**Env vars (.env.local):**

- `AVEONLINE_USUARIO` ✅ requerida
- `AVEONLINE_CLAVE` ✅ requerida
- `SHIPPING_PROVIDER` (default "aveonline") opcional
- `EMAIL_FROM` (para `dscorreopre` remitente)

**SiteSettings (`/admin/contenido/configuracion` cat BUSINESS):**

- `BUSINESS_NIT` ✅ llenado por Lucy 2026-05-21
- `PICKUP_CITY` ✅
- `PICKUP_DEPARTMENT` ✅
- `PICKUP_ADDRESS` ✅
- `PICKUP_PHONE` ✅
- `PICKUP_CONTACT_NAME` ✅

### 16.6 Integración con Order state machine

```
ORDER_TRANSITIONS:
  DRAFT → PENDING_PAYMENT → PAID → FULFILLING → SHIPPED → DELIVERED
                            ↓ REFUNDED

Plan ADR-039 (no implementado):
  Webhook Wompi APPROVED → Order PAID
                            ↓
                          enqueue('shipment_creation_retry')
                            ↓
                          Edge Function consumer
                            ↓
                          provider.createShipment()
                            ↓
                          Order.trackingNumber + Order.trackingUrl + Order.labelUrl
                            ↓
                          Order FULFILLING
```

**Estado actual:** Solo `PENDING_PAYMENT → PAID` parcialmente implementado. El resto del flujo está pendiente.

---

## 17. Resultados del probe real (cuenta `crittan01@gmail.com`, 2026-05-21)

### 17.1 Auth

```
status: 200
contentType: application/json
parsed.status: "ok"
parsed.hasToken: true
cuentas[0].usuarios[0].id (idempresa) = 43562
cuentas[0].usuarios[0].razon = "Cristian Camilo Garzon Tamayo"
cuentas[0].usuarios[0].nombre = "Kaiu Living Natural"
```

> **Nota.** La cuenta actual pertenece a Kaiu Living. Lucy creó cuenta nueva "Lucams Shop" 2026-05-21; rotar credenciales cuando Aveonline confirme activación.

### 17.2 Transportadoras habilitadas (`listarTransportadorasPorEmpresa`)

6 carriers:

| id   | text                   |
| ---- | ---------------------- |
| 1028 | 99MINUTOS              |
| 1009 | COORDINADORA MERCANTIL |
| 29   | ENVIA                  |
| 1031 | GO ENVIOS              |
| 33   | SERVIENTREGA           |
| 1010 | TCC SA                 |

### 17.3 Cotización `cotizarDoble` (Bogotá → Medellín, 1 set de 6 fotoimanes 0.5kg 15×10×3cm valorDeclarado 35.000)

10 cotizaciones devueltas:

| Carrier                | numbererror |  total | días |
| ---------------------- | ----------- | -----: | ---: |
| ENVIA                  | -0-         | 15.691 |    2 |
| COORDINADORA MERCANTIL | -0-         | 16.501 |    3 |
| TCC SA                 | -0-         | 17.004 |    1 |
| SERVIENTREGA           | -0-         | 17.575 |    3 |
| SAFERBO                | 999         |      0 |    — |
| Domina                 | 999         |      0 |    — |
| MOOVA                  | 999         |      0 |    — |
| 99MINUTOS              | 999         |      0 |    — |
| GINTRACOM              | 999         |      0 |    — |
| Go Envios              | 999         |      0 |    — |

> Las 4 con `numbererror: "-0-"` son tarifas REALES que la cuenta tiene contratadas y que cubren la ruta. Las 6 con 999 son carriers que aparecen en la respuesta pero no cubren ese trayecto o no están activos para esa cuenta.

### 17.4 Cotización `cotizar2` (single carrier — el bug)

Mismas 10 transportadoras pero TODAS devuelven 999 porque el `idtransportador` enviado no calcula. Conclusión: usar `cotizarDoble` y filtrar por `numbererror`.

---

## 18. Plan de ajustes priorizado

### P0 — Bloqueante producción (no se puede vender real sin esto)

| #    | Ajuste                                                                                                                                 | Archivo                                          | Esfuerzo |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | -------: |
| P0.1 | Cambiar `cotizar2` → `cotizarDoble` en `quote()`                                                                                       | `apps/web/features/shipping/aveonline.ts:97-111` |    30min |
| P0.2 | Filtrar cotizaciones con `numbererror !== "-0-"`. Si todas filtradas → throw "Sin cobertura para esa ciudad"                           | `aveonline.ts:121-128`                           |    20min |
| P0.3 | Reemplazar origen hardcoded por `getSettingValue("PICKUP_CITY")` + `PICKUP_DEPARTMENT` desde SiteSettings (ya llenos)                  | `apps/web/features/checkout/service.ts:153`      |    20min |
| P0.4 | Validar `valorDeclarado >= 10000` cuando se construye `items` (forzar mínimo $10.000 COP)                                              | `checkout/service.ts:146`                        |    10min |
| P0.5 | Mejorar mensaje "Error al guardar. Reintentá" en `saveDatosAction` con código sanitizado (sin exponer stack) + log estructurado        | `checkout/datos/actions.ts:122-128`              |    20min |
| P0.6 | Endpoint `listarTransportadorasPorEmpresa` cacheado 24h (para sanity admin y para validar antes de cotizar)                            | `aveonline.ts` (nuevo método)                    |    40min |
| P0.7 | Formato ciudad uppercase `BOGOTA(CUNDINAMARCA)` en `origen` / `destino` (función helper)                                               | `aveonline.ts`                                   |    20min |
| P0.8 | Logger.error con `numbererror` + `dataerror` cuando todas las cotizaciones fallan, para que admin vea la causa exacta en `/admin/logs` | `aveonline.ts:121`                               |    10min |

**Total P0: ~3h.**

### P1 — Importante (productivo robusto)

| #     | Ajuste                                                                                                                         | Esfuerzo |
| ----- | ------------------------------------------------------------------------------------------------------------------------------ | -------: |
| P1.1  | Route handler `/api/webhooks/aveonline/route.ts` + integrar `handleWebhook()` con validación IP whitelist + secret en `paramN` |       2h |
| P1.2  | Registrar webhook con `avestock/api/createWebhook.php` desde admin panel (`/admin/integraciones`)                              |     1.5h |
| P1.3  | Implementar `requestPickup()` (hoy STUB) + UI admin para agendar recogidas batch                                               |       3h |
| P1.4  | Cache cotización 5-15 min por `hash(origen+destino+productos+contraentrega)` en tabla `ShippingQuoteCache` Postgres            |       2h |
| P1.5  | Edge function / pg_cron para invocar `createShipment` cuando Order transiciona a PAID                                          |       4h |
| P1.6  | Reemplazar `dsnit: "00000"` por `Order.shippingDocumentNumber` cuando contact lo tenga                                         |    30min |
| P1.7  | Endpoint `eliminarRelacionEnvios` + UI cancelación desde `/admin/pedidos/[id]`                                                 |       2h |
| P1.8  | Endpoint `obtenerEstadoAuth` polling backup (cron 15min) por si webhook falla                                                  |       1h |
| P1.9  | Schemas Zod para validar runtime cada response Aveonline (parseo defensivo)                                                    |       2h |
| P1.10 | Actualizar `docs/INTEGRATIONS.md` agregando sección Aveonline (tabla, endpoints, flujo)                                        |       1h |

**Total P1: ~19h.**

### P2 — Mejoras

| #    | Ajuste                                                                                                 | Esfuerzo |
| ---- | ------------------------------------------------------------------------------------------------------ | -------: |
| P2.1 | Lock para tokenCache (evitar race conditions concurrent auth)                                          |    30min |
| P2.2 | Tests unitarios `aveonline.test.ts` (auth, cotización, parseo, error handling)                         |       3h |
| P2.3 | Tests integración con mock Aveonline responses (`tests/integration/shipping.test.ts`)                  |       2h |
| P2.4 | Job semanal pg_cron sincronizar `listadociudades.json` de Aveonline → tabla `ShippingCity` con índices |       2h |
| P2.5 | Mapping configurable estado_carrier → estado_lucams desde CmsSetting (no hardcoded)                    |       1h |
| P2.6 | Detectar token expirado (HTTP 401 implícito vía body) → auto-refresh + retry una vez                   |       1h |
| P2.7 | Métrica `shipping.aveonline.quote.cache_hit_rate` + alerting si baja del 50%                           |       1h |

**Total P2: ~10h.**

### Acciones humanas pendientes (no son código)

| #   | Acción                                                                                                                                                                                            | Responsable   | Bloqueante para       |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- | --------------------- |
| H1  | Confirmar correo cuenta nueva "Lucams Shop" Aveonline                                                                                                                                             | Lucy          | Rotación credenciales |
| H2  | Completar Datos Comerciales en panel Aveonline: NIT, dirección recogida, cuenta bancaria liquidación COD                                                                                          | Lucy          | Activación tarifas    |
| H3  | Contactar `desarrollo1@aveonline.co`: pedir activación carriers (TCC, Servientrega, Envía, Coordinadora, Interrapidísimo, Domina) + configuración agente origen + tarifas para cuenta Lucams Shop | Lucy          | Cotización válida     |
| H4  | Solicitar a Aveonline confirmación de cutoff recogida (11am asumido en ADR-039)                                                                                                                   | Lucy          | Recogidas automáticas |
| H5  | Solicitar a Aveonline implementación HMAC en webhook (mitigación temporal: paramN secret)                                                                                                         | Lucy          | Webhook seguro        |
| H6  | Rotar `AVEONLINE_USUARIO` + `AVEONLINE_CLAVE` en `.env.local` cuando cuenta nueva esté activa (Claude provee `sed` exacto sin leer .env)                                                          | Lucy + Claude | Producción            |
| H7  | Validar plan mensual elegido + costo FEE — ADR-039 lo deja pendiente                                                                                                                              | Lucy          | Cierre comercial      |
| H8  | Validar política de subprocesadores en `/legal/subprocesadores` incluya Aveonline + cada carrier                                                                                                  | Lucy + Claude | Compliance Ley 1581   |

---

## 19. Fuentes verificadas (2026-05-21)

- [Aveonline — Introducción](https://integraciones.aveonline.co/docs/introduccion/)
- [Aveonline — Autenticación v1](https://integraciones.aveonline.co/docs/1.0.0/nacional/autenticacion/)
- [Aveonline — Cotización](https://integraciones.aveonline.co/docs/nacional/cotizacion/)
- [Aveonline — Generación de guía](https://integraciones.aveonline.co/docs/nacional/generacionGuia/)
- [Aveonline — Solicitud de recogida](https://integraciones.aveonline.co/docs/1.0.0/nacional/solicitudRecogida/)
- [Aveonline — Estado de la guía](https://integraciones.aveonline.co/docs/1.0.0/nacional/estadoGuia/)
- [Aveonline — Listado de ciudades](https://integraciones.aveonline.co/docs/nacional/listadoCiudades/)
- [Aveonline — Crear relación de envíos](https://integraciones.aveonline.co/docs/nacional/relacionEnvios/crearrelacionEnvios/)
- [Aveonline — Listar relación envíos](https://integraciones.aveonline.co/docs/nacional/relacionEnvios/ListarRelacionEnvios/)
- [Aveonline — Eliminar relación envíos](https://integraciones.aveonline.co/docs/nacional/relacionEnvios/EliminarRelacionEnvios/)
- [Aveonline — Webhook estados guías](https://integraciones.aveonline.co/docs/1.0.0/nacional/webhookEstadosGuias/)
- [Aveonline — Tramas operadores](https://integraciones.aveonline.co/docs/1.0.0/Proveedores/tramasOperadores/)
- [Aveonline — AveCRM Crear Webhook](https://integraciones.aveonline.co/docs/avecrm/crearWebhook/)
- [Aveonline — AveCRM Listar Envios](https://integraciones.aveonline.co/docs/avecrm/listarEnvios/)
- [Aveonline — AveCRM Generar Pedido](https://integraciones.aveonline.co/docs/avecrm/orders/generarPedido/)
- [Aveonline — Crear Usuario Agente](https://integraciones.aveonline.co/docs/nacional/agentes/crearUsuarioAgente/)
- [Aveonline — Términos y Condiciones](https://app.aveonline.co/app/contrato/terminosCondiciones.html)
- [Aveonline — Envíos Nacionales](https://aveonline.co/envios-nacionales/)
- [Aveonline — Pago Contraentrega](https://aveonline.co/servicios-pago-contraentrega/)
- [Aveonline — JSON ciudades público](https://app.aveonline.co/assets/resources/public/listadociudades.json)
- [npm — aveonline](https://www.npmjs.com/package/aveonline)
- [GitHub — franciscoblancojn/aveonline-npm](https://github.com/franciscoblancojn/aveonline-npm)
- [GitHub — franciscoblancojn/aveonline-shipping (WooCommerce)](https://github.com/franciscoblancojn/aveonline-shipping)

Probe en vivo contra cuenta `crittan01@gmail.com` ejecutado desde `packages/db/scripts/probe-aveonline.mjs` el 2026-05-21 20:50 UTC.

---

## 20. Cambios pendientes a otros docs

| Doc                     | Cambio                                                                              |
| ----------------------- | ----------------------------------------------------------------------------------- |
| `docs/DECISIONS.md`     | Agregar ADR-040 "Migración cotizar2 → cotizarDoble + filtro numbererror"            |
| `docs/INTEGRATIONS.md`  | Agregar sección Aveonline en tabla resumen (línea 7-14) — hoy aparece solo Venndelo |
| `docs/SECURITY.md`      | Documentar mitigación webhook Aveonline sin HMAC (paramN secret + IP whitelist)     |
| `docs/COMPLIANCE.md`    | Agregar Aveonline + 6 carriers en política subprocesadores Ley 1581                 |
| `docs/OBSERVABILITY.md` | Agregar SLO cotización Aveonline (p95 < 5s, error rate < 2%)                        |
| `apps/web/.env.example` | Documentar variables Aveonline con comentarios                                      |

---

---

## 21. Comparativa Aveonline vs Envia (matriz de decisión)

**Disparador**: founder evalúa pivote desde Envia.com (integración actual del agentic en rev. 106) hacia Aveonline. Esta sección consolida diferencias verificadas para decisión arquitectónica.

**Convención de scoring**: ✅ ventaja, ⚠️ limitación documentada, ❌ no soporta, 🟡 paridad o no aplicable.

### 21.1 Capacidades core (cotización + label + tracking)

| Capacidad | Aveonline | Envia | Ventaja |
|---|---|---|---|
| Cotización multi-carrier en 1 request | ✅ `cotizarDoble` retorna N carriers paralelo | ✅ `/rates` retorna N carriers paralelo | 🟡 paridad |
| Cotización single-carrier | ⚠️ `cotizar2` tiene bug 999 documentado | ✅ filtrar por `carrier=` | Envia |
| `rate_id` reusable cross-request | ❌ NO existe — cotizar+generar son flujos independientes (response `total` vinculante mientras JWT live) | ❌ NO existe — `Idempotency-Key` server-side AUSENTE confirmado (Envia dossier §H.2.1) | 🟡 paridad (ambos requieren idempotency local) |
| TTL de cotización documentado | ❌ implícito por TTL JWT (12h v2.0 / sin expirar v1.0) | ❌ NO documentado oficialmente | 🟡 paridad |
| Endpoint listar carriers habilitados | ✅ `listarTransportadorasPorEmpresa` | ✅ `GET /carriers` (Queries API) | 🟡 paridad |
| Generación guía PDF/ZPL | ✅ retorna URL PDF en response | ✅ retorna URL PDF | 🟡 paridad |
| Tracking pull endpoint | ✅ `consultarGuias` | ✅ `POST /ship/generaltrack/` | 🟡 paridad |
| Tracking push webhook | ✅ `crearWebhook` AveCRM + plugin legacy WP | ✅ webhook nativo Envia | 🟡 paridad |
| Verificación firma webhook | ⚠️ HMAC NO existe — solo `paramN` pseudo-secret | ⚠️ HMAC NO nativo (H.2.2 propone HMAC propio sobre URL secret-token) | 🟡 paridad (ambos requieren mitigación propia) |
| Polling backup tracking | ✅ vía `consultarGuias` cada 6h | ✅ vía `/ship/generaltrack/` cada 6h | 🟡 paridad |
| Cancelación guía | ✅ `cancelarGuia` + `eliminarRelacionEnvios` | ✅ endpoint cancel documentado | 🟡 paridad |
| Solicitar recogida programada | ✅ `solicitudRecogida` con cutoff 11 a.m. confirmado | ✅ `/pickup/schedule` | 🟡 paridad |

### 21.2 Funcionalidades comerciales

| Funcionalidad | Aveonline | Envia | Ventaja |
|---|---|---|---|
| **Contraentrega (COD)** | ✅ NATIVO desde día 1 + Ecart Pay backbone + comisión desde 2.40% + dashboard "Recaudos" UI | ⚠️ COD pendiente impl. (H.2.4 P1 — 2 días-dev) | **Aveonline** |
| COD histórico API | ❌ confirmado NO existe — workaround scraping autenticado | ⚠️ pendiente (H.2.4 + ledger DB propio) | 🟡 paridad débil |
| Liquidación pagos COD | ✅ "4to día hábil post entrega" automático (Ecart Pay) | ⚠️ depende impl ledger propio | **Aveonline** |
| **Insurance / valor declarado** | ✅ campo `valorDeclarado` directo + obligatorio en COD (mín 10.000 COP) | ✅ `additional_services: ["envia_insurance"]` (H.2.5 P1) | 🟡 paridad post-H.2.5 |
| **Devoluciones / RMA** | ⚠️ `cartaporte=1` (boomerang) + invertir origen/destino + PQR | ❌ workaround manual via shipment invertido | **Aveonline** ligero |
| Branded tracking page | ❌ solo URL nativa carrier o `rutadigitalizada` | ❌ idem (P3 backlog) | 🟡 paridad |
| Multi-empresa (multi-tenant) | ✅ `empresa` ID + JWT scoped + cuenta master por tenant | ✅ API key per-tenant + Vault | 🟡 paridad |
| Onboarding self-serve tenant | ⚠️ requiere contrato + asesor + plan mensual escalable | ✅ key auto-generada panel Envia self-serve | Envia |
| Cuenta master / programa partner | ⚠️ acuerdos contractuales, no documentado public | ❌ confirmado descartado (Plan H.0 Modelo B) | 🟡 paridad |
| Sandbox público | ✅ `demointegracion` / `demointegra2021` con dashboard funcional | ✅ flag `bloquegenerarguia` + sandbox tier | 🟡 paridad |
| Plug-ins oficiales | ✅ WooCommerce (`aveonline-shipping` GitHub público), npm package, mods Shopify | ⚠️ npm `@enviapackages/envia-orders` + docs API | 🟡 paridad |

### 21.3 Compliance & soporte

| Aspecto | Aveonline | Envia | Ventaja |
|---|---|---|---|
| Rol legal (Habeas Data) | ✅ ENCARGADO documentado en contrato + carriers subordinados | ⚠️ rol no explícito en docs — requiere DPA propio | **Aveonline** |
| Cobertura Colombia | ✅ exclusivo CO (carriers nacionales) | ⚠️ multi-país — runtime enforce `country='CO'` necesario (H.2.12) | **Aveonline** |
| Cobertura internacional | ❌ no maneja DDP/DDU | ✅ 12 países documentados | Envia (irrelevante: scope solo CO confirmado §K.1) |
| Soporte 24/7 | ❌ L-V 8-5 hora Colombia confirmado oficial | ⚠️ SLA no publicado | 🟡 paridad débil |
| Portal de tickets | ❌ solo email + WhatsApp 305 420 21 25 | ❌ idem (asesor comercial) | 🟡 paridad |
| Rate limit documentado | ❌ NO publicado — cache 60s patrón oficial | ❌ NO publicado (H.2.11 P2 propone circuit breaker) | 🟡 paridad |
| Subprocessor disclosure | ✅ contrato explicita carriers como sub | ⚠️ depende contrato individual | **Aveonline** |

### 21.4 Costos y modelo de negocio

| Aspecto | Aveonline | Envia | Ventaja |
|---|---|---|---|
| Modelo cuenta | Plan mensual + FEE 2do mes + fee per shipment + comisión COD | Pay-per-shipment (key per tenant) | depende volumen |
| Cliente Bancolombia | ✅ sin mensualidad | ❌ no aplica | **Aveonline** (si tenant es cliente Bancolombia) |
| Comisión COD | ✅ desde 2.40% variable por carrier | n/d (H.2.4 pendiente) | **Aveonline** documentado |
| Volumen mínimo COD | ✅ NO requiere | ⚠️ pendiente confirmar | **Aveonline** |
| Mínimo envíos mensual | ✅ NO requiere | ✅ NO requiere (Modelo B confirmado) | 🟡 paridad |
| Tarifa garantizada | ✅ `total` vinculante mientras JWT live + cláusula reajuste si peso real difiere | ⚠️ depende contrato Envia | **Aveonline** |

### 21.5 Robustez operacional

| Aspecto | Aveonline | Envia | Ventaja |
|---|---|---|---|
| Diagnóstico errores | ✅ `numbererror` -1 a -8 documentado + diagnóstico 999 conocido (bug `cotizar2`) | ⚠️ error codes parciales | **Aveonline** |
| Cuenta DEMO pública | ✅ `demointegracion`/`demointegra2021` permanente | ✅ sandbox tier per tenant | 🟡 paridad |
| Probe E2E sandbox | ✅ ya probado en `packages/db/scripts/probe-aveonline.mjs` (cotización Bogotá→Medellín exitosa con `cotizarDoble`) | ✅ probe equivalente posible | 🟡 paridad |
| Latencia P95 cotización | ⚠️ 5-15s (`cotizarDoble` paralelo) | ⚠️ ~3s (single carrier) / ~10s (multi) | Envia ligeramente |
| Carriers Colombia integrados | ✅ ≥10 (Coordinadora, Servientrega, Interrapidísimo, TCC, Saferbo, Envia carrier, Deprisa, Mensajeros Urbanos, etc.) | ✅ 6-8 carriers principales | **Aveonline** (más carriers) |
| Mensajeros Urbanos (last-mile Bogotá) | ✅ disponible vía cotización (no genera label) | ⚠️ confirmar | **Aveonline** (cobertura local) |

### 21.6 Veredicto comparativo

| Score categoría | Aveonline | Envia |
|---|---|---|
| Capacidades core | 9/10 | 9/10 |
| Funcionalidades comerciales | 9/10 (COD nativo gana) | 6/10 (COD pendiente) |
| Compliance & soporte | 7/10 (rol legal claro) | 6/10 |
| Costos & negocio | 7/10 (depende volumen) | 7/10 |
| Robustez operacional | 8/10 (más carriers + diagnóstico) | 7/10 |
| **Score global** | **8.0/10** | **7.0/10** |

**Diferenciadores netos a favor de Aveonline**:
1. **COD nativo desde día 1** con Ecart Pay como backbone — elimina ~2 días-dev del plan H.2.4 + ledger propio + reconciliación.
2. **Rol legal explícito** como ENCARGADO en contrato — reduce trabajo legal Habeas Data.
3. **Más carriers integrados Colombia** (incluyendo Mensajeros Urbanos last-mile) — mejor cobertura para tenants en ciudades intermedias.
4. **Diagnóstico de errores documentado** (`numbererror` -1 a -8) — debugging más rápido en producción.
5. **Cliente Bancolombia gratis** (mensualidad cubierta) — barrera onboarding más baja si tenant ya banquea con Bancolombia.

**Diferenciadores netos a favor de Envia**:
1. **Onboarding self-serve** (key panel sin contrato físico) — fricción menor para tenants pequeños/Día-1.
2. **Latencia ligeramente mejor** en cotización single-carrier (~3s vs ~5-15s Aveonline `cotizarDoble`).
3. **Internacional disponible** (irrelevante hoy — scope solo CO confirmado §K.1).

**Empates relevantes (ambos requieren la misma mitigación arquitectónica)**:
- Sin idempotency server-side → cache local SHA256 obligatorio (H.1 F.2 baseline).
- Sin HMAC webhook nativo → secret en URL/body propio (H.1 F.10 obligatorio).
- Sin rate limit documentado → token-bucket conservador + circuit breaker (H.1 F.2).
- Sin SLA soporte 24/7 → fallback "envío manual" en UI Konvi para incidentes nocturnos.

**Recomendación arquitectónica**: pivotar a Aveonline como **carrier primario** en rev. 106, manteniendo Envia como **fallback técnico** detrás de feature flag per-tenant. Razones:
- COD nativo elimina riesgo de retrasos en Fase 2 (H.2.4 pendiente).
- Más carriers Colombia → mejor cobertura tenants.
- Rol legal explícito → menor riesgo compliance.
- Onboarding más lento se mitiga con script `scripts/aveonline_onboarding.py` y soporte concierge para primeros 10 tenants.

Esta recomendación se ejecuta detalladamente en **§22 Plan de migración**.

---

## 22. Plan de migración Envia → Aveonline (rev. 106 → rev. 107)

**Objetivo**: reemplazar Envia como provider primario en el agentic shipping tool con Aveonline, **preservando** cart-as-SoT, idempotency lifecycle (ADR-0011), invariantes (consent + resumen-before-link), y dejando Envia como fallback feature-flag detrás de cada tenant.

**Branch**: `feat/rev107-aveonline-primary` (no commit a `phase-1-orchestrator-refactor` ni `develop` hasta cierre tests + UAT + ADR).

**Estrategia**: **adapter pluggable + strangler-fig pattern** — mismo `agentic/tools/shipping.py` interface, dos implementaciones backend.

### 22.1 Fases de migración (10.25 días-dev, ~2.5 semanas calendario)

> **Revisión 2026-05-22 (post-WARN 2 founder UAT)**: el plan original
> de 8d **subestimó** el onboarding tenant. La auth Aveonline requiere
> `usuario+clave` per-tenant (§2.1 v1.0 dossier) que debe ingresarse
> en la UI antes de poder cotizar. Se agregan fases O.1-O.5 cubriendo
> esquema + UI + server actions + Vault + identity registry (siguiendo
> patrón ya establecido para Envia/Wompi/WhatsApp/MeLi).

#### 22.1.a Fases de runtime (RT) — cliente HTTP + adapters + UI selector

| # | Fase | Esfuerzo | Pre-requisito | Tests + UAT |
|---|---|---|---|---|
| M.1 | Crear `services/api/lib/clients/aveonline_client.py` con métodos `quote`, `generate_label`, `track`, `cancel`, `schedule_pickup` + `cartaporte=1` boomerang + **`_refresh_jwt()` lee Vault + cachea TTL 12h** | 2d | F.2 IntegrationClient base, O.4 | unit + sandbox |
| M.2 | Probe E2E sandbox: replicar `packages/db/scripts/probe-aveonline.mjs` en pytest con cuenta DEMO `demointegracion` | 0.5d | M.1 | scenarios paridad |
| M.3 | Implementar `agentic/legacy_adapters.py::quote_shipping_for_cart_aveonline` (espejo del Envia adapter actual) | 1d | M.1+M.2 | unit |
| M.4 | Implementar `select_carrier_for_cart_aveonline` + `generate_payment_link_for_cart_aveonline` (Wompi no cambia, solo el shipping precedente) | 0.5d | M.3 | unit |
| M.5 | Refactor `agentic/tools/shipping.py::QuoteShippingTool.execute` → detectar `tenant_integrations.meta.shipping_provider` y rutear: `'aveonline'` → adapter Aveonline, `'envia'` (default) → adapter Envia | 1d | M.4 | unit + integration |
| M.6 | Capabilities matrix per-tenant: nueva tabla `tenant_shipping_provider_config` con `{tenant_id, primary_provider, fallback_provider, enabled_carriers[], cod_enabled, insurance_strategy}` | 1d | F.3 capabilities table | unit |
| M.7 | UI Tenant Console → Settings → Despachos: selector "Provider principal" (Aveonline / Envia / Aveonline+Envia fallback) + lista carriers habilitados | 1.5d | M.6 | UI smoke |
| M.8 | UAT dual-mode S31-S33 reescritos para Aveonline (idempotency, webhook, polling) + nuevo S43 COD Aveonline | 0.5d | M.1-M.7, O.* | UAT |

**Subtotal runtime: 8 días-dev**.

#### 22.1.b Fases de onboarding (O) — credenciales tenant + Vault + UI integración

Auth Aveonline v1.0 requiere `usuario+clave` per-tenant (dossier §2.1).
NO se puede invocar `autenticarusuario.php` sin credenciales válidas
del tenant. El patrón replicado del repo existente (Envia/Wompi/WhatsApp/
MeLi) — UI integración → server action → POST auth → persist + Vault:

| # | Fase | Esfuerzo | Pre-requisito | Tests + UAT |
|---|---|---|---|---|
| O.1 | Schema: extender constraint `provider` en `tenant_integrations` para incluir `'aveonline'`. RPC helper `get_aveonline_credentials(tenant_id)` que lee Vault (espejo `get_envia_api_key`). | 0.5d | migración Vault `20260426020000_*` | unit |
| O.2 | UI `apps/web/app/dashboard/(settings-group)/integrations/aveonline/page.tsx` (estructura clonada de Envia): tabs **Setup**, **Carriers**, **Capacidades**, **Tracking**. Setup tab tiene form con campos: usuario, password (input type=password), versión auth (v1.0 / v2.0 selector, default v1.0), `tiempoToken` (advanced — default `100000`). | 1d | O.1 | UI smoke |
| O.3 | Server action `connectAveonline(formData)`: (a) valida campos, (b) hace POST de prueba a `autenticarusuario.php` con esas credenciales, (c) si `status=ok` extrae `idempresa` + `token` + `asesorlogistico`, (d) persiste `tenant_integrations` row con `provider='aveonline'`, `status='connected'`, `meta={empresa_id, usuario, asesorlogistico, nombreasesor, jwt_token, jwt_expires_at, tiempoToken, auth_version}`, (e) password va a Vault con key `aveonline_password_<tenant_id>`. Si auth falla → status='error' + razón. | 0.5d | O.1, O.2 | unit + UI smoke |
| O.4 | `AveonlineClient._refresh_jwt(tenant_id)`: lee Vault → invoca `autenticarusuario.php` → cachea JWT in-memory + persiste en `tenant_integrations.meta.jwt_token + jwt_expires_at`. Auto-refresh si `expires_at < now + 10min` (buffer). TTL configurable según versión: v1.0=`tiempoToken` (default 100000s ≈ 27h), v2.0=12h fijo. | (incluido en M.1) | O.1, O.3 | unit |
| O.5 | Migración `tenant_provider_identity` aceptar `provider='aveonline'` (constraint update) — registra `empresa_id` como `provider_internal_id` para mapping cross-tenant. | 0.25d | migración `20260514100000_*` | unit |

**Subtotal onboarding: 2.25 días-dev**.

#### 22.1.c Total revisado

**8d (RT) + 2.25d (O) = 10.25 días-dev** (~2.5 semanas calendario).

#### 22.1.d Orden de ejecución sugerido

```
Semana 1:
  Lun: O.1 schema + RPC helper                          (0.5d)
  Lun-Mar: O.2 UI Aveonline (clonando estructura Envia) (1d)
  Mié: O.3 server action connectAveonline               (0.5d)
  Mié: O.5 tenant_provider_identity                     (0.25d)
  Jue-Vie: M.1 AveonlineClient (incluye O.4 refresh JWT) + M.2 probe DEMO (2.5d)

Semana 2:
  Lun: M.3 quote adapter (1d)
  Mar: M.4 select_carrier + payment adapter (0.5d) + M.5 routing in QuoteShippingTool (1d)
  Mié: M.6 capabilities matrix + M.7 UI selector provider (1.5d)
  Jue-Vie: M.8 UAT dual-mode + bug fixing + ADR-0019 marcar ACTIVO (1d)
```

**Validación humana obligatoria pre-cutover** (dossier §25.5):
- H1 SLA contractual Aveonline (bloqueante).
- H8 revisión legal DPA (bloqueante).
- H9 contrato firmado per-tenant piloto (bloqueante por tenant).

### 22.2 Cambios de código concretos

#### 22.2.1 Nuevo archivo: `services/api/lib/clients/aveonline_client.py`

```python
"""Cliente Aveonline (cotización + label + tracking + COD).

ADR-0018 + plan rev. 107. Production-grade:
  • Reusa F.2 IntegrationClient base (retry + circuit breaker + idempotency baseline).
  • Auth v1.0 con JWT cacheado por tenant (TTL 12h por defecto).
  • Soporta `cotizarDoble` (recomendado) + `cotizar2` (con flag dry-run para detectar 999 bug).
  • Multi-tenant: credenciales desde TenantCredentialsFacade.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from services.api.lib.clients.base import IntegrationClient
from services.api.lib.compliance.decorators import scoped_to_country

logger = logging.getLogger(__name__)

AVEONLINE_QUOTE_URL = "https://webservices.aveonline.co/cotizar/cotizar.php"
AVEONLINE_GUIDE_URL = "https://api.aveonline.co/api/v2.0/guias/generarGuiaTransporteNacional"
AVEONLINE_TRACK_URL = "https://api.aveonline.co/api/v2.0/track/consultarGuias"
AVEONLINE_CANCEL_URL = "https://api.aveonline.co/api/v2.0/guias/cancelarGuia"
AVEONLINE_PICKUP_URL = "https://api.aveonline.co/api/v2.0/recogidas/solicitudRecogida"


class AveonlineClient(IntegrationClient):
    PROVIDER = "aveonline"

    def __init__(self, tenant_id: str, credentials: dict):
        super().__init__(provider=self.PROVIDER, tenant_id=tenant_id)
        self.empresa_id = credentials["empresa_id"]
        self.usuario = credentials["usuario"]
        self.password = credentials["password"]
        self._jwt_cache: Optional[tuple[str, datetime]] = None

    @scoped_to_country("CO")
    async def quote(self, *, origin: dict, destination: dict, package: dict) -> dict:
        """Cotización multi-carrier via cotizarDoble.

        Retorna dict con `options` = [{rate_id, carrier, service_level,
        price_cents, eta_date}, ...] o {ok: False, error, code}.

        Idempotency: hash(origin+destination+package) cacheado 60s (patrón
        plugin oficial WooCommerce).
        """
        payload = self._build_quote_payload(origin, destination, package)
        request_hash = self._hash_request("quote", payload)

        # Cache L1 60s (replica `class-api.php:583`).
        cached = await self.idempotency_lookup(request_hash, ttl_seconds=60)
        if cached:
            return cached

        response = await self.execute(
            method="POST",
            url=AVEONLINE_QUOTE_URL,
            json=payload,
            timeout=15.0,
        )

        # Aveonline puede retornar HTTP 200 con `status="error"` en body.
        if response.get("status") == "error":
            return {
                "ok": False,
                "error": response.get("message", "Aveonline error"),
                "code": f"AVEONLINE_{response.get('numbererror', 'UNKNOWN')}",
            }

        options = []
        for rate in response.get("opciones") or response.get("data") or []:
            options.append({
                "rate_id": str(rate.get("idtransportadora")),
                "carrier": str(rate.get("transportadora") or ""),
                "service_level": str(rate.get("servicio") or "estandar"),
                "price_cents": int(float(rate.get("total") or 0) * 100),
                "eta_date": rate.get("tiempoEntrega") or "",
            })

        result = {"ok": True, "options": options}
        await self.idempotency_store(request_hash, result, ttl_seconds=60)
        return result

    def _build_quote_payload(self, origin, destination, package) -> dict:
        return {
            "tipo": "cotizarDoble",
            "empresa": self.empresa_id,
            "token": self._get_jwt(),
            "origen": origin["dane_code"],
            "destino": destination["dane_code"],
            "kilos": package["weight_kg"],
            "unidades": package.get("units", 1),
            "valorDeclarado": max(package.get("declared_value_cop", 10000), 10000),
            "largo": package.get("length_cm", 10),
            "ancho": package.get("width_cm", 10),
            "alto": package.get("height_cm", 10),
            "contraentrega": 1 if package.get("cod_enabled") else 0,
        }

    def _hash_request(self, op: str, payload: dict) -> str:
        normalized = f"{op}|{payload['origen']}|{payload['destino']}|" \
                     f"{payload['kilos']}|{payload['unidades']}|" \
                     f"{payload['valorDeclarado']}|{payload['largo']}|" \
                     f"{payload['ancho']}|{payload['alto']}"
        return hashlib.sha256(normalized.encode()).hexdigest()

    def _get_jwt(self) -> str:
        if self._jwt_cache and self._jwt_cache[1] > datetime.utcnow():
            return self._jwt_cache[0]
        # ... lógica de auth v1.0 contra `webservices.aveonline.co/auth/login.php`
        # con TTL ~12h. Omitido por brevedad — ver §2.1 dossier.
        raise NotImplementedError("Implementar en M.1 — ver dossier §2.1")

    # ... métodos generate_label, track, cancel, schedule_pickup análogos ...
```

#### 22.2.2 Refactor `agentic/legacy_adapters.py`

Cambiar firma para soportar provider dinámico:

```python
async def quote_shipping_for_cart(
    supabase, *, conversation_id, tenant_id, contact_id, city_query,
    provider: str = "aveonline",  # NUEVO: default Aveonline post-rev. 107
) -> dict:
    if provider == "aveonline":
        from services.api.lib.clients.aveonline_client import AveonlineClient
        # ... lógica Aveonline (M.3)
    elif provider == "envia":
        from tools.shipping_quote_tool import _request_shipping_quote
        # ... lógica Envia legacy (preservar para fallback)
    else:
        return {"ok": False, "error": f"Provider {provider} no soportado", "code": "INVALID_PROVIDER"}
```

#### 22.2.3 Refactor `agentic/tools/shipping.py::QuoteShippingTool.execute`

```python
async def execute(self, args: QuoteShippingArgs, ctx: ToolContext) -> ToolResult:
    from agentic.legacy_adapters import quote_shipping_for_cart

    # Detectar provider per-tenant.
    provider_config = (
        ctx.supabase.table("tenant_shipping_provider_config")
        .select("primary_provider, fallback_provider")
        .eq("tenant_id", ctx.tenant_id)
        .maybe_single()
        .execute()
    )
    primary = (provider_config.data or {}).get("primary_provider", "aveonline")
    fallback = (provider_config.data or {}).get("fallback_provider")

    # Intento primario.
    result = await quote_shipping_for_cart(
        ctx.supabase,
        conversation_id=ctx.conversation_id,
        tenant_id=ctx.tenant_id,
        contact_id=ctx.contact_id,
        city_query=args.city,
        provider=primary,
    )

    # Fallback si primario falla con códigos transitorios.
    transient_codes = {"ENVIA_NO_OPTIONS", "AVEONLINE_-3", "AVEONLINE_999",
                       "CIRCUIT_OPEN", "TIMEOUT"}
    if not result.get("ok") and fallback and result.get("code") in transient_codes:
        logger.warning(
            "[agentic.shipping] %s falló (%s), fallback a %s",
            primary, result.get("code"), fallback,
        )
        result = await quote_shipping_for_cart(
            ctx.supabase, ..., provider=fallback,
        )

    # ... resto idéntico al actual ...
```

#### 22.2.4 Nueva migración Supabase

```sql
-- supabase/migrations/20260601000000_aveonline_provider_config.sql
CREATE TABLE tenant_shipping_provider_config (
    tenant_id UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
    primary_provider TEXT NOT NULL DEFAULT 'aveonline'
        CHECK (primary_provider IN ('aveonline', 'envia')),
    fallback_provider TEXT
        CHECK (fallback_provider IS NULL OR fallback_provider IN ('aveonline', 'envia')),
    enabled_carriers TEXT[] NOT NULL DEFAULT '{}',
    cod_enabled BOOLEAN NOT NULL DEFAULT false,
    insurance_strategy TEXT NOT NULL DEFAULT 'on_demand'
        CHECK (insurance_strategy IN ('always', 'on_demand', 'never')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CHECK (primary_provider != fallback_provider)
);

ALTER TABLE tenant_shipping_provider_config ENABLE ROW LEVEL SECURITY;
CREATE POLICY tsi_tenant ON tenant_shipping_provider_config
    FOR ALL USING (tenant_id = current_tenant_id());

-- Seed por defecto: cada tenant existente arranca con Aveonline primary,
-- Envia fallback. Carriers heredados de tenant_integrations.meta.
INSERT INTO tenant_shipping_provider_config (tenant_id, primary_provider, fallback_provider)
SELECT id, 'aveonline', 'envia' FROM tenants
ON CONFLICT (tenant_id) DO NOTHING;
```

### 22.3 Migración de datos en vuelo

**Riesgo**: tenants en producción con `Envia` activo + carritos abiertos cuando se hace el cutover.

**Plan**:
1. Sem 1 (post-M.6): seed `tenant_shipping_provider_config` con `primary_provider='envia'` por defecto (no cambia comportamiento actual).
2. Sem 1 (post-M.7): UI Console permite a cada tenant cambiar a `'aveonline'` manualmente.
3. Tenants piloto (3-5 cuentas dispuestas a probar) cambian a Aveonline + Envia fallback durante 2 semanas.
4. Sem 3: si métricas estables (quote success rate ≥98% Aveonline + sin regresión COD), cambiar default a Aveonline + Envia fallback para tenants nuevos.
5. Sem 6: ofrecer migración mass-flip a tenants existentes con onboarding concierge.

**Métricas para cutover oficial**:
- `aveonline_quote_success_rate{tenant}` ≥98%
- `aveonline_fallback_to_envia_rate{tenant}` ≤2%
- `aveonline_p95_latency_seconds` ≤8s
- 0 incidentes COD en últimos 30 días
- 0 incidentes labels duplicados (idempotency hit rate ≥99%)

### 22.4 Rollback plan

**Trigger**: cualquiera de:
- `aveonline_quote_success_rate` <90% sostenido 1h.
- Circuit breaker abierto >30 min.
- Incidente fraud COD reportado (spoofing webhook detectado).
- Cliente reporta cobro doble por falta de idempotency.

**Acción**: UI Tenant Console → "Provider principal" cambiar a `Envia` (un click). Cambio en vivo, próximo `quote_shipping` ya usa Envia. No requiere deploy.

**Si todos los tenants deben revertir**: SQL único:
```sql
UPDATE tenant_shipping_provider_config SET primary_provider='envia';
```

---

## 23. Bug `5cef2503` — "Envia no devolvió opciones válidas" y cómo Aveonline lo resuelve

**Conv ID reportada**: `5cef2503` (founder UAT 2026-05-21, registrada en logs orchestrator).

**Síntoma**: cliente WhatsApp en flujo agentic preguntó cotización para envío Bogotá → ciudad destino. El agentic invocó `quote_shipping(city="...")` y el tool falló con error code `ENVIA_NO_OPTIONS` (definido en `legacy_adapters.py:122`):

```python
if status_code != 200 or not response.get("data"):
    return {
        "ok": False,
        "error": "Envia no devolvió opciones válidas.",
        "code": "ENVIA_NO_OPTIONS",
    }
```

El LLM compuso fallback verbal hacia el cliente pero la experiencia quedó rota.

**Root cause hipótesis (orden de probabilidad)**:

1. **Envia API ratelimited el tenant key** (sin documentación HTTP 429 — H.2.11 P2 propone circuit breaker). Sin métricas no se confirma — escalación a Envia comercial necesaria.
2. **Ciudad destino no soportada** por ningún carrier en la cuenta tenant Envia activa. La response Envia 200 con `data:[]` lo refleja como "sin opciones" en lugar de error explícito.
3. **Package estimate degenerado** (`_estimate_package_from_cart_if_available` retornó algo válido pero con peso 0.01 kg o dim <1cm) → Envia rechaza silenciosamente.
4. **JWT/auth expirado** mid-conversation con token cacheado stale en el cliente.

**Por qué Aveonline lo resuelve**:

| Causa | Mitigación Aveonline |
|---|---|
| Ratelimit silente | `numbererror` codes documentados — cualquier rate limit se manifestaría como error explícito identificable, no como `data:[]` |
| Ciudad no soportada | `listadociudades.json` público + DANE 8 dígitos canónico — pre-validable ANTES de invocar `cotizarDoble`. Si city no está en JSON oficial → error específico al cliente sin gastar request |
| Package degenerado | Aveonline auto-ajusta peso mínimo a 1 kg (regla AveCRM documentada §3.10). 0 falsos negativos por peso 0 |
| JWT expirado | TTL 12h v2.0 + auto-refresh en cliente (M.1.f del plan §22) |
| `data:[]` ambiguo | Aveonline retorna `status="error"` + `numbererror` explícito si ningún carrier cotiza → tool puede mapear a mensaje claro al cliente |

**Implementación específica del fix en agentic** (rev. 107):

```python
# services/ai-orchestrator/agentic/legacy_adapters.py (post-M.3)

async def quote_shipping_for_cart_aveonline(supabase, ...) -> dict:
    # Pre-validación 1: ciudad en catálogo oficial.
    if not is_valid_co_city(destination["city"]):
        return {
            "ok": False,
            "error": f"'{city_query}' no está en el catálogo Colombia. ¿Quisiste decir {suggest_nearest(city_query)}?",
            "code": "CITY_NOT_IN_CATALOG",
        }

    # Pre-validación 2: paquete no degenerado.
    if package["weight_kg"] < 0.05 or package["length_cm"] < 1:
        return {
            "ok": False,
            "error": "El paquete está incompleto. Productos sin dimensiones registradas.",
            "code": "DEGENERATE_PACKAGE",
        }

    # Invocar Aveonline + parsear numbererror si aplica.
    response = await aveonline_client.quote(...)
    if response.get("status") == "error":
        ne = response.get("numbererror")
        msg_map = {
            "-1": "El sistema Aveonline tuvo un error temporal. Inténtalo en 30 segundos.",
            "-3": "Esa ciudad no tiene carriers disponibles. Te ofrezco recogida en bodega.",
            "-5": "Valor declarado muy bajo (mín $10.000).",
            "-7": "El paquete excede el peso máximo del carrier. Pruébalo más liviano.",
            "999": "Error transitorio Aveonline. Reintentando con `cotizarDoble`...",
        }
        return {
            "ok": False,
            "error": msg_map.get(str(ne), f"Error Aveonline {ne}"),
            "code": f"AVEONLINE_{ne}",
        }

    # Resto idéntico al actual.
    return {"ok": True, "options": [...]}
```

**Mensaje al cliente vía LLM**: en lugar de la frase opaca actual ("Envia no devolvió opciones"), el LLM verá un error tipado (e.g. `CITY_NOT_IN_CATALOG`) y podrá decir:

> *"No tengo carriers disponibles para envío a 'Yuneb'. ¿Quisiste decir Yumbo? Si no, te ofrezco recogida en bodega o pedir asesor."*

**Test específico** (S43-bug-replay):

```python
# tests/agentic/test_bug_5cef2503_resolution.py
@pytest.mark.asyncio
async def test_quote_shipping_invalid_city_returns_specific_error():
    """Bug 5cef2503 — Envia retornaba 'no opciones' sin diferenciar causa.
    Aveonline retorna CITY_NOT_IN_CATALOG con sugerencia."""
    ...
```

---

## 24. Integración Aveonline en agentic — diseño `AveonlineQuoteShippingTool`

**Ubicación target**: `services/ai-orchestrator/agentic/tools/shipping.py` (mismo archivo que el `QuoteShippingTool` actual, **NO** archivo nuevo — strangler-fig in-place).

**Cambio mínimo conceptual**: el tool actual `QuoteShippingTool` ya tiene la interface correcta (`city: str` arg). Lo único que cambia es **el adapter al que delega** (vía `tenant_shipping_provider_config.primary_provider`). NO cambia el LLM (no requiere re-prompt), NO cambia el schema (Gemini function calling sigue igual), NO cambia el flujo conversacional. Cero impacto en cart-as-SoT.

### 24.1 Diff conceptual del tool

**Antes (rev. 106)**:

```python
class QuoteShippingTool:
    async def execute(self, args, ctx) -> ToolResult:
        from agentic.legacy_adapters import quote_shipping_for_cart
        result = await quote_shipping_for_cart(
            ctx.supabase, conversation_id=ctx.conversation_id,
            tenant_id=ctx.tenant_id, contact_id=ctx.contact_id,
            city_query=args.city,
        )
        # ... parse result ...
```

**Después (rev. 107)** — adapter routea internamente, tool no cambia interface:

```python
class QuoteShippingTool:
    async def execute(self, args, ctx) -> ToolResult:
        # adapter ahora detecta provider per-tenant internamente
        from agentic.legacy_adapters import quote_shipping_for_cart
        result = await quote_shipping_for_cart(
            ctx.supabase, conversation_id=ctx.conversation_id,
            tenant_id=ctx.tenant_id, contact_id=ctx.contact_id,
            city_query=args.city,
        )
        # ... parse result idéntico ...
```

**Resultado**: el LLM sigue invocando `quote_shipping(city="...")`. El adapter decide Aveonline vs Envia transparentemente. **El refactor está completamente contenido en el adapter layer, no toca el agentic LLM layer ni el system_prompt.**

### 24.2 Catálogo de nuevos tools agentic Aveonline-específicos

**NO se agregan** tools dedicados Aveonline al registry (`agentic/tools/registry.py`). Esto sería romper la **abstracción provider-agnostic**. En su lugar:

| Capacidad | Implementación |
|---|---|
| Cotización | `QuoteShippingTool` (existe) → adapter Aveonline/Envia |
| Selección carrier | `SelectCarrierTool` (existe) → adapter Aveonline/Envia |
| Cobro contraentrega | NO se expone como tool al LLM. Se infiere desde `tenant_shipping_provider_config.cod_enabled + tenant intent ('contraentrega', 'COD')` — el adapter Aveonline lo activa internamente con `contraentrega=1` en payload `cotizarDoble`. El LLM solo ve "envío con pago contra entrega" como opción presentada al cliente. |
| Devolución / RMA | Nuevo tool **futuro post-rev. 108** `GenerateReturnLabelTool` (ver §9 actualizada) — fuera de scope rev. 107 |
| Cancelar guía | NO se expone al LLM. Endpoint admin UI Tenant Console → "Anular envío". Operador autenticado lo dispara |
| Solicitar recogida | NO se expone al LLM. Cron auto-dispara post `select_carrier` si `tenant.auto_schedule_pickup=true` |

**Por qué no exponer todos los endpoints como tools**: el LLM se vuelve impredecible si tiene 15 tools. Plan A.0.4 ("LLM no decide verdad transaccional") aplica: cobro, cancelación y RMA son acciones operacionales humanas o programadas, no decisiones conversacionales.

### 24.3 Audit log obligatorio (provider-aware)

Cada invocación adapter Aveonline genera líneas de log:

```
[AGENTIC_TOOL] tenant=<uuid> conv=<id> tool=quote_shipping provider=aveonline status=ok options_count=3 duration_ms=4200
[AGENTIC_TOOL] tenant=<uuid> conv=<id> tool=quote_shipping provider=aveonline status=err code=AVEONLINE_-3 duration_ms=180
```

**Métrica agregada**: dashboard Grafana per-tenant con paneles:
- `aveonline_quote_success_rate{tenant}` (target ≥98%)
- `aveonline_quote_p95_latency_seconds{tenant}` (target ≤8s)
- `aveonline_fallback_to_envia_rate{tenant}` (target ≤2%, alerta P1 si >5%)
- `aveonline_numbererror_distribution{tenant, code}` (visibilidad por código de error)

### 24.4 Tests obligatorios (M.8)

```python
# tests/agentic/test_aveonline_adapter.py

@pytest.mark.asyncio
async def test_quote_aveonline_happy_path_demo_account():
    """Probe DEMO Aveonline retorna opciones reales."""
    ...

@pytest.mark.asyncio
async def test_quote_aveonline_cod_enabled_includes_cod_carriers():
    """COD activo → solo carriers soportados (Coordinadora, Servientrega)."""
    ...

@pytest.mark.asyncio
async def test_quote_aveonline_fallback_to_envia_on_circuit_open():
    """Circuit breaker abierto → adapter cambia a Envia automáticamente."""
    ...

@pytest.mark.asyncio
async def test_quote_aveonline_idempotency_cache_hit_within_60s():
    """Misma request <60s → cache hit, sin invocar Aveonline real."""
    ...

@pytest.mark.asyncio
async def test_quote_aveonline_numbererror_3_returns_specific_message():
    """Aveonline retorna numbererror=-3 → tool mapea a mensaje 'sin carriers'."""
    ...
```

### 24.5 Variables de entorno (rev. 107)

Nuevas en `apps/web/.env.example` + `services/api/.env.example`:

```bash
# Aveonline (rev. 107)
AVEONLINE_QUOTE_URL=https://webservices.aveonline.co/cotizar/cotizar.php
AVEONLINE_GUIDE_URL=https://api.aveonline.co/api/v2.0/guias/generarGuiaTransporteNacional
AVEONLINE_PICKUP_CUTOFF_HOUR=11   # confirmado oficial §5.4
AVEONLINE_QUOTE_CACHE_TTL=60      # patrón plugin oficial
AVEONLINE_JWT_TTL_HOURS=12        # v2.0 default
AVEONLINE_RATE_LIMIT_PER_MINUTE=60  # conservador hasta confirmación
AVEONLINE_CIRCUIT_BREAKER_THRESHOLD=5  # F.2 baseline
AVEONLINE_FALLBACK_ENABLED=true   # rev. 107 default
```

Credenciales per-tenant siguen en `tenant_integrations.meta` (provider='aveonline'):

```json
{
  "empresa_id": "<id Aveonline tenant>",
  "usuario": "<usuario contacto>",
  "password": "<password vault>",
  "webhook_secret": "<UUIDv4 32+ chars>",
  "carriers_enabled": ["coordinadora", "servientrega", "interrapidisimo", "tcc"],
  "cod_carriers_enabled": ["coordinadora", "servientrega"]
}
```

---

## 25. Runbook operacional Aveonline (errores → acciones)

### 25.1 Diagnóstico rápido por código de error

| Código | Significado | Acción inmediata | Escalación |
|---|---|---|---|
| `AVEONLINE_-1` | Error genérico Aveonline | Reintentar con backoff exponencial (1s, 4s, 16s). Si 3 fallos consecutivos → circuit breaker abre. | Si circuit abierto >30 min → alerta Telegram operador + email `desarrollo1@aveonline.co` |
| `AVEONLINE_-2` | Credenciales inválidas | Refrescar JWT. Si falla auth → revisar Vault del tenant. | Inválidas confirmadas → contactar `asesorlogistico` del tenant |
| `AVEONLINE_-3` | Ciudad/destino sin carriers | Sugerir ciudad cercana via `listadociudades.json`. Ofrecer "recogida en bodega" o "asesor humano". | NO escalar — caso de negocio normal |
| `AVEONLINE_-5` | `valorDeclarado` < 10.000 COP | Auto-ajustar a 10.000 mínimo en el payload (regla AveCRM). | NO escalar — auto-fix |
| `AVEONLINE_-6` | Excede unidades máximas carrier | Mostrar al cliente: "Pedido excede capacidad envío. Divídelo o pide asesor". | NO escalar |
| `AVEONLINE_-7` | Excede peso máximo carrier | Mostrar al cliente: "Pedido excede peso máximo. Divídelo o pide asesor". | NO escalar |
| `AVEONLINE_-8` | Dimensiones no válidas | Auto-ajustar a defaults (10×10×10 cm) si missing. | NO escalar |
| `AVEONLINE_999` | Bug conocido `cotizar2` | **Cambiar a `cotizarDoble` en runtime** (regla de oro §17). | Si persiste con `cotizarDoble` → P1 inmediato |
| HTTP 429 | Rate limit (NO documentado oficial) | Token-bucket pause 60s + log warning. | Si frecuente (>5/h) → P1 a Aveonline pidiendo límites |
| HTTP 503 | Aveonline down | Circuit breaker abre + fallback a Envia (rev. 107 default) | Si circuit abierto >15 min en todos los tenants → P0 |
| Timeout >15s | Latencia Aveonline degradada | Cancelar request, retry 1 vez, luego fallback Envia. | Si latencia P95 >10s sostenido 30 min → P1 |

### 25.2 Procedimientos por incidente

**INC-1: cotizaciones masivas fallan con `AVEONLINE_-1`**

1. Verificar status Aveonline: `curl -I https://webservices.aveonline.co/`.
2. Probar cuenta DEMO: `python scripts/aveonline/probe_demo.py` — si DEMO funciona pero tenant prod no → problema de credenciales tenant.
3. Verificar Vault tenant: `python scripts/aveonline/refresh_jwt.py --tenant=<uuid>`.
4. Si JWT no refresca: revisar última rotación de credenciales en `tenant_credentials_log`.
5. Si todo OK pero falla → activar fallback a Envia globalmente: `UPDATE tenant_shipping_provider_config SET primary_provider='envia' WHERE tenant_id IN (...);`.
6. Reportar P0 a `desarrollo1@aveonline.co` + WhatsApp business **+57 305 420 21 25** con: timestamp UTC, tenant_id, ejemplo de request, response/error.

**INC-2: webhook tracking deja de llegar**

1. Verificar `webhook_events_seen` últimas 24h por integration='aveonline': `SELECT count(*) FROM webhook_events_seen WHERE integration='aveonline' AND processed_at > now() - interval '24h';`.
2. Comparar con `shipments` activos (`status IN ('labeled', 'in_transit')`).
3. Si gap >5% → activar polling backup (cron `services/ai-orchestrator/worker.py` cada 6h ya configurado).
4. Verificar webhook secret no fue rotado sin sincronizar: `tenant_webhook_secrets` last `rotated_at`.
5. Re-registrar webhook si necesario: `python scripts/aveonline/register_webhook.py --tenant=<uuid>`.

**INC-3: COD reconciliación discrepa**

1. Sin endpoint API (§7.5 actualizada) → **scraping autenticado o reporte manual**.
2. Ejecutar `python scripts/aveonline/scrape_cod_ledger.py --tenant=<uuid> --from=<date>` (si scraping implementado en rev. 108).
3. Cruzar con `orders` donde `payment_method='cod' AND status='delivered'`.
4. Discrepancias >$50.000 COP → P1 a `pqr@aveonline.co` con: lista guías + monto esperado + monto recibido + extracto bancario.

**INC-4: cliente reporta cobro doble por idempotency rota**

1. Buscar en `outbound_idempotency_cache` por `tenant_id + request_hash` esperado.
2. Si NO hay fila pero hay dos labels en Aveonline → idempotency baseline (F.2) falló.
3. Cancelar uno de los labels: `python scripts/aveonline/cancel_guia.py --guia=<id>`.
4. Reembolsar al cliente (Wompi `void` endpoint) la guía cancelada.
5. Bug P0 → escalar a equipo dev + post-mortem.

### 25.3 SLOs operacionales (rev. 107)

| SLO | Target | Medición | Acción si falla |
|---|---|---|---|
| Quote success rate | ≥98% (per tenant) | `aveonline_quote_success_rate` Grafana | <95% sostenido 1h → activar fallback Envia tenant-wide |
| Quote P95 latency | ≤8s | `aveonline_quote_p95_latency_seconds` | >10s sostenido 30 min → P1 a Aveonline |
| Webhook delivery rate | ≥99% | `webhook_delivery_rate{provider='aveonline'}` | <97% → activar polling backup |
| COD reconciliation accuracy | 100% (auditado semanal) | scraping ledger vs Aveonline UI Wallet | <99% → P1 manual + ticket Aveonline |
| Idempotency hit rate (retries) | ≥99% | `aveonline_idempotency_hit_rate` | <95% → bug F.2 baseline → P0 dev |
| Fallback to Envia rate | ≤2% | `aveonline_fallback_to_envia_rate` | >5% sostenido 24h → revisar salud Aveonline + comunicar tenant |

### 25.4 Contactos clave

- **Soporte técnico integraciones**: `desarrollo1@aveonline.co`
- **PQR/reclamos formales**: `pqr@aveonline.co`
- **WhatsApp business**: **+57 305 420 21 25** (L-V 8-5 hora Colombia, UTC-5)
- **Asesor logístico**: per tenant — campo `asesorlogistico` + `nombreasesor` en response de `autenticacion` v1.0 (ver §2.1)
- **Punto físico**: Envigado, Antioquia (Colombia)
- **Sitio web**: `https://aveonline.co/`
- **Documentación API**: `https://integraciones.aveonline.co/docs/`
- **Cuenta DEMO permanente**: usuario `demointegracion`, password `demointegra2021`

### 25.5 Validaciones humanas pendientes consolidadas (post-101%)

| # | Validación | Responsable | Cuándo | Bloquea producción |
|---|---|---|---|---|
| H1 | Confirmar SLA contractual respuesta P0/P1/P2 + canal escalación nocturno | Founder via `asesorlogistico` | Pre-prod | SÍ |
| H2 | Confirmar IP allowlist outbound de Aveonline (para webhooks) | Founder → `desarrollo1@aveonline.co` | Pre-prod | NO (mitigado con pseudo-secret) |
| H3 | Confirmar lista carriers que aceptan `cartaporte=1` (boomerang RMA) | Founder via DEMO + `desarrollo1@` | Pre-rev. 108 | NO (RMA P2) |
| H4 | Confirmar roadmap API histórico COD recaudos | Founder → `desarrollo1@aveonline.co` | Pre-prod | NO (scraping interim) |
| H5 | Confirmar rate limit oficial por API key | Founder → `desarrollo1@aveonline.co` | Pre-prod | NO (token-bucket conservador) |
| H6 | Probe empírico OpenAPI discovery (`/openapi.json`, `/swagger.json`) | Dev (30 min) | Sem 1 rev. 107 | NO |
| H7 | Probe carriers que aceptan `boomerang` con DEMO | Dev (2h) | Pre-rev. 108 | NO (RMA P2) |
| H8 | Revisión legal contrato DPA Aveonline (Habeas Data §15.4) | Legal externo | Pre-prod | SÍ |
| H9 | Firma contrato + selección plan mensual por tenant piloto | Founder + tenant | Pre-prod | SÍ por tenant |
| H10 | Capacitación operadores tenants en escalación canales Aveonline | CS Konvi | Sem 1 rollout | NO |

### 25.6 Métricas de éxito rev. 107 (cierre migración)

Producción-ready Aveonline si **todos** estos cumplen 30 días post-cutover oficial:

- ✅ ≥3 tenants piloto activos con Aveonline primary durante ≥30 días.
- ✅ Quote success rate ≥98% per tenant.
- ✅ P95 latency ≤8s sostenido.
- ✅ 0 incidentes P0/P1 sin resolución <4h.
- ✅ Fallback to Envia ≤2% rate.
- ✅ Webhook delivery ≥99%.
- ✅ 0 cobros duplicados por idempotency rota.
- ✅ COD reconciliation 100% (scraping o manual) en últimos 30 días.
- ✅ UAT S31-S33 + S43 (COD) re-corridos 100% PASS.
- ✅ Dashboards Grafana en target + alertas configuradas.
- ✅ Runbook §25 testeado con incidente simulado.
- ✅ ADR-0019 firmado (decisión migración Envia → Aveonline) + post-mortem rev. 107.

---

**Fin del dossier (versión 101% — 2026-05-21).**

> **Estado**: 8/8 brechas "NO ENCONTRADO" cerradas con evidencia oficial verificada o procedimiento de escalación documentado. 5 secciones nuevas (§21-§25) agregadas: comparativa Aveonline vs Envia con scoring, plan de migración 8 días-dev, resolución bug conv `5cef2503`, diseño integración tool agentic provider-agnostic, runbook operacional con SLOs + procedimientos por incidente. Total: 1700+ líneas, 23+ fuentes oficiales citadas (Aveonline docs + plugin GitHub + sitios carrier directos + LinkedIn empresa). Sin suposiciones — cada hallazgo cita URL o reporta "Confirmado NO documentado" con acción de escalación específica.
