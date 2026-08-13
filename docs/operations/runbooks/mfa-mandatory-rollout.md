# Runbook — Rollout MFA obligatorio para write-roles (A1 / PLAN §A #7)

**Qué activa:** el flip de `MFA_MANDATORY_ENABLED=true` en **konvi-api** (Render).
**A quién:** roles `owner` + `manager` (`MFA_MANDATORY_ROLES = WRITE_ROLES`, `services/api/dependencies/auth.py:68`). `operator` NO es forzado.
**Comportamiento exacto** (`auth.py:326-348`): usuario write-role **sin factor TOTP verificado** y **fuera de gracia** → `403` con mensaje "Tu cuenta requiere activar la verificación en dos pasos (MFA)… Ajustes → Seguridad". Fail-open si el lookup de factores cae (disponibilidad sobre enforcement).
**Gracia:** `deadline = max(user.created_at, MFA_MANDATORY_START) + MFA_MANDATORY_GRACE_DAYS` (default 14 días). Sin ancla temporal parseable → no bloquea (conservador).
**Ya existe:** página de enrolamiento `/dashboard/settings/security` (TOTP + recovery codes), gate AAL2 en middleware web, cookie de recovery `mfa_recovery_session` (24h).

## Pasos

1. **Anuncio (día 0):** comunicar a owners/managers de cada tenant: "desde el día X la escritura en la consola exigirá verificación en dos pasos; actívala ya en Ajustes → Seguridad". Anotar la fecha X.
2. **Setear ancla (día 0):** en Render → konvi-api → env `MFA_MANDATORY_START = <fecha ISO del anuncio, ej. 2026-08-20>`. Con esto la gracia corre desde una fecha cierta para todos (incl. cuentas viejas), no desde su `created_at`.
3. **Ventana de enrolamiento (día 0 → X):** verificar enrolamiento por tenant — query solo-lectura: usuarios write-role sin factor. Si llega el día X y alguien crítico no enroló, extender `MFA_MANDATORY_START` antes del flip, no después.
4. **Flip (día X):** `MFA_MANDATORY_ENABLED = "true"` en konvi-api. Render redespliega solo. No tocar `MFA_MANDATORY_GRACE_DAYS` (14) salvo decisión explícita.
5. **Verificación (día X):**
   - Cuenta de prueba owner **con** MFA: operación de escritura normal → 200.
   - Cuenta write-role **sin** MFA y fuera de gracia → 403 con el mensaje de enrolamiento.
   - Logs konvi-api: sin ráfaga de `[MFA] lookup de factores falló` (eso sería fail-open por outage del Auth admin — investigar antes de seguir).
6. **Post-flip:** soporte a usuarios que se encerraron → recovery codes (si los generaron) o reset TOTP por owner vía `/dashboard/team` (flujo ya existente). Registrar la fecha del flip en `docs/PLAN.md` §A #7.

## Rollback

`MFA_MANDATORY_ENABLED = "false"` en konvi-api → redeploy. Efecto inmediato, sin estado residual (el gate es stateless por request).

## Notas

- El middleware web ya fuerza AAL2 a quien **tiene** factor enrolado (independiente de este flag). Este flag es la obligación de **enrolarse** para write-roles.
- Llamadas service-to-service (orchestrator → api con `X-Internal-Service-Secret`) son NO-OP en este gate por diseño (`enforce_mfa_internal_or_user`).
- Relacionado: rotación de `MFA_RECOVERY_COOKIE_SECRET` en [credential-rotation.md](credential-rotation.md) §1-B.
