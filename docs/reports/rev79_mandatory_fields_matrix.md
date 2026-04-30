# Rev. 79 — Matriz Canónica de Campos Obligatorios

**Fuente única de verdad** para todos los datos que el sistema captura del cliente: qué se pide, dónde se valida, cuándo es obligatorio, según qué documentación.

**Fecha**: 2026-04-29
**Alcance**: bot conversacional WhatsApp (FSM), formulario web (`apps/web`), API contactos, integración Wompi (pasarela), integración Envia (logística).

---

## 1. Datos de identidad

| Campo | DB column | Pydantic API | TS form | FSM bot | Wompi customer_data | Envia destination | Obligatorio para… |
|---|---|---|---|---|---|---|---|
| **Nombre completo** | `contacts.name` (TEXT, max 120) | `name: Optional[str]` (max 120) | input text | `NEEDS_NAME` step | `full_name` (opcional pero recomendado) | `name` (req. para guía) | Pago + guía Envia |
| **Correo electrónico** | `contacts.email` (TEXT, max 254) | `email: Optional[str]` (max 254, **sin regex**) ⚠️ | input email (HTML5) | `NEEDS_EMAIL` step | `email` (opcional) | `email` (recomendado) | Pago Wompi (recibo) |
| **Teléfono** | `contacts.phone` (TEXT, regex `^\+?[1-9]\d{7,19}$`) | `phone: str` (req., regex) | — (viene de WhatsApp) | implícito (= número WhatsApp) | `phone_number` + `phone_number_prefix` | `phone` (req. para guía) | Identificación + guía |
| **Tipo de documento** | `contacts.document_type` (TEXT, CHECK CC/CE/NIT/PP/TI/OTHER) | `document_type` (Pydantic enum) | select | `NEEDS_DOCUMENT` step | `legal_id_type` (opcional) | — | Pago Wompi |
| **Número documento** | `contacts.document_number` (TEXT, normalizado sin puntos) | `document_number` (str, NIT con DV módulo-11 DIAN) | input text | `NEEDS_DOCUMENT` step | `legal_id` (opcional) | — | Pago Wompi |

**Hallazgos**:
- ⚠️ **Email sin regex**: `services/api/routers/contacts.py:53` solo valida `max_length=254`. Cualquier string es aceptado. El cliente HTML5 (`<input type="email">`) sí valida, pero la API directa no.
- ✅ **Teléfono con regex** (`^\+?[1-9]\d{7,19}$`): obligatorio en API, formato E.164 colombiano `+57XXXXXXXXXX`.
- ✅ **NIT con DV verificado**: módulo-11 oficial DIAN en `contact_validators._calculate_nit_dv`.

**Recomendación**: agregar regex email en `ContactCreate.email` para parity con teléfono. Pendiente.

---

## 2. Dirección estructurada

Schema canónico documentado en migración `20260429000000_contacts_document_and_address`. Espejos coherentes en:
- TS: `apps/web/lib/validators/address.ts`
- Python: `services/api/dependencies/contact_validators.py`

| Campo address | Tipo | Casa | Edificio | Conjunto | Notas |
|---|---|---|---|---|---|
| `street` | string | ✅ | ✅ | ✅ | "Calle 10 # 5-23" |
| `neighborhood` | string | ✅ | ✅ | ✅ | Barrio (= Envia `district`) |
| `city` | string | ✅ | ✅ | ✅ | "Bogotá" |
| `state` | string | ✅ | ✅ | ✅ | "DC" / "Antioquia" |
| `dane_code` | string | ✅ | ✅ | ✅ | Código DANE municipal (Envia lo prefiere para CO) |
| `country` | string | ⚪ | ⚪ | ⚪ | Default "CO" |
| `building_type` | enum | "casa" | "edificio" | "conjunto" | Determina campos extra |
| `apartment` | string | ⚪ | ✅ | ✅ | Apto/oficina |
| `tower` | string | ⚪ | ⚪ | ✅ | Torre/bloque |
| `complex_name` | string | ⚪ | ⚪ | ⚪ | Nombre del conjunto/edificio (opcional) |
| `number` | string | ⚪ | ⚪ | ⚪ | Número de placa (opcional, parseable de street) |
| `reference` | string | ⚪ | ⚪ | ⚪ | "Frente al parque" (opcional) |

**Reglas de obligatoriedad** (espejo TS↔Python en sección 2 abajo):

```
casa      → street + neighborhood + city + state + dane_code
edificio  → street + neighborhood + city + state + dane_code + apartment
conjunto  → street + neighborhood + city + state + dane_code + apartment + tower
```

**Coherencia verificada**:
- `apps/web/lib/validators/address.ts::addressRequiredFields()`
- `services/api/dependencies/contact_validators.py::address_required_fields()`
- `services/ai-orchestrator/orchestrator.py::_missing_address_fields()` (FSM bot)

