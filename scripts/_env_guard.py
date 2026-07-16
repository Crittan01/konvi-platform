"""Guard anti-prod para scripts destructivos (cutover dev/prod, sección D.4).

Cierra la última capa del CRITICAL `dev = prod comparten Supabase`: tras el
cutover, `.env` apunta a `konvi-dev` (sintético, seguro) y `.env.prod` a
`konvi-prod` (datos reales). Este guard evita que un script *testing-only*
(wipe/purge) borre datos reales si por error carga credenciales de producción.

Contrato:
- `assert_not_prod(creds, action=...)` aborta si el `NEXT_PUBLIC_SUPABASE_URL`
  (o `SUPABASE_URL`) resuelve al *project-ref* de producción.
- Override explícito y auditable: `KONVI_ALLOW_PROD=1` permite correr contra
  prod (imprime AVISO). Sin esa variable, el default es FALLAR (fail-closed).
- El ref de prod es configurable vía `KONVI_PROD_REF` (default: el ref real
  inmutable de `konvi-prod`).

Uso:
    from _env_guard import assert_not_prod
    creds = _load_env()
    assert_not_prod(creds, action="wipe_conversation")
"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional

# Ref inmutable del proyecto Supabase de producción (konvi-prod). El project-ref
# no cambia aunque se renombre el proyecto (ver docs/infra/environments.md).
PROD_REF = os.getenv("KONVI_PROD_REF", "xmelwnhhphksbpdjmbbp").strip()

_URL_RE = re.compile(r"https?://([a-z0-9]+)\.supabase\.co", re.IGNORECASE)


def extract_ref(creds: dict) -> Optional[str]:
    """Deriva el project-ref del URL Supabase (`https://<ref>.supabase.co`)."""
    url = creds.get("NEXT_PUBLIC_SUPABASE_URL") or creds.get("SUPABASE_URL") or ""
    m = _URL_RE.search(url)
    return m.group(1).lower() if m else None


def is_prod(creds: dict) -> bool:
    """True si las credenciales resuelven al proyecto de producción."""
    ref = extract_ref(creds)
    return bool(ref) and ref == PROD_REF


def assert_not_prod(creds: dict, *, action: str = "operación destructiva") -> None:
    """Aborta (exit 2) si `creds` apunta a prod, salvo override `KONVI_ALLOW_PROD=1`.

    Fail-closed: la ausencia o el valor inválido de la variable de override
    equivalen a "no permitido". Se evalúa en cada llamada (no se cachea) para
    respetar cambios de entorno en procesos de larga vida.
    """
    if not is_prod(creds):
        return
    allow = os.getenv("KONVI_ALLOW_PROD", "").strip() == "1"
    ref = extract_ref(creds)
    if not allow:
        print(
            f"ABORTADO: «{action}» apunta a PRODUCCIÓN (ref={ref}).\n"
            f"  Este script es testing-only y borra datos sin preservar audit.\n"
            f"  El default seguro es `.env` (apunta a konvi-dev).\n"
            f"  Si REALMENTE necesitás correr contra prod, exportá KONVI_ALLOW_PROD=1.",
            file=sys.stderr,
        )
        sys.exit(2)
    print(
        f"AVISO: «{action}» corriendo contra PRODUCCIÓN (ref={ref}) por override "
        f"explícito KONVI_ALLOW_PROD=1.",
        file=sys.stderr,
    )
