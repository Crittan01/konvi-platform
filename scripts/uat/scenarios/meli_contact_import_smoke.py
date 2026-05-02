"""C1 — Smoke test del MeLi contact import (Bloque 2 rev. 103).

Llama `_upsert_meli_contact` directamente contra la DB real con un buyer
ficticio. Verifica que persiste:
  • Contact con consent_source='marketplace_meli', consent_given=true.
  • consent_evidence con imported_from='mercadolibre' + meli_order_id.
  • consent_audit_log con event='granted' source='system'.

Cleanup: opcionalmente borra el contact + audit fila al final con --cleanup.
Sin cleanup, el contact queda visible en /dashboard/contacts para
inspección visual (badge consent + canal MeLi en evidence).

USO:
  python3.11 scripts/uat/scenarios/meli_contact_import_smoke.py [--cleanup]

Requiere env vars: NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
"""
import argparse
import json
import os
import sys
from pathlib import Path

# Cargar .env de la raíz del repo si python-dotenv está disponible.
REPO = Path(__file__).resolve().parents[3]
env_file = REPO / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        # Strip optional surrounding quotes
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)

# Importar desde services/api (path adjustment, mismo patrón que data_subject_request).
sys.path.insert(0, str(REPO / "services/api"))

from supabase import create_client  # noqa: E402

# Defer import of meli_webhook hasta tener supabase listo.
SUPABASE_URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SERVICE_KEY:
    print("FATAL: faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en env.")
    sys.exit(2)

# Tenant productivo (manager registrado).
TENANT_ID = "0fb0777e-f3e4-48c7-89bf-a25aa201c0c9"

# Buyer ficticio — phone único de test.
BUYER = {
    "first_name": "Carlos",
    "last_name": "MeLi-Test",
    "nickname": "carlos_meli",
    "phone": "5755555550901",
    "billing_info": {"phone": "5755555550901"},
}
MELI_ORDER_ID = "TEST-C1-202605021700"


def main() -> int:
    parser = argparse.ArgumentParser(description="C1 smoke MeLi import")
    parser.add_argument("--cleanup", action="store_true",
                        help="Borrar contact + audit row tras validar")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SERVICE_KEY)
    from routers.meli_webhook import _upsert_meli_contact  # noqa: E402

    # 0. Cleanup defensivo si quedó del run anterior.
    sb.table("contacts").delete().eq("phone", BUYER["phone"]).eq("tenant_id", TENANT_ID).execute()

    print(f"━━━ C1 smoke: simular orden MeLi ━━━")
    print(f"  tenant_id     = {TENANT_ID}")
    print(f"  meli_order_id = {MELI_ORDER_ID}")
    print(f"  phone         = +{BUYER['phone']}")

    contact_id = _upsert_meli_contact(BUYER, TENANT_ID, sb, meli_order_id=MELI_ORDER_ID)
    if not contact_id:
        print("\n❌ FAIL: _upsert_meli_contact devolvió None")
        return 1
    print(f"\n  contact_id    = {contact_id}")

    # 1. Verificar contact persistido.
    contact_res = sb.table("contacts").select("*").eq("id", contact_id).single().execute()
    contact = contact_res.data
    expected_contact = {
        "consent_given": True,
        "consent_source": "marketplace_meli",
        "consent_channel": "marketplace_meli",
    }
    fails = []
    for k, v in expected_contact.items():
        if contact.get(k) != v:
            fails.append(f"contact.{k}={contact.get(k)!r} (esperado {v!r})")

    evidence = contact.get("consent_evidence") or {}
    if evidence.get("imported_from") != "mercadolibre":
        fails.append(f"consent_evidence.imported_from={evidence.get('imported_from')!r}")
    if evidence.get("meli_order_id") != MELI_ORDER_ID:
        fails.append(f"consent_evidence.meli_order_id={evidence.get('meli_order_id')!r}")
    if not contact.get("consent_date"):
        fails.append("consent_date=None")
    if not contact.get("consent_notice_version"):
        fails.append("consent_notice_version=None")

    print("\n━━━ Verificación contacts ━━━")
    print(f"  consent_given            = {contact.get('consent_given')}")
    print(f"  consent_source           = {contact.get('consent_source')}")
    print(f"  consent_channel          = {contact.get('consent_channel')}")
    print(f"  consent_date             = {contact.get('consent_date')}")
    print(f"  consent_notice_version   = {contact.get('consent_notice_version')}")
    print(f"  consent_actor_email      = {contact.get('consent_actor_email')}")
    print(f"  consent_evidence         = {json.dumps(evidence, default=str)}")

    # 2. Verificar audit log.
    audit_res = (
        sb.table("consent_audit_log")
        .select("*")
        .eq("contact_id", contact_id)
        .eq("event", "granted")
        .order("occurred_at", desc=True)
        .limit(5)
        .execute()
    )
    audit_rows = audit_res.data or []

    print("\n━━━ Verificación consent_audit_log ━━━")
    if not audit_rows:
        fails.append("audit log: ninguna fila event='granted' para este contact_id")
    else:
        row = audit_rows[0]
        print(f"  event                    = {row.get('event')}")
        print(f"  source                   = {row.get('source')}")
        print(f"  phone_hash               = {row.get('phone_hash')[:16]}...{row.get('phone_hash')[-8:] if row.get('phone_hash') else ''}")
        print(f"  actor_email              = {row.get('actor_email')}")
        print(f"  evidence                 = {json.dumps(row.get('evidence') or {}, default=str)}")
        if row.get("source") != "system":
            fails.append(f"audit.source={row.get('source')!r} (esperado 'system')")
        if row.get("event") != "granted":
            fails.append(f"audit.event={row.get('event')!r} (esperado 'granted')")
        if not row.get("phone_hash") or len(row.get("phone_hash") or "") != 64:
            fails.append(f"audit.phone_hash inválido (len={len(row.get('phone_hash') or '')})")
        audit_evidence = row.get("evidence") or {}
        if audit_evidence.get("imported_from") != "mercadolibre":
            fails.append(f"audit.evidence.imported_from={audit_evidence.get('imported_from')!r}")
        if audit_evidence.get("meli_order_id") != MELI_ORDER_ID:
            fails.append(f"audit.evidence.meli_order_id={audit_evidence.get('meli_order_id')!r}")

    # 3. Resultado.
    print("\n━━━ Resultado ━━━")
    if fails:
        print(f"❌ FAIL — {len(fails)} aserciones rotas:")
        for f in fails:
            print(f"  · {f}")
        ret = 1
    else:
        print("✅ PASS — contact + audit log persistidos correctamente.")
        ret = 0

    if args.cleanup:
        print("\n━━━ Cleanup ━━━")
        sb.table("consent_audit_log").delete().eq("contact_id", contact_id).execute()
        sb.table("contacts").delete().eq("id", contact_id).execute()
        print(f"  contact y audit borrados.")
    else:
        print(f"\n  (sin cleanup; revisa /dashboard/contacts → +{BUYER['phone']})")
        print(f"  (rerun con --cleanup para limpiar)")

    return ret


if __name__ == "__main__":
    sys.exit(main())
