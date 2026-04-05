---
description: Revisa si el proyecto está listo para despliegue, verificando secretos, migraciones, RLS, webhooks, workers, cron jobs y bloqueantes operativos.
---

# deployment-readiness

1. Verifica:
   - variables de entorno
   - secretos
   - migraciones
   - RLS
   - webhooks
   - storage policies
   - workers
   - cron jobs
2. Lista intervención humana requerida.
3. Identifica bloqueantes para prod.
4. No ejecutes despliegue sin confirmación.