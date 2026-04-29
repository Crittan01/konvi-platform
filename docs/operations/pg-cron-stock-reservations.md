# Habilitar `pg_cron` para barrer reservas de stock vencidas

Esta guía explica paso a paso cómo dejar corriendo el cleanup automático de
reservas de inventario expiradas (`stock_reservations.status='active'` con
`expires_at <= NOW()`) en Supabase Cloud.

> **¿Es bloqueante?** **NO.** El cálculo de "stock disponible" filtra
> defensivamente por `expires_at > NOW()` aún sin el cron — las reservas
> vencidas dejan de descontar automáticamente. Sin `pg_cron` simplemente
> quedan filas con `status='active'` y `expires_at` en el pasado (ruido en
> auditoría). Con `pg_cron` se marcan como `expired` cada minuto.

---

## Pasos en el Dashboard de Supabase

### 1. Habilitar la extensión `pg_cron`

1. Abrir Supabase Dashboard del proyecto.
2. Menú izquierdo → **Database** → **Extensions**.
3. Buscar `pg_cron` en la lista.
4. Click en el toggle para habilitarla. Aparece "Enabled".

> Esto solo se hace una vez por proyecto.

### 2. Programar el job

1. Menú izquierdo → **SQL Editor**.
2. Pegar el siguiente SQL y ejecutar:

```sql
-- Programa fn_expire_stock_reservations() cada minuto.
-- Idempotente: si ya existía un job con el mismo nombre, lo reemplaza.
SELECT cron.schedule(
  'expire_stock_reservations',           -- nombre del job (único)
  '* * * * *',                           -- cron expression: cada minuto
  $$ SELECT public.fn_expire_stock_reservations(); $$
);
```

### 3. Verificar que está corriendo

Ejecutar en SQL Editor:

```sql
-- Estado del job
SELECT jobid, jobname, schedule, active
FROM cron.job
WHERE jobname = 'expire_stock_reservations';
```

Resultado esperado: una fila con `active = true` y `schedule = '* * * * *'`.

Para ver los últimos runs (después de ~1 min):

```sql
SELECT job_run_details.start_time, job_run_details.status, job_run_details.return_message
FROM cron.job_run_details
JOIN cron.job ON cron.job.jobid = cron.job_run_details.jobid
WHERE cron.job.jobname = 'expire_stock_reservations'
ORDER BY job_run_details.start_time DESC
LIMIT 10;
```

Resultado esperado: filas con `status = 'succeeded'` cada minuto.

### 4. Apagar el job (si fuera necesario)

```sql
SELECT cron.unschedule('expire_stock_reservations');
```

---

## Alternativa sin `pg_cron` (worker Python)

Si por política del proyecto no se habilita `pg_cron`, agregar al worker
del orchestrator un loop periódico que llame el RPC. Pseudocódigo:

```python
# En services/ai-orchestrator/worker.py
import asyncio
from supabase import Client

async def expire_stock_reservations_loop(supabase: Client):
    while True:
        try:
            res = supabase.rpc("fn_expire_stock_reservations", {}).execute()
            n = (res.data or [{}])[0].get("count", 0) if res.data else 0
            if n:
                logger.info("[STOCK_TTL] %d reservas marcadas como expired", n)
        except Exception as exc:
            logger.warning("[STOCK_TTL] sweep failed: %s", exc)
        await asyncio.sleep(60)  # cada minuto
```

Y en el `start()` del worker:

```python
asyncio.create_task(expire_stock_reservations_loop(self.supabase))
```

> **Decisión actual recomendada**: `pg_cron`. Es más confiable (corre en
> el motor PG, no depende del proceso Python), observable vía
> `cron.job_run_details`, y no requiere cambios de código.

---

## Smoke test

Para verificar que todo funciona end-to-end después de programar el cron:

```sql
-- 1) Crear una reserva manual con TTL muy corto (10 seg) en una variation real
SELECT * FROM public.rpc_stock_reserve(
  p_tenant_id      := '<TU_TENANT_UUID>',
  p_variation_id   := '<UNA_VARIATION_UUID>',
  p_qty            := 1,
  p_cart_id        := NULL,
  p_conversation_id := NULL,
  p_ttl_minutes    := 0  -- crea con expires_at = NOW(), ya expirada
);

-- 2) Esperar 1-2 minutos y verificar que pasó a 'expired'
SELECT status, expires_at, released_at
FROM public.stock_reservations
ORDER BY created_at DESC
LIMIT 1;
-- Resultado esperado: status='expired', released_at no nulo
```

---

## Referencias

- [pg_cron — repo oficial](https://github.com/citusdata/pg_cron)
- [Supabase Database Extensions](https://supabase.com/docs/guides/database/extensions/pg_cron)
- Migración interna: `supabase/migrations/20260502000000_stock_reservations.sql`
- Función SQL: `public.fn_expire_stock_reservations()` (definida en la migración).
