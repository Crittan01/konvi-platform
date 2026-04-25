# Wompi — Integración Técnica (Preparación Fase C)

Última actualización: 2026-04-24
Estado: documento de diseño técnico validado en docs oficiales. **Implementación runtime bloqueada hasta gate Fase C.**

> Validado contra: https://docs.wompi.co/en/docs/colombia/

---

## 1. Decisiones de diseño

- Sandbox primero, luego producción.
- Confirmación de pago **solo** por webhook server-side validado (checksum).
- Nunca confirmar pago por interpretación de texto del cliente en chat.
- Llaves privadas **nunca** en frontend ni en repositorio.

---

## 2. Ambientes y endpoints

| Ambiente | Base URL |
|---|---|
| Sandbox | `https://sandbox.wompi.co/v1` |
| Producción | `https://production.wompi.co/v1` |

### Endpoints validados

| Endpoint | Método | Auth | Uso |
|---|---|---|---|
| `/payment_links` | POST | Bearer private_key | Crear link de pago |
| `/payment_links/:id` | GET | Ninguna | Consultar link de pago |
| `/transactions/:id` | GET | Bearer private_key | Consultar estado de transacción |

> **Nota**: No existe endpoint documentado de búsqueda de transacción por `reference`. Solo por `id`. La correlación con la orden propia se hace por `reference` en el webhook `transaction.updated`.

### Webhooks (eventos verificados en docs oficiales)

| Evento | Descripción |
|---|---|
| `transaction.updated` | Cambio de estado en transacción (APPROVED, DECLINED, VOIDED, ERROR, PENDING) |
| `nequi_token.updated` | Estado de token Nequi a estado final |
| `bancolombia_transfer_token.updated` | Estado de token Bancolombia a estado final |

> **IMPORTANTE**: El evento `payment_link.payment_received` **no está listado en la documentación oficial** de Wompi (validado 2026-04-24). Para detectar pagos vía link, usar `transaction.updated` con el campo `payment_link_id` en el objeto `transaction`.

El endpoint receptor propio:
```
POST /api/v1/webhooks/wompi
```

---

## 3. Secretos requeridos

| Variable | Ambiente | Uso |
|---|---|---|
| `WOMPI_PUBLIC_KEY_SANDBOX` | Sandbox | Identificar comercio (prefijo `pub_test_`) |
| `WOMPI_PRIVATE_KEY_SANDBOX` | Sandbox | Auth server-side en requests (prefijo `prv_test_`) |
| `WOMPI_EVENTS_KEY_SANDBOX` | Sandbox | Validar firma de webhooks (prefijo `test_events_`) |
| `WOMPI_INTEGRITY_KEY_SANDBOX` | Sandbox | Tokens de integridad (prefijo `test_integrity_`) |
| `WOMPI_PUBLIC_KEY_PROD` | Producción | Identificar comercio (prefijo `pub_prod_`) |
| `WOMPI_PRIVATE_KEY_PROD` | Producción | Auth server-side en requests (prefijo `prv_prod_`) |
| `WOMPI_EVENTS_KEY_PROD` | Producción | Validar firma de webhooks (prefijo `prod_events_`) |
| `WOMPI_INTEGRITY_KEY_PROD` | Producción | Tokens de integridad (prefijo `prod_integrity_`) |
| `WOMPI_ENV` | Ambos | `sandbox` o `production` |

> Llaves se obtienen en: https://comercios.wompi.co → Desarrollo → Programadores

---

## 4. Contrato de creación de link de pago

### Campos requeridos (validados en docs oficiales)
```
name, description, single_use, collect_shipping
```

### Campos opcionales
```
amount_in_cents, currency, expires_at, redirect_url, image_url, sku (max 36 chars),
customer_data.customer_references (max 2 items), taxes
```

### Request
```http
POST https://sandbox.wompi.co/v1/payment_links
Authorization: Bearer {WOMPI_PRIVATE_KEY_SANDBOX}
Content-Type: application/json

{
  "name": "Pedido #ABC123",
  "description": "Camiseta Tech Negro Talla M x2",
  "single_use": true,
  "collect_shipping": false,
  "amount_in_cents": 12000000,
  "currency": "COP",
  "expires_at": "2026-04-24T19:00:00.000Z",
  "redirect_url": "https://commerce-ops-web.onrender.com/pedido/ABC123",
  "customer_data": {
    "customer_references": [
      {
        "label": "Pedido",
        "is_required": true
      }
    ]
  }
}
```

> **Nota de monto**: `amount_in_cents` es en centavos de COP. Ej: $120.000 COP = `12000000`.
> **Formato `expires_at`**: ISO 8601 UTC. Ej: `"2026-04-24T19:00:00.000Z"`
> **Sin `metadata`**: La API de Wompi no acepta campo `metadata` libre en payment_links. La correlación con `tenant_id`/`order_id` debe ir en el campo `sku` (36 chars) o en `customer_references`.

