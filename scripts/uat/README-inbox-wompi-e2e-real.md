# Inbox Wompi — Instrucciones de Prueba E2E Real (Móvil)

## Objetivo
Validar el flujo completo desde un teléfono físico:
```
WhatsApp → Bot → Cotización → Resumen → Link Wompi → Pago → Webhook → Confirmación
```

## Requisitos previos
- Entorno local levantado (`make up` en `/home/ansible/commerce-ops-local/`)
- ngrok API activo (Wompi puede llegar al webhook)
- Túneles corriendo (`make print-urls` debe mostrar URL pública de API)
- URL de webhook Wompi configurada en dashboard sandbox apuntando a `{ngrok-api}/api/v1/webhooks/wompi`
- Llaves Wompi sandbox en `.env` local
- Tu número de teléfono agregado como destinatario de prueba en Meta WABA (para recibir mensajes del bot)

## Paso 1 — Verificar entorno
```bash
cd /home/ansible/commerce-ops-local
make status
make print-urls
```
Asegurar que:
- `api` está corriendo
- `orchestrator` está corriendo
- ngrok API muestra URL pública

## Paso 2 — Preparar producto de prueba
En el Tenant Console (`http://localhost:3000` o URL Render):
- Verificar que exista al menos un producto con **stock > 0** y precio **≥ $1.500 COP** (recomendado: Camiseta Polo Testing $60.000).
- Verificar que el tenant tenga **dirección de origen** configurada en Configuración → General (para que Envia pueda cotizar).

## Paso 3 — Enviar mensajes desde tu móvil
Abre WhatsApp y envía los siguientes mensajes **uno por uno** al número del bot (tu WABA). Lee cada respuesta antes de enviar el siguiente.

| # | Mensaje a enviar | Qué esperar del bot |
|---|---|---|
| 1 | `Hola` | Saludo corto, sin spam. |
| 2 | `Quiero una camiseta polo roja` | Confirma disponibilidad, precio y stock. |
| 3 | `Sí, envíame una. Me llamo Cristian Camilo Garzon Tamayo` | Debe responder usando solo **"Cristian"** (no nombre completo). Preguntará ciudad de envío. |
| 4 | `Medellín` | Debe cotizar envío real con tarifas de Envia (económica + rápida). |
| 5 | `Económica` | Pide dirección de entrega. |
| 6 | `Cra 10 #20-30, Barrio Centro, Medellín. Es una casa.` | Resume pedido y pide confirmación final. |
| 7 | `Sí confirmo` | Debe enviar link de pago Wompi (URL tipo `https://checkout.wompi.co/l/...`). |

> **Nota**: Si en algún punto el bot dice "te paso con un asesor" o la conversación cambia a `human_takeover`, ve al Inbox (`/dashboard/inbox`) y cambia el estado a `bot_active` para continuar.

## Paso 4 — Pagar en Wompi Sandbox
1. Abre el link enviado por el bot en tu navegador.
2. Selecciona **Tarjeta de crédito**.
3. Usa los datos de prueba oficiales Wompi:
   - Número: `4242 4242 4242 4242`
   - Fecha vencimiento: cualquiera futura
   - CVV: `123`
   - Titular: `APPROVED`
4. Completa el pago.

## Paso 5 — Verificar webhook y confirmación
Después de pagar, espera 5-15 segundos. El bot debería enviar automáticamente un mensaje de confirmación tipo:
> "✅ ¡Pago confirmado! Tu pedido #XXXX está registrado y en preparación..."

Verifica en el sistema:
```bash
# En la VM, consulta la última orden del tenant
cd /home/ansible/workspaces/commerce-ops-platform
supabase db query --linked "SELECT id, status, total_amount FROM orders WHERE tenant_id = '0fb0777e-f3e4-48c7-89bf-a25aa201c0c9' ORDER BY created_at DESC LIMIT 3;"
```
- La orden debe aparecer con `status = confirmed`.
- En tabla `payments` debe aparecer `wompi_status = APPROVED`.

## Paso 6 — Probar escenario DECLINED (opcional)
Para validar idempotencia, repite el flujo completo con otro producto o variante, pero en el paso de pago de Wompi usa:
- Número: `4111 1111 1111 1111`
- Titular: `DECLINED`

El bot **no** debe enviar mensaje de confirmación. La orden debe quedar en `pending_payment` (o si ya fue confirmada por error, revisa logs).

> Alternativa: usa el script de emulación para DECLINED sin repetir flujo completo:
> ```bash
> cd /home/ansible/workspaces/commerce-ops-platform
> python3.11 scripts/uat/inbox_wompi_e2e_simulated.py
> ```

## Paso 7 — Revisar logs en caso de fallo
```bash
cd /home/ansible/commerce-ops-local
make logs SERVICE=api       # Ver webhook Wompi recibido
make logs SERVICE=orchestrator  # Ver procesamiento del bot
```

## Hallazgos conocidos (2026-04-24)
- El flujo conversacional crea una orden genérica sin `variation_id` en `order_items`; por eso el **stock no se decrementa automáticamente** en el flujo bot-to-payment. El decremento de stock ocurre en `_decrement_stock_on_confirm` pero solo afecta items con `variation_id` explícito.
- El bot usa nombre completo del cliente si viene en el historial; la humanización a primer nombre está activa en runtime pero depende de que el nombre completo aparezca exactamente en la respuesta del LLM.
