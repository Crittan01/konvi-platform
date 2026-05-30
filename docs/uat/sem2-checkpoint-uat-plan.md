# UAT Checkpoint Sem 2 Framework Común — Plan de pruebas

**Sesión origen**: 2026-05-06 · **Branch**: `phase-0-pre-prod` · **Commits a verificar**: `6345b25..05f7417`

**Objetivo**: confirmar que los 5 commits de Sem 0+1+2 (research dossiers + CI/CD + 4 tablas DB + 4 libs) NO rompieron nada en producción funcional, antes de proceder con F.3 → F.1 → F.2 → F.9.

**Análisis de cambios — blast radius**:

| Commit | Archivos código existentes tocados | Riesgo regresión |
|---|---|---|
| `6345b25` Dossiers | 0 (solo `docs/research/`) | 🟢 nulo |
| `1aa574f` CI/CD | `scripts/validate.sh`, `CLAUDE.md`, `.gitignore`, `pyproject.toml` (nuevo) | 🟢 dev-tool only |
| `b0a737f` F.12 | **`services/api/routers/telegram_webhook.py`** ← ÚNICA ruta refactorizada | 🟡 testear Telegram |
| `85394b7` F.10 | `services/api/requirements.txt` (+bcrypt 5.0.0) | 🟢 lib nueva sin consumidores |
| `4d24f1e` F.11 | 0 código existente | 🟢 lib nueva sin consumidores |
| `05f7417` F.4 | 0 código existente | 🟢 lib nueva sin consumidores |

**Resultado**: la única regresión posible está en **flujo Telegram operadores**. Todo lo demás es puramente aditivo.

---

## 1. Pre-flight (5 min)

### 1.1 Servicios live (VM local)

```bash
cd /home/ansible/commerce-ops-local
make status
```

Esperar 4 servicios `Up`: web, api, ai-orchestrator, connector-whatsapp.

Si alguno está `Down`:
```bash
make restart
```

### 1.2 Verificar bcrypt instalado en API

```bash
docker exec commerce-ops-local-api-1 python -c "import bcrypt; print(bcrypt.__version__)"
```

**Esperado**: `5.0.0`. Si falla → rebuild el container API:
```bash
make build-api && make restart
```

### 1.3 Verificar 4 tablas nuevas en Supabase remote

Abrir Supabase Dashboard → SQL Editor → ejecutar:

```sql
SELECT table_name,
       (SELECT COUNT(*) FROM information_schema.columns WHERE c.table_name = t.table_name AND table_schema='public') AS cols
FROM information_schema.tables t
WHERE table_schema='public'
  AND table_name IN (
    'tenant_provider_identity',
    'tenant_webhook_secrets',
    'credential_access_log',
    'webhook_events_seen'
  )
ORDER BY table_name;
```

**Esperado**: 4 filas, columnas:
- `credential_access_log`: 8
- `tenant_provider_identity`: 9
- `tenant_webhook_secrets`: 11
- `webhook_events_seen`: 9

### 1.4 Verificar 0 filas en cada tabla nueva

```sql
SELECT 'tenant_provider_identity' AS t, COUNT(*) AS rows FROM tenant_provider_identity
UNION ALL SELECT 'tenant_webhook_secrets', COUNT(*) FROM tenant_webhook_secrets
UNION ALL SELECT 'credential_access_log', COUNT(*) FROM credential_access_log
UNION ALL SELECT 'webhook_events_seen', COUNT(*) FROM webhook_events_seen;
```

**Esperado**: todas 0 (no se ha consumido nada todavía — libs aditivas sin wiring).

### 1.5 Smoke RPC dedup F.4

```sql
SELECT public.webhook_event_check_or_register(
  'envia', 'uat-smoke-001', NULL, 'smoke', 'uat-001'
) AS first_call;
SELECT public.webhook_event_check_or_register(
  'envia', 'uat-smoke-001', NULL, 'smoke', 'uat-001'
) AS second_call;
DELETE FROM webhook_events_seen WHERE event_uid='uat-smoke-001';
```

**Esperado**: `first_call=false` (insertado), `second_call=true` (duplicado), DELETE 1 row.

---

## 2. Smoke regresión Tenant Console (15 min)

Login con tu cuenta operadora habitual.

### 2.1 Auth + dashboard

- [ ] Login funciona → redirect a `/dashboard`
- [ ] Sidebar muestra todos los módulos: Inbox, Catálogo, Pedidos, Despachos, Contactos, Reclamos, Settings, Equipo
- [ ] Dashboard cards renderizan sin error en consola del navegador