---

## 3. Consentimiento legal

| Campo | DB column | Cuándo se llena | Notas |
|---|---|---|---|
| `consent_given` | BOOLEAN | Al aceptar TyC | Default `false` |
| `consent_given_at` | TIMESTAMPTZ | NOW() al aceptar | (= "tos_accepted_at" semántico) |
| `consent_text_version` | TEXT | Versión del aviso legal vigente | (= "tos_version" semántico) |
| `consent_source` / `consent_channel` | TEXT | "whatsapp" / "web_form" / "manual_console" / etc. | Auditoría canal de captación |
| `consent_notice_version` | TEXT (max 80) | Mismo que text_version (campo legacy paralelo) | Consolidar en futura rev |
| `consent_evidence` | JSONB | Evidencia (mensaje WhatsApp, IP, timestamp UI, etc.) | Default `{}` |
| `consent_actor_email` | TEXT | Email del operador que registró consentimiento manual | Solo en captura console |
| `consent_revoked_at` | TIMESTAMPTZ | NOW() cuando cliente revoca | NULL si nunca revocó |
| `consent_revoked_reason` | TEXT (max 500) | Motivo de revocación dicho por el cliente | NULL si nunca revocó |

**Revocación**: detectada por `_detect_revocation_intent` (orchestrator.py:100). Al activarse, persiste con `_record_consent(given=False)` que setea `consent_revoked_at` + responde mensaje de cierre formal.

**Sin consentimiento (NEEDS_CONSENT="no")**: detectado por `_detect_consent_no` (orchestrator.py:116). Bot responde con explicación + escalación a rol del tenant. NO persiste datos.

---

## 4. Wompi customer_data (pasarela de pagos)

**Fuente oficial**: <https://docs.wompi.co/docs/colombia/widget-checkout-web/>

Todos los campos son **opcionales** desde la perspectiva de Wompi (si no los enviamos, Wompi los pide en su widget al cliente). Pero los enviamos para minimizar fricción:

| Campo Wompi | Origen en nuestra DB | Obligatoriedad para flujo nuestro |
|---|---|---|
| `email` | `contacts.email` | ✅ obligatorio (FSM no avanza sin email) |
| `full_name` | `contacts.name` | ✅ obligatorio |
| `phone_number_prefix` | derivado de `contacts.phone` (`+57`) | ✅ |
| `phone_number` | derivado de `contacts.phone` (sin prefix) | ✅ |
| `legal_id` | `contacts.document_number` | ✅ (FSM lo pide en NEEDS_DOCUMENT) |
| `legal_id_type` | `contacts.document_type` (CC/CE/NIT/PP/TI/OTHER) | ✅ |

**Cita FAQ Wompi (verificada via WebFetch)**:
> CC, CE, NIT, PP, TI son los tipos aceptados para Colombia.

`DNI` (Argentina) y `RG` (Brasil) están en la doc Wompi pero NO los aceptamos (filtro `_WOMPI_LEGAL_ID_TYPES_ACCEPTED` en `wompi_client.py:117`).

**Verificación**: harness D4 confirma 6 campos prepoblados.

---

## 5. Envia destination (logística)

**Fuente oficial**: <https://docs.envia.com/> — actualmente **no accesible desde sandbox** (404/ECONNREFUSED). Validación es empírica vía registros `bot_source_log` en producción.

**Mapeo `contacts.address` → Envia `destination`** (verificado en `tools/shipping_quote_tool.py`):

| Envia field | Nuestra fuente | Obligatorio (empírico) |
|---|---|---|
| `name` | `contacts.name` | ✅ |
| `phone` | `contacts.phone` | ✅ |
| `email` | `contacts.email` | recomendado |
| `street` | `address.street` | ✅ |
| `district` | `address.neighborhood` | ✅ |
| `city` | `address.city` | ✅ |
| `state` | `address.state` | ✅ |
| `country` | `address.country` ?? "CO" | ✅ |
| `postalCode` | DANE municipal o "000000" | tolerado vacío en CO |
| `dane_code` | `address.dane_code` (Envia lo usa para CO) | ✅ |

**Hallazgo**: Envia.com **no expone docs públicas accesibles** desde el sandbox actual. Toda verificación es empírica. Recomendación: cuando los docs vuelvan, validar formalmente y registrar versión consultada.

---

## 6. Datos por etapa del flujo conversacional

