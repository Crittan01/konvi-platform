# Official Doc Checklist

[ ] Validar límites de rate de WA.
[ ] Webhooks Supabase retry model.
[ ] Gemini Tool calling limites.
[x] Validar Supabase JWT (Custom Claims): Al inyectar propiedades nativas como el `tenant_id` en el objeto `app_metadata` de Auth, estas persistirán durante la vida original del token.
[ ] Validar "Stale Claims Refresh": Si se expulsa temporalmente a un `Agent`, el token JWT activo durante la prox hora debe caducar forzosamente para no permitir fugas, verificando `supabase.auth.refreshSession()`.