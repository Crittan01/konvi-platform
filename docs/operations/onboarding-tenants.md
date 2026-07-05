# Runbook — Onboarding de un tenant nuevo (provisión → operando)

**Última actualización**: 2026-07-04
**Audiencia**: founder/admin de Konvi. Proceso **ADMIN-controlado** (decisión founder: NO signup público).
**Objetivo**: que integrar un tenant nuevo sea **repetible** y verificable de punta a punta.
**Modelo Meta**: Direct Provider per-tenant — cada tenant trae SU PROPIA Meta App (ADR-0023).

> Este runbook es la fuente de verdad operativa. La guía que le pasás al tenant para WhatsApp es
> `docs/onboarding/whatsapp-tenant-setup.md`. Trámites Meta humanos: `docs/onboarding/H1-H5-checklist.md`.

---

## Requisitos previos (una sola vez, del lado Konvi)

- Env con `NEXT_PUBLIC_SUPABASE_URL` + `SUPABASE_SECRET_KEY` (o `SUPABASE_SERVICE_ROLE_KEY`).
- Migración `20260702190000_f3_provision_tenant.sql` aplicada (RPC `public.provision_tenant`).
- Opcional (audit trail atómico): `20260704120000_f3_provision_tenant_audit.sql` — **pendiente aplicar**
  (ver §7). Sin ella, el audit lo escribe el script best-effort.

---

## 1 · Provisionar el tenant + owner (1 comando, atómico)

El RPC `provision_tenant` crea **tenant + tenant_users(owner) + subscripción** en UNA transacción. El script
`scripts/admin/provision_tenant.py` crea el usuario auth del owner (si no existe) y lo invoca.

```bash
# Recomendado: enlace de recuperación (no expone contraseñas) + actor para audit trail
python3.11 scripts/admin/provision_tenant.py \
  --tenant-name "Mi Negocio" \
  --owner-email owner@negocio.co \
  --plan basic \
  --reset-link \
  --actor-email founder@konvi.co

# Si el usuario auth YA existe:
python3.11 scripts/admin/provision_tenant.py --tenant-name "Mi Negocio" --owner-user-id <uuid> --actor-email founder@konvi.co

# Ensayo sin escribir nada (imprime el plan + checklist):
python3.11 scripts/admin/provision_tenant.py --tenant-name "Mi Negocio" --owner-email owner@negocio.co --dry-run
```

**Planes válidos**: `basic` (default) · `pro` · `enterprise`.

**Salvaguardas del script (idempotencia / seguridad)**:

- **Owner ya-owner** → **aborta**. Provisionar un 2º tenant para el mismo owner deja su JWT no
  determinístico (`custom_access_token_hook` hace `SELECT ... LIMIT 1` sin `ORDER BY`). Forzá con
  `--allow-multi-tenant` sólo si el negocio maneja varias marcas y aceptás ese no-determinismo.
- **Nombre de tenant duplicado** → **aborta** (`tenants.name` no tiene UNIQUE). Forzá con
  `--allow-duplicate-name`.
- **Búsqueda de email pagina completa** la lista de usuarios auth (no sólo la 1ª página).
- **`--reset-link`**: entrega un enlace de recuperación Supabase en vez de imprimir una contraseña temporal.
- **`--actor-email`**: escribe la fila de audit (`action='tenant.provisioned'`) en `public.audit_log`.

**Cómo queda operativo el owner**: NO hay trigger `on_tenant_assignment` (eliminado en
`20260426080000_drop_tenant_assignment_trigger.sql`). El `custom_access_token_hook` inyecta `tenant_id` al
access token en cada emisión de JWT. El owner sólo tiene que entrar (su primer JWT ya trae el tenant).

**Verificación del paso 1**:

```sql
-- tenant + owner + subscripción
SELECT t.id, t.name, tu.role, tu.status, ts.plan_code
FROM tenants t
JOIN tenant_users tu ON tu.tenant_id = t.id AND tu.role='owner'
JOIN tenant_subscriptions ts ON ts.tenant_id = t.id
WHERE t.name = 'Mi Negocio';
-- audit trail
SELECT action, user_email, created_at FROM audit_log
WHERE entity_type='tenant' AND action='tenant.provisioned' ORDER BY created_at DESC LIMIT 3;
```

