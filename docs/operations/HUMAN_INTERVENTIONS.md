# Intervenciones Humanas Requeridas (vigente)

Última actualización: 2026-04-21

Este documento conserva solo intervenciones activas reales.

---

## IH-SEC-01 — Rotación preventiva de credenciales sensibles

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner/DevOps  
**MOMENTO**: Inmediato (antes de siguiente release candidato)  
**PASOS DUMMY O GUIADOS**:
1. Rotar `SUPABASE_SERVICE_ROLE_KEY` en Supabase.
2. Actualizar key nueva en Render (`web`, `connector`, `api`, `orchestrator`) y entorno local.
3. Validar health checks y operaciones críticas.
**INSUMOS NECESARIOS**: Acceso Supabase + Render.  
**CRITERIO DE EXITO**: key anterior inválida, key nueva funcionando, sin errores de auth backend.

---

## IH-SEC-02 — Auditoría de exposición histórica de credenciales

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner/DevOps  
**MOMENTO**: Antes de release candidate público  
**PASOS DUMMY O GUIADOS**:
1. Revisar historial git y secretos del repositorio en GitHub (secret scanning / push protection).
2. Confirmar que no existan tokens activos en URLs remotas locales/equipos.
3. Rotar cualquier credencial que haya sido expuesta históricamente (aunque hoy no esté en HEAD).
4. Documentar la rotación en este archivo y en `docs/HANDOFF.md`.
**INSUMOS NECESARIOS**: Acceso admin a GitHub, Supabase, Render y proveedores externos.
**CRITERIO DE EXITO**: no hay secretos activos expuestos en historia utilizable ni remotes locales con credenciales embebidas.

---

## IH-INFRA-01 — Decisión de upgrade a plan pago

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner del producto  
**MOMENTO**: Cerca de salida a producción o ante bloqueante operacional en Free  
**PASOS DUMMY O GUIADOS**:
1. Confirmar trigger real (tenant productivo o degradación por Free).
2. Aprobar presupuesto y método de pago.
3. Ejecutar upgrade de servicios en Render.
4. Cambiar orchestrator a `type: worker` y revalidar colas.
**INSUMOS NECESARIOS**: Cuenta Render con billing habilitado.  
**CRITERIO DE EXITO**: operación estable sin dependencia del workaround de daemon thread.

---

## IH-META-01 — Meta Embedded Signup / Tech Provider (futuro de onboarding)

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner de plataforma  
**MOMENTO**: Antes de habilitar onboarding self-serve multi-canal  
**PASOS DUMMY O GUIADOS**:
1. Verificar negocio y app en Meta.
2. Completar app review/permisos requeridos.
3. Configurar Embedded Signup y callback productivo.
4. Validar flujo end-to-end con tenant piloto.
**INSUMOS NECESARIOS**: Cuenta Meta Business verificada + dominio + política de privacidad.  
**CRITERIO DE EXITO**: tenant conecta su canal sin intervención manual de soporte.

---

## IH-AGENT-01 — Regenerar prompt de agente Carolina (Reclamos) post-rev109

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner del tenant (founder KAIU + cada tenant con agente claims)  
**MOMENTO**: Recomendado ahora (post-commit `888af91`). Opcional — el invariant FakeEscalation respalda si Carolina olvida el tool.  
**PASOS DUMMY O GUIADOS**:
1. Abrir Tenant Console → IA y Conocimiento → Agentes IA.
2. Click "Editar" en Carolina (agente role=claims).
3. Click "Sugerir con IA" para regenerar `role_description` con el skeleton actualizado (que ahora instruye usar `create_claim` ANTES de escalar).
4. Revisar el texto sugerido — debe mencionar create_claim explícitamente.
5. Click "Guardar cambios".
6. Repetir para cualquier OTRO agente role=claims de cualquier tenant.

**INSUMOS NECESARIOS**: Tenant Console activo + sesión owner/manager.

**CRITERIO DE EXITO**: Carolina (o el agente claims del tenant) tiene `role_description` que menciona create_claim y `get_claim_status`. En UAT live, Carolina invoca create_claim en lugar de escalar.

**Por qué OPCIONAL**: el invariant `FakeEscalationInvariant` (rev. 109) detecta promesas de escalación sin tool real y respalda. Pero tener el prompt actualizado mejora UX (Carolina sabe el flujo correcto desde el primer turn, sin necesidad de respaldo del invariant).

---

