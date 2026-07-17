# Ambientes e infraestructura — convención de nombres + runbook

> Cierra el CRITICAL **dev = prod comparten Supabase** (auditoría 2026-07-13/16). Alinea
> con la guía oficial de Supabase [Managing Environments](https://supabase.com/docs/guides/deployment/managing-environments):
> **proyectos separados por ambiente** + migraciones como fuente de sincronización de schema.
> Precios verificados 2026-07-16 ([Supabase pricing](https://supabase.com/pricing), [Render free](https://render.com/docs/free)).

## 1. Estrategia

Dos ambientes, **aislados a nivel de organización Supabase** (no solo de proyecto):

- **prod** — datos reales (pedidos, pagos, audit Habeas Data, Vault). Plan **Pro** (backups diarios). Es el único que NO puede perder datos.
- **dev** — datos **sintéticos** (seed). Plan **Free** (sin backups; se pausa tras >1 semana inactivo — **reanudación MANUAL en el Dashboard**, no auto-wake ante request [verificado: [free-project-pausing](https://supabase.com/docs/guides/platform/free-project-pausing)]). Aísla el desarrollo local para que un test destructivo JAMÁS toque prod. *(Si el pausing molesta: subir la org Dev a Pro — sigue aislada — en vez de un ping semanal.)*

**Por qué orgs SEPARADAS y no 2 proyectos en la misma org:** la facturación de Supabase es por-org; un 2º proyecto en la org Pro cuesta **+~$10/mes** (compute), mientras que un proyecto en una **org Free separada = $0** + aislamiento total de billing/acceso.

## 2. Convención de nombres (canónica)

### Supabase
| Ambiente | Organización | Proyecto | Plan | Ref (inmutable) |
|---|---|---|---|---|
| **prod** | `Konvi` *(org existente)* | **`konvi-prod`** *(renombrar de `konvi-ops`)* | **Pro** | `xmelwnhhphksbpdjmbbp` |
| **dev** | **`Konvi Dev`** *(nueva, Free)* | **`konvi-dev`** | **Free** | `qkltqxbhssgnyjqltwcr` |

- **Renombrar `konvi-ops` → `konvi-prod` es SEGURO y cosmético:** el *project ref* (`xmelwnhhphksbpdjmbbp`) y la URL de conexión son **inmutables**; solo cambia el nombre visible. Verificar en Settings → General que el ref no cambia.
- **Región del dev = la misma que prod** (paridad de latencia/comportamiento).

### Render — estructura (workspace → project → environment → servicios)
```
Workspace:  My Workspace (crittan01@gmail.com)
└── Project:  Konvi                       (prj-d6hlqr9aae7s73c0kp20)
    └── Environment:  Production          (evm-d6hlqr9aae7s73c0kp2g)
        ├── konvi-connector   (srv-d8e9mk4m0tmc73elvme0)  webhooks Meta (mensajes)
        ├── konvi-api         (srv-d8e9mk4m0tmc73elvmeg)  webhooks Wompi/MeLi/Aveonline
        ├── konvi-orchestrator(srv-d8e9mk4m0tmc73elvmdg)  worker/bot
        └── konvi-web         (srv-d8e9mk4m0tmc73elvmf0)  backoffice Next.js (interno)
```

| Servicio | Rol | Instancia recomendada |
|---|---|---|
| `konvi-connector` | webhooks Meta (mensajes) | **Starter** (always-on) |
| `konvi-api` | webhooks Wompi/MeLi/Aveonline | **Starter** |
| `konvi-orchestrator` | worker/bot | **Starter** |
| `konvi-web` | backoffice Next.js (interno) | Starter recomendado / Free aceptable |

- **Multi-tenant real:** estos **4 servicios sirven a TODOS los tenants** (routing por `tenant_id` + RLS + credenciales por-tenant en Vault, ADR-0023 Model B). **N tenants = 4 servicios, siempre.** Agregar un tenant = datos (`provision_tenant.py`), NO un deploy nuevo.
- Regla de nombres: prefijo `konvi-<rol>`. Si a futuro hay staging: nuevo **environment `Staging`** dentro del mismo project `Konvi` (no servicios sueltos).
- **No** se necesita un Render dev por ahora: el desarrollo local apunta al Supabase **dev**.
- *(Limpieza 2026-07-16: se eliminó `kaiu-api` — deploy legacy de un repo distinto (`kaiu-natural-living`), NO parte de Konvi. KAIU es un tenant, no un servicio.)*

### Local / credenciales (repo)
| Archivo | Apunta a | Uso |
|---|---|---|
| `.env` | **dev** (`konvi-dev`) tras el cutover | desarrollo local + ngrok (default seguro) |
| `.env.prod` | **prod** (`konvi-prod`) | operaciones EXPLÍCITAS de prod (migraciones vía protocolo seguro, Render API) — nunca el default |

Ambos gitignored. El `env_guard` anti-prod de scripts destructivos valida contra ambos.

## 3. Runbook (INTERVENCION HUMANA — founder, ~35 min)

### A. Supabase Pro en prod *(no-negociable, primero — ~5 min)*
1. Dashboard → org que contiene **`konvi-ops`** → **Settings → Billing → Upgrade to Pro**.
2. Aceptar el estimado (**~$34.81/mes bruto** = $25 Pro + $9.81 compute Micro; el **crédito de $10 de compute** que incluye Pro cubre un Micro → **~$25/mes neto** [verificado: [manage-your-usage/compute](https://supabase.com/docs/guides/platform/manage-your-usage/compute)]).
3. *(Opcional, clarificación)* Settings → General → renombrar `konvi-ops` → **`konvi-prod`** (el ref no cambia).
- **CRITERIO DE ÉXITO:** proyecto en plan **Pro** + Database → Backups con schedule diario en <24h.
- **PITR:** NO activar (backup diario basta para 1 tenant; reevaluar con >1 tenant pagando).

### B. Proyecto dev en org Free SEPARADA *(~15 min)*
1. Dashboard → menú de org → **New organization** → nombre **`Konvi Dev`** → plan **Free**.
2. Dentro de `Konvi Dev` → **New project** → nombre **`konvi-dev`**, **misma región que prod**, guardar la **DB password**.
3. Settings → API: copiar `Project URL`, `anon key`, `service_role/secret key` + la DB password → pasármelos (o ponerlos en `.env.dev`).
- **CRITERIO DE ÉXITO:** `konvi-dev` activo en org Free separada + credenciales disponibles.

### C. Render — instancias a Starter *(~10 min)*
Para `konvi-connector`, `konvi-api`, `konvi-orchestrator` *(y opcionalmente `konvi-web`)*:
1. Dashboard → servicio → **Settings → Instance Type** → **Free → Starter** → Save.
2. Tras pasar a Starter, retirar el hack anti-hibernación (ya no hace falta).
- **CRITERIO DE ÉXITO:** `/health` responde sin cold-start tras 20+ min inactivo.

### D. Cutover local a dev — ✅ HECHO 2026-07-16 *(no-cost)*
1. ✅ Schema baseline aplicado a `konvi-dev` (77 tablas, 45 policies, 106 funcs).
2. ✅ Seed sintético mínimo: tenant `KAIU Dev (sandbox)` (`d0000000-…0001`) + owner
   login-able (`dev-owner@konvi.test`) + subscription auto (`billing_plans('basic')`).
   *(DIFERIDO: Vault sandbox Meta/Wompi/Aveonline — el bot end-to-end en dev lo
   requiere; no bloquea el aislamiento de datos, que es el CRITICAL.)*
3. ✅ Cutover de credenciales locales → `konvi-dev` (default seguro); snapshots prod aparte:
   - raíz `.env` → dev; prod → `.env.prod`.
   - frontend `apps/web/.env.local` → dev (6 vars Supabase, incl. `DATABASE_URL` pooler
     + `SUPABASE_PROJECT_REF`); prod → `apps/web/.env.local.prod`.
   Todos gitignored.
4. ✅ `env_guard` fail-closed (`scripts/_env_guard.py`, modelo **deny-by-default /
   allow-only-known-dev**): `assert_safe_target()` aborta (exit 2) contra prod, ref
   desconocido o host no-parseable, salvo override auditable `KONVI_ALLOW_PROD=1`.
   Cableado en los **4 scripts destructivos**: `wipe_conversation.py`,
   `admin/purge_tenant_storage.py`, `uat/e2e_chat.py`, `uat/live/helpers.py`.
   Cubierto por `tests/test_env_guard.py` (19 tests, incl. bypass pooler/custom-domain).
- **CRITERIO DE ÉXITO:** ✅ verificado empíricamente — con `.env` / `apps/web/.env.local`
  un query solo ve `KAIU Dev (sandbox)`; prod (`*.prod`) intacto. Los 4 scripts
  destructivos abortan (exit 2) contra prod antes de tocar datos. **CRITICAL
  `dev = prod` CERRADO a nivel local (backend + frontend).**
  *(Pendiente Render: prod ya usa `konvi-prod`; no hay Render dev — local basta.)*

## 4. Costo mensual resultante (verificado)
| Ítem | Costo |
|---|---|
| Supabase `konvi-prod` (Pro + Micro, − $10 crédito compute) | ~$25 (bruto ~$34.81) |
| Supabase `konvi-dev` (org Free separada) | $0 |
| Render 3× Starter (backend) | ~$21 |
| *(opcional) Render `konvi-web` Starter* | +$7 |
| **Total** | **~$46/mes** (~$53 con web) — piso en Micro, no techo a escala |