---

## 2 · Primer login del owner

1. Entregale el **enlace de recuperación** (o la contraseña temporal) que imprimió el script.
2. El owner entra, fija su contraseña, y aterriza en `/dashboard` **aislado** (multi-tenant real).
3. Pasale la guía tenant de WhatsApp: `docs/onboarding/whatsapp-tenant-setup.md`.

---

## 3 · Checklist de credenciales por integración (lo captura el owner)

El script imprime este checklist al final. Cada integración es **per-tenant** (el tenant trae sus keys).

### WhatsApp — ADR-0023 Model B (SU PROPIA Meta App, 6 credenciales)

Panel: **Integraciones → WhatsApp → panel completo** (form de 6 campos; el de 3 campos es legacy e
insuficiente — falta `app_secret` + `verify_token`).

> ⚠️ **Gate legal (tenant externo, producción)**: capturar `app_secret` implica custodia de una credencial de
> la Meta App del tenant → exige **DPA tenant-Konvi** con la cláusula de custodia aceptada
> (`docs/legal/dpa.md` §5.bis, ADR-0023 OQ-1). Cláusula **pendiente de cierre legal** (ver §7). Hasta el
> cierre, no capturar `app_secret` de tenants externos en producción. **KAIU (self) exento.**

- [ ] **DPA tenant-Konvi** aceptado (custodia `app_secret`, Model B) — pre-requisito de las 2 filas Vault de
      abajo para tenants externos en producción. Estado de la cláusula: **pendiente legal** (§7).
- [ ] `app_id`
- [ ] `app_secret` → Vault (HMAC del webhook)
- [ ] `verify_token` (lo elige el tenant; handshake GET)
- [ ] `phone_number_id`
- [ ] `waba_id`
- [ ] `access_token` (System User never-expires) → Vault
- [ ] Webhook en la Meta App del tenant apuntando a la URL **per-tenant**:
      `<WHATSAPP_CONNECTOR_URL>/api/v1/whatsapp/webhook/{tenant_id}` (la muestra el panel, botón Copiar).

> El host del webhook lo define el env **`WHATSAPP_CONNECTOR_URL`** del API (`services/api/routers/integrations.py`).
> Si no está seteado, el endpoint defaultea a `https://api.konvi.co` — que hoy NO tiene DNS y no puede servir
> a la vez al API y al connector (ADR-0023 OQ-4, acción founder). Ver §7.

### Wompi (pagos)

- [ ] `private_key` · [ ] `events_key` → panel Wompi.
- [ ] Webhook Wompi apuntando a `<API>/api/v1/webhooks/wompi` (ruta real; NO `/api/v1/wompi/webhook`).

### Aveonline (despacho — provider activo, ADR-0019; Envia fue retirado en rev. 109)

- [ ] Credenciales del carrier + **origen de despacho** (sin origen el bot no cotiza envíos).
- [ ] Webhook de estados de guía (lo configura el panel Aveonline).

### Telegram (opcional)

- [ ] Bot token. Webhook: `<API>/api/v1/integrations/telegram/webhook` (ruta real).

### Contenido operativo

- [ ] **Catálogo**: productos cargados (sin productos el bot no cotiza).
- [ ] **Agente IA**: prompt configurado + agente activo.
- [ ] **Plantillas HSM** (si aplica): se crean en el panel; el **submit a Meta para review es admin-run**
      (`scripts/admin/submit_template_to_meta.py`, requiere `SUPABASE_SERVICE_ROLE_KEY`) — el operador tenant
      no lo ejecuta. Coordinar con el founder (ver `needs_founder` en §7: exponer submit en UI).

---

## 4 · Trámites Meta del tenant (calendario largo)