### Response (éxito)
```json
{
  "data": {
    "id": "pl-test-...",
    "name": "Pedido #ABC123",
    "description": "Camiseta Tech Negro Talla M x2",
    "single_use": true,
    "collect_shipping": false,
    "active": true,
    "currency": "COP",
    "amount_in_cents": 12000000,
    "expires_at": "2026-04-24T19:00:00.000Z",
    "redirect_url": "https://...",
    "merchant_public_key": "pub_test_..."
  },
  "meta": {}
}
```

> **CORRECCIÓN**: El campo en response es `"active": boolean`, no `"status": "active"`.

### URL del link generado
```
https://checkout.wompi.co/l/{data.id}
```
Esta es la URL que se envía al cliente por WhatsApp.

---

## 5. Validación de webhook

### Headers entrantes
```
X-Event-Checksum: <sha256_hex_string>
X-Event-Name: transaction.updated
```

### Payload completo `transaction.updated`
```json
{
  "event": "transaction.updated",
  "data": {
    "transaction": {
      "id": "txn-...",
      "status": "APPROVED",
      "amount_in_cents": 12000000,
      "currency": "COP",
      "reference": "test_g3HGYQ_1777065941_GMZX8yX1Q",
      "payment_link_id": "test_g3HGYQ",
      "customer_email": "cliente@ejemplo.com",
      "payment_method_type": "CARD"
    }
  },
  "sent_at": "2026-04-24T19:05:00.000Z",
  "timestamp": 1745521500,
  "signature": {
    "properties": ["transaction.id", "transaction.status", "transaction.amount_in_cents"],
    "checksum": "3476DDA50F64CD7CBD160689640506FEBEA93239BC524FC0469B2C68A3CC8BD0"
  }
}
```

### Verificación de firma (CORRECTO — SHA256 simple, NO HMAC)

El algoritmo oficial de Wompi usa SHA256 simple sobre string concatenado, **no HMAC**.

```python
import hashlib

def verify_wompi_signature(payload_dict: dict, events_key: str) -> bool:
    """
    Algoritmo oficial Wompi (validado 2026-04-24):
    1. Concatenar valores de signature.properties en orden
    2. Concatenar timestamp (entero)
    3. Concatenar events_key
    4. SHA256 del string completo
    5. Comparar con signature.checksum (o header X-Event-Checksum)
    """
    sig = payload_dict.get("signature", {})
    properties = sig.get("properties", [])
    checksum = sig.get("checksum", "")
    timestamp = payload_dict.get("timestamp", 0)

    # Paso 1: extraer valores de data usando dot-path de signature.properties
    data = payload_dict.get("data", {})
    parts = []
    for prop in properties:
        keys = prop.split(".")
        val = data
        for k in keys:
            val = val.get(k, "") if isinstance(val, dict) else ""
        parts.append(str(val))

    # Paso 2 y 3: concatenar timestamp y events_key
    concat = "".join(parts) + str(timestamp) + events_key

    # Paso 4: SHA256 simple (no HMAC)
    computed = hashlib.sha256(concat.encode()).hexdigest().upper()

    return computed == checksum.upper()
```

> **ADVERTENCIA**: La verificación anterior en este documento usaba `hmac.new(events_key, payload, sha256)` — eso es **incorrecto** según la documentación oficial.

### Estados de transacción (validados)

| Status | Significado |
|---|---|
| `APPROVED` | Pago exitoso |
| `DECLINED` | Rechazado (fondos, datos inválidos, etc.) |
| `PENDING` | En proceso |
| `VOIDED` | Anulado (solo tarjetas crédito/débito) |
| `ERROR` | Error en procesamiento |

### Acciones del webhook
1. Validar firma con `verify_wompi_signature()` antes de procesar.
2. Verificar que `event == "transaction.updated"`.
3. **Correlacionar orden**:
   - **NO usar `data.transaction.reference`** — es generado por Wompi (`test_g3HGYQ_timestamp_CODE`), no es nuestro `order_id`.
   - Usar `data.transaction.payment_link_id` → lookup en `payments.wompi_link_id` → obtener `order_id`.
   - Validado con pago real sandbox (2026-04-24): `reference = "test_g3HGYQ_1777065941_GMZX8yX1Q"`, `payment_link_id = "test_g3HGYQ"`.
4. Si `status == "APPROVED"`:
   - Actualizar `orders.status = confirmed`
   - Descontar stock definitivamente
   - Notificar al cliente vía WhatsApp (outbound queue)
5. Si `status == "DECLINED"` o `"VOIDED"`:
   - Log de rechazo
   - NO liberar stock automáticamente (el `release_order_tool` maneja TTL)
6. Responder `HTTP 200` (vacío es aceptable).

### Política de reintentos de Wompi (validada)
Si el webhook no recibe `2xx`, Wompi reintentará:
- Primer reintento: 30 minutos
- Segundo reintento: 3 horas
- Tercer reintento: 24 horas (máximo 3 intentos)

---

## 6. Moneda y restricciones (Colombia — validadas)

