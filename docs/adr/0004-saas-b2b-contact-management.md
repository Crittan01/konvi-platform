# ADR-0004: Modelo SaaS B2B para módulo Contactos (rev. 103)

## 1. Status

**Accepted** · 2026-05-02 (rev. 103)
Reemplaza la postura UX hardening de rev. 102 conservando los controles
legales reales de rev. 93–99 (audit log inmutable, SAR, anonimización,
DPA click-wrap).

## 2. Context

### Detonante

Tras revs 93–102 (cierre Habeas Data + UX hardening), una pregunta del
usuario sobre referentes en la industria (Mailchimp, Wati, Whaticket,
Respond.io) forzó re-evaluación del rol legal del proyecto.

Habíamos posicionado a la plataforma como "Encargado activo" con captura
estricta de consent en cada interacción del operador del Tenant Console.
Esto resultó en 3 capas de validación (UI preventiva, server guards, DB
constraints) que generaban fricción operacional sin valor legal
incremental real para un modelo SaaS B2B:

- Inputs PII bloqueados (`disabled`) si el operador no marcaba el
  check de consent antes.
- Server actions rechazaban guardado si llegaba PII sin `consent_given=true`.
- Banners amber permanentes "Marca el check para habilitar" en forms.
- Mensajes "Documento de identidad bloqueado — marca el consentimiento".

Mientras tanto, los referentes de la industria (Wati, Mailchimp,
Respond.io) aplican un modelo donde:

- El tenant es **Responsable** del tratamiento (firma DPA con la
  plataforma + se compromete a tener base legal de los datos que registra).
- La plataforma es **Encargado puro**: facilita herramientas, no juzga
  cada captura individual.
- Los inputs PII son siempre editables; el consent es metadata.

### Paradoja operacional

El modelo rev. 102 generaba un caso paradójico:

> "No puedo despachar un pedido si no capturo la dirección, pero no
> puedo capturar la dirección sin marcar consent."

Wompi (PSE/Bancolombia) y Envía exigen estos campos por razones
operacionales (no legales), no por consent. Bloquearlos detrás de un
checkbox de consent rompía flujos legítimos de operación.

## 3. Decisión

La plataforma **Commerce Ops Platform** es **Encargado puro** bajo el
modelo SaaS B2B (estilo Wati/Mailchimp/Respond.io):

- El tenant es Responsable del tratamiento; firma DPA con la plataforma
  (rev. 99 click-wrap) y certifica al firmar que registra datos solo
  con base legal apropiada.
- La plataforma facilita herramientas; no bloquea PII sin consent en
  el form Add/Edit del Tenant Console.
- El bot WhatsApp **mantiene** captura activa de consent — feature
  operacional valiosa que NO contradice el modelo SaaS B2B.
- Cuando el operador llena PII sin marcar consent, el sistema persiste
  con `consent_given=false`. El bot pedirá consent activamente al
  titular en su próxima interacción WhatsApp.
- La anonimización Art. 15 sigue siendo ritual legal serio: el operador
  no puede "revocar por desmarcar el check"; debe usar el botón
  Anonimizar dedicado.

## 4. Consecuencias

### Positivas

- Reducción de fricción operacional (operador no pelea con guards).
- Alineación con la industria (referentes claros: Wati, Mailchimp).
- Audit log inmutable sigue siendo defensa real ante SIC.
- DPA + click-wrap acceptance es el corazón legal.
- Forma natural de manejar imports MeLi (sin flags `purpose_limited`).
- Eliminación de contacto deja audit log con phone hasheado (event
  `deleted` añadido al CHECK constraint).

### Negativas / trade-offs aceptados

- Si un operador del tenant ingresa PII sin consent real del titular,
  la plataforma no lo bloquea técnicamente. Riesgo contractual del
  tenant (cubierto por DPA).
- Cambio de filosofía implica revertir ~10 cambios UX de rev. 102.

### Lo que se mantiene de rev. 93–102 (sigue siendo valioso)

- `consent_audit_log` y `pii_access_log` append-only via DB triggers.
- SAR endpoint con 4 tipos (export, portability, erase, rectify).
- Anonimización Art. 15 con flujo dedicado.
- Detector pre-LLM de revocación en bot WhatsApp.
- Detector pre-LLM de minoría de edad (riesgo real Decreto 1377/2013).
- Click-wrap legal acceptance (DPA tenant ↔ plataforma).
- DPA + privacy policy + subprocessors templates.
- Retention policies con pg_cron domingos 03:xx UTC.
- Vista SQL `vw_consent_events_unified` para reportes SIC.
- Reporte SIC pre-cocinado endpoint.
- Renewed_consent flow post-anonim (ritual Art. 15 mantenido).
- Phone country code multi-país (operacional, sin emoji).
- Validación dinámica documento por tipo (CC/CE/NIT/PP/OTHER).
- Motivo Anonimizar obligatorio.
- Sin TI en select (Decreto 1377/2013 requiere representante legal —
  riesgo legal real evitado).

