# Reporte de cierre rev. 102 — Habeas Data UX hardening + bug fixes runtime

**Fecha:** 2026-05-01
**Origen:** sesión de iteración con usuario sobre módulo Contactos en VM local (no Render).
**Branch:** develop
**Commits:** 18 commits, desde `0f82242` hasta `f496dad`.

---

## Contexto

Tras cerrar rev. 100 (cierre real de certificación) + rev. 101 (backlog ADR-0003 F1-F7 cerrado), el usuario empezó a probar el módulo Contactos contra la VM local. Surgieron 2 categorías de problemas:

1. **Bugs runtime reales** (errores 500 o digests opacos) — no detectables sin leer logs.
2. **Iteración UX/legal** — el usuario interroga cada elemento de la UI con visión legal y de cumplimiento Habeas Data, llevando a un módulo significativamente más defensible.

---

## Bugs runtime resueltos

### Bug #1 — Digest `3617361344` "Error al cargar el módulo"

**Síntoma:** error boundary genérico al guardar contacto manual.
**Causa real (en `web.log`):** server actions inline capturaban en su closure `CONSENT_SOURCES = new Set([...])` y `normalizeDaneCode` definidos DENTRO del componente. Next intentaba serializar `Set.has()` (función no-serializable) → throw.
**Fix:** mover ambas a module scope. `0f82242`.

### Bug #2 — Build apps/web bloqueado en main

**Síntoma:** Render no desplegaba revisiones del web service. Usuario veía código stale.
**Causa real:** `pnpm build` fallaba en 2 ESLint errors pre-existentes (no míos):
- `templates-section.tsx:47` — ternary como statement
- `catalog-table.tsx:320` — `let` debía ser `const`

`validate.sh` usaba `pnpm lint` (regex que no detectaba ese formato de error) en lugar de `next build`.
**Fix:** corregir los 2 errores + reforzar `validate.sh` con `next build` opt-in via `--build`. `78fcc01`.

### Bug #3 — SAR endpoints 500 `'str' object has no attribute 'tenant_id'`

**Síntoma:** click en cualquier botón Habeas Data → 500.
**Causa (en `api.log`):** `get_current_tenant` retorna `str` (tenant_id), no objeto. Mi rev. 100 asumía `tenant.tenant_id` y `tenant.email`.
**Fix:** signature `tenant_id: str = Depends(get_current_tenant)` + nuevo helper `_actor_from_request(request)` que extrae `sub` y `email` del JWT. Aplicado en data_subject_request.py + sic_report.py + endpoint /printable. `41ffe1f`.

### Bug #4 — SAR 503 `column orders.currency does not exist`

**Síntoma:** Reporte JSON/PDF/Portabilidad → 503.
**Causa (en `api.log`):** `_build_export_payload` seleccionaba `currency, paid_at` que no existen en `orders`. Schema real: `id, tenant_id, contact_id, conversation_id, status, total_amount, notes, created_at, updated_at, shipping_cost`.
**Fix:** select corregido con columnas reales. HTML render actualizado (Total COP | Envío | Creada | Actualizada). `d7b4e63`.

### Bug #5 — UI no se refrescaba post-Anonimizar

**Síntoma:** card seguía mostrando datos viejos hasta refresh manual.
**Causa:** `router.refresh()` disparaba el GET fresh pero el client component no re-renderizaba la card.
**Fix:** combinar router.refresh() con **optimistic update**. Nuevo prop `onEraseSuccess(contactId)` en HabeasDataActions. ContactsManager mantiene `Set<string> optimisticErasedIds` que filtra/anonimiza la card localmente al instante. `useEffect` limpia el set cuando initialContacts cambia (RSC fresh). `409b079`.

---

## Iteración UX / legal

### Paleta de colores

- Eliminados Tailwind shades fluorescentes (300/400/500). Reemplazados por shade 700 en componentes Habeas Data: emerald-700, amber-700, red-700, blue-700.
- Regla persistida en memoria: [feedback_ui_colors.md](../../.claude/projects/.../memory/feedback_ui_colors.md).
- `2b5bfaa`.

### Campo `document_number`