| Parámetro | Valor / Nota |
|---|---|
| Moneda | `COP` (única soportada) |
| Monto mínimo — modelo Agregador | $1.500 COP = `150000` en cents |
| Monto mínimo — modelo Gateway | $1 COP = `100` en cents |
| Formato de monto | Centavos (integer) |
| Monto máximo | Depende del contrato del comercio |
| Fees | Depende del medio de pago; consultar dashboard Wompi |
| TTL link de pago | Configurable via `expires_at` |
| Campos custom | Máximo 2 por payment link (`customer_references`) |

---

## 7. Correlación de orden con pago (sin metadata libre)

La API de payment_links **no acepta un campo `metadata` libre**. La correlación `tenant_id + order_id` se gestiona así:

**Opción A — `sku` field** (máx 36 chars, recomendada):
```json
"sku": "order-{short_uuid}"
```
El `sku` aparece en el webhook `transaction.updated` como `data.transaction.reference`.

**Opción B — `reference` en la transacción**:
El campo `reference` en el payload del webhook (`data.transaction.reference`) es el identificador de la transacción generado por Wompi. El `sku` del link se correlaciona internamente.

**Estrategia recomendada**:
- Crear el pedido en DB con `status=pending_payment` antes de generar el link.
- Usar `order_id` (UUID) como valor del campo `sku` del payment link (si cabe en 36 chars, un UUID v4 estándar tiene exactamente 36 chars incluyendo guiones).
- Guardar `payment_link_id` de Wompi en la tabla de pagos.
- En el webhook, buscar la orden por `sku` / `order_id`.

---

## 8. Multi-tenant

Cada tenant debe tener sus propias llaves Wompi almacenadas en:
- Tabla propuesta: `tenant_integrations` con `provider='wompi'`
- Campos: `config->public_key`, `config->private_key`, `config->events_key`, `config->environment`

> El webhook receptor (`POST /api/v1/webhooks/wompi`) debe identificar el tenant por `sku` (order_id) → join con `orders.tenant_id`. El evento llega sin tenant context.

---

## 9. Testing (casos de prueba e2e)

Suite automatizada en `tests/`:

| Test file | Cobertura |
|---|---|
| `test_wompi_signature.py` | Validación de firma SHA256: correcta, incorrecta, sin properties, sin checksum, events_key vacío, case-insensitive, dot-paths anidados. |
| `test_wompi_webhook.py` | Router `_process_wompi_event`: firma inválida rechaza, evento no-transaction ignorado, link no encontrado sin acción, idempotencia (orden ya confirmed), confirmación + decremento de stock + notificación WhatsApp, estados DECLINED/ERROR sin acción, error en confirmación logueado sin crash. |
| `test_wompi_payment_link_endpoint.py` | Endpoint `POST /orders/{id}/payment-link`: happy path genera link y persiste en `payments`, 404 orden no existe, 409 estado inválido, 422 monto menor a $1.500 COP, 503 Wompi no configurado. |
| `test_payment_link_tool.py` | Tool del orchestrator: total inválido (bajo/alto), JWT ausente, Core API 503, happy path retorna `PaymentLinkResult`, humanización de nombre (primer nombre) en `response_text`. |
| `helpers/wompi_payload_builder.py` | Builder reutilizable de payloads `transaction.updated` con firma SHA256 válida determinística para emulación de webhooks. |

Ejecutar suite:
```bash
python3.11 -m unittest discover -s tests -p 'test_*.py'
```

### Prueba e2e simulada (runtime completo)

Script en `scripts/uat/inbox_wompi_e2e_simulated.py` que ejecuta el flujo completo contra la DB linked real:
1. Crea contacto + conversación `bot_active`.
2. Siembra historial conversacional completo (saludo → consulta → compra → cotización → dirección → resumen).
3. Procesa confirmación final con el orchestrator real (incluye llamada a Gemini).
4. Verifica generación automática de orden `pending_payment` + link Wompi.
5. Emula webhook `APPROVED` → confirma orden + notificación WhatsApp.
6. Emula webhook `DECLINED` → valida idempotencia (no afecta orden confirmed).

Ejecutar:
```bash
cd /home/ansible/workspaces/commerce-ops-platform
python3.11 scripts/uat/inbox_wompi_e2e_simulated.py
```

### Prueba e2e real desde móvil físico

Ver instrucciones paso a paso en:
```
scripts/uat/README-inbox-wompi-e2e-real.md
```

## 10. Go / No-Go checklist

Ver `.context/04-next-steps.md` para checklist completo de Fase C.

---

## 11. Referencias oficiales (validadas 2026-04-24)

- https://docs.wompi.co/en/docs/colombia/inicio-rapido/
- https://docs.wompi.co/en/docs/colombia/ambientes-y-llaves/
- https://docs.wompi.co/en/docs/colombia/links-de-pago/
- https://docs.wompi.co/en/docs/colombia/eventos/
- https://docs.wompi.co/en/docs/colombia/transacciones/
- https://docs.wompi.co/en/docs/colombia/datos-de-prueba-en-sandbox/
