"""Ninguna función que destruya datos sin validar pertenencia queda al alcance de un usuario.

EL AGUJERO QUE ESTO CIERRA (encontrado 2026-07-27, vivo en producción)
`fn_apply_retention` es SECURITY DEFINER, recorre `public.tenants` ENTERA borrando
mensajes, conversaciones y contactos, y **no valida absolutamente nada**. Tenía EXECUTE
para `authenticated`: cualquier usuario con sesión de cualquier tenant podía invocarla por
PostgREST y borrar los datos de todos los demás comerciantes de la plataforma.

Nadie concedió ese permiso. Lo dan los privilegios por defecto del esquema: sin
`ALTER DEFAULT PRIVILEGES`, toda función nace con EXECUTE para `authenticated`. Es el
mismo mecanismo de #162/#164 un rol más arriba, y la migración 20260725020000 lo dejó
anotado como "fuera de alcance, siguiente ola".

POR QUÉ ESTE TEST ES UN BARRIDO Y NO UNA LISTA
Una lista de funciones prohibidas envejece: la número seis se agrega mañana y nace
expuesta, igual que nació esta. El test recorre el esquema y aplica el criterio.
"""
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness

#: Destruyen filas pero SÍ verifican quién llama, así que un usuario puede invocarlas:
#: la consola las usa con la sesión del operador. Cada excepción se justifica o no entra.
CON_GUARDA_PROPIA = {
    # Comprueba que auth.uid() sea owner/manager del tenant dueño del secreto antes de
    # borrarlo. La consola la llama al desconectar una integración.
    "pgsec_delete_secret",
}


def _destructivas_al_alcance(cur, rol: str):
    """Funciones SECURITY DEFINER que borran filas, no validan pertenencia, y que `rol`
    puede ejecutar."""
    cur.execute(
        """
        SELECT p.proname
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.prosecdef
           AND has_function_privilege(%s, p.oid, 'EXECUTE')
           AND pg_get_functiondef(p.oid) ~* '(DELETE[[:space:]]+FROM|TRUNCATE)'
           -- "valida pertenencia" = mira quién llama, de alguna de las formas del repo.
           AND pg_get_functiondef(p.oid) !~* '(auth\\.uid|tenant_users|app_current_tenant)'
        """,
        (rol,),
    )
    return {r[0] for r in cur.fetchall()} - CON_GUARDA_PROPIA


def test_un_usuario_logueado_no_puede_destruir_datos_sin_guarda():
    """EL PUNTO. `authenticated` es cualquier persona con sesión, de CUALQUIER tenant."""
    with connect() as conn, conn.cursor() as cur:
        alcanzables = _destructivas_al_alcance(cur, "authenticated")
    assert not alcanzables, (
        "estas funciones borran filas sin validar quién llama y las puede ejecutar "
        f"cualquier usuario logueado: {sorted(alcanzables)}. Revócalas de `authenticated` "
        "o agrégales una guarda de pertenencia."
    )


def test_tampoco_el_visitante_sin_sesion():
    """`anon` es la llave publishable, que viaja en el bundle del navegador. Cerrado en
    #164; este test evita que se reabra."""
    with connect() as conn, conn.cursor() as cur:
        alcanzables = _destructivas_al_alcance(cur, "anon")
    assert not alcanzables, sorted(alcanzables)


def test_el_barrido_de_retencion_sigue_siendo_del_backend():
    """Concreto y por nombre, además del barrido genérico: es la única que recorre
    `public.tenants` completa, así que su exposición es borrado cross-tenant."""
    with connect() as conn, conn.cursor() as cur:
        for rol, esperado in (("anon", False), ("authenticated", False), ("service_role", True)):
            cur.execute(
                "SELECT has_function_privilege(%s,"
                "'public.fn_apply_retention(text,boolean)','EXECUTE')", (rol,))
            assert cur.fetchone()[0] is esperado, rol


def test_la_funcion_de_retencion_efectivamente_no_valida_nada():
    """Si algún día SÍ valida pertenencia, este test falla y hay que revisar el criterio
    del barrido de arriba — no borrarlo, porque el permiso seguiría siendo innecesario."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT pg_get_functiondef("
                    "'public.fn_apply_retention(text,boolean)'::regprocedure)")
        d = cur.fetchone()[0]
    assert "FROM public.tenants" in d, "ya no recorre todos los tenants: revisar el riesgo"
    for guarda in ("auth.uid", "tenant_users", "app_current_tenant"):
        assert guarda not in d, f"ahora sí valida con {guarda}: revisar este test"
