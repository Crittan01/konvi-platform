"""Tests del guard CI de migraciones Track 9 (scripts/check_secdef_grants.py).

El guard existe porque los defaults NO bastan: Postgres otorga EXECUTE a PUBLIC en
toda función nueva (built-in, no removible vía ALTER DEFAULT PRIVILEGES — demostrado
empíricamente en PG 17.6) y Supabase a anon/authenticated vía default ACL. Sin un
lint que lo exija, cualquier migración futura puede reabrir el hueco de Track 9.
"""
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_secdef_grants", Path(__file__).resolve().parents[1] / "scripts" / "check_secdef_grants.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

check_migration = _mod.check_migration


def _escribe(tmp_path: Path, nombre: str, cuerpo: str) -> Path:
    p = tmp_path / nombre
    p.write_text(cuerpo, encoding="utf-8")
    return p


def test_secdef_con_revoke_y_search_path_pasa(tmp_path):
    p = _escribe(tmp_path, "20260101000000_ok.sql", """
CREATE OR REPLACE FUNCTION public.f_bien(uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $$ BEGIN RETURN; END; $$;
REVOKE ALL ON FUNCTION public.f_bien(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.f_bien(uuid) TO service_role;
""")
    assert check_migration(p) == []


def test_secdef_sin_revoke_falla(tmp_path):
    p = _escribe(tmp_path, "20260101000001_mala.sql", """
CREATE OR REPLACE FUNCTION public.f_abierta(uuid)
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $$ BEGIN RETURN; END; $$;
GRANT EXECUTE ON FUNCTION public.f_abierta(uuid) TO authenticated, service_role;
""")
    viol = check_migration(p)
    assert len(viol) == 1 and "sin REVOKE" in viol[0]


def test_secdef_sin_search_path_falla(tmp_path):
    p = _escribe(tmp_path, "20260101000002_mala2.sql", """
CREATE FUNCTION public.f_sin_path()
 RETURNS int LANGUAGE sql SECURITY DEFINER
AS $$ SELECT 1 $$;
REVOKE ALL ON FUNCTION public.f_sin_path() FROM PUBLIC, anon;
""")
    viol = check_migration(p)
    assert len(viol) == 1 and "search_path" in viol[0]


def test_security_invoker_no_aplica(tmp_path):
    """Una función SIN SECURITY DEFINER corre con privilegios del caller — fuera del guard."""
    p = _escribe(tmp_path, "20260101000003_invoker.sql", """
CREATE OR REPLACE FUNCTION public.f_invoker()
 RETURNS int LANGUAGE sql
AS $$ SELECT 1 $$;
""")
    assert check_migration(p) == []


def test_exencion_justificada_pasa(tmp_path):
    """RPC de consola (guarda interna de membresía): la exención documenta la decisión."""
    p = _escribe(tmp_path, "20260101000004_exenta.sql", """
-- track9:exempt:f_consola — la consola la invoca con authenticated; el candado es
-- la guarda interna owner/manager+active, no el ACL (patrón pgsec_*).
CREATE OR REPLACE FUNCTION public.f_consola(uuid)
 RETURNS text LANGUAGE plpgsql SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $$ BEGIN RETURN 'x'; END; $$;
""")
    assert check_migration(p) == []


def test_exencion_sin_razon_no_vale(tmp_path):
    p = _escribe(tmp_path, "20260101000005_exenta_mal.sql", """
-- track9:exempt:f_consola
CREATE OR REPLACE FUNCTION public.f_consola(uuid)
 RETURNS text LANGUAGE plpgsql SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $$ BEGIN RETURN 'x'; END; $$;
""")
    assert len(check_migration(p)) == 1


def test_migracion_sin_funciones_pasa(tmp_path):
    p = _escribe(tmp_path, "20260101000006_solo_tabla.sql", """
CREATE TABLE public.demo (id uuid PRIMARY KEY);
ALTER TABLE public.demo ENABLE ROW LEVEL SECURITY;
""")
    assert check_migration(p) == []


def test_revoke_solo_de_anon_tambien_cuenta(tmp_path):
    p = _escribe(tmp_path, "20260101000007_ok2.sql", """
CREATE OR REPLACE FUNCTION public.f_bien2()
 RETURNS void LANGUAGE plpgsql SECURITY DEFINER
 SET search_path TO 'public', 'pg_catalog'
AS $$ BEGIN RETURN; END; $$;
REVOKE EXECUTE ON FUNCTION public.f_bien2() FROM PUBLIC, anon;
""")
    assert check_migration(p) == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