Bajo Model B el tenant hace **con su propia App/Business**: Business Verification (1-3 semanas) + App Review
para Advanced Access (1-2 semanas). En Development Mode puede probar con ~5 números. Detalle en la guía
tenant §"Trámites Meta para producción". Konvi NO tramita en nombre del tenant.

---

## 5 · Verificación end-to-end (criterio de éxito)

- [ ] Owner entra y ve SU dashboard (sin datos de otros tenants).
- [ ] WhatsApp: handshake del webhook OK (Meta "Verify and save" verde) + HMAC OK.
- [ ] **Primer mensaje**: enviar "Hola" al número → aparece en Inbox → el bot responde.
- [ ] **Primer pedido**: el bot cotiza (catálogo + origen) → genera link Wompi → pago → orden confirmada.
- [ ] Audit: `SELECT * FROM audit_log WHERE action='tenant.provisioned'` tiene la fila del tenant.

Aislamiento (spot-check): con el JWT del owner, cualquier query devuelve sólo filas de su `tenant_id`
(RLS + lint AST `scripts/audit_tenant_filter.py`, ADR-0025).

---

## 6 · Rollback / errores comunes

| Síntoma | Causa probable | Acción |
|---|---|---|
| Script aborta "owner ya es owner activo" | El owner ya tiene tenant | Confirmar intención; `--allow-multi-tenant` sólo si aplica |
| Script aborta "ya existe tenant con name" | Nombre repetido | Renombrar o `--allow-duplicate-name` |
| `create_user already exists` | Email ya en auth | Reusar con `--owner-user-id <uuid>` |
| Webhook handshake falla | verify_token distinto o no guardado en Konvi | Guardar en Konvi primero, verify_token idéntico |
| Bot no recibe mensajes | app_secret equivocado / no suscrito a `messages` | Revisar app_secret de la App del tenant + fields |
| Confirmaciones de pago 404 | URL Wompi mal (`/api/v1/wompi/webhook`) | Usar `/api/v1/webhooks/wompi` |

Para deshacer una provisión de prueba, ver `docs/operations/` (offboarding) y `tests/test_tenant_offboarding.py`.

---

## 7 · Acciones founder pendientes (bloqueantes de producción)

- **Aplicar** `supabase/migrations/20260704120000_f3_provision_tenant_audit.sql` (audit trail atómico en el
  RPC). Requiere protocolo seguro de migración al remote (ledger con drift). Hasta entonces, el audit lo hace
  el script best-effort con `--actor-email`.
- **DNS / `WHATSAPP_CONNECTOR_URL`** (ADR-0023 OQ-4): definir el host del connector y setear el env en
  `render.yaml` para que la URL de webhook que muestra el panel sea servible. `api.konvi.co` sin DNS no puede
  servir a la vez API (wompi/telegram) y connector (whatsapp).
- **DPA tenant-Konvi** para custodia del `app_secret` (ADR-0023 OQ-1, legal externo). **Bloquea onboarding de
  tenants externos en producción** (no KAIU=self). Placeholder trazable de la cláusula:
  `docs/legal/dpa.md` §5.bis (redacción vinculante pendiente). El gate operativo está en §3 (checklist
  WhatsApp) y en la guía tenant Paso 6 (`docs/onboarding/whatsapp-tenant-setup.md`).
- **Submit de plantillas HSM en UI**: hoy es admin-run (`submit_template_to_meta.py`); decidir si se expone
  al operador tenant o se mantiene como acción admin.

---

## Referencias

- `scripts/admin/provision_tenant.py` — el comando de provisión.
- `supabase/migrations/20260702190000_f3_provision_tenant.sql` — RPC transaccional.
- `docs/onboarding/whatsapp-tenant-setup.md` — guía tenant WhatsApp Model B.
- `docs/onboarding/H1-H5-checklist.md` — trámites Meta humanos.
- `docs/adr/0023-meta-model-b-direct-provider-per-tenant.md` — Direct Provider per-tenant.
- `docs/adr/0025-multi-tenant-isolation-strategy.md` — aislamiento (lint AST + RLS + Vault).
- `docs/adr/0019-*` — Aveonline como shipping provider (Envia retirado rev. 109).
