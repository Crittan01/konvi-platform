"""Las funciones de trigger no deben figurar como ejecutables por los roles de cliente.

NO es una vulnerabilidad: Postgres rechaza invocar directamente cualquier función que
devuelva `trigger` ("trigger functions can only be called as triggers"), así que el
EXECUTE sobre ellas es inerte. Este archivo lo DEMUESTRA en vez de afirmarlo.

Se limpian igual porque 28 de 32 figuraban ejecutables por `anon`, y cualquier auditoría
que pregunte "¿qué puede ejecutar la llave pública del navegador?" recibía 28 falsos
positivos. La pregunta tiene que poder responderse de un vistazo, porque el día que
aparezca un positivo REAL tiene que destacarse.
"""
import pytest

from _harness import as_anon, connect

pytestmark = pytest.mark.dbharness


@pytest.fixture(scope="module")
def db():
    with connect() as conn:
        yield conn


def test_ningun_rol_de_cliente_las_tiene(db):
    """La propiedad, no la lista: si mañana alguien agrega un trigger nuevo y nace con el
    grant por defecto, este test lo caza."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT p.oid::regprocedure::text
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname='public' AND p.prorettype='trigger'::regtype
              AND (has_function_privilege('anon', p.oid,'EXECUTE')
                   OR has_function_privilege('authenticated', p.oid,'EXECUTE'))
            ORDER BY 1
        """)
        abiertas = [r[0] for r in cur.fetchall()]
    assert abiertas == [], f"{len(abiertas)} funciones de trigger siguen expuestas: {abiertas[:5]}"


def test_hay_funciones_de_trigger_que_verificar(db):
    """Si el patrón dejara de matchear, el test de arriba pasaría verificando nada."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prorettype='trigger'::regtype
        """)
        assert cur.fetchone()[0] > 10


# NO se incluye un test que INVOQUE una función de trigger.
#
# Se intentó, y el hallazgo fue serio: `SELECT public.update_marketplace_updated_at()`
# ejecutado como `anon` NO devuelve "permission denied" ni "trigger functions can only be
# called as triggers" — TUMBA el backend de PostgreSQL y deja la base en modo recuperación.
# Reproducido tres veces contra el harness, que es réplica fiel de prod (mismo replay de
# migraciones, misma versión). El crash ocurre ANTES del chequeo de privilegios, así que
# revocar el EXECUTE no lo evita a nivel SQL.
#
# Lo que el REVOKE sí hace es quitar la precondición para que PostgREST exponga la función
# como endpoint `/rpc/<nombre>`: sin EXECUTE no entra en su cache de esquema. No se pudo
# verificar esa vía localmente (el harness levanta solo la DB, no PostgREST) y NO se probó
# contra producción a propósito: un resultado positivo sería una caída real.
#
# Un test que invoque la función dejaría el harness inutilizable para todo lo demás.


def test_los_triggers_siguen_disparando(db):
    """Lo que de verdad podría romperse. Los triggers corren con los privilegios del
    dueño de la tabla, no con los de quien hace el INSERT — pero conviene comprobarlo."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal
        """)
        assert cur.fetchone()[0] > 5, "deberían seguir existiendo triggers activos"
