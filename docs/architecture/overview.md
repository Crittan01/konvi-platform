# Architecture Overview

## Visión general
La plataforma se diseña como un SaaS multi-tenant con un núcleo transaccional y módulos desacoplados por dominio.

## Componentes principales
- Frontend web
- API backend
- workers asincrónicos
- cron jobs
- AI orchestrator
- connector framework
- conectores por canal/marketplace

## Núcleo tecnológico
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

## Principios
- modularidad
- seguridad por diseño
- multi-tenant real
- documentación oficial antes de implementar
- nada crítico depende del LLM