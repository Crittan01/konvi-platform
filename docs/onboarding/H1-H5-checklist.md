# Checklist trámites Meta humanos — Commerce Ops platform readiness

**Audiencia**: founder de Commerce Ops.
**Disparador**: clarificación arquitectónica 2026-05-08. Para escalar a 10+ tenants en producción WhatsApp Cloud API, hay que destrabar 4 trámites humanos en Meta. Cada uno tiene su propio tiempo de espera.

**Principio**: estos trámites **NO bloquean desarrollo** del código (sigo construyendo features). Bloquean **deployment a producción multi-tenant**. KAIU funciona en Development Mode mientras tanto.

---

## H1 — Decidir nombre platform (sesión aparte)

**Estado**: 🟡 EN PROGRESO — **Konvi** seleccionado en sesión 2026-05-08, pendiente verificación SIC + registro dominios.

**Decisión documentada**:
- Nombre elegido: **Konvi**
- Justificación: evoca "konvi-versación" (bot conversacional) + sonoridad latino-tech (≈ Wompi, Rappi) + 5 letras memorables + dominios `.co` y `.io` libres + sin colisión cultural sensible.
- Alternativas evaluadas: Konvai (variant AI explícito), Klipa (tabula rasa style), Koru (descartado — todos los TLDs tomados + trademark Air New Zealand).

**Acciones inmediatas (founder, ~45 min total)**:

