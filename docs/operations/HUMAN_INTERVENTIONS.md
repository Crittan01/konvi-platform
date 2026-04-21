# Intervenciones Humanas Requeridas (vigente)

Última actualización: 2026-04-21

Este documento conserva solo intervenciones activas reales.

---

## IH-SEC-01 — Rotación preventiva de credenciales sensibles

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner/DevOps  
**MOMENTO**: Inmediato (antes de siguiente release candidato)  
**PASOS DUMMY O GUIADOS**:
1. Rotar `SUPABASE_SERVICE_ROLE_KEY` en Supabase.
2. Actualizar key nueva en Render (`web`, `connector`, `api`, `orchestrator`) y entorno local.
3. Validar health checks y operaciones críticas.
**INSUMOS NECESARIOS**: Acceso Supabase + Render.  
**CRITERIO DE EXITO**: key anterior inválida, key nueva funcionando, sin errores de auth backend.

---

## IH-SEC-02 — Auditoría de exposición histórica de credenciales

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner/DevOps  
**MOMENTO**: Antes de release candidate público  
**PASOS DUMMY O GUIADOS**:
1. Revisar historial git y secretos del repositorio en GitHub (secret scanning / push protection).
2. Confirmar que no existan tokens activos en URLs remotas locales/equipos.
3. Rotar cualquier credencial que haya sido expuesta históricamente (aunque hoy no esté en HEAD).
4. Documentar la rotación en este archivo y en `docs/HANDOFF.md`.
**INSUMOS NECESARIOS**: Acceso admin a GitHub, Supabase, Render y proveedores externos.
**CRITERIO DE EXITO**: no hay secretos activos expuestos en historia utilizable ni remotes locales con credenciales embebidas.

---

## IH-INFRA-01 — Decisión de upgrade a plan pago

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner del producto  
**MOMENTO**: Cerca de salida a producción o ante bloqueante operacional en Free  
**PASOS DUMMY O GUIADOS**:
1. Confirmar trigger real (tenant productivo o degradación por Free).
2. Aprobar presupuesto y método de pago.
3. Ejecutar upgrade de servicios en Render.
4. Cambiar orchestrator a `type: worker` y revalidar colas.
**INSUMOS NECESARIOS**: Cuenta Render con billing habilitado.  
**CRITERIO DE EXITO**: operación estable sin dependencia del workaround de daemon thread.

---

## IH-META-01 — Meta Embedded Signup / Tech Provider (futuro de onboarding)

**INTERVENCION HUMANA REQUERIDA**: Sí  
**RESPONSABLE**: Owner de plataforma  
**MOMENTO**: Antes de habilitar onboarding self-serve multi-canal  
**PASOS DUMMY O GUIADOS**:
1. Verificar negocio y app en Meta.
2. Completar app review/permisos requeridos.
3. Configurar Embedded Signup y callback productivo.
4. Validar flujo end-to-end con tenant piloto.
**INSUMOS NECESARIOS**: Cuenta Meta Business verificada + dominio + política de privacidad.  
**CRITERIO DE EXITO**: tenant conecta su canal sin intervención manual de soporte.
