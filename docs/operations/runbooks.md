# Runbooks Operacionales (vigente)

Última actualización: 2026-04-21

## 1) Health check rápido

```bash
curl https://commerce-ops-connector.onrender.com/health
curl https://commerce-ops-api.onrender.com/health
curl https://commerce-ops-orchestrator.onrender.com/health
curl -I https://commerce-ops-web.onrender.com
```

## 2) Reinicio controlado en Render

1. Render Dashboard -> servicio.
2. `Manual Deploy` -> `Deploy latest commit` (o Restart).
3. Revisar logs del servicio + health check.

## 3) Variables de entorno

1. Render Dashboard -> servicio -> Environment.
2. Editar variable.
3. Guardar y validar redeploy + health.

## 4) SQL/migraciones en Supabase

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

## 5) Checklist de incidente conversacional

1. Verificar inbound en connector logs.
2. Verificar inserción en `messages`.
3. Verificar colas `pgmq` (takeover/outbound).
4. Verificar worker orchestrator consumiendo cola.
5. Verificar actualización de `processing_status`.
6. Verificar `messages.payload` para contexto (`context.id`, `interactive/button`) cuando aplique.

## 6) Checklist de certificacion Inbox por intents

1. Ejecutar pruebas UAT segun `docs/operations/inbox-intents-matrix.md`.
2. Usar plantilla base de ejecucion: `docs/operations/inbox-uat-fase-a.md`.
3. Registrar resultado por intent (`auto`, `humano`, `fallo`).
4. Validar que intents de Fase A/B cumplen porcentaje objetivo.
5. Documentar evidencias y decidir `GO/NO-GO` de fase siguiente.

Fallback en Render Free (cold starts/congelamiento):

```bash
./scripts/uat/fase_a_free_fallback.sh
```