## IH-NOTIF-01 — Migrar tenants legacy de `tenant_integrations.telegram` a `notification_settings`

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner/DevOps  
**MOMENTO**: D+30 post-rev109 commit `eb30a74` (~2026-06-27). Solo si hay tenants legacy con configuración en `tenant_integrations` pero NO en `notification_settings`.  
**PASOS DUMMY O GUIADOS**:
1. Ejecutar audit query:
   ```sql
   SELECT ti.tenant_id, ti.meta->>'chat_id' AS chat_id
   FROM tenant_integrations ti
   LEFT JOIN notification_settings ns
     ON ns.tenant_id = ti.tenant_id AND ns.channel = 'telegram'
   WHERE ti.provider = 'telegram'
     AND ti.status = 'connected'
     AND (ns.id IS NULL OR ns.enabled = false);
   ```
2. Para cada tenant retornado:
   - Coordinar ventana con tenant.
   - Upsert en `notification_settings` (channel='telegram', enabled=true, config={chat_id, bot_token_secret_id}).
   - Verificar smoke: triggear escalación de prueba → verificar POST api.telegram.org → 200 OK.
3. Tras verificación: ejecutar Fase 3 del ADR-0021 (DELETE rows path A) en D+60.

**INSUMOS NECESARIOS**: Acceso DB Supabase + coordinación con cada tenant.

**CRITERIO DE EXITO**: query audit retorna 0 rows; ADR-0021 marcado CERRADO.

**Referencia**: ver `docs/adr/0021-notification-channels-unified-source.md`.

---

## IH-EMAIL-01 — Site URL productivo + allow-list de redirects (Supabase Auth)

**INTERVENCION HUMANA REQUERIDA**: Sí
**RESPONSABLE**: Owner/DevOps
**MOMENTO**: Antes del primer tenant productivo (bloqueante: sin esto los links de invite/recovery salen a `127.0.0.1:3000`).
**PASOS DUMMY O GUIADOS**:
1. Dashboard Supabase → Authentication → URL Configuration.
2. `Site URL` = dominio web productivo (igual a `APP_URL` en Render).
3. `Redirect URLs`: agregar `https://<dominio-web>/auth/callback` y `https://<dominio-web>/auth/confirm` (URLs exactas).
**INSUMOS NECESARIOS**: dominio web productivo confirmado.
**CRITERIO DE EXITO**: invite de prueba llega con link al dominio prod y `/auth/callback` establece sesión sin "redirect not allowed".
**Referencia**: `docs/operations/runbooks/supabase-auth-email.md`.

---

## IH-EMAIL-02 — Aplicar plantillas es-CO + branding en el dashboard (Supabase Auth)

**INTERVENCION HUMANA REQUERIDA**: Sí
**RESPONSABLE**: Owner/DevOps
**MOMENTO**: Antes del primer invite productivo (si no, salen defaults de Supabase en inglés).
**PASOS DUMMY O GUIADOS**:
1. Dashboard → Authentication → Emails (Templates).
2. Pegar `subject` + HTML desde `supabase/templates/*.html` en cada plantilla (Invite, Reset Password, Confirm signup, Magic Link, Change Email).
3. Verificar que el link siga siendo `{{ .ConfirmationURL }}` (no reescribirlo a mano: desacopla de `/auth/callback` y `/auth/confirm`).
**INSUMOS NECESARIOS**: acceso admin dashboard; archivos del repo como fuente de verdad.
**CRITERIO DE EXITO**: invite de prueba llega en es-CO, con "Konvi" y nombre del negocio visible; botón lleva a `/auth/callback`.
**Referencia**: `docs/operations/runbooks/supabase-auth-email.md`.

---

## IH-EMAIL-03 — Custom SMTP: deliverability + rate-limit (Supabase Auth)

**INTERVENCION HUMANA REQUERIDA**: Sí
**RESPONSABLE**: Owner/DevOps + acceso al registrar DNS
**MOMENTO**: Antes de producción (bloqueante legal Ley 1581 + funcional).
**PASOS DUMMY O GUIADOS**:
1. Elegir proveedor (recomendado dossier: Resend, `smtp.resend.com:587`). Ver `docs/research/sender-email-dossier-2026-05-05.md`.
2. Verificar dominio: SPF + DKIM + DMARC en DNS.
3. Dashboard → Authentication → SMTP Settings → habilitar Custom SMTP (`sender_name = "Konvi"`).
4. Dashboard → Authentication → Rate Limits → subir emails/hora (default compartido ~2-4/h bloquea invitar 3+ seguidos).
**INSUMOS NECESARIOS**: cuenta proveedor SMTP + acceso DNS del dominio.
**CRITERIO DE EXITO**: envío de prueba a Gmail llega a inbox (no spam); invitar 3+ miembros seguidos no choca rate-limit.
**Referencia**: `docs/operations/runbooks/supabase-auth-email.md` + dossier §8-9.
