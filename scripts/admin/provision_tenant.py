"""F3 activación — provisión ADMIN-controlada de un tenant nuevo (decisión founder: NO signup público).

Crea el usuario auth del owner (si no existe) + invoca el RPC transaccional public.provision_tenant
(tenant + tenant_users owner + subscripción, atómico). El trigger on_tenant_assignment inyecta el
tenant_id al app_metadata del owner → su JWT queda operativo automáticamente.

Uso:
  # crea el usuario auth con ese email + lo hace owner de un tenant nuevo:
  python3.11 scripts/admin/provision_tenant.py --tenant-name "Mi Negocio" --owner-email owner@negocio.co
  # o si el usuario auth YA existe (lo creaste en el dashboard), pasa su id:
  python3.11 scripts/admin/provision_tenant.py --tenant-name "Mi Negocio" --owner-user-id <uuid>
  # plan (default basic) y dry-run:
  python3.11 scripts/admin/provision_tenant.py --tenant-name X --owner-email y@z.co --plan enterprise --dry-run

Requiere env: NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY).

INTERVENCION HUMANA REQUERIDA (onboarding de un tenant nuevo)
  RESPONSABLE: founder/admin.
  PASOS: (1) correr este script con el nombre del negocio + email del owner; (2) entregar al owner la
    contraseña temporal impresa (o el enlace de reset) para que entre y la cambie; (3) el owner captura
    sus credenciales de WhatsApp en Integraciones → WhatsApp (ver F3), Wompi, Aveonline.
  INSUMOS: nombre del negocio, email del owner.
  CRITERIO DE EXITO: el owner entra, ve su dashboard aislado, y puede configurar sus integraciones.
"""
from __future__ import annotations

import argparse
import os
import secrets

from supabase import create_client


def _client():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Falta NEXT_PUBLIC_SUPABASE_URL y/o SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _resolve_owner(sb, *, email: str | None, user_id: str | None, dry_run: bool) -> tuple[str, str | None]:
    """Devuelve (owner_user_id, temp_password|None). Crea el usuario auth si se pasó email y no existe."""
    if user_id:
        return user_id, None
    assert email
    # ¿ya existe? (list_users pagina; para bases chicas basta buscar en la 1ª página).
    try:
        existing = sb.auth.admin.list_users()
        for u in (existing or []):
            if (getattr(u, "email", None) or "").lower() == email.lower():
                print(f"[provision] usuario auth ya existe email={email} id={u.id} — se reusa")
                return u.id, None
    except Exception as exc:  # noqa: BLE001
        print(f"[provision] WARN: no pude listar usuarios ({exc}); intento crear")
    temp_pw = secrets.token_urlsafe(16)
    if dry_run:
        print(f"[DRY-RUN] crearía usuario auth email={email} (password temporal random)")
        return "00000000-0000-0000-0000-000000000000", temp_pw
    created = sb.auth.admin.create_user({
        "email": email,
        "password": temp_pw,
        "email_confirm": True,  # admin-provisioned: confirmado; el owner cambia la contraseña al entrar
    })
    new_user = getattr(created, "user", None) or created
    return new_user.id, temp_pw


def main() -> None:
    ap = argparse.ArgumentParser(description="Provisiona un tenant nuevo (admin-controlado, F3).")
    ap.add_argument("--tenant-name", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--owner-email", help="crea (o reusa) el usuario auth con este email y lo hace owner")
    g.add_argument("--owner-user-id", help="UUID de un usuario auth EXISTENTE para hacer owner")
    ap.add_argument("--plan", default="basic")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sb = _client()
    owner_id, temp_pw = _resolve_owner(sb, email=args.owner_email, user_id=args.owner_user_id, dry_run=args.dry_run)

    if args.dry_run:
        print(f"[DRY-RUN] provision_tenant(name={args.tenant_name!r}, owner={owner_id}, plan={args.plan!r})")
        return

    res = sb.rpc("provision_tenant", {
        "p_tenant_name": args.tenant_name,
        "p_owner_user_id": owner_id,
        "p_plan_code": args.plan,
    }).execute()
    tenant_id = res.data
    print("─" * 60)
    print(f"✅ Tenant provisionado: {args.tenant_name!r}")
    print(f"   tenant_id : {tenant_id}")
    print(f"   owner     : {owner_id}")
    print(f"   plan      : {args.plan}")
    if temp_pw:
        print(f"   ⚠️  Contraseña TEMPORAL del owner (entrégala y pídele cambiarla): {temp_pw}")
    print("─" * 60)
    print("Siguiente paso del owner: entrar → Integraciones → WhatsApp (capturar credenciales de su Meta App),")
    print("Wompi, Aveonline. La máquina multi-tenant ya lo aísla del resto.")


if __name__ == "__main__":
    main()
