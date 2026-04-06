import os

base_dir = "/home/ansible/workspaces/commerce-ops-platform"

files = {
    "packages/auth/package.json": """{
  "name": "@commerce/auth",
  "version": "0.1.0",
  "private": true,
  "description": "Capa de SSR Supabase y Auth Hooks",
  "dependencies": {
    "@supabase/ssr": "latest",
    "@supabase/supabase-js": "latest"
  }
}
""",
    "packages/auth/README.md": """# Auth Module
Garantiza el Server Side Rendering para el frontend, y define los Auth Hooks o Triggers Postgres para inyectar `tenant_id` en los JWTs de la sesión.
Riesgo mitigado: El frontend nunca recibe llaves admin.
""",
    "packages/auth/lib/server-client.ts": """import { createServerClient, type CookieOptions } from '@supabase/ssr'

export function createSSRClient(cookies: any) {
  // Patrón SSR Seguro Oficial Supabase
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return cookies.get(name)?.value
        },
        set(name: string, value: string, options: CookieOptions) {
          cookies.set({ name, value, ...options })
        },
        remove(name: string, options: CookieOptions) {
          cookies.set({ name, value: '', ...options })
        },
      },
    }
  )
}
""",
    "packages/auth/lib/client-browser.ts": """import { createBrowserClient } from '@supabase/ssr'

export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  )
}
""",
    "packages/db/migrations/00005_custom_claims_trigger.sql": """-- Manejo de Custom Claims
-- Inyecta el tenant_id en el JWT de cada sesión recien creada

CREATE OR REPLACE FUNCTION public.handle_new_user_claims()
RETURNS trigger AS $$
DECLARE
  v_tenant_id uuid;
  v_role text;
BEGIN
  -- Busca la asignación del usuario en los recursos de tenant
  SELECT tenant_id, role INTO v_tenant_id, v_role
  FROM public.tenant_users
  WHERE user_id = NEW.id
  LIMIT 1;

  IF v_tenant_id IS NOT NULL THEN
    -- Modifica los crudos jsonb del usuario de auth nativo para reflejarlos en auth.jwt()
    UPDATE auth.users
    SET raw_app_meta_data = 
      jsonb_set(
        jsonb_set(COALESCE(raw_app_meta_data, '{}'::jsonb), '{tenant_id}', to_jsonb(v_tenant_id::text)),
        '{role}', to_jsonb(v_role)
      )
    WHERE id = NEW.id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Disparador cada vez que un usuario se relaciona internamente
CREATE OR REPLACE TRIGGER on_tenant_assignment
  AFTER INSERT OR UPDATE ON public.tenant_users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_claims();
"""
}

# Create dirs
os.makedirs(os.path.join(base_dir, "packages/auth/lib"), exist_ok=True)
os.makedirs(os.path.join(base_dir, "packages/db/migrations"), exist_ok=True)

# Write files
for filepath, content in files.items():
    full_path = os.path.join(base_dir, filepath)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\\n")
    print("Created:", full_path)
