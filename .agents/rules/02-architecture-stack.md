---
trigger: always_on
---

# Stack objetivo

Preferir:
- React + TypeScript + Tailwind + shadcn/ui
- Python + FastAPI
- Render
- Supabase Postgres
- Supabase Auth
- Postgres RLS + RBAC + custom claims
- Supabase Storage
- Supabase Realtime
- pgvector
- Supabase Queues / pgmq
- WhatsApp Cloud API oficial
- Telegram Bot API

## Reglas
- no agregar piezas extra sin justificarlo documentalmente
- no introducir servicios innecesarios si Supabase + Render cubren el caso
- no tratar el LLM como fuente de verdad transaccional
- modularizar por dominios e integraciones