| Estado FSM (orchestrator.py:1591) | Pide | Persiste en |
|---|---|---|
| `NEEDS_CONSENT` | "¿Aceptas que guarde tus datos para procesar el pedido?" | `contacts.consent_given/_at/_text_version/_source/_evidence` |
| `NEEDS_EMAIL` | Email | `contacts.email` |
| `NEEDS_NAME` | Nombre completo | `contacts.name` |
| `NEEDS_DOCUMENT` | Tipo + número documento | `contacts.document_type/_number` |
| `NEEDS_DIRECTION` | Dirección estructurada (street, barrio, ciudad, dpto, building_type, apt/torre si aplica) | `contacts.address` JSONB |
| `READY_FOR_SUMMARY` | (sin pregunta — muestra resumen) | — |
| `AWAITING_ORDER_CONFIRMATION` | "¿Confirmas para generar link de pago?" | (link Wompi) |

**Datos desordenados**: el FSM evalúa el estado MÍNIMO faltante en cada turno. Si el cliente da "Calle 10, soy Juan, mi correo es x@y.com" (3 campos en 1 mensaje), el LLM extrae los 3 y `_resolve_display_state` salta al siguiente faltante. Si el LLM falla extracción, hard-lock en orchestrator.py:4295 fuerza pregunta determinística por el siguiente campo.

---

## 7. Persistencia de carrito (abandono)

Tabla `conversation_carts` (migración `20260501000000_conversation_carts`):

| Estado | Cuándo | Reservas asociadas |
|---|---|---|
| `open` | Cliente agrega productos al carrito | `stock_reservations` activas |
| `checkout` | Cliente avanza a confirmar pedido | activas |
| `converted` | APPROVED desde Wompi → `_convert_to_order` (orders.py:483-486) | consumidas |
| `cancelled` | Cliente dice "cancelar" o `_detect_revocation_intent` | liberadas |

**Carrito abandonado** = cart con `status IN ('open', 'checkout')` y sin actividad reciente. Rev. 70 inyecta el último cart `cancelled` reciente al contexto del LLM para ofrecer "retomar pedido" (orchestrator.py:424-427).

**Tras DECLINED de Wompi**: rev. 78 F1 libera reservas pero el cart queda en `checkout`. Si el cliente reintenta pago, el flujo lo reusa. Si no reintenta, el cart caduca con la conversación (no hay TTL explícito, depende del context lazy-load).

---

## 8. Fotos de productos a solicitud

**Trigger**: `image_send_tool.handle_image_request_if_applicable` (rev. 73). Detecta intents tipo "mándame foto", "tienes imagen", "muéstrame".

**Resolución**:
1. Si el cliente identificó variante específica → `variation.image_url`.
2. Fallback → `product.cover_image_url`.
3. Si ninguna → mensaje "no tengo foto disponible" + escalación si insiste.

**Envío**: `send_whatsapp_message(image_link=URL, image_caption=...)` con `content_type='image'` registrado en `messages` para que Inbox renderice.

---

## 9. Resumen de obligatoriedad por canal de captura

| Campo | Bot (FSM) | Form web | API directo | Pago Wompi | Guía Envia |
|---|---|---|---|---|---|
| Nombre | ✅ | ✅ | opcional | ✅ | ✅ |
| Email | ✅ | ✅ | opcional | ✅ recomendado | recomendado |
| Teléfono | implícito | — | ✅ | ✅ | ✅ |
| Documento (tipo+número) | ✅ | ✅ | opcional | ✅ | — |
| Consentimiento | ✅ | ✅ | ⚪ (default false) | — | — |
| Address.street | ✅ | ✅ | opcional | — | ✅ |
| Address.neighborhood | ✅ | ✅ | opcional | — | ✅ |
| Address.city + state | ✅ | ✅ | opcional | — | ✅ |
| Address.dane_code | implícito (resuelto desde city) | ✅ | opcional | — | ✅ |
| Address.building_type | ✅ | ✅ | opcional | — | — |
| Address.apartment | si edificio/conjunto | si edificio/conjunto | opcional | — | recomendado |
| Address.tower | si conjunto | si conjunto | opcional | — | recomendado |
| Address.complex_name | opcional | opcional | opcional | — | opcional |
| Address.reference | opcional | opcional | opcional | — | opcional |

Leyenda: ✅ obligatorio · ⚪ opcional · — no aplica

---

## 10. Pendientes y acciones recomendadas

| # | Hallazgo | Prioridad | Acción |
|---|---|---|---|
| 1 | Email API sin regex (solo max_length) | M | Agregar `pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"` o `EmailStr` de Pydantic en `ContactCreate.email`. Espejo en TS. |
| 2 | `consent_text_version` y `consent_notice_version` son redundantes | L | Consolidar en una sola columna o documentar la diferencia. |
| 3 | Docs Envia.com no accesibles | L | Cuando vuelvan, validar formato de payload y registrar versión consultada en este doc. |
| 4 | Carrito abandonado sin TTL explícito | M | Definir cron que marque `conversation_carts.status='abandoned'` después de N días sin actividad. |
| 5 | "Compatibilidad química/alimentos" | — | No aplica al tenant actual (cosmética artesanal). Documentado out of scope. |