**rev. 100** placeholder con puntos `1.234.567.890` → sin puntos `1234567890`. `8ee799c`.
**rev. 101** validación dinámica por tipo de documento — DocumentFields component:
- CC: 6-12 dígitos solo numéricos (luego ajustado a 6-10 estricto)
- CE: 6-7 dígitos
- NIT: 9-11 chars con DV opcional `-X`
- PP: 6-15 alfanumérico
- TI: REMOVIDO (decreto 1377/2013 Art. 7 menores)
- OTHER: 3-30 chars
Cambia `inputMode`, `maxLength`, `pattern`, `placeholder` y `disabled` según tipo. `734dd8b` + `a8ae7d3`.

### Decisión: TI (Tarjeta de Identidad) eliminado del sistema

Decreto 1377/2013 Art. 7 prohíbe tratamiento de datos de menores sin representante legal. El sistema NO soporta flujo de representante (F8 backlog). Cambios:
- Frontend select sin opción TI.
- Validador TS y Python sin TI en `DOCUMENT_TYPES_CO`.
- Detector pre-LLM `_detect_minor_intent` en orchestrator: 10+ frases ("soy menor", "tengo permiso de mi mamá") + regex `tengo N años` con N<18. PRIORIDAD MÁXIMA en flujo (antes de revocación). Si detecta → respuesta cordial pidiendo representante + audit + escala a `human_takeover`.
- Cláusula §8 nueva en `docs/legal/privacy-policy.md`.
- 11 tests nuevos.
`a8ae7d3`.

### Botones Habeas Data — refactor visual + UX

- Botones `variant="ghost"` (texto coloreado) → `variant="outline"` con border de color por acción (rev. 100).
- Eventualmente unificados a paleta verde oscuro emerald-700 + Anonimizar amber-700 hover (señalización destructiva).
- Header *"Habeas Data — Derechos del titular"* con icono `(?)` → abre Dialog grande con guía explicativa de cada acción.
- 4 botones: **Reporte (JSON)**, **Reporte (PDF)**, **Portabilidad**, **Anonimizar**.
- Cada acción abre Dialog de confirmación pre-ejecución con: nombre del contact, descripción, "Qué pasa", "Lo que queda guardado" (lenguaje plano, no nombres de tabla técnicos).
- Dialog `(?)` con scroll (`max-h-[85vh] flex flex-col` + `overflow-y-auto`).
- `df526b8`, `5df239a`, `ee17c2d`.

### `window.alert` reemplazado por Dialog

Tras Anonimizar, success Dialog verde con `CheckCircle2`. Tras error en cualquier acción, error Dialog rojo con `XCircle`. Reads exitosos NO disparan dialog (la descarga es feedback). `ee17c2d`.

### Form Add — UX preventiva (Opción A+B+C Habeas Data)

**Antes:** los campos PII (name, email, document, address, notes) eran editables independiente del check de consent. El operador podía guardar PII sin consent (Art. 9 violation).

**Ahora:**
- Inputs PII `disabled` mientras `consent_given` está OFF.
- Banner amber arriba: *"Marca el check para habilitar los campos personales. Sin autorización el sistema solo registra el teléfono."*
- Documento y dirección se ocultan completamente cuando OFF.
- "Evidencia (nota interna)" visible solo si check ON.
- "Razón de revocatoria" visible solo si check OFF (caso raro: contact que nace revocado).
- Validación servidor: si `!consent_given` y se intenta enviar PII → `Error: "No se pueden registrar datos personales sin consentimiento del titular (Ley 1581/2012 Art. 9)..."`.
`8e96cb4`.

### Form Edit — Read-only consent + Opción B post-anonimización

**Refactor de la lógica de check `consent_given`:**

| Estado del contact | UI mostrada |
|---|---|
| `consent_given=true` (activo) | **Sin checkbox.** Label: *"Consentimiento activo desde [fecha]. Para revocar usa el botón Anonimizar — esa acción borra PII + deja audit + notifica al tenant. Desmarcar este check NO es la vía correcta."* |
| `consent_given=false + revoked_at` (anonimizado) | Banner amber + checkbox `renewed_consent` + textarea evidencia obligatoria minLength=10. PII inputs disabled hasta marcar + escribir evidencia |
| `consent_given=false + sin revoked_at` (legacy/raro) | Checkbox normal para activar |

