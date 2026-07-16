# Ambientes e infraestructura — convención de nombres + runbook

> Cierra el CRITICAL **dev = prod comparten Supabase** (auditoría 2026-07-13/16). Alinea
> con la guía oficial de Supabase [Managing Environments](https://supabase.com/docs/guides/deployment/managing-environments):
> **proyectos separados por ambiente** + migraciones como fuente de sincronización de schema.
> Precios verificados 2026-07-16 ([Supabase pricing](https://supabase.com/pricing), [Render free](https://render.com/docs/free)).

## 1. Estrategia

Dos ambientes, **aislados a nivel de organización Supabase** (no solo de proyecto):

- **prod** — datos reales (pedidos, pagos, audit Habeas Data, Vault). Plan **Pro** (backups diarios). Es el único que NO puede perder datos.
- **dev** — datos **sintéticos** (seed). Plan **Free** (sin backups, se pausa si >1 semana inactivo — se reanuda en ~1min). Aísla el desarrollo local para que un test destructivo JAMÁS toque prod.

**Por qué orgs SEPARADAS y no 2 proyectos en la misma org:** la facturación de Supabase es por-org; un 2º proyecto en la org Pro cuesta **+~$10/mes** (compute), mientras que un proyecto en una **org Free separada = $0** + aislamiento total de billing/acceso.

## 2. Convención de nombres (canónica)

### Supabase
| Ambiente | Organización | Proyecto | Plan | Ref (inmutable) |
|---|---|---|---|---|
| **prod** | `Konvi` *(org existente)* | **`konvi-prod`** *(renombrar de `konvi-ops`)* | **Pro** | `xmelwnhhphksbpdjmbbp` |
| **dev** | **`Konvi Dev`** *(nueva, Free)* | **`konvi-dev`** | **Free** | *(se genera al crear)* |

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
2. Aceptar el estimado (**~$34.81/mes** = $25 Pro + $9.81 compute Micro del proyecto — es el piso de prod-con-backups).
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

### D. Cutover local a dev *(lo hago yo — no-cost, tras B)*
1. Aplicar el schema baseline (`tests/dbharness/schema_baseline.sql`) a `konvi-dev`.
2. Seed sintético (tenant de prueba + Vault sandbox Meta/Wompi/Aveonline).
3. Cambiar `.env` local + ngrok a `konvi-dev`; mover credenciales prod a `.env.prod`.
4. `env_guard` anti-prod en scripts destructivos (cubre `.env` y `.env.prod`).
- **CRITERIO DE ÉXITO:** un test local destructivo afecta SOLO `konvi-dev`; prod intacto. **Cierra el CRITICAL.**

## 4. Costo mensual resultante (verificado)
| Ítem | Costo |
|---|---|
| Supabase `konvi-prod` (Pro + Micro compute) | ~$34.81 |
| Supabase `konvi-dev` (org Free separada) | $0 |
| Render 3× Starter (backend) | ~$21 |
| *(opcional) Render `konvi-web` Starter* | +$7 |
| **Total** | **~$56/mes** (~$63 con web) |
