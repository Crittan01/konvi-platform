# Guía Dummie de Setup: Meta WhatsApp Cloud API

Nunca asumo que conoces de antemano el caótico ecosistema de Facebook Developers. Para interceptar tráfico y recibir Webhooks legalmente, **es obligatorio crear una App "Business"**.

Sigue estas casillas minuciosamente sin saltarte nada:

## PARTE 1: La Creación de la Entidad (Meta App)

1. **Ingreso y Registro Inicial:**
   - Abre `https://developers.facebook.com/apps/`
   - Si nunca has desarrollado en Meta, te pedirá "Register" (Vincular un número o aceptar términos). Hazlo.

2. **Crear la App:**
   - Haz clic en el botón verde/azul **"Create App"** (Crear aplicación).
   - **Paso 1:** Te preguntará qué quieres que haga tu app. Dependiendo de si tienes la UI vieja o nueva, _NO escojas Consumer o Gaming_. Selecciona **"Other"** (Otro) en la zona inferior, y dale _Next_.
   - **Paso 2 (App Type):** Selecciona rigurosamente el recuadro que dice **"Business"** (Negocios). Esto es obligatorio para habilitar la API de WhatsApp sin fricción. Dale _Next_.

3. **Llenado de Detalles:**
   - **App Name:** Nómbrala `Commerce Ops App` (o el nombre de tu empresa). Meta no te dejará usar palabras con "WA" o "WhatsApp" en el nombre.
   - **Contact Email:** Déjalo como está o usa el tuyo de trabajo.
   - **Business Account (Opcional por ahora):** Si tienes un "Business Manager", selecciónalo. Si no te sale o dice opcional, déjalo vacío y dale **"Create app"**. Es probable que te pida tu clave de Facebook personal para motivos de seguridad.

---

## PARTE 2: Activar el Módulo de WhatsApp

4. **El Dashboard Central:**
   - Serás redirigido a una pantalla inmensa con tarjetas cuadradas. Desplázate hacia abajo hasta que encuentres una tarjeta que dice **"WhatsApp"** que tiene un ícono verde.
   - Presiona el botón gris que dice **"Set up"** (Configurar) en esa tarjeta.
   - En el menú izquierdo aparecerá automáticamente una sub-sección llamada "WhatsApp".

5. **Entendiendo tu Verify Token:**
   - Desplázate hacia tu Block de Notas local. El **META_VERIFY_TOKEN** no existe en ningún lado de Meta: _es un candado que tú creas de la nada_. Escribe o inventa una palabra secreta (Ejemplo: `***META_VERIFY_TOKEN_LEGACY_REDACTED***`). Copéala porque luego se la informaremos a Meta.

---

## PARTE 3: Extracción de Claves

6. **Extracción del App Secret:**
   - Ahora, fíjate en el gran menú de navegación en la columna negra de la izquierda.
   - Haz clic en **"App Settings"** (Configuración de la app) -> **"Basic"** (Básico).
   - Se abrirá una página con el nombre de tu app ("Commerce Ops App") en la parte superior.
   - Busca el campo llamado **"App Secret"** (Clave secreta de la aplicación).
   - Estará en blanco o con asteriscos `***`. Haz clic en el botón que dice **"Show"** (Mostrar). (Facebook volverá a pedir contraseña humana).
   - **Acción Humana 1:** Copia toda la cadena alfanumérica que se acaba de revelar. NO la pierdas.

---

## PARTE 4: Inyectarlo en la Arquitectura

7. **Trasladar tus hallazgos a la Máquina Virtual:**
   - Abre en tu editor actual el archivo `/home/ansible/workspaces/commerce-ops-platform/.env`.
   - Busca: `META_VERIFY_TOKEN="..."` y pon ahí dentro la clave que tú te inventaste en el **Paso 5**.
   - Busca: `META_APP_SECRET="..."` y pon ahí dentro la enorme clave secreta que expusiste en el **Paso 6**.
   - Guarda el archivo.

## Docs

- https://developers.facebook.com/documentation/business-messaging/whatsapp/overview
