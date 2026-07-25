"""La segunda puerta a la escritura de dinero: las RPC SECURITY DEFINER.

Las policies RESTRICTIVE de W2b gobiernan el acceso a la TABLA. Una función SECURITY DEFINER
corre con los privilegios de quien la creó y NO evalúa RLS — así que con el EXECUTE otorgado
a `authenticated`, un usuario logueado se saltaba el candado llamando a la función en vez de
escribir la tabla.

El caso más claro: `cart_add_item` recibe `p_unit_price_cents` como PARÁMETRO. El precio lo
elegía quien llamara.

Este archivo fija la propiedad de forma que no dependa de la lista de nombres que yo escribí:
recorre el esquema real y falla si aparece CUALQUIER función SECURITY DEFINER de dinero
ejecutable por `authenticated` — incluida una que alguien agregue el mes que viene.
"""
import pytest

from _harness import connect

pytestmark = pytest.mark.dbharness


# Escritura de dinero/inventario. Los `metrics_*` quedan fuera a propósito: son agregados de
# solo lectura y el dashboard llama a uno de ellos con JWT de usuario.
PATRON_DINERO = r'^(cart_add_item|fn_expire_abandoned_carts|rpc_stock_)'


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


def _funcs(cur, rol):
    cur.execute(
        """
        SELECT p.oid::regprocedure::text
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prosecdef
          AND p.proname ~ %s
          AND has_function_privilege(%s, p.oid, 'EXECUTE')
        ORDER BY 1
        """,
        (PATRON_DINERO, rol),
    )
    return [r[0] for r in cur.fetchall()]


@pytest.mark.parametrize("rol", ["authenticated", "anon"])
def test_ningun_rol_de_cliente_ejecuta_rpc_de_dinero(db, rol):
    """La propiedad, no la lista: si mañana alguien agrega una rpc_stock_* nueva y nace con el
    GRANT por defecto, este test la caza."""
    with db.cursor() as cur:
        abiertas = _funcs(cur, rol)
    assert abiertas == [], (
        f"{rol} puede ejecutar {len(abiertas)} función(es) de dinero que evaden RLS: {abiertas}"
    )


def test_el_backend_las_sigue_pudiendo_ejecutar(db):
    """Revocar de más rompería el bot entero: reservar stock, consumir al pagar, devolverlo al
    cancelar. Ese es el riesgo real de esta migración."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.oid::regprocedure::text
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prosecdef AND p.proname ~ %s
            ORDER BY 1
            """,
            (PATRON_DINERO,),
        )
        todas = [r[0] for r in cur.fetchall()]
        assert todas, "no hay funciones de dinero en el esquema — el patrón no matchea nada"
        sin_acceso = [f for f in todas if not _puede(cur, "service_role", f)]
    assert sin_acceso == [], f"service_role perdió acceso a: {sin_acceso}"


def _puede(cur, rol, sig):
    cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (rol, sig))
    return cur.fetchone()[0]


def test_todas_las_sobrecargas_quedaron_cerradas(db):
    """consume/extend/release tienen dos firmas cada una. Dejar una abierta reabre el hueco
    entero, y es justo el error que un REVOKE escrito a mano comete."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT p.proname, count(*)
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prosecdef AND p.proname ~ %s
            GROUP BY p.proname HAVING count(*) > 1
            """,
            (PATRON_DINERO,),
        )
        con_sobrecarga = cur.fetchall()
        assert con_sobrecarga, "se esperaban funciones sobrecargadas (consume/extend/release)"
        for nombre, _n in con_sobrecarga:
            cur.execute(
                """
                SELECT p.oid::regprocedure::text
                FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                WHERE n.nspname = 'public' AND p.proname = %s
                  AND has_function_privilege('authenticated', p.oid, 'EXECUTE')
                """,
                (nombre,),
            )
            abiertas = [r[0] for r in cur.fetchall()]
            assert abiertas == [], f"sobrecarga de {nombre} sigue abierta: {abiertas}"


def test_el_precio_de_cart_add_item_sigue_siendo_un_parametro(db):
    """Documenta POR QUÉ esta migración existe. Si algún día el precio deja de ser parámetro y
    se lee del catálogo, este test falla y hay que revisar si el REVOKE sigue haciendo falta —
    o si conviene además quitar el parámetro."""
    with db.cursor() as cur:
        cur.execute(
            """
            SELECT pg_get_function_arguments(p.oid)
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.proname = 'cart_add_item'
            """
        )
        args = cur.fetchone()
    assert args and "p_unit_price_cents" in args[0], (
        "cart_add_item ya no recibe el precio: revisar si este candado sigue siendo el correcto"
    )
