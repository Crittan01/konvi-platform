#!/usr/bin/env python3.11
"""Track 9 — guard CI: toda función SECURITY DEFINER creada por una migración NUEVA
debe nacer cerrada.

Reglas por cada `CREATE [OR REPLACE] FUNCTION` con `SECURITY DEFINER` en una
migración nueva (diff vs origin/develop):

  1. El encabezado de la función fija `SET search_path` (sin él, un objeto malicioso
     en otro schema puede secuestrar referencias no calificadas — el caller corre con
     privilegios del OWNER).
  2. La misma migración revoca el EXECUTE a los roles de cliente:
     `REVOKE ... ON FUNCTION <nombre> ... FROM PUBLIC` / `anon` (el built-in de
     Postgres otorga EXECUTE a PUBLIC en TODA función nueva; el default ACL de
     Supabase a anon/authenticated — ver migración 20260822120300).
  3. Excepción justificada: `-- track9:exempt:<nombre> — <razón>` en el archivo
     (p.ej. una RPC pensada para la consola con guarda interna de membresía/rol,
     como pgsec_*). La exención queda en el diff: es una decisión auditable.

El event trigger `track9_revoke_public_on_new_function` es la RED (revoca PUBLIC al
crear); este lint es la PREVENCIÓN (la migración declara su intención de acceso).

Uso:
  python3.11 scripts/check_secdef_grants.py                # migraciones nuevas vs origin/develop
  python3.11 scripts/check_secdef_grants.py <archivo...>   # lista explícita
  python3.11 scripts/check_secdef_grants.py --all          # todo el corpus (auditoría)
Exit 0 = OK · 1 = violaciones.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

EXEMPT_PREFIX = "track9:exempt"

_CREATE_FN = re.compile(
    r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(?:public\.)?(?P<name>[a-zA-Z_][\w]*)\s*\(",
    re.IGNORECASE,
)
_HEADER_END = re.compile(r"\bAS\s+\$", re.IGNORECASE)
_SECDEF = re.compile(r"SECURITY\s+DEFINER", re.IGNORECASE)
_SEARCH_PATH = re.compile(r"search_path", re.IGNORECASE)


def _revoca_a_clientes(texto: str, nombre: str) -> bool:
    """True si el archivo tiene `REVOKE ... ON FUNCTION [public.]<nombre>(... ) FROM
    ... PUBLIC/anon` (cualquier variante de privilegio y orden tras FROM)."""
    patron = re.compile(
        r"REVOKE\s+[^;]*?\bON\s+FUNCTION\s+(?:public\.)?"
        + re.escape(nombre)
        + r"\s*\([^;]*?FROM\s+[^;]*?\b(PUBLIC|anon)\b",
        re.IGNORECASE | re.DOTALL,
    )
    return bool(patron.search(texto))


def _exenta(texto: str, nombre: str) -> bool:
    """`-- track9:exempt:<nombre>` (razón obligatoria en la misma línea)."""
    patron = re.compile(
        r"--\s*" + re.escape(EXEMPT_PREFIX) + r"\s*:\s*" + re.escape(nombre) + r"\s*[—:\-]\s*\S+",
        re.IGNORECASE,
    )
    return bool(patron.search(texto))


def check_migration(path: Path) -> list[str]:
    """Violaciones de una migración. Lista vacía = OK."""
    texto = path.read_text(encoding="utf-8")
    violaciones: list[str] = []
    for match in _CREATE_FN.finditer(texto):
        nombre = match.group("name")
        fin = _HEADER_END.search(texto, match.end())
        encabezado = texto[match.start(): fin.start() if fin else match.end() + 2000]
        if not _SECDEF.search(encabezado):
            continue  # SECURITY INVOKER: corre con privilegios del caller, fuera de alcance
        if _exenta(texto, nombre):
            continue
        if not _SEARCH_PATH.search(encabezado):
            violaciones.append(f"{path.name}: `{nombre}` es SECURITY DEFINER sin SET search_path")
        if not _revoca_a_clientes(texto, nombre):
            violaciones.append(
                f"{path.name}: `{nombre}` es SECURITY DEFINER sin REVOKE de PUBLIC/anon "
                f"(o `-- {EXEMPT_PREFIX}:{nombre} — <razón>` si es RPC de consola con guarda interna)"
            )
    return violaciones


def migraciones_nuevas() -> list[Path]:
    """Migraciones nuevas/modificadas vs origin/develop (merge-base, como el job changes)."""
    base = subprocess.run(
        ["git", "merge-base", "HEAD", "origin/develop"], capture_output=True, text=True
    )
    ref = base.stdout.strip() if base.returncode == 0 and base.stdout.strip() else "HEAD~1"
    diff = subprocess.run(
        ["git", "diff", "--name-only", f"{ref}..HEAD", "--", "supabase/migrations/"],
        capture_output=True,
        text=True,
    )
    if diff.returncode != 0:
        return []
    return [Path(linea) for linea in diff.stdout.splitlines() if linea.endswith(".sql")]


def main(argv: list[str]) -> int:
    args = argv[1:]
    if args and args[0] == "--all":
        archivos = sorted(Path("supabase/migrations").glob("*.sql"))
    elif args:
        archivos = [Path(a) for a in args]
    else:
        archivos = migraciones_nuevas()

    if not archivos:
        print("check_secdef_grants: sin migraciones nuevas que revisar")
        return 0

    violaciones: list[str] = []
    for archivo in archivos:
        if not archivo.exists():
            print(f"check_secdef_grants: {archivo} no existe (¿borrada en el diff?)")
            continue
        violaciones.extend(check_migration(archivo))

    if violaciones:
        print("check_secdef_grants: FUNCIONES SECURITY DEFINER ABIERTAS en migraciones nuevas:")
        for v in violaciones:
            print(f"  ❌ {v}")
        return 1
    print(f"check_secdef_grants: OK ({len(archivos)} migración(es) revisadas)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
