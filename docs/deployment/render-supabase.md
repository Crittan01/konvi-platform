# Render and Supabase Deployment

## Objetivo
Definir la base de despliegue productivo sobre Render y Supabase.

## Render
Servicios previstos:
- frontend
- api
- worker
- cron jobs

## Supabase
Servicios previstos:
- Postgres
- Auth
- Storage
- Realtime
- pgvector
- Queues / pgmq

## Principios
- separar local y producción
- preparar staging para fase posterior
- usar variables de entorno por servicio
- no exponer secrets al frontend

## Intervención humana esperada
- creación de servicios en Render
- creación de proyectos en Supabase
- carga de variables de entorno
- configuración de dominios y DNS