### 2.2 Inbox conversacional (rev. 104 base)

**Escenario A — cliente nuevo**:
- [ ] Abrir Inbox → ves conversaciones recientes
- [ ] Click en una conversación → mensajes cargan en orden cronológico
- [ ] Cart panel lateral muestra estado del carrito (vacío o con items según conv)
- [ ] Pedidos del cliente conocido aparecen en pestaña "Historial"

**Escenario B — enviar mensaje manual desde Inbox**:
- [ ] Pestaña "Modo manual" en una conversación
- [ ] Escribir "test sem 2 checkpoint" → enviar
- [ ] Mensaje aparece en el hilo → cliente lo recibe en WhatsApp

### 2.3 Catálogo

- [ ] Listado productos carga
- [ ] Click producto → detalle + variantes
- [ ] Stock actual visible

### 2.4 Pedidos

- [ ] Listado pedidos recientes
- [ ] Click pedido → detalle + items + estado pago
- [ ] Filtros estado funcionan (PENDING / APPROVED / DECLINED)

### 2.5 Despachos

- [ ] Listado despachos cotizados
- [ ] Tracking on-demand de un envío con `tracking_number` real

### 2.6 Contactos + Habeas Data

- [ ] Listado contactos
- [ ] Click un contacto → ver consent status + audit log
- [ ] **NO probar SAR/borrado real** salvo que tengas tenant test dedicado

### 2.7 Reclamos

- [ ] Listado claims tickets
- [ ] Click ticket → detalle

### 2.8 Settings

- [ ] **Settings → Información** carga sin error
- [ ] **Settings → Integraciones** muestra Wompi/Envia/MeLi/WhatsApp/Telegram con status correcto
- [ ] **Settings → Equipo** carga lista users

---

## 3. Telegram operadores — ÚNICA ruta refactorizada (10 min)

**Importante**: este es el único flow que cambió. El refactor introduce un fallback que mantiene comportamiento legacy mientras `tenant_provider_identity` esté vacía (esperado pre-backfill).

### 3.1 Pre-condición

Verificar que tu bot Telegram operador está configurado en `notification_settings`:
```sql
SELECT tenant_id, channel, enabled, config->>'bot_token' IS NOT NULL AS has_token
FROM notification_settings
WHERE channel='telegram';
```

**Esperado**: al menos 1 fila `enabled=true, has_token=true`.

### 3.2 Comando `/ayuda` (smoke básico)

Desde Telegram en el chat operador:
```
/ayuda
```

**Esperado**: bot responde con lista de comandos `/resolver`, `/estado`, `/ayuda`.

### 3.3 Comando `/estado {conv_id}` (read-only, seguro)

Tomar un `conv_id` real del Inbox → desde Telegram:
```
/estado abc-123-xyz
```

**Esperado**: bot responde con `Estado: ... Cliente: ... Última interacción: ...`.

### 3.4 Logs API — verificar fallback warning

```bash
docker logs commerce-ops-local-api-1 2>&1 | grep -E "TG_WH|chat_id" | tail -10
```

**Esperado**: ver línea como:
```
[TG_WH] chat_id=123456 sin identidad en tenant_provider_identity, usando fallback 'primer tenant activo' (legacy pre-backfill)
```

Esto **es lo correcto** — el fallback funciona porque aún no hay identidades registradas. Se removerá en sesión posterior cuando ejecutemos el backfill.

### 3.5 Comando `/resolver {conv_id}` (escribe DB, hacer en tenant test)

Si tienes una conversación de test escalada (`status='human_takeover'`):
```
/resolver abc-123-xyz
```

**Esperado**: bot responde "✅ Conversación restaurada al bot". Verificar en Inbox que la conversación volvió a estado bot.

---

## 4. Webhooks productivos (no refactorizados) — siguen funcionando (5 min)

### 4.1 Wompi webhook delivery

Generar un payment link sandbox desde el bot WhatsApp en una conversación:
- Pedir al cliente confirmar resumen → bot genera link Wompi → pagar con tarjeta sandbox visa exitosa.

**Esperado**:
- Webhook Wompi llega al endpoint
- Orden cambia a `APPROVED`
- Cliente recibe confirmación WhatsApp

```bash
docker logs commerce-ops-local-api-1 2>&1 | grep "WOMPI" | tail -5
```

