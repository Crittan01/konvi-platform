# Flujo — Opt-out y Habeas Data (Ley 1581 / Decreto 1377)

> Estado: VIGENTE · Última verificación contra código: 2026-08-02 @ develop

Revocación de consentimiento (STOP), re-opt-in, solicitudes de derechos del titular (DSR) y retención de datos. Principio rector verificado en todo el path: **fail-closed** — ante error, se calla el bot; nunca se auto-borra nada sin humano.

---

## 1. STOP → consent revocado → conversación `opted_out`

1. **Detección de keyword inequívoca**: `STOP/BAJA/CANCELAR/UNSUBSCRIBE/...` (`services/ai-orchestrator/agentic/dispatcher.py:3810, 3926`; clasificadores en `lib/whatsapp_optout.py:129` `is_optout_keyword` y `:88` `is_ambiguous_optout_keyword` — las ambiguas NO disparan opt-out).
2. **Handler determinístico, sin LLM** — `_handle_optout_if_keyword` (`dispatcher.py:3856`, invocado en el gate de 196-224):
   - Envía confirmación canónica al cliente.
   - **Revoca consent (soft)**: `soft_revoke_consent` (`whatsapp_optout.py:195`) → `contacts.consent_revoked_at` + `consent_revoked_reason` + evento en `consent_audit_log`. **NO anonimiza PII** — es opt-out suave: revoca el canal, no borra los datos (docstring 203-208; matriz de escenarios en 10-17).
   - **Marca la conversación** `status='opted_out'` (`mark_conversation_opted_out`, 241).
   - El turno **no avanza al LLM** (post-check `dispatcher.py:212-216`).
3. **Fail-closed**: si el handler falla estando presente la keyword, `_optout_failclosed_should_skip` silencia el turno (`dispatcher.py:222-224`) — un STOP jamás se procesa como mensaje normal.

## 2. Gate outbound (el opt-out se respeta en ambos sentidos)

- **Inbound**: `opted_out ∈ _SKIP_STATUSES` del dispatcher (`dispatcher.py:3618`) — el bot no responde. Además el connector **re-fuerza** `conv='opted_out'` en CADA inbound mientras `consent_revoked_at NOT NULL` (`whatsapp_optout.py:162-165`) — defensa en profundidad.
- **Proactivo/outbound**: los envíos proactivos se filtran por `consent_revoked_at` no-NULL (`whatsapp_optout.py:31`).
- **Validador pre-envío**: `outbound/validator.py` aplica el hard gate **no-PII-pre-consent** (Ley 1581 art. 9, 90-101): si el texto candidato pide PII y `contact.consent_given=false` → reescritura dura al template de consentimiento.
- Contrato de dominio: `services/api/domain/conversation_contract.py` — `opted_out` como estado canónico (12) + `SKIP_REASON_OPTED_OUT` (21).

## 3. DSR (acceso / rectificación / eliminación) → escalación humana, NO auto-borra

- **Detección**: `safety/consent_gates.py` — `detect_revocation_intent` (143) y detectores de rectificación/export, con **precedencia** `revocación > rectificación > export` (16-18, 168): "elimina mis datos" siempre domina por riesgo.
- **Gate en dispatcher** (252-270) → `_handle_data_rights_if_intent` (513):
  - **Nunca auto-ejecuta borrados** (docstring 525): un DSR exige verificación de identidad + plazo legal; lo tramita un humano.
  - Audit del evento (`_log_habeas_event`, 489) con gate de origen.
  - **Pausa la conversación** tras el DSR — el bot no puede seguir conversando como si nada (612-627); si la pausa falla, log crítico (627).
  - Notifica Telegram con la acción requerida: "tramitar el DSR + responder al cliente" (642).
  - Ante error del handler → skip del turno (270): responder mal a un DSR es la dirección legalmente insegura.
