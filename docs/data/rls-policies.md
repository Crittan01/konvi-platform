# Row Level Security (RLS) & Aislamiento Multi-Tenant

La seguridad core de Supabase depende de la restricción RLS para nuestra estructura SaaS. Las reglas implementadas en `packages/db/migrations/00004_rls_policies.sql` garantizan que los tokens escapados o los exploits a nivel de backend no puedan cruzar los límites del Workspace.

## 1. Patrón Híbrido de JWT / Context Setting
Para cubrir el escenario donde las APIs internas operan mediante FastApi/Render (y no un navegador de usuario), hemos implementado la función estabilizadora `app_current_tenant()`.

**Flujo:**
1. Si el *llamado* viene vía Supabase Client (Navegador): lee el `auth.jwt() -> app_metadata`.
2. Si el *llamado* viene vía Server/Worker: FastAPI inyecta `SET app.current_tenant_id = 'xxxx'` (Current Context Setting) al iniciar la sesión local SQL contra Postgres, comportándose en la misma regla sin bypasear el RLS.

## 2. Aplicación Universal
Toda tabla (Products, Messages, Conversations, Variations) posee **exactamente** esta política:
```sql
CREATE POLICY "Tenant Isolation" 
ON public.<tabla> 
FOR ALL USING (tenant_id = app_current_tenant());
```
Con esta aserción, el motor de Postgres abortará cualquier acción si el Orchestrator AI comete un error manipulando la Tool que intercepte u homologe IDs de otro tenant.