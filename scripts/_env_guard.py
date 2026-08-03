"""Guard fail-closed anti-prod para scripts destructivos (cutover dev/prod, D.4).

Modelo DENY-BY-DEFAULT (allow-only-known-dev): un script testing-only solo corre
si su destino Supabase es un ref de dev EXPLÍCITAMENTE reconocido (o un Supabase
local). Contra prod, contra un ref desconocido, o contra un host no parseable,
ABORTA (exit 2) salvo override auditable `KONVI_ALLOW_PROD=1`.

Por qué deny-by-default y no "abortar solo si es el ref de prod conocido":
extraer el ref del URL es frágil (custom domains, pooler, `db.<ref>`, connection
strings). Un modelo "prohibir solo lo conocido-malo" hace FAIL-OPEN ante lo que
no reconoce. Invertirlo — "permitir solo lo conocido-bueno" — convierte todo lo
no-identificable en fail-closed, la postura correcta para borrado de datos.

ESTADO PRE-LANZAMIENTO (decisión founder 2026-07-20)
----------------------------------------------------
`konvi-prod` es hoy el ÚNICO entorno: no atiende clientes reales todavía, y
mantener un segundo proyecto sólo generaba confusión (el proyecto `konvi-dev` se
eliminó). Pero apagar el guard —o correr todo con `KONVI_ALLOW_PROD=1`— dejaría el
hábito instalado justo para el día en que sí importe.

Solución: mientras `LAUNCHED` sea False, el ref de prod se clasifica `prelaunch`:
los scripts corren, pero SIEMPRE avisando por stderr contra qué están corriendo.

>>> EL DÍA DEL LANZAMIENTO REAL: poner `LAUNCHED = True` (una línea, abajo).
    Desde ese momento `konvi-prod` vuelve a ser `prod` duro y los 16 scripts
    testing-only abortan salvo override explícito. Es una decisión deliberada y
    auditable en git, no un olvido.

Config (env):
- `KONVI_SAFE_REFS`   : refs de dev permitidos, coma-separado (vacío por default:
                        ya no hay proyecto dev; local sigue siendo seguro).
- `KONVI_PROD_REF`    : ref de prod (solo para un mensaje de error explícito).
- `KONVI_LAUNCHED=1`  : fuerza modo post-lanzamiento sin tocar código.
- `KONVI_ALLOW_PROD=1`: override auditable para correr contra un destino no-dev.

Uso:
    from _env_guard import assert_safe_target
    creds = _load_env()
    assert_safe_target(creds, action="wipe_conversation")
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
from typing import Optional

# Ref inmutable del proyecto Supabase de producción (konvi-prod). El project-ref
# no cambia aunque se renombre el proyecto (ver docs/infra/environments.md).
PROD_REF = os.getenv("KONVI_PROD_REF", "xmelwnhhphksbpdjmbbp").strip().lower()

# >>> CAMBIAR A True EL DÍA DEL LANZAMIENTO REAL (ver docstring). <<<
# False = pre-lanzamiento: konvi-prod se clasifica 'prelaunch' y los scripts
# testing-only corren, avisando siempre. True = prod duro, fail-closed.
LAUNCHED = False

# Ya no existe un proyecto dev (konvi-dev eliminado 2026-07-20). La allowlist
# queda vacía por default: sólo un Supabase LOCAL es 'dev-safe' sin configurar
# nada. Si algún día vuelve a haber un proyecto dev, basta exportar
# KONVI_SAFE_REFS=<ref> — no hace falta tocar este archivo.
_DEFAULT_DEV_REF = ""

# Un ref Supabase es un slug de 20 chars [a-z0-9]; aceptamos `<ref>.supabase.co`
# y el host directo de Postgres `db.<ref>.supabase.co`.
_HOST_REF_RE = re.compile(r"^(?:db\.)?([a-z0-9]{16,})\.supabase\.co$", re.IGNORECASE)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1", "[::1]"}


def _safe_refs() -> set:
    """Allowlist de refs de dev (fail-closed: solo estos, más local, son seguros)."""
    raw = os.getenv("KONVI_SAFE_REFS", _DEFAULT_DEV_REF)
    return {r.strip().lower() for r in raw.split(",") if r.strip()}


def _host(creds: dict) -> Optional[str]:
    """Hostname del endpoint Supabase (parsing robusto vía urllib)."""
    url = (creds.get("NEXT_PUBLIC_SUPABASE_URL") or creds.get("SUPABASE_URL") or "").strip()
    if not url:
        return None
    parsed = urllib.parse.urlparse(url if "://" in url else "//" + url)
    return (parsed.hostname or "").lower() or None


def extract_ref(creds: dict) -> Optional[str]:
    """Deriva el project-ref del host (`<ref>.supabase.co` o `db.<ref>.supabase.co`)."""
    host = _host(creds)
    if not host:
        return None
    m = _HOST_REF_RE.match(host)
    return m.group(1).lower() if m else None


def is_local(creds: dict) -> bool:
    """True si el destino es un Supabase local (localhost / *.local)."""
    host = _host(creds)
    if not host:
        return False
    return host in _LOCAL_HOSTS or host.endswith(".local")


_REF_RE = re.compile(r"^[a-z0-9]{16,}$")


def _ref_from_database_url(creds: dict) -> tuple[Optional[str], bool, bool]:
    """Deriva el ref de una connection string Postgres (`DATABASE_URL`).

      • directo: postgresql://postgres:pwd@db.<ref>.supabase.co:5432/postgres
      • pooler:  postgres://postgres.<ref>:pwd@aws-0-...pooler.supabase.com:6543/postgres

    Cierra el fail-open (audit cierre prod): antes classify() solo miraba la URL
    Supabase; una tool que conecte por DATABASE_URL a PROD con URL=dev pasaba como
    'dev-safe'. Retorna (ref|None, is_set, is_local).
    """
    url = (creds.get("DATABASE_URL") or "").strip()
    if not url:
        return (None, False, False)
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _LOCAL_HOSTS or host.endswith(".local"):
        return (None, True, True)
    m = _HOST_REF_RE.match(host)          # directo: db.<ref>.supabase.co
    if m:
        return (m.group(1).lower(), True, False)
    user = parsed.username or ""          # pooler: postgres.<ref>
    if "." in user:
        cand = user.split(".", 1)[1].lower()
        if _REF_RE.match(cand):
            return (cand, True, False)
    return (None, True, False)            # seteado pero no identificable → deny


def _launched() -> bool:
    """True si ya se lanzó a producción real (env pisa la constante del módulo)."""
    env = os.getenv("KONVI_LAUNCHED", "").strip()
    if env:
        return env == "1"
    return LAUNCHED


def _prod_kind() -> str:
    """Etiqueta del ref de prod según el estado de lanzamiento."""
    return "prod" if _launched() else "prelaunch"


def classify(creds: dict) -> str:
    """Clasifica el destino: 'dev-safe' | 'prelaunch' | 'prod' | 'unknown'.

    Deny-by-default sobre TODAS las fuentes (URL Supabase + DATABASE_URL +
    SUPABASE_PROJECT_REF): si CUALQUIERA apunta a prod → 'prod'/'prelaunch'; si
    cualquiera está seteada pero no se resuelve a un dev conocido → 'unknown'. Solo
    'dev-safe' si todas las fuentes presentes son local o un ref de dev reconocido.
    Excepción: un SUPABASE_PROJECT_REF sin forma de ref cloud (20 chars [a-z0-9]) —
    p.ej. el slug del proyecto local del CLI — no puede direccionar un proyecto
    cloud y se trata como neutro (ENV-1: dev local por defecto contra podman).

    'prelaunch' es el ref de PROD antes del lanzamiento: mismo proyecto, pero los
    scripts testing-only pueden correr contra él avisando (ver assert_safe_target).
    """
    safe = _safe_refs()
    saw_safe = False
    saw_unsafe = False

    # Fuente 1 — URL Supabase.
    if _host(creds):
        if is_local(creds):
            saw_safe = True
        else:
            ref = extract_ref(creds)
            if ref == PROD_REF:
                return _prod_kind()
            if ref is not None and ref in safe:
                saw_safe = True
            else:
                saw_unsafe = True

    # Fuente 2 — DATABASE_URL (connection string Postgres).
    db_ref, db_set, db_local = _ref_from_database_url(creds)
    if db_set:
        if db_local:
            saw_safe = True
        elif db_ref == PROD_REF:
            return _prod_kind()
        elif db_ref is not None and db_ref in safe:
            saw_safe = True
        else:
            saw_unsafe = True

    # Fuente 3 — SUPABASE_PROJECT_REF directo.
    pr = (creds.get("SUPABASE_PROJECT_REF") or "").strip().lower()
    if pr:
        if pr == PROD_REF:
            return _prod_kind()
        if _REF_RE.match(pr):
            if pr in safe:
                saw_safe = True
            else:
                saw_unsafe = True
        # else: slug SIN forma de ref cloud (los refs cloud son 20 chars [a-z0-9];
        # p.ej. el project_id local del CLI "konvi-platform" tiene guion). No puede
        # direccionar ningún proyecto cloud → neutro: la clasificación la deciden
        # URL + DATABASE_URL. Un string de 16+ alnum (forma de ref) sigue fail-closed.

    if saw_unsafe:
        return "unknown"
    return "dev-safe" if saw_safe else "unknown"


def is_prod(creds: dict) -> bool:
    """True si el destino es el PROYECTO de producción — lanzado o no.

    Deliberadamente cubre 'prelaunch': sigue siendo konvi-prod, sólo que aún sin
    clientes. Quien pregunte "¿esto es prod?" debe oír que sí.
    """
    return classify(creds) in ("prod", "prelaunch")


def assert_safe_target(creds: dict, *, action: str = "operación destructiva") -> None:
    """Aborta (exit 2) salvo que el destino sea un dev reconocido. Deny-by-default.

    Fail-closed: prod, ref desconocido y host no-parseable requieren override
    explícito `KONVI_ALLOW_PROD=1`. Se evalúa en cada llamada (no cachea el env).

    Excepción PRE-LANZAMIENTO: 'prelaunch' (konvi-prod antes del lanzamiento) SÍ
    pasa, pero nunca en silencio — se avisa por stderr en cada corrida. Con
    `LAUNCHED = True` esta rama desaparece y vuelve a ser fail-closed.
    """
    kind = classify(creds)
    if kind == "dev-safe":
        return
    if kind == "prelaunch":
        print(
            f"⚠️  «{action}» corre contra konvi-prod (PRE-LANZAMIENTO, ref={PROD_REF}).\n"
            f"   Es el proyecto real: los datos que escribas quedan ahí.\n"
            f"   Al lanzar, poné LAUNCHED = True en scripts/_env_guard.py y esto abortará.",
            file=sys.stderr,
        )
        return
    allow = os.getenv("KONVI_ALLOW_PROD", "").strip() == "1"
    ref = extract_ref(creds)
    target = f"ref={ref}" if ref else f"host={_host(creds) or '?'}"
    if allow:
        print(
            f"AVISO: «{action}» corriendo contra destino NO-dev ({kind}, {target}) "
            f"por override explícito KONVI_ALLOW_PROD=1.",
            file=sys.stderr,
        )
        return
    reason = (
        f"apunta a PRODUCCIÓN ({target})"
        if kind == "prod"
        else f"apunta a un destino NO reconocido como dev ({target})"
    )
    print(
        f"ABORTADO: «{action}» {reason}.\n"
        f"  Este script es testing-only y borra datos sin preservar audit.\n"
        f"  Solo corre contra un Supabase local o un ref listado en KONVI_SAFE_REFS.\n"
        f"  Si REALMENTE necesitás correr contra este destino, exportá KONVI_ALLOW_PROD=1.",
        file=sys.stderr,
    )
    sys.exit(2)


# Compat: nombre anterior (semántica idéntica al nuevo modelo deny-by-default).
assert_not_prod = assert_safe_target
