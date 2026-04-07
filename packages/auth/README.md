# Auth Module
Garantiza el Server Side Rendering para el frontend, y define los Auth Hooks o Triggers Postgres para inyectar `tenant_id` en los JWTs de la sesión.
Riesgo mitigado: El frontend nunca recibe llaves admin.