**Server guards:**
- `prev.consent_given === true && !consentGiven && !renewedConsentChecked` → throw *"No puedes revocar desmarcando el check. Usa el botón Anonimizar (Art. 15)."*.
- Bloquea cualquier intento (form, curl, API directa) de "soft revoke".
- Cuando renewed_consent válido: append a `consent_evidence.renewals_after_revocation[]` (array inmutable con todos los renewals históricos) + auto-fuerza `consent_given=true` + limpia `revoked_at`/`reason`.

`6bf151c`, `f496dad`.

### Canales de consent — refinados a 5 defensibles

**Antes:** 7 canales (`manual_console`, `whatsapp`, `web_form`, `phone_call`, `in_person`, `import`, `other`).
**Ahora:** 5 con criterios legales:

| Canal | Justificación |
|---|---|
| `whatsapp` | Hilo es la evidencia, nativo del sistema |
| `web_form` | Form web del tenant con timestamp+IP+checkbox |
| `in_person` | Documento físico firmado, archivado |
| `import` | Sistema origen con due diligence del tenant |
| `other` | Catch-all con Evidencia OBLIGATORIA minLength=20 |
| ~~`manual_console`~~ | El operador marcando un check NO es evidencia del titular |
| ~~`phone_call`~~ | Requiere grabación cara, no factible para pequeño e-commerce |

- Default vacío + `required` (antes era `manual_console`).
- Help text contextual debajo del select según opción seleccionada.
- Evidencia required + minLength=20 cuando canal = `other`.
- Server valida coherencia.

`aaa5fe8`, `1e54c35`.

### Versión aviso/política — auto-completar transparente

**Antes:** input text libre. Operador no sabía qué poner.
**Ahora:** campo eliminado del form. Constante module-level `CURRENT_PRIVACY_NOTICE_VERSION = 'v2026-05-01'` sincronizada con `docs/legal/privacy-policy.md`. Server estampa automáticamente. Bumpear constante al actualizar el documento legal.
`aaa5fe8`.

### Phone country code internacional

**Antes:** +57 hardcoded + 10 dígitos exactos. Extranjeros con CE/PP no podían registrarse.
**Ahora:** 10 países soportados:

🇨🇴 +57 (default) · 🇻🇪 +58 · 🇪🇨 +593 · 🇵🇪 +51 · 🇲🇽 +52 · 🇺🇸 +1 · 🇪🇸 +34 · 🇦🇷 +54 · 🇨🇱 +56 · 🇧🇷 +55

- Dropdown con bandera + código + label.
- Validación: 7-14 dígitos en el número (sin contar prefix).
- E.164 construction: `+<country><digits>`.
- `formatPhone()` mejorado para mostrar `+<code> <digits>` con detección de prefijo.
- Disclaimer: bot WhatsApp optimizado para CO; otros países el contact se registra OK pero el flujo del bot puede ser limitado (i18n out of scope rev. 102).

`f496dad`.

### Anonimizar — Dialog con motivo obligatorio

**Antes:** `consent_revoked_reason="Solicitud de supresión vía SAR"` hardcoded.
**Ahora:** dialog confirmación incluye input requerido **"Motivo de la supresión"** con minLength=10. Botón "Sí, anonimizar" disabled hasta cumplir mínimo. Server rechaza con HTTP 400 si reason length entre 1-9.
`aaa5fe8`.

### `primary_identifier` en SAR JSON export

Nuevo bloque al inicio del JSON descargado:

```json
{
  "primary_identifier": {
    "kind": "document|phone|internal_uuid",
    "value": "CC 1234567890",
    "note": "Identificador legal primario del titular..."
  },
  "subject": { ... },
  ...
}
```

Jerarquía: document > phone > UUID. PDF muestra banner verde prominente al inicio. `df526b8`.

### Form Add — fix UX

- Después de save exitoso: `form.reset()` + remount `AddressSelector` con `key` + reset `addConsentChecked` + reset `addConsentSource` + reset `addPhoneCountry='57'`.
- Banner verde flotante top-right con `CheckCircle2` (3.5s fade) — sustituye absence de feedback.
- Botón "Editar datos" reemplaza `<details>/<summary>` gris pequeño por Button outline con icono Pencil + label *"Editar datos / Acciones Habeas Data"*.

