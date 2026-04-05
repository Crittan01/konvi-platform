---
name: webhook-checklist
description: Usa esta skill cuando una tarea implique diseñar, implementar o revisar webhooks e integraciones event-driven.
---

# Webhook Checklist Skill

## Objetivo
Asegurar que cualquier webhook se diseñe con validación, seguridad, idempotencia y observabilidad.

## Checklist
1. Confirmar documentación oficial del proveedor.
2. Definir método de validación/autenticación del webhook.
3. Confirmar endpoint y ownership del tenant.
4. Definir idempotencia.
5. Confirmar manejo de retries y duplicados.
6. Separar request path de procesamiento pesado.
7. Registrar logs y auditoría.
8. Manejar errores recuperables y no recuperables.
9. Confirmar intervención humana requerida si aplica.
10. Definir runbook básico ante falla.

## Regla
Nunca asumir que el proveedor enviará el evento una sola vez o en orden perfecto.