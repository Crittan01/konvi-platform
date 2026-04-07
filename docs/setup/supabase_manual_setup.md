# Guía Dummie de Setup: Supabase (Tier de Nube)

Al ser una arquitectura Multi-Tenant, tu infraestructura de Base de datos, Autenticación y Colas se apoya en Supabase. Dado que no tenemos Docker local, usaremos el servicio de Supabase Cloud.

## Sobre Licenciamiento: ¿Free o Pro?
Para **TODA esta fase de construcción, desarrollo y pruebas (Pre-Producción)** de WhatsApp y el Backoffice, debes elegir usar el **Nivel Gratuito (Free Plan)**. 
- **Razones oficiales:** La documentación de Supabase indica que el Free Plan incluye PostgreSQL Dedicado (500MB límite de Storage, 50,000 requests activos y 50 conexiones simultáneas concurrentes de Base de datos). Todo tu orquestador asíncrono y los webhooks de Meta encajan milimétricamente allí para la etapa fundacional.
- **¿Cuándo hacer Upgrade a Pro?** *Exclusivamente* el día que lances a producción y esperes rebasar el límite de las 50 conexiones concurrentes, o necesites respaldos automáticos por día (PITR Recovery).

---

## PASO A PASO: Configuración de Proyecto

No des por sentado ningún conocimiento técnico, sigue estos movimientos de ratón estrictos:

1. **Ingreso a la Plataforma:**
   - Abre una pestaña en tu navegador, navega hacia la URL oficial: `https://supabase.com/dashboard`
   - Si no tienes cuenta, te pedirá *Sign in with GitHub* (O usar un correo). Procede de la forma que sea más cómoda.

2. **Creación de la Agrupación (Organization):**
   - Una vez dentro, en la pantalla central o esquina superior izquierda, asegúrate de pertenecer a una "Organization", si no la tienes, te saldrá un prompt preguntando "Create Organization".
   - **Name:** Nómbrala como tu empresa (ej. *Commerce Ops Corp*).
   - **Type:** Selecciona la categoría que representa este proyecto. Para evitar flujos agresivos de validación de ventas, te sugiero seleccionar **"Company"** o **"Startup"**. Si es un proyecto de laboratorio tuyo, sirve **"Personal"**.
   - **Plan:** Escoge "Free Plan" (o "Hobby Plan", dependiendo de cómo lo nombren en la interfaz).

3. **Creación del Proyecto Dedicado:**
   - En tu pantalla principal, busca el gran botón verde/negro que dice **"New Project"**.
   - Haz clic en él y selecciona tu Organización (Si pide confirmarla).

4. **Llenado exacto de Casillas del Proyecto:**
   - **Name:** Escribe `commerce-ops-dev`
   - **Database Password:** Debes poner una contraseña extraordinariamente fuerte e irrepetible. Te saldrá un botón de *"Generate a password"*. Presiónalo, y **CÓPIALA de inmediato a un documento o block de notas seguro temporal en tu computadora. No la pierdas.**
   - **Region:** Selecciona la región AWS/Servidor que te ofrezcan que sea físicamente más cercana geográficamente a tus futuros clientes (Por ejemplo `US East, N. Virginia` o `South America, São Paulo`). 
   - **Pricing Plan:** Asegúrate que aquí abajo diga "Free plan". ¡No ingreses datos de tarjeta de crédito si no lo deseas firmemente en este punto!
   - **Checkboxes Avanzados (MUY IMPORTANTE):**
     - **Enable Data API:** *MARCADO (Sí).* Lo usaremos porque el Frontend de React utilizará `@supabase/supabase-js`.
     - **Enable automatic RLS:** *MARCADO (Sí).* Actévalo sin dudar. Hemos definido que el proyecto entero se blinda mediante políticas Row Level Security; activarlo por defecto te protege de fugas en tablas futuras.
   - **Advanced Configuration:**
     - **Postgres Type:** Selecciona **Postgres (Default)**. OrioleDB aún se encuentra en fase Alpha limitando capacidades nativas, por ende debe evitarse contundentemente para este proyecto que tiene miras a producción crítica.
   - Dale clic en **"Create new project"**.

5. **Tiempo de Provisión:**
   - La pantalla cambiará y dirá *"Setting up project"*. Esto demora de **2 a 4 minutos** mientras provisionan tu contenedor privado de base de datos allá en la nube. ¡NO recargues la página agresivamente, espera que termine!

---

## PASO A PASO: Extracción de Entradas Clave (Tus Llaves)

Cuando la barra termine y te dejen ver el "Dashboard" principal de tu nuevo proyecto, harás exactamente esta rutina extractora:

1. **Obtener las Claves de Frontend:**
   - Busca en el Menú lateral izquierdo (columna negra) abajo del todo, el icono de un *engranaje* llamado **"Project Settings"**. Dale clic.
   - Dentro de ese menú, ve a la sección **"API"**.
   - Verás dos cajas importantes: una gran "URL" del proyecto, y las **Project API keys**.
   - **Acicón Humana 1:** Copia el valor de `Project URL` (que empieza por `https://xxx.supabase.co`).
   - **Acicón Humana 2:** Copia el valor que dice `anon` (También etiquetado como `public`).

2. **Obtener la Cadena de la Base de Datos:**
   - Sin salirte de "Project Settings", baja en ese mismo sub-menú izquierdo y haz clic en **"Database"**.
   - Busca una sección blanca en el centro de tu pantalla que dice **"Connection string"**.
   - Asegúrate de seleccionar la pestaña que dice **"URI"**. 
   - Te enseñará un link largo que empieza por `postgresql://postgres.[tu_id_proyecto]:[YOUR-PASSWORD]@aws-0-....`
   - **Acción Humana 3:** Copia toda esa línea de texto larguísima.

3. **El Destino Final Mío:**
   - En la ventana del chat de terminal conmigo (el de Antigravity AI), pégame lo que recolectaste bajo este formato, sin miedo, para que yo proceda automágicamente:
   ```txt
   SUPABASE_URL = "https://xxxxxx.supabase.co"
   SUPABASE_ANON_KEY = "eyJhXXXXXX"
   DATABASE_URL = "postgresql://postgres... (reemplaza mentalmente u aquí en el chat el texto [YOUR-PASSWORD] incrustando la clave real que guardaste en el paso 4 de arriba)"
   ```