### 4.2 MeLi webhook delivery (si tienes tenant con MeLi conectado)

- Crear orden manual en MeLi sandbox o tu cuenta dev
- Verificar que webhook entra y orden aparece en Pedidos del Tenant Console.

```bash
docker logs commerce-ops-local-api-1 2>&1 | grep "MELI" | tail -5
```

---

## 5. CI verify (opcional, 5 min)

**Si decides hacer push de la rama** `phase-0-pre-prod` a GitHub para validar la pipeline CI:

```bash
git push origin phase-0-pre-prod
```

Luego abrir GitHub → Actions tab → el workflow `CI` debe correr y pasar:
- Job `validate` (validate.sh --ci): ~3-4 min
- Job `build-web` (Next.js build): ~2-3 min

**Esperado**: ambos jobs ✅. Si fallan, NO afecta producción (la rama no está mergeable a develop/main).

---

## 6. Suite test local (1 min)

```bash
cd /home/ansible/workspaces/commerce-ops-platform
bash scripts/validate.sh
```

**Esperado**: `13 OK / 0 ERROR / 0 WARN / 1542 tests / Listo para despliegue`.

---

## 7. Sign-off criteria

Para autorizar continuar con F.3 → F.1 → F.2 → F.9 deben pasar:

| # | Criterio | Bloqueante |
|---|---|---|
| 1 | 4 tablas DB nuevas existen con shape correcto | 🔴 |
| 2 | 0 filas en las 4 tablas (libs aditivas sin consumir aún) | 🔴 |
| 3 | Smoke RPC F.4: `false` → `true` → cleanup OK | 🔴 |
| 4 | Auth + Dashboard + Inbox cargan sin errores consola | 🔴 |
| 5 | Telegram `/ayuda` responde | 🔴 |
| 6 | Telegram `/estado` responde con datos reales | 🔴 |
| 7 | Logs muestran fallback warning Telegram (esperado) | 🟢 informativo |
| 8 | Wompi webhook procesa payment OK (escenario E2E) | 🔴 |
| 9 | Suite local 1542 tests verde | 🔴 |
| 10 | bcrypt instalado en container API | 🔴 |
| 11 | (opcional) CI pipeline GitHub verde | 🟡 |

---

## 8. Si algo falla

### 8.1 bcrypt no encontrado en container

```bash
make build-api  # rebuild con requirements actualizado
make restart
```

### 8.2 Telegram comandos no responden

Pasos diagnósticos en orden:
1. ¿Servicio API respondiendo? `curl http://localhost:8000/health`
2. ¿Webhook Telegram registrado? Verificar en `@BotFather` → bot → "Webhook info"
3. ¿Logs muestran error de import?
   ```bash
   docker logs commerce-ops-local-api-1 2>&1 | grep -E "import|identity_registry" | tail -10
   ```
4. **Hot fix temporal**: revertir solo el commit Telegram fix manteniendo el resto:
   ```bash
   # Solo si estrictamente necesario, NO usar git revert (rompería F.12)
   git checkout 6a60914 -- services/api/routers/telegram_webhook.py
   make restart
   ```
   Reportar para análisis en próxima sesión.

### 8.3 Wompi webhook no procesa

NO está relacionado con commits de esta sesión (Wompi no fue tocado). Si falla, problema preexistente. Verificar `wompi_events_seen` table tiene filas recientes:
```sql
SELECT received_at, event_type, status FROM wompi_events_seen
ORDER BY received_at DESC LIMIT 10;
```

### 8.4 Tablas DB no existen

Significa que el ledger Supabase está desincronizado. Reportar inmediatamente para investigación.

---

## 9. Reporte resultado UAT

Al terminar, comentar en chat con:

```
UAT Sem 2 Checkpoint:
- Pre-flight: [✅/❌]
- Smoke regresión: [✅/❌] (módulos con problema si los hay)
- Telegram operadores: [✅/❌]
- Webhooks Wompi/MeLi: [✅/❌]
- Suite local: [✅/❌]
- (opcional) CI GitHub: [✅/❌]
- Bloqueantes detectados: [ninguno / lista]
```

Si todo ✅ → autorizo proceder con F.3 → F.1 → F.2 → F.9.
Si hay bloqueantes → reportar logs + reproducción para fix antes de seguir.

---

**Documento vivo**. Actualizar tras ejecución con resultados reales como `docs/uat/sem2-checkpoint-uat-results-{YYYY-MM-DD}.md`.