### Lo que se simplifica (rev. 103)

| Aspecto | Modelo rev. 102 | Modelo rev. 103 |
|---|---|---|
| Form Add Contacto | Inputs PII `disabled` sin consent + 3 capas de defensa Art. 9 | Operador llena lo necesario; persiste con `consent_given=false` si no marca |
| Form Edit Contacto | `disabled={!piiUnlocked}` requiere consent + canal | Editable libre; solo gating en post-anonimización (Art. 15) |
| MeLi import | `purpose_limited` + restricciones bot + base legal compleja | `consent_source='marketplace_meli'` + audit log; bot trata como cualquier contact |
| Eliminar contact | Guards educativos rechazaban motivos con palabras Habeas Data | Audit log antes del DELETE, motivo opcional |
| Canales consent | 5 "defensibles" (eliminados manual_console + phone_call) | 7 operacionales (restaurados) + `marketplace_meli` (solo backend) |
| Bot WhatsApp consent | Activo | Activo (sin cambios — feature operacional valiosa) |

## 5. Componentes implementados (rev. 103)

### Migraciones SQL

- `20260510010000_consent_audit_log_add_deleted_event.sql` — añade
  `event='deleted'` al CHECK constraint del audit log.
- `20260510011000_contacts_consent_source_marketplace.sql` — añade
  `marketplace_meli` al CHECK de `contacts.consent_source`.
- `20260510020000_consent_evidence_bucket.sql` — bucket privado
  Storage `consent-evidence` con RLS por tenant + role check
  (owner/manager para INSERT, todos los miembros para SELECT).

### Code paths

- `apps/web/.../contacts/page.tsx` — server actions sin guards
  educativos; `deleteContact` hace audit antes del DELETE.
- `apps/web/lib/crypto/phone-hash.ts` — espejo TS del Python
  `_hash_phone` (orchestrator + meli_webhook + data_subject_request).
- `services/api/routers/meli_webhook.py` — `_upsert_meli_contact`
  reescrito con consent simple + audit log inmutable.
- `apps/web/.../contacts/_components/helpers/upload-evidence.ts` —
  server action para upload de evidencia física al bucket Storage.
- `apps/web/.../contacts/_components/helpers/phone-countries.ts` —
  extraído de contacts-manager.tsx (Bloque 4 parcial).
- `apps/web/.../contacts/_components/helpers/consent-source-help.ts` —
  extraído de contacts-manager.tsx (Bloque 4 parcial).

### Tests (rev. 103)

- `tests/test_rev103_form_simplified.py` (20 tests).
- `tests/test_rev103_delete_contact_audit.py` (19 tests).
- `tests/test_rev103_meli_contact_import.py` (12 tests).
- `tests/test_rev103_consent_evidence_cap.py` (4 tests).
- `tests/test_rev103_consent_evidence_upload.py` (26 tests).

### Documentación

- `docs/legal/privacy-policy.md` §10 — datos importados desde
  marketplaces.
- Esta ADR.

## 6. Alternativas consideradas

- **A1**: Mantener Habeas Data full rev. 102. **Rechazada** por
  over-engineering: 3 capas de defensa para un modelo donde el
  Responsable es el tenant, no la plataforma.
- **A2**: Pivot total a SaaS puro (bot NO captura consent, todo lo
  registra el tenant manualmente). **Rechazada**: el bot capturando
  consent es feature operacional valiosa que no contradice el modelo
  SaaS B2B (Wati también lo hace).
- **A3**: Refactor full de `contacts-manager.tsx` (1080 LOC →
  4-5 sub-componentes). **Diferida** a sesión dedicada por riesgo
  de regresión sin tests UI E2E. Bloque 4 parcial extrae solo
  constantes/helpers, no React components.

## 7. Out of scope explícito (futuras revisiones)

- **F2** (Vault tokenization `document_number`) — DEFER. Trigger:
  SIC exige cifrado-at-rest específico, breach demuestra plaintext es
  vector real, o enterprise tenant lo requiere por contrato.
- **F8** (representante legal menores TI) — DEFER. Trigger: tenant
  sector uniformes escolares o similar.
- **F9** (i18n bot WhatsApp) — DEFER. Trigger: tenants con base
  internacional > 5% del volumen.
- **F11** (SAR endpoint público OTP) — DEFER. Trigger: enterprise
  tenant lo exige por contrato.

## 8. Referencias

- `docs/reports/rev93_99_habeas_data_completion.md`
- `docs/reports/rev100_certification_closure.md`
- `docs/reports/rev102_habeas_data_ux_hardening.md`
- `docs/adr/0003-habeas-data-compliance-strategy.md`
- `docs/legal/dpa-template.md`
- `docs/legal/privacy-policy.md`
- Plan: `~/.claude/plans/declarative-wondering-patterson.md`
