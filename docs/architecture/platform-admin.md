# Platform Admin

## Objetivo
Definir el rol, límites y mecanismos seguros de administración para los usuarios Staff o super-administradores (Platform Admin) respetando RLS.

## Inyección y Bypass Controlado RLS
La seguridad de filas no se ignorará mediante keys privilegiadas persistentes. Para resolver el desafío de soporte:
1. No se utilizará de modo generalizado y abierto la **Service Role Key** o Master keys en interfaces operativas ligadas a Dashboards Frontend.
2. Las asignaciones de administradores de plataforma usarán inyección nativa de **Custom JWT Claims**. Un token emitido tendrá el claim validado: `{"user_role": "platform_admin"}` firmado por Supabase.
3. Las reglas Row-Level Security interceptan este nodo en tiempo relacional `(auth.jwt()->>'user_role' = 'platform_admin')`, lo que provee selectividad de control con huella de acceso rastreable.

## Responsabilidades válidas
- onboarding o rectificación técnica de tenants atascados
- suspensión forzosa en tablas subyacentes.
- acceso a logs transaccionales anómalos.
- monitoreo general y troubleshooting de colas (`pgmq`).

## Accesos que deben restringirse
- Interfaz no controlada al contenido confidencial del tenant (Lectura íntegra indiscriminada explícita de `messages`).
- Ejecutar bypass no justificado sin una huella insertada preventivamente en `support_access_logs`.

## Reglas Operativas Seguras
- Una query orientada al modo `Platform Admin` obligatoriamente incluirá wrappers de la API FastAPI y enviará una invocación HTTP context.
- Todo soporte proactivo que implique modificar metadata ajena debe acompañarse de request trace.