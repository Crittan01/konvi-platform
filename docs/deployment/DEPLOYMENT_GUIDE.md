# Guía Explícita (Dummy) para Despliegue Físico 🚀

Esta guía es tu faro. Ya posees el código fuente de un Software Multi-Tenant, ahora toca la Fase 10: **Conectar los cables al mundo real.**

Vamos paso a paso para encender físicamente el robot.

## Paso 1: Pidiendo Cerebro (La API Key de Inteligencia Artificial)

Tu SaaS no puede pensar si no le conectamos a Google Gemini.
1. Entra a: [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Haz clic en el gran botón azul **"Create API Key"**.
3. Te dará un string largo (ej: `AIzaSyBxxxxxxx`).
4. Ve a tu archivo `.env` local en la VM y pégalo así:
   `GEMINI_API_KEY="AIzaSyBxxxxxxx"`

> **¡Felicidades! Tu IA ya puede razonar y tiene permisos.**

## Paso 2: Abriendo la Ventanilla en WhatsApp (Meta Developers)

Le diremos a Facebook que queremos mandar y recibir mensajes para tu empresa.
1. Entra a [Meta Developers](https://developers.facebook.com/apps/) y haz clic en "Crear Aplicación".
2. Elige el tipo **"Negocios (Business)"**.
3. En el menú de la izquierda, agrega el producto **"WhatsApp"**.
4. Meta te va a regalar automáticamente un *Número de Teléfono de Prueba* y un *Token de Acceso Temporal (de 24 horas)*.

De esta pantalla, copia lo siguiente a tu archivo `.env`:
- `META_ACCESS_TOKEN` = (Es el token ridículamente largo que empieza con `EAA...`)
- `WHATSAPP_PHONE_ID` = (Es el "Phone Number ID" que Meta te asignó).
- `META_APP_SECRET` = (Lo encuentras en la sección Settings > Basic).
- `META_VERIFY_TOKEN` = (Este lo inventamos nosotros desde la Fase 3, déjale `"commercesuperclave2025"`).

## Paso 3: Poniendo la "Oreja" en Internet (Pinggy Tunnel)

Meta (WhatsApp) necesita enviarte los mensajes a una dirección en la nube (URL HTTPS), no puede enviarlos directamente a tu disco local de desarrollo. 
Debido a que Ngrok exige cuenta y LocalTunnel se congela, usaremos tecnología SSH nativa de linux con **Pinggy** que es irrompible y no exige registros:

1. Abre una terminal y enciende el Gateway de FastAPI (Tu Aduana):
   ```bash
   cd services/connector-whatsapp
   source ../../.venv/bin/activate
   uvicorn main:app --port 8000
   ```
2. Abre OTRA terminal y ejecuta este comando estándar:
   ```bash
   ssh -p 443 -R0:localhost:8000 a.pinggy.io
   ```
3. En la pantalla verás un cuadro gigante, copia la URL que empieza con `HTTPS://` (ej: `https://abcd.run.pinggy-free.link`).

## Paso 4: El Apretón de Manos Final (Callback Webhook)

Vuelve a la pantalla de Meta Developers (Sección WhatsApp > Configuration):
1. Dale clic en "Editar Webhook".
2. **Callback URL:** Pega aquí tu link de ngrok + el endpoint. (Ej: `https://abcd-1234.ngrok-free.app/webhook`)
3. **Verify Token:** El que escribiste en el env: `commercesuperclave2025`.
4. Botón verde verificar. *(Meta mandará la señal, tu FastAPI lo desencriptará usando HMAC usando el código que creamos, y Meta dirá "¡OK VERIFICADO!")*.
5. Suscríbete al recuadro llamado `messages` para que WhatsApp sepa que debe enviarnos textos.

## Paso 5: ¡Manda un chat real!

1. Pon a correr al robot "Cerebro":
   ```bash
   source .venv/bin/activate
   python3 services/orchestrator/worker.py
   ```
2. Y tu Frontend para ver todo:
   ```bash
   pnpm run dev --filter web
   ```
3. Desde tu celular personal, manda un mensaje de WhatsApp al *Número de Prueba* que te dio Meta Developers preguntando *"Hola, ¿cuánto valen las zapatillas rojas?"*.
4. **LA MAGIA OCURRE:**
   - FastAPI atrapará el chat asíncronamente en tu PC (`Ngrok` -> `8000`).
   - Lo guardará en `Supabase`.
   - El daemon `worker.py` detectará que te hablaron, le pedirá permiso al `LLM Gemini` mandándole SQL y Catálogos.
   - Mandará el POST de Whatsapp Api.
   - Verás en tu celular la respuesta perfecta de venta, ¡y podrás auditarlo en vivo en `http://localhost:3000/dashboard/inbox`!
