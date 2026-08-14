#!/usr/bin/env python3.11
"""G8b fase 4 — migración one-shot de adjuntos viejos del inbox a bucket privado.

Los adjuntos que el operador enviaba a clientes vivían en el bucket PÚBLICO
`tenant-media` bajo `inbox-attachments/{tenant_id}/{conversation_id}/{archivo}`
y `messages.media_url` guardaba la URL pública completa. G8b los mueve al
bucket PRIVADO `tenant-inbox-media` y re-apunta los mensajes al esquema
`inbox-media://{path}` (chat firma al render, worker firma al enviar a Meta).

Por cada objeto viejo:
  1. Descarga del bucket viejo (público hoy).
  2. Sube al bucket privado con path SIN el prefijo 'inbox-attachments/'
     (el bucket ya es dedicado): {tenant_id}/{conversation_id}/{archivo}.
  3. UPDATE messages.media_url de la URL pública vieja → inbox-media://{nuevo}.
  4. Borra el objeto viejo (solo tras 2+3 confirmados).

Uso:
  python3.11 scripts/admin/migrate_inbox_media_private.py            # dry-run (cuenta)
  python3.11 scripts/admin/migrate_inbox_media_private.py --apply    # ejecuta
Env: .env.prod (prod) — env_guard fail-closed aplica.
"""
from __future__ import annotations

import argparse
import os
import sys

from supabase import create_client

_OLD_BUCKET = "tenant-media"
_NEW_BUCKET = "tenant-inbox-media"
_OLD_PREFIX = "inbox-attachments/"
_SCHEME = "inbox-media://"


def _client():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Falta NEXT_PUBLIC_SUPABASE_URL y/o SUPABASE_SECRET_KEY")
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from _env_guard import assert_safe_target
    assert_safe_target(dict(os.environ), action="migrate_inbox_media_private")
    return create_client(url, key)


def _list_old_objects(sb) -> list[str]:
    """Todos los objetos bajo inbox-attachments/ en el bucket viejo (BFS por carpeta)."""
    out: list[str] = []
    pending = [_OLD_PREFIX.rstrip("/")]
    while pending:
        folder = pending.pop()
        offset = 0
        while True:
            entries = sb.storage.from_(_OLD_BUCKET).list(
                path=folder, options={"limit": 100, "offset": offset},
            )
            if not entries:
                break
            for e in entries:
                name = e.get("name")
                if not name:
                    continue
                full = f"{folder}/{name}" if folder else name
                if e.get("id") is None:
                    pending.append(full)
                else:
                    out.append(full)
            if len(entries) < 100:
                break
            offset += 100
    return out


def migrate(sb, apply: bool) -> dict:
    objects = _list_old_objects(sb)
    report = {"found": len(objects), "migrated": 0, "messages_updated": 0, "errors": 0}
    for old_path in objects:
        new_path = old_path[len(_OLD_PREFIX):]  # quita 'inbox-attachments/'
        old_public_url = (
            f"{os.environ['NEXT_PUBLIC_SUPABASE_URL'].rstrip('/')}"
            f"/storage/v1/object/public/{_OLD_BUCKET}/{old_path}"
        )
        try:
            if apply:
                blob = sb.storage.from_(_OLD_BUCKET).download(old_path)
                sb.storage.from_(_NEW_BUCKET).upload(
                    new_path, blob, {"content-type": "image/jpeg"},
                )
                # Re-apuntar mensajes que usaban la URL pública vieja
                res = (
                    sb.table("messages")
                    .update({"media_url": f"{_SCHEME}{new_path}"})
                    .eq("media_url", old_public_url)
                    .execute()  # tenant_filter:exempt:migracion_one_shot_admin
                )
                n = len(res.data or [])
                report["messages_updated"] += n
                sb.storage.from_(_OLD_BUCKET).remove([old_path])
            report["migrated"] += 1
        except Exception as exc:  # noqa: BLE001 — un objeto fallido no frena el resto
            print(f"  [error] {old_path}: {exc}", file=sys.stderr)
            report["errors"] += 1
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="Ejecuta (default: dry-run)")
    args = ap.parse_args()
    sb = _client()
    report = migrate(sb, apply=args.apply)
    mode = "APLICADO" if args.apply else "DRY-RUN (sin cambios)"
    print(f"\n{mode}: {report}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