1. ✅ **Verificación SIC marca** (15 min, gratis):
   - Ir a [sic.gov.co → Trámites → Búsqueda de marcas](https://www.sic.gov.co/)
   - Buscar `KONVI` en clases:
     - Clase 9 — Software / aplicaciones / programas computación
     - Clase 35 — Servicios publicidad / gestión negocio / comercio
   - Si **0 colisiones** en estas clases → Konvi viable. Continuar.
   - Si colisión → fallback a **Konvai** (con AI explícito) o **Klipa**.

2. ✅ **Registrar dominios** (15 min, ~$95 USD/año):
   - **Primario**: `konvi.co` ($25-30/año en [openhost.com.co](https://www.openhost.com.co/) o GoDaddy)
   - **Secundario**: `konvi.io` ($45-60/año en [namecheap.com](https://www.namecheap.com/))
   - **Defensivo opcional**: `konvi.com.co` ($25/año, redirect 301 → konvi.co)

3. ✅ **Reservar handles redes sociales** (15 min, gratis):
   - `@konvi` en [Instagram](https://instagram.com/konvi)
   - `@konvi` en [X/Twitter](https://x.com/konvi)
   - [LinkedIn → crear empresa "Konvi"](https://www.linkedin.com/company/setup/new/) (requiere algún detalle de empresa, OK con nombre legal personal)

4. ✅ **Volver a sesión técnica**: confirmar a Claude que Konvi pasó SIC + dominios registrados → procede con find&replace `Commerce Ops` → `Konvi` en código y documentación (~30 min, controlado, una sola sesión).

**Si SIC colisiona en Konvi** (plan B):
- Verificar `KONVAI` en mismas clases.
- Si pasa → ese es el nombre. Re-validar dominios `konvai.co` + `konvai.io`.
- Si Konvai también colisiona → escalar a Klipa o nueva ronda creativa.

**Por qué importa**: el nombre se usa en:
- Business Portfolio Meta (visible a tenants cuando autorizan la App).
- Meta App display name (visible en developers.facebook.com + tenant Business Manager).
- Marca registrada SIC Colombia.
- Dominios web + handles redes sociales.

**Cambiar después**: posible pero costoso. Re-branding implica:
- Crear nuevo Business Portfolio (no se puede renombrar fácil sin verification path).
- Re-submit App Review con nuevo nombre.
- Notificar a tenants existentes (mensaje en panel admin).

**Checklist antes de decidir**:
- [ ] 5 nombres candidatos cortos (< 10 letras), pronunciables es+en.
- [ ] Verificar disponibilidad en SIC Colombia: [sic.gov.co búsqueda marcas](https://www.sic.gov.co/) (gratuito).
- [ ] Verificar dominio `.com` disponible: [namecheap.com](https://www.namecheap.com) o [godaddy.com](https://www.godaddy.com).
- [ ] Verificar dominio `.co` disponible: [openhost.com.co](https://www.openhost.com.co/) o registrador local.
- [ ] Verificar handles disponibles: Instagram + Twitter/X + LinkedIn.
- [ ] Pronunciable y memorable a primera escucha (test con 3 personas no-técnicas).

**Sugerencia operativa**: hasta decidir, código y docs usan **`Commerce Ops`** como placeholder. Cuando elijas, find&replace controlado en una sola sesión.

---

## H2 — Crear Business Portfolio + transferir Meta App

**Estado**: pendiente.
**Tiempo estimado**: 30 min.
**Pre-requisito**: H1 (idealmente decidido) o usar placeholder "Commerce Ops".

### H2.1 — Crear Business Portfolio platform

1. Entrá a [business.facebook.com](https://business.facebook.com) con tu cuenta personal de Facebook (la misma que usaste para crear la Meta App).
2. Esquina superior izquierda: **selector** de Business → **Crear cuenta**.
3. Llenar:
   - **Nombre del negocio**: `Commerce Ops` (o el nombre final post-H1).
   - **Tu nombre**: tu nombre completo.
   - **Email comercial**: idealmente uno con dominio del platform (`founder@commerce-ops.com`). Si aún no tenés dominio, usar email principal.
4. **Configuración → Información del negocio** → llenar:
   - País: Colombia.
   - NIT (si tenés SAS) o número de identificación personal (si vas a operar como persona natural mientras se constituye SAS).
   - Dirección comercial.
   - Teléfono.
   - Sitio web (poner uno aunque sea provisional — `https://commerce-ops.com` por ej.).
5. Guardar.

### H2.2 — Transferir Meta App `819229210624423` al nuevo Business Portfolio

1. En el nuevo Business Portfolio: **Configuración → Cuentas → Apps** → **Agregar**.
2. Seleccionar **Reclamar una app existente**.
3. Pegar App ID: `819229210624423`.
4. Seguir el flow de transferencia (Meta valida que sos owner de la App vía tu cuenta personal).
5. Confirmar transferencia.

> ⚠️ Importante: tras transferir, gestionarás la App SOLO desde el Business Portfolio nuevo. La cuenta personal pierde el rol owner. Asegurate de tener acceso al Business Portfolio antes de transferir.

### H2.3 — Verificar transferencia

- En [developers.facebook.com](https://developers.facebook.com) → My Apps → seleccionar Commerce Ops App → **Settings → Basic** → **App Owner** debe decir "Commerce Ops" (el Business Portfolio).
- Si dice "Personal" o tu nombre individual: la transferencia no se completó — re-intentar.

### H2.4 — Mover el System User commerce-ops (opcional)

**Pregunta clave**: ¿el System User `commerce-ops` debe estar en el Business Portfolio platform o en el del tenant (Kaiu Natural Living)?

**Respuesta**: del **tenant** (Kaiu Natural Living). Cada tenant genera su propio System User en su propio Business Portfolio para autorizar Commerce Ops App.

**Acción**: dejar el System User actual en Kaiu Natural Living. Cuando vengan otros tenants, ellos crearán los suyos en sus propios Business Portfolios.

---

## H3 — Iniciar Business Verification del Business Portfolio platform

**Estado**: pendiente.
**Tiempo estimado**: 10 min trámite + **1 a 3 semanas review Meta**.
**Pre-requisito**: H2 completado.
**Bloqueante para**: H4 (App Review) → producción multi-tenant.

### H3.1 — Preparar documentos

| # | Documento | Dónde lo obtenés |
|---|---|---|
| 1 | RUT empresarial (si SAS) o RUT persona natural | DIAN online |
| 2 | Certificación bancaria del negocio (cuenta a nombre del Business Portfolio) | Banco emisor |
| 3 | Factura de servicios públicos a nombre del negocio (luz, agua, internet) | Empresa de servicios |
| 4 | Sitio web activo del negocio (con SSL) | Si no tenés, crear landing simple |

> ⚠️ Meta pide consistencia: nombre en RUT = nombre en Business Portfolio = nombre en facturas. Si usaste persona natural, nombre completo en todos.

### H3.2 — Submit Business Verification

1. En Business Portfolio platform: **Configuración → Centro de seguridad → Verificación del negocio** (o `/security_center`).
2. Click **Empezar verificación**.
3. Llenar formulario:
   - Nombre legal del negocio.
   - Dirección.
   - Teléfono.
   - Sitio web.
4. Subir documentos (escanear o foto clara).
5. Submit.
6. Esperar email de Meta (1-3 semanas, a veces más rápido).

### H3.3 — Tracking

Estados posibles en Business Verification dashboard:
- **In Progress** — Meta revisando.
- **Approved** ✅ — desbloqueás H4 (App Review).
- **Rejected** ❌ — leer feedback Meta, corregir, re-submit. Causas comunes:
  - Documento ilegible.
  - Inconsistencia nombre.
  - Sitio web no resuelve / sin SSL.
  - Negocio no verificable en directorios públicos (Cámara de Comercio, etc.).

---

## H4 — Submit App Review (Advanced Access)

**Estado**: pendiente.
**Tiempo estimado**: 30 min preparación + screencast + **1 a 2 semanas review Meta**.
**Pre-requisito**: H3 (Business Verification approved).
**Bloqueante para**: producción real con tenants externos. Sin Advanced Access, la Meta App está en "Standard Access" — limitado a 5-10 testers + features incompletas.

### H4.1 — Permisos a solicitar

En developers.facebook.com → Commerce Ops App → **App Review → Permissions and Features**:

| Permiso | Por qué lo necesitás |
|---|---|
| `whatsapp_business_messaging` (Advanced) | Enviar/recibir mensajes WhatsApp en producción multi-tenant |
| `whatsapp_business_management` (Advanced) | CRUD HSM templates en F2 (POST /{WABA_ID}/message_templates) |

### H4.2 — Preparar screencast de uso

Meta pide demo de uso real del permiso. Grabar (5-10 min) mostrando:
1. Tenant (KAIU) onboardado en Commerce Ops admin panel.
2. Cliente real escribe a WhatsApp KAIU.
3. Bot responde + cotiza producto + genera link Wompi.
4. Cliente paga → orden confirmada → mensaje de confirmación enviado por bot.
5. Mostrar Inbox del Tenant Console con la conversación.

> Tips:
> - Locución en español o inglés (Meta acepta ambos).
> - Subir a YouTube (privado) o link Loom — pegar URL en App Review.
> - Si grabás con OBS, calidad mínima 720p.

### H4.3 — Llenar formulario App Review

- **Use case description** (cómo se usa el permiso): texto claro, sin tecnicismos. Ejemplo:
  > Commerce Ops is a SaaS B2B platform for Colombian merchants. We use whatsapp_business_messaging to allow merchants to receive customer messages and respond automatically with our AI bot. Each merchant connects their own WABA + System User token to our platform. We do NOT use this to send unsolicited messages or marketing content without consent.
- **Privacy policy URL**: requerida. Si no tenés sitio web aún, crear landing simple con `/privacy`.
- **Terms of Service URL**: idem.
- **Data deletion instructions URL**: idem (Habeas Data + Meta exigen flow para que usuarios pidan borrar datos).

### H4.4 — Submit + tracking

- Submit el App Review.
- Estados: **In Review** → **Approved** ✅ / **Rejected** ❌.
- Si rejected: leer comentarios Meta, ajustar (ej. screencast más completo, privacy policy más explícita), re-submit.

---

## H5 — Doc onboarding tenant ✅ COMPLETADO 2026-05-08

[`docs/onboarding/whatsapp-tenant-setup.md`](./whatsapp-tenant-setup.md).

Compartir el link con cada tenant que vaya a onboardearse. Contiene:
- Pre-requisitos.
- Pasos 1-6 con screenshots conceptuales.
- Resolución de problemas comunes.
- Política y compliance.

---

## Resumen orden de ejecución

```
HOY (paralelo a desarrollo código):
  [ ] H1 — Decidir nombre platform (1-2 días brainstorm + verificación)

SEMANA 1:
  [ ] H2.1-H2.3 — Crear Business Portfolio + transferir Meta App (30 min total)
  [ ] H3.1 — Preparar documentos verificación (1-2 horas)
  [ ] H3.2 — Submit Business Verification (10 min)

SEMANAS 1-3 (waiting Meta):
  → Business Verification "In Progress"
  → Mientras tanto: continuar desarrollo F2 HSM (no bloqueado)

SEMANA 4 aprox (post Business Verification approved):
  [ ] H4.1 — Identificar permisos a pedir (30 min)
  [ ] H4.2 — Grabar screencast demo (1-2 horas)
  [ ] H4.3 — Crear privacy + terms + data deletion pages (1 día si no existen)
  [ ] H4.4 — Submit App Review

SEMANAS 4-6 (waiting Meta):
  → App Review "In Review"
  → Mientras tanto: completar F2 HSM + UI + tests UAT

SEMANA 7+ (post App Review approved):
  [ ] Toggle App Mode → Live
  [ ] Onboardear primer tenant externo (no-KAIU) usando docs/onboarding/whatsapp-tenant-setup.md
  [ ] Validate end-to-end con tenant piloto
  → Producción multi-tenant 🚀
```

**Calendar realista**: Business Verification + App Review pueden tomar 4-6 semanas calendario (cada uno con waiting time). Si los hacés en paralelo a Sem 7-9 del roadmap K (F2 HSM + MeLi), llegás listo para producción justo cuando código lo esté.

---

**Última actualización**: 2026-05-08.
**Owner del checklist**: founder de Commerce Ops.
**Tracking**: actualizar este doc cuando un item pase de [ ] a [x] con fecha al lado.
