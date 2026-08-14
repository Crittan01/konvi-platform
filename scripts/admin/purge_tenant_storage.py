"""Purga FÍSICA de objetos de Storage de un tenant (erasure Ley 1581 Art. 16).

CONTEXTO (Fase 6 audit offboarding, sev ALTO): el hard-delete irreversible
(fn_hard_delete_tenant) ejecuta DELETE FROM tenants con CASCADE, pero el CASCADE
NO alcanza storage.objects (esa tabla no tiene FK a tenants). Sin una purga
explícita, los archivos subidos por el tenant y por SUS CLIENTES quedan en los
buckets con PII → erasure legalmente INCOMPLETA.

Este script borra, vía Storage API oficial (.remove), TODOS los objetos bajo el
prefijo '{tenant_id}/' de los buckets indicados. A diferencia del borrado por SQL
(RPC fn_purge_tenant_storage_objects, que borra la fila de storage.objects), la
Storage API elimina el blob físico + la fila → purga completa y verificable.

Mecanismo PARAMETRIZADO por lista de buckets/prefijos:
  - Default: bucket 'tenant-media', prefijo '{tenant_id}/'  (único bucket con PII
    per-tenant conocido hoy; documentado).
  - La lista canónica COMPLETA de buckets con PII la confirma el founder; se pasa
    con --buckets sin cambiar el mecanismo.
  - NUNCA se purga 'offboarding-archive' (retención legal 5 años, Art. 22): está
    excluido de forma defensiva aunque se pase por error.

Requiere env:
  NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY)

Uso:
  python3.11 scripts/admin/purge_tenant_storage.py --tenant <uuid> --dry-run
  python3.11 scripts/admin/purge_tenant_storage.py --tenant <uuid> --yes
  python3.11 scripts/admin/purge_tenant_storage.py --tenant <uuid> \
      --buckets tenant-media otro-bucket-con-pii --yes

Salida: conteo de objetos listados/borrados por bucket. Idempotente: correrlo
dos veces sobre el mismo tenant borra 0 la segunda vez (ya no hay objetos).
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Optional

from supabase import create_client

# Bucket de archivo legal (Art. 22, retención 5 años). NUNCA purgar.
PROTECTED_BUCKETS = frozenset({"offboarding-archive"})

# Default documentado: único bucket con PII per-tenant conocido hoy.
DEFAULT_BUCKETS = ("tenant-media",)

# Tamaño de página al listar y de lote al borrar (defensivo).
_LIST_PAGE = 100


def _client():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    if not url or not key:
        raise SystemExit(
            "Falta NEXT_PUBLIC_SUPABASE_URL y/o "
            "SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY"
        )
    # Cutover dev/prod (D.4): rechaza purgar storage de prod salvo override.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from _env_guard import assert_safe_target
    assert_safe_target(dict(os.environ), action="purge_tenant_storage")
    return create_client(url, key)


def _list_all_object_paths(sb: Any, bucket: str, prefix: str) -> list[str]:
    """Lista recursivamente TODAS las rutas de objeto bajo `prefix` en `bucket`.

    La Storage API .list() devuelve, por carpeta, tanto archivos (id != None)
    como subcarpetas (id == None). Recorremos en anchura para no asumir
    profundidad de directorios. Retorna rutas completas listas para .remove().
    """
    collected: list[str] = []
    # Normalizar: sin '/' inicial; el prefijo tenant termina en '/'.
    pending: list[str] = [prefix.rstrip("/")]

    while pending:
        folder = pending.pop()
        offset = 0
        while True:
            try:
                entries = sb.storage.from_(bucket).list(
                    path=folder,
                    options={"limit": _LIST_PAGE, "offset": offset},
                )
            except Exception as exc:  # bucket inexistente / permisos → skip.
                print(
                    f"  [warn] no se pudo listar {bucket}/{folder or '<root>'}: {exc}",
                    file=sys.stderr,
                )
                entries = []
            if not entries:
                break

            for e in entries:
                name = e.get("name")
                if not name:
                    continue
                full = f"{folder}/{name}" if folder else name
                # id None => subcarpeta (placeholder); recursar.
                if e.get("id") is None:
                    pending.append(full)
                else:
                    collected.append(full)

            if len(entries) < _LIST_PAGE:
                break
            offset += _LIST_PAGE

    return collected


def purge_tenant_storage(
    sb: Any,
    tenant_id: str,
    buckets: Optional[tuple[str, ...]] = None,
    dry_run: bool = True,
) -> dict[str, dict[str, int]]:
    """Purga (o cuenta, si dry_run) los objetos '{tenant_id}/%' de los buckets.

    Retorna { bucket: {"listed": n, "removed": m} }. Excluye PROTECTED_BUCKETS.
    """
    if not tenant_id:
        raise ValueError("tenant_id es obligatorio")

    target = tuple(
        b for b in (buckets or DEFAULT_BUCKETS)
        if b and b not in PROTECTED_BUCKETS
    )
    # G8a: el tenant tiene DOS prefijos con PII en el bucket — '{tenant_id}/'
    # (media library, logo) e 'inbox-attachments/{tenant_id}/' (adjuntos de
    # conversación). Antes solo se purgaba el primero → los adjuntos de inbox
    # sobrevivían al hard-delete (fuga Habeas Data post-erasure).
    prefixes = [f"{tenant_id}/", f"inbox-attachments/{tenant_id}/"]
    report: dict[str, dict[str, int]] = {}

    for bucket in target:
        paths: list[str] = []
        for prefix in prefixes:
            paths.extend(_list_all_object_paths(sb, bucket, prefix))
        removed = 0
        if paths and not dry_run:
            # Borrar en lotes para no exceder límites de payload de la API.
            for i in range(0, len(paths), _LIST_PAGE):
                batch = paths[i : i + _LIST_PAGE]
                try:
                    sb.storage.from_(bucket).remove(batch)
                    removed += len(batch)
                except Exception as exc:
                    print(
                        f"  [error] fallo borrando lote en {bucket}: {exc}",
                        file=sys.stderr,
                    )
        report[bucket] = {"listed": len(paths), "removed": removed}

    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Purga física de objetos de Storage de un tenant (erasure)."
    )
    ap.add_argument("--tenant", required=True, help="tenant_id (UUID) a purgar")
    ap.add_argument(
        "--buckets",
        nargs="+",
        default=list(DEFAULT_BUCKETS),
        help=f"Buckets a purgar (default: {' '.join(DEFAULT_BUCKETS)}). "
        "offboarding-archive se ignora siempre.",
    )
    ap.add_argument(
        "--dry-run", action="store_true", help="Solo listar/contar, no borrar."
    )
    ap.add_argument(
        "--yes", action="store_true", help="Confirmar borrado real (irreversible)."
    )
    args = ap.parse_args()

    if not args.dry_run and not args.yes:
        raise SystemExit("Borrado real requiere --yes (o usa --dry-run).")

    sb = _client()
    report = purge_tenant_storage(
        sb,
        tenant_id=args.tenant,
        buckets=tuple(args.buckets),
        dry_run=args.dry_run or not args.yes,
    )

    mode = "DRY-RUN (no se borró nada)" if (args.dry_run or not args.yes) else "PURGA REAL"
    print(f"[purge_tenant_storage] tenant={args.tenant} — {mode}")
    total_listed = total_removed = 0
    for bucket, c in report.items():
        total_listed += c["listed"]
        total_removed += c["removed"]
        print(f"  {bucket}: listados={c['listed']} borrados={c['removed']}")
    print(f"  TOTAL: listados={total_listed} borrados={total_removed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
