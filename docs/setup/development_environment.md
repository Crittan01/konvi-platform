# Entorno de Desarrollo (vigente)

Última actualización: 2026-04-21

## Requisitos base

- Node + pnpm
- Python + dependencias de `services/*/requirements.txt`
- Supabase CLI (`supabase db query --linked`)

## Variables locales

Usar `.env.example` como base y completar valores reales en `.env` (no versionado).

## Comandos locales

```bash
pnpm --filter web dev

cd services/connector-whatsapp
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

cd services/api
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

cd services/ai-orchestrator
export $(grep -v '^#' ../../.env | sed 's/="\(.*\)"/=\1/' | xargs)
python3.11 main.py
```

## SQL remoto seguro

```bash
supabase db query --linked -f supabase/migrations/<archivo>.sql
```

## Nota

En esta VM, usar `python3.11` explícito para servicios/tests hasta alinear el alias `python3`.
