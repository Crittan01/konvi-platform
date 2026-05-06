# Changelog Watch — Política de re-investigación per provider

**Sesión origen**: 2026-05-05 · **Driver**: meta-análisis cross-dossier identificó que docs de proveedores cambian (WhatsApp 4 cambios breaking en 2025, Cloudflare Page Rules deprecated, DMARC obligatorio Gmail/Yahoo 2026). Sin re-investigación periódica → código obsoleto silente en producción.

**Política mínima**: dossier `docs/research/{provider}-dossier-{YYYY-MM-DD}.md` se refresca con la frecuencia indicada abajo, o ante triggers explícitos (newsletter, email comercial, cliente reporta cambio).

---

## 1. Frecuencia recomendada per provider

| Provider | Frecuencia | Razón | Triggers extras |
|---|---|---|---|
| **WhatsApp / Meta Cloud API** | **3 meses** | Cambia frecuente (PMP Jul-2025, On-Premise sunset Oct-2025, BSUID Q3-2026) | Email Meta Developer News con "deprecated" o "breaking change"; cualquier cambio en https://developers.facebook.com/docs/graph-api/changelog |
| **Wompi** | 6 meses | Cambia moderadamente | Cambio en panel Wompi reportado por tenant; nueva regulación Superintendencia Financiera Colombia |
| **Envia** | 6 meses | Cambia moderadamente, docs fragmentadas | Email Envia comercial; cambio en sandbox/production parity reportado por smoke E2E |
| **MercadoLibre** | 6 meses | Cambia frecuente, **portal bloquea WebFetch (403)** — re-investigación manual con login | Cambios en CBT publicados en blog MeLi; comisiones actualizadas anualmente |
| **Telegram Bot API** | 12 meses | Cambia poco, backward-compat fuerte | Bot API changelog https://core.telegram.org/bots/api#recent-changes |
| **Render** | 12 meses | Cambia poco, pricing review semestral | Email Render changelog; cambio en planes Workspace/Starter |
| **Cloudflare** | 12 meses | Cambia poco para Pro plan | Email Cloudflare Status; deprecation announcements (ej. Page Rules) |
| **Supabase** | 6 meses | Cambia frecuente (nuevas features), backward-compat fuerte | Supabase changelog https://supabase.com/changelog (RSS subscribible) |
| **Resend** | 12 meses | Cambia poco, API estable | Resend changelog https://resend.com/changelog |

---

## 2. Mecánica operativa

### 2.1 Calendario fijo (Q1 + Q3 anuales)

Cada **15 de Febrero** y **15 de Agosto** del año, ejecutar re-investigación de los providers con frecuencia **3-6 meses**:
- WhatsApp/Meta (siempre — frecuencia 3 meses)
- Wompi
- Envia
- MercadoLibre
- Supabase

Cada **15 de Mayo** anual, ejecutar re-investigación de providers **12 meses**:
- Telegram, Render, Cloudflare, Resend

### 2.2 Output de cada re-investigación

Para cada provider re-investigado:
1. Generar `docs/research/{provider}-dossier-{YYYY-MM-DD}.md` (NO sobrescribir el viejo — preservar como histórico).
2. Comparar con la versión anterior usando `diff` y documentar deltas en sección "Changes since {previous_date}" del nuevo dossier.
3. Si delta tiene **breaking changes** (ej. endpoint deprecated, pricing change, scope change, signature change):
   - Crear issue Linear/GitHub con label `provider-changelog`
   - Estimar esfuerzo de migración interna
   - Actualizar plan maestro `/home/ansible/.claude/plans/*.md` si afecta roadmap
4. Si delta tiene **features nuevas** que aplican a roadmap:
   - Evaluar si re-priorizar items del backlog P3
5. Commit con mensaje `chore(research): refresh {provider} dossier {YYYY-MM} — {N} breaking changes`.

### 2.3 Trigger anticipado (eventos no-calendario)

Re-investigar **inmediatamente** ante:

