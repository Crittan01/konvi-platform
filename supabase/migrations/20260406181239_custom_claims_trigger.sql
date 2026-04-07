-- Manejo de Custom Claims
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