`41ffe1f`, `5df239a`.

### Eliminar contacto — Dialog con educación

`window.confirm` nativo → Dialog rojo con warning + comparación clara entre **Eliminar** vs **Anonimizar**:

> **Diferencia:**
> - **Eliminar**: borra el contacto completo. No queda registro Habeas Data.
> - **Anonimizar**: borra solo PII pero conserva audit inmutable.
>
> Si el motivo es solicitud Habeas Data del titular, usa Anonimizar.

`5df239a`.

---

## Métricas de cierre

| Aspecto | Antes (rev. 101) | Después (rev. 102) |
|---|---|---|
| Tests Python | 1167 | **1178** (+11) |
| validate.sh | 13/13 | **14/14** (incluye `next build` opt-in) |
| TypeScript | OK | OK |
| ESLint | OK | OK (con warnings pre-existentes irrelevantes) |
| Bugs runtime detectados+fix | n/a | **5** (digest, build, tenant API, orders schema, refresh) |
| Países soportados en phone | 1 (CO) | **10** |
| Canales de consent (UI) | 7 | **5** (defensibles) |
| Tipos de documento | 6 (incl. TI) | **5** (sin TI menores) |
| Detectores pre-LLM Habeas Data | 3 (revoke, export, rectify) | **4** (+ `_detect_minor_intent`) |
| Capas de defensa Art. 9 | 1 (UI laxa) | **3** (UI preventiva + server guard + DB constraint heredada) |

---

## Memorias persistidas en sesión

| Archivo | Regla |
|---|---|
| [feedback_local_logs.md](../../.claude/projects/.../memory/feedback_local_logs.md) | Logs en `/home/ansible/commerce-ops-local/logs/` son fuente de verdad runtime — leer ANTES de especular causas |
| [feedback_ui_colors.md](../../.claude/projects/.../memory/feedback_ui_colors.md) | Tailwind shades 300-500 son fluorescentes; usar 700 para texto/borders |
| [feedback_scope_discipline.md](../../.claude/projects/.../memory/feedback_scope_discipline.md) | Pregunta = respuesta de texto. NO hacer cambios anticipados que el usuario no pidió literalmente |

---

## Follow-ups

| ID | Tarea | Esfuerzo | Prioridad |
|---|---|---|---|
| **F8** | Flujo de representante legal para venta a menores (TI). Tablas extra: `representative_*`. Sprint dedicado | ~3-5 días | Solo si llega tenant que vende a menores |
| **F9** | i18n del bot WhatsApp para países no-CO. Adapt prompts + detectores por idioma/país | ~1-2 semanas | Solo si llegan tenants con base internacional |
| **F10** | Upload de evidencia física (PDF/imagen) para canal `in_person` | ~3 días | Solo si el tenant lo necesita explícitamente |
| **F11** | Reporte SIC pre-cocinado más rico — incluir `consent_evidence.renewals_after_revocation` | ~1 día | Cuando llegue queja SIC |
| F2 | Tokenización Vault de `document_number` | (pendiente desde rev. 99) | Cuando SIC exija cifrado at-rest |

---

## Estado del repo

- **Tip:** `f496dad` (post este reporte: TBD).
- Todos los cambios pusheados a `origin/develop`.
- Render auto-deploy activo para `konvi-web` y `konvi-api`.
- VM local: requiere reinicio de API tras cambios server-side (`make -C /home/ansible/commerce-ops-local restart-api`).

## INTERVENCION HUMANA todavía pendiente

| ID | Acción | Bloqueante |
|---|---|---|
| **H7** | Rotar Supabase service_role + anon + DB password + Meta App Secret + Wompi sandbox keys | Sí, único bloqueante real para producción real (commit be739a4 con plaintext en historia git pushed a GitHub) |
| H2 | Configurar `RESEND_API_KEY` en Render Dashboard | No (sistema usa fallback graceful log-only) |

---

**Estado certificación:** ✅ rev. 102 técnicamente CERTIFIED + Habeas Data UX/legal hardening operacional. Solo H7 condiciona el go-live real.
