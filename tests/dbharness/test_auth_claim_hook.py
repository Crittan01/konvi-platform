"""Test ejecutable del `custom_access_token_hook` — raíz de confianza de la RLS.

El hook inyecta `tenant_id` + `role` en `app_metadata` del JWT en CADA emisión de
token, leyendo `tenant_users` con `status='active'`, y BORRA el claim si no hay
membresía activa. TODA la RLS `authenticated` (app_current_tenant(), policies
role-aware) confía en ese claim. Hasta esta suite el hook solo se validó a mano en
prod (3/3); acá queda anclado como gate reproducible en CI.

Cubre: (1) inyecta tenant/rol de miembro activo; (2) preserva los claims requeridos
que Supabase Auth exige tras el hook; (3) cierra el gap de stale-role (limpia el
claim al inactivar la membresía — lo que el trigger legacy NO hacía); (4) sin
membresía activa no inyecta nada.
"""
import json

import pytest

from _harness import TENANT_A, OWNER_A

pytestmark = pytest.mark.dbharness

# user sin membresía (no está en el seed) para el caso "sin tenant".
_ORPHAN = "99999999-0000-0000-0000-0000000000ff"


def _call_hook(cur, user_id: str) -> dict:
    """Invoca el hook como lo hace GoTrue: event con user_id + claims base
    (app_metadata vacío + los claims requeridos que Auth ya trae)."""
    event = json.dumps({
        "user_id": user_id,
        "claims": {
            "app_metadata": {},
            "sub": user_id, "aud": "authenticated", "role": "authenticated",
            "exp": 9999999999, "iat": 1, "iss": "https://x", "session_id": "s1",
        },
    })
    cur.execute("SELECT public.custom_access_token_hook(%s::jsonb)", (event,))
    return cur.fetchone()[0]


def test_hook_inyecta_tenant_y_rol_de_miembro_activo(db, seed):
    with db.cursor() as cur:
        am = _call_hook(cur, OWNER_A)["claims"]["app_metadata"]
        assert am.get("tenant_id") == TENANT_A, "el hook no inyectó el tenant_id del miembro activo"
        assert am.get("role") == "owner", "el hook no inyectó el rol del miembro activo"


def test_hook_preserva_claims_requeridos(db, seed):
    """Auth rechaza el token si faltan iss/aud/exp/sub/role tras el hook."""
    with db.cursor() as cur:
        cl = _call_hook(cur, OWNER_A)["claims"]
        for req in ("sub", "aud", "exp", "role", "iss", "session_id"):
            assert req in cl, f"el hook eliminó el claim requerido {req!r}"
        assert cl["role"] == "authenticated", "el hook pisó el claim top-level 'role' (debe ser el rol de GoTrue)"


def test_hook_limpia_claim_al_inactivar_membresia(db, seed):
    """Gap stale-role: al inactivar la membresía, el hook DEBE quitar tenant_id/role
    del próximo token. El trigger legacy (ya dropeado) NO filtraba status → el rol
    persistía hasta re-login."""
    with db.cursor() as cur:
        assert _call_hook(cur, OWNER_A)["claims"]["app_metadata"].get("role") == "owner"
        cur.execute(
            "UPDATE public.tenant_users SET status='inactive' WHERE user_id=%s AND tenant_id=%s",
            (OWNER_A, TENANT_A),
        )
        am2 = _call_hook(cur, OWNER_A)["claims"]["app_metadata"]
        assert am2.get("tenant_id") is None, "tenant_id persistió tras inactivar (stale-role)"
        assert am2.get("role") is None, "role persistió tras inactivar (stale-role)"


def test_hook_sin_membresia_activa_no_inyecta(db, seed):
    with db.cursor() as cur:
        cur.execute("INSERT INTO auth.users (id) VALUES (%s) ON CONFLICT DO NOTHING", (_ORPHAN,))
        try:
            am = _call_hook(cur, _ORPHAN)["claims"]["app_metadata"]
            assert am.get("tenant_id") is None, "inyectó tenant_id a un user sin membresía"
            assert am.get("role") is None, "inyectó role a un user sin membresía"
        finally:
            cur.execute("DELETE FROM auth.users WHERE id=%s", (_ORPHAN,))
