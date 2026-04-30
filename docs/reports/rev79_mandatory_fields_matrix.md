# Rev. 79 — Matriz Canónica de Campos Obligatorios

**Fuente única de verdad** para todos los datos que el sistema captura del cliente: qué se pide, dónde se valida, cuándo es obligatorio, según qué documentación.

**Fecha**: 2026-04-29
**Alcance**: bot conversacional WhatsApp (FSM), formulario web (`apps/web`), API contactos, integración Wompi (pasarela), integración Envia (logística).

---

## 1. Datos de identidad

| Campo | DB column | Pydantic API | TS form | FSM bot | Wompi customer_data | Envia destination | Obligatorio para… |
|---|---|---|---|---|---|---|---|
| **Nombre completo** | `contacts.name` (TEXT, max 120) | `name: Optional[str]` (max 120) | input text | `NEEDS_NAME` step | `full_name` (opcional pero recomendado) | `name` (req. para guía) | Pago + guía Envia |
| **Correo electrónico** | `contacts.email` (TEXT, max 254) | `email: Optional[str]` (max 254 + regex `^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$`) | input email (HTML5) | `NEEDS_EMAIL` step | `email` (opcional) | `email` (recomendado) | Pago Wompi (recibo) |
| **Teléfono** | `contacts.phone` (TEXT, regex `^\+?[1-9]\d{7,19}$`) | `phone: str` (req., regex) | — (viene de WhatsApp) | implícito (= número WhatsApp) | `phone_number` + `phone_number_prefix` | `phone` (req. para guía) | Identificación + guía |
| **Tipo de documento** | `contacts.document_type` (TEXT, CHECK CC/CE/NIT/PP/TI/OTHER) | `document_type` (Pydantic enum) | select | `NEEDS_DOCUMENT` step | `legal_id_type` (opcional) | — | Pago Wompi |
| **Número documento** | `contacts.document_number` (TEXT, normalizado sin puntos) | `document_number` (str, NIT con DV módulo-11 DIAN) | input text | `NEEDS_DOCUMENT` step | `legal_id` (opcional) | — | Pago Wompi |

**Hallazgos**:
- ✅ **Email con regex (rev. 79)**: pattern aplicado en `ContactCreate.email` y `ContactPatch.email` rechaza `"abc"`, `"@x.co"`, `"a@b"`, `"a@b..co"`, `"a b@c.co"`. Verificado en harness D10.
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
| `consent_text_version` | TEXT | **CANÓNICO (rev. 79)** — versión del aviso legal vigente | (= "tos_version" semántico) |
| `consent_source` / `consent_channel` | TEXT | "whatsapp" / "web_form" / "manual_console" / etc. | Auditoría canal de captación |
| `consent_notice_version` | TEXT (max 80) | **DEPRECADO (rev. 79)** — mantener por backward compat; nuevo código debe escribir solo `consent_text_version` | A retirar en migración futura |
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

**Hallazgo (rev. 79 confirmado)**: Envia.com **no expone docs públicas accesibles** desde el sandbox actual.

URLs intentadas (todas fallan con 404 o ECONNREFUSED desde nuestro entorno):
- `https://api-docs.envia.com/`
- `https://docs.envia.com/`
- `https://docs.envia.com/api/intro`
- `https://docs.envia.com/api/labels`
- `https://envia.com/docs/api`

**Política de validación adoptada**: contrato Envia se valida empíricamente vía:
1. Implementación canónica en código: `services/api/integrations/envia_client.py` y `services/ai-orchestrator/tools/shipping_quote_tool.py`.
2. Registros operativos: `bot_source_log` (rev. 71) — cada cotización exitosa demuestra que el payload actual es aceptado por la API.
3. Cuando los docs oficiales vuelvan a estar accesibles, validar formato de payload `/ship/rate` y `/ship/generate`, registrar versión consultada, y actualizar esta sección.

Owner del seguimiento: cualquier rev futura que toque el cliente Envia debe re-intentar el WebFetch a las URLs anteriores y registrar el resultado.

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

**Limitación observada (rev. 79 conversational E2E S6)**: la extracción multi-campo solo opera cuando la conversación ya pasó por `NEEDS_CONSENT`. Si el cliente, sin haber dado consentimiento explícito, dispara un mensaje con todos los datos de una, el bot **no** abre el `contacts` row porque la persistencia exige `consent_given=true` (ver orchestrator.py:4437–4440). La transición correcta requiere primer turno: buying intent → catálogo → consent → datos. Documentado como comportamiento esperado por compliance, no un bug.

**Hallazgo crítico (rev. 79 conversational E2E, runs múltiples)**: el bot LLM (Gemini-2.5-flash) es **excesivamente conversacional** — añade preguntas retóricas ("¿para qué tipo de piel lo buscas?", "¿qué uso le quieres dar?", "¿tienes alguna otra consulta?") antes de avanzar el FSM hacia consent / data capture / payment. En el harness E2E:

- **7/7 escenarios single-turn pasan al 100%**: saludo, catálogo, KB-cita, out-of-domain, foto, formato canónico, revocación.
- **0/5 escenarios multi-turn alcanzan el cierre de venta** en runs consecutivos: happy-path, datos desordenados, address conjunto, multi-producto, escalación humana.

El driver adaptativo `ConversationDriver` (rev79_conversation_scenarios.py) reacciona a la PREGUNTA real del bot, pero el bot no progresa al FSM en una cantidad razonable de turnos (< 14). Recomendación de producto: revisar el system prompt del orchestrator (orchestrator.py:~3076) para que ANTES de hacer preguntas conversacionales abiertas, el bot evalúe si ya tiene producto + ciudad + presentación y avance directo a NEEDS_CONSENT. La conversación adicional encarece (LLM cost) y reduce conversion rate.

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
| 1 | Email API sin regex | ~~M~~ | ✅ **Cerrado rev. 79** — `pattern` agregado en `ContactCreate.email` y `ContactPatch.email` (`services/api/routers/contacts.py`). Verificado por D10 del harness. |
| 2 | `consent_text_version` y `consent_notice_version` redundantes | ~~L~~ | ✅ **Documentado rev. 79** — `consent_text_version` declarado canónico; `consent_notice_version` deprecado (mantener por compat). Ver §3 de este doc. |
| 3 | Docs Envia.com no accesibles | ~~L~~ | ✅ **Política adoptada rev. 79** — validación empírica vía `bot_source_log` + reintento documentado. Ver §5. |
| 4 | Carrito abandonado sin TTL | ~~M~~ | ✅ **Cerrado rev. 79** — migración `20260504000000_carts_abandonment_cron.sql`: función `fn_expire_abandoned_carts()` + schedule pg_cron horario. Política: 7 días sin actividad → `status='abandoned'`. |
| 5 | "Compatibilidad química/alimentos" | — | No aplica al tenant actual (cosmética artesanal). Documentado out of scope. |
