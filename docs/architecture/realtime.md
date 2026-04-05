# Realtime Architecture

## Objetivo
Definir qué partes del sistema necesitan actualizaciones en tiempo real y qué mecanismo usar.

## Casos de uso principales
- inbox de conversaciones exclusivas (mensajes).
- cambios de asignación de agente rápidos.

## Restricciones y Resoluciones de Cuotas
El acceso "Realtime" se limitará estrictamente al dominio de **Conversaciones**.
- **Postgres Changes**: Usado para actualizaciones en vivo de la tabla `messages` e `inbox`.
- **Fallo / Fallback a REST**: Si las suscripciones del WebSocket agotan el channel limit (tier limit usual = 500 max per project), la UI reactiva debe hacer un fallback graceful hacia SWR/React Query polling de baja frecuencia en las pantallas de Operación (Dashboard de Pedidos o Logs). 

## Qué debe ir en realtime explícito
- nuevas conversaciones
- nuevos mensajes
- handoff abierto/cerrado

## Qué NO debe depender jamás de realtime (REST only)
- carga masiva de grillas de pedidos
- actualizaciones de cálculo de stock
- auditoría de sistema
- persistencia original de un dato (fuente de verdad)

## Reglas
- realtime es para UX, nunca fuente de verdad.
- el fallback programático en React ante un rechazo (rate limiting de WS) es imperativo.
- todo evento reportado visualmente tuvo que existir antes como row en PostgreSQL.