| Evento | Provider afectado | Acción |
|---|---|---|
| Email/notificación oficial provider con palabras "deprecated", "sunset", "breaking", "migration required" | El que envió | Re-investigar dossier completo en <48h |
| Tenant reporta error inexplicable en integración | El reportado | Re-investigar sección relevante (autenticación, endpoint, limits) |
| Smoke E2E sandbox/prod paridad cae <95% | El afectado | Re-investigar limitaciones documentadas |
| Métrica `tenant_provider_health` cambia a RED inexplicable | El afectado | Re-investigar status page + changelog último trimestre |
| Cambio regulatorio Colombia (Habeas Data, DIAN, Superfinanciera) | Aplicable a Wompi/Envia/MeLi | Re-investigar compliance section |

---

## 3. Subscripciones recomendadas (alternativa más liviana)

En vez de calendario fijo, suscribirse a:

| Source | URL | Provider |
|---|---|---|
| Meta Developer News | https://developers.facebook.com/blog/?cat=131 | WhatsApp/Meta |
| Cloudflare Blog | https://blog.cloudflare.com/feed/ | Cloudflare |
| Supabase Changelog | https://supabase.com/changelog (RSS) | Supabase |
| Render Status | https://status.render.com/ + email status | Render |
| Resend Changelog | https://resend.com/changelog | Resend |
| Telegram Bot API Changelog | https://core.telegram.org/bots/api#recent-changes (manual check) | Telegram |
| Wompi/Envia/MeLi | Email comercial cuenta-persona del provider (no RSS oficial) | Wompi/Envia/MeLi |

---

## 4. Tabla de seguimiento (estado actual)

Estado al **2026-05-05** (sesión actual cerró Sem 0):

| Provider | Última investigación | Próxima fecha objetivo | Estado |
|---|---|---|---|
| WhatsApp/Meta | 2026-05-05 | 2026-08-05 | ✅ Vigente |
| Wompi | 2026-05-05 | 2026-11-05 | ✅ Vigente |
| Envia | 2026-05-05 | 2026-11-05 | ✅ Vigente |
| MercadoLibre | 2026-05-05 | 2026-11-05 | ⚠️ Vigente (portal 403 — datos `[VALIDAR]` marcados) |
| Telegram | 2026-05-05 | 2027-05-05 | ✅ Vigente |
| Render | 2026-05-05 | 2027-05-05 | ✅ Vigente |
| Cloudflare | 2026-05-05 | 2027-05-05 | ✅ Vigente |
| Supabase | 2026-05-05 | 2026-11-05 | ✅ Vigente |
| Resend | 2026-05-05 | 2027-05-05 | ✅ Vigente |

---

## 5. Auditoría CI semanal (futuro Sem 11)

**Idea**: CI job semanal que pingue las URLs documentadas en cada dossier (50+ URLs total) y alerte si retornan 404 / 5xx / cambio de contenido (hash diff > threshold).

**Implementación sugerida** (cuando llegue Sem 11):
- Script `scripts/changelog/check_dossier_urls.py` que:
  1. Parsea cada `*-dossier-*.md` extrayendo URLs en formato markdown.
  2. HTTP HEAD request a cada URL.
  3. Si 404/5xx → flag URL como "moved" o "dead".
  4. Si 200 + body hash != hash previo → flag como "content-changed".
- Output: `docs/research/url-health-{YYYY-MM-DD}.json` + alerta Telegram al equipo si > N% URLs degradadas.
- Cron weekly en GitHub Actions.

**Esfuerzo**: ~1d. **Sem 11 (post-cierre observability F.6).**

---

## 6. Quién es responsable

- **Founder + dev senior**: ejecutar re-investigaciones calendarizadas (Q1 + Q3 + anual mayo).
- **Cualquier dev**: re-investigar ante trigger anticipado (sec. 2.3) si afecta su feature actual.
- **Reviewer en PR**: si ven que una integración se modifica, validar que el dossier referenciado tenga fecha < 6 meses; si está vencido, bloquear PR hasta refresh dossier.

---

**Documento vivo.** Actualizar tabla §4 al cerrar cada re-investigación. Última actualización: 2026-05-05.