- **Trámite en consola** (el humano): `services/api/routers/data_subject_request.py` — `POST /contacts/{contact_id}/data-subject-request` (256): estados `received` → `pending_review` (339-344) → `erased` (401); export de datos del titular (`_build_export_payload` 127, render HTML 414); borrado ejecutado por operador (`_execute_erase` 235); auditoría con **teléfono hasheado** (67); notificación SAR best-effort (101). UI: `apps/web/app/dashboard/(sales)/contacts/_components/habeas-data-actions.tsx`.
- **Menores**: intent de menor de edad → gate de prioridad máxima ANTES del DSR (`dispatcher.py:230-248`; Decreto 1377/2013 Art. 7) — no se tratan datos de menores sin representante.

## 4. Re-opt-in (volver a hablar con el bot)

- **Keywords afirmativas**: `SUSCRIBIR`/`START`/`REACTIVAR` (`is_optin_keyword`, `whatsapp_optout.py:140`). Re-otorgar consent exige **acto afirmativo inequívoco** — no se infiere de un mensaje ambiguo; mismo rigor que el opt-out (107-110). "Nadie adivina" estas keywords (`dispatcher.py:3923`).
- **Orden del gate**: el re-opt-in corre **ANTES** del skip por `opted_out` (`dispatcher.py:167-185`) — sin esto, un cliente opted-out quedaría mudo de por vida.
- **Restauración**: `restore_consent` (`whatsapp_optout.py:153`) limpia `consent_revoked_at` + `consent_revoked_reason` (OBLIGATORIO: sin limpiar, el connector re-marca `opted_out` en el siguiente inbound, 162-165). No toca `consent_given` original.
- **Desde consola**: el operador también puede reactivar un contacto (`services/api/routers/contacts.py:675-685`: STOP→`opted_out` / Reactivar→`bot_active`).

## 5. Retención de datos

- **Políticas per-tenant**: `/dashboard/settings/retention` (`retention-policies-form.tsx`); la retención archiva conversaciones de cualquier status (el badge de takeover excluye archivadas, `layout.tsx:88-90`).
- **Motor**: `fn_apply_retention` (SECURITY DEFINER). **Gap latente M6**: la función no tiene rama para `audit_log` (la política insertada queda con condición FALSE) — pendiente.
- **Retenciones duras verificadas en código**: inbox de webhooks Wompi — **7 días procesadas / 30 días dead-letter** vía RPC `cleanup_wompi_inbox` cada 6h (`worker.py:3290-3301`); el payload crudo contiene PII del pagador y la purga corre aunque el reconcile esté desactivado.

## 6. Secuencia resumida

```text
STOP/BAJA/CANCELAR/UNSUBSCRIBE
  → confirmación canónica + soft_revoke_consent (consent_revoked_at + audit_log)
  → conv='opted_out' · turno NO llega al LLM (fail-closed)
  → outbound proactivo filtrado · connector re-fuerza opted_out en cada inbound

"elimina mis datos" / DSR
  → detect (precedencia revocación>rectificación>export)
  → escalación humana + conv pausada + Telegram + audit
  → operador tramita en Contactos (received→pending_review→erased) — NUNCA auto-borra el bot

SUSCRIBIR/START/REACTIVAR (acto afirmativo)
  → gate ANTES del skip → restore_consent (limpia revoked_at/reason)
  → conv vuelve a bot_active · siguiente inbound procesa normal
```

---

### Archivos clave

| Pieza | Archivo |
|---|---|
| Gates dispatcher | `services/ai-orchestrator/agentic/dispatcher.py` (167-270, 3618, 3856) |
| Opt-out/consent lib | `services/ai-orchestrator/lib/whatsapp_optout.py` |
| Detección DSR/minor | `services/ai-orchestrator/safety/consent_gates.py` |
| Validador outbound | `services/ai-orchestrator/outbound/validator.py` (90-101) |
| Trámite DSR consola | `services/api/routers/data_subject_request.py` |
| Reactivación consola | `services/api/routers/contacts.py` (675-685) + `habeas-data-actions.tsx` |
| Contrato estados | `services/api/domain/conversation_contract.py` |
| Retención | `apps/web/.../settings/retention/`, `fn_apply_retention` (M6), `worker.py:3290-3301` |
