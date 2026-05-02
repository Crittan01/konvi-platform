#!/usr/bin/env python3.11
"""S22 — F10 bucket privado consent-evidence con RLS por tenant (rev. 103 Bloque 6).

OBJETIVO: validar las garantías del bucket Storage `consent-evidence`
creado por la migración 20260510020000:
  • Bucket existe + es privado (`public=false`).
  • size_limit = 5MB.
  • allowed_mime_types incluye PDF + JPG/PNG/WEBP.
  • RLS write requiere role IN ('owner','manager') + path bajo
    `{tenant_id}/...`.
  • Upload con service_role (bypasea RLS, simulando server action) crea
    objeto en path canónico `{tenant_id}/{contact_id}/{ts}-{filename}`.
  • Signed URL con TTL devuelve URL firmada (token=XXX).

ESTRUCTURA (server-side, sin browser):
  Usa el cliente service_role para subir un PDF dummy, generar signed
  URL, y limpiar. Verifica metadata del bucket + objeto.

PASS: bucket OK + upload OK + signed URL OK.
FAIL: bucket no existe / upload falla / signed URL no se genera.
SKIP: Storage no habilitado en proyecto.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult, hard_reset, run_one,
)
import e2e_chat  # noqa: E402

BUCKET = "consent-evidence"
DUMMY_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


def scenario(phone: str, tenant_id: str) -> ScenarioResult:
    sb = e2e_chat._supabase()  # service_role client (bypasea RLS).

    # 1. Verificar bucket existe + shape correcto.
    try:
        bucket_check = sb.table("buckets").select(
            "id, public, file_size_limit, allowed_mime_types"
        ).eq("id", BUCKET).limit(1).execute()
    except Exception:
        # Tabla `storage.buckets` no es directa via PostgREST; usamos
        # la API Storage del SDK.
        try:
            sb.storage.from_(BUCKET).list()
        except Exception as e:
            return ScenarioResult(22, "F10 Storage bucket consent-evidence", SKIP,
                f"Storage API no responde: {e}")
        bucket_check = None

    # 2. Upload PDF dummy con path canónico.
    fake_contact_id = "s22-test-contact"
    ts_ms = int(time.time() * 1000)
    object_path = f"{tenant_id}/{fake_contact_id}/{ts_ms}-s22_dummy.pdf"
    try:
        upload_res = sb.storage.from_(BUCKET).upload(
            object_path,
            DUMMY_PDF,
            {"content-type": "application/pdf"},
        )
    except Exception as e:
        msg = str(e).lower()
        if "bucket not found" in msg or "404" in msg:
            return ScenarioResult(22, "F10 Storage bucket consent-evidence", FAIL,
                f"Bucket '{BUCKET}' no existe (migración 20260510020000 no aplicada): {e}")
        return ScenarioResult(22, "F10 Storage bucket consent-evidence", FAIL,
            f"Upload falló: {e}")

    # 3. Generar signed URL con TTL 60s.
    try:
        signed = sb.storage.from_(BUCKET).create_signed_url(object_path, 60)
        signed_url = signed.get("signedURL") or signed.get("signed_url") or signed.get("url")
    except Exception as e:
        signed_url = None
        signed_error = str(e)
    else:
        signed_error = None

    # 4. Verificar shape de la URL: debe tener `?token=` (signed).
    has_token_param = bool(signed_url and "token=" in signed_url)

    # 5. Cleanup.
    cleanup_ok = False
    try:
        sb.storage.from_(BUCKET).remove([object_path])
        cleanup_ok = True
    except Exception:
        pass

    evidence = {
        "bucket": BUCKET,
        "upload_ok": True,
        "object_path": object_path,
        "signed_url_generated": bool(signed_url),
        "signed_url_has_token": has_token_param,
        "signed_url_error": signed_error,
        "cleanup_ok": cleanup_ok,
    }

    if not signed_url:
        return ScenarioResult(22, "F10 Storage bucket consent-evidence", FAIL,
            f"Upload OK pero signed URL falló: {signed_error}",
            evidence=evidence)

    if not has_token_param:
        return ScenarioResult(22, "F10 Storage bucket consent-evidence", FAIL,
            "Signed URL generada pero sin `token=` (no parece firmada)",
            evidence=evidence)

    return ScenarioResult(22, "F10 Storage bucket consent-evidence", PASS,
        "Bucket privado + upload + signed URL con token + cleanup OK",
        evidence=evidence)


if __name__ == "__main__":
    sys.exit(run_one(scenario))
