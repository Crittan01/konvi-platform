"""F3 activación — provisión ADMIN-controlada de un tenant nuevo (decisión founder: NO signup público).

Crea el usuario auth del owner (si no existe) + invoca el RPC transaccional public.provision_tenant
(tenant + tenant_users owner + subscripción, atómico). El owner queda operativo automáticamente: el
`custom_access_token_hook` (SECURITY DEFINER) inyecta `tenant_id` al access token en cada emisión de JWT
—NO hay ya trigger `on_tenant_assignment` (eliminado en 20260426080000_drop_tenant_assignment_trigger.sql).

Uso:
  # crea el usuario auth con ese email + lo hace owner de un tenant nuevo:
  python3.11 scripts/admin/provision_tenant.py --tenant-name "Mi Negocio" --owner-email owner@negocio.co
  # o si el usuario auth YA existe (lo creaste en el dashboard), pasa su id:
  python3.11 scripts/admin/provision_tenant.py --tenant-name "Mi Negocio" --owner-user-id <uuid>
  # plan (default basic) y dry-run:
  python3.11 scripts/admin/provision_tenant.py --tenant-name X --owner-email y@z.co --plan enterprise --dry-run
  # entregar un enlace de recuperación (recomendado) en vez de una contraseña temporal en stdout:
  python3.11 scripts/admin/provision_tenant.py --tenant-name X --owner-email y@z.co --reset-link
  # registrar QUIÉN provisionó (audit trail en public.audit_log):
  python3.11 scripts/admin/provision_tenant.py --tenant-name X --owner-email y@z.co --actor-email founder@konvi.co

Requiere env: NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY (o SUPABASE_SERVICE_ROLE_KEY).

IDEMPOTENCIA / SEGURIDAD:
  - Si el owner YA es owner activo de algún tenant, el script ABORTA por defecto (evita crear un 2º tenant
    y dejar el JWT nondeterminístico: `custom_access_token_hook` hace SELECT ... LIMIT 1). Forzar con
    `--allow-multi-tenant` sólo si el negocio realmente maneja varias marcas y aceptás que el tenant que
    cae al JWT es no determinístico.
  - Nombre de tenant duplicado: aborta salvo `--allow-duplicate-name` (tenants.name no tiene UNIQUE).

INTERVENCION HUMANA REQUERIDA (onboarding de un tenant nuevo)
  RESPONSABLE: founder/admin.
  PASOS: (1) correr este script con el nombre del negocio + email del owner (idealmente `--reset-link`
    para no exponer contraseñas en stdout, y `--actor-email` para trazabilidad); (2) entregar al owner el
    enlace de recuperación (o la contraseña temporal) para que entre y la cambie; (3) el owner captura sus
    credenciales por integración siguiendo el checklist que imprime este script (WhatsApp Model B 6 campos,
    Wompi, Aveonline). Guía tenant: docs/onboarding/whatsapp-tenant-setup.md · Runbook interno:
    docs/operations/onboarding-tenants.md.
  INSUMOS: nombre del negocio, email del owner.
  CRITERIO DE EXITO: el owner entra, ve su dashboard aislado, y puede configurar sus integraciones.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets

from supabase import create_client

ALLOWED_PLANS = ("basic", "pro", "enterprise")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _client():
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("Falta NEXT_PUBLIC_SUPABASE_URL y/o SUPABASE_SECRET_KEY / SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, key)


def _iter_all_users(sb):
    """Itera TODOS los usuarios auth paginando (list_users trae 1 página de ~50).

    El código previo sólo miraba la 1ª página → con >50 usuarios auth un email existente no se encontraba
    y create_user reventaba con 'already exists'. Aquí paginamos hasta agotar.
    """
    page = 1
    while True:
        batch = sb.auth.admin.list_users(page=page, per_page=200)
        # supabase-py puede devolver una lista o un objeto con .users según versión.
        users = getattr(batch, "users", None)
        if users is None:
            users = batch if isinstance(batch, list) else []
        if not users:
            return
        yield from users
        if len(users) < 200:
            return
        page += 1


def _find_user_by_email(sb, email: str):
    target = email.lower()
    for u in _iter_all_users(sb):
        if (getattr(u, "email", None) or "").lower() == target:
            return u
    return None


def _resolve_owner(
    sb, *, email: str | None, user_id: str | None, dry_run: bool, reset_link: bool
) -> tuple[str, str | None, str | None]:
    """Devuelve (owner_user_id, temp_password|None, recovery_link|None).

    Crea el usuario auth si se pasó email y no existe. Con `reset_link=True` NO imprime contraseña:
    genera un enlace de recuperación (Supabase) que el owner usa para fijar su propia contraseña.
    """
    if user_id:
        return user_id, None, None
    assert email
    existing = None
    try:
        existing = _find_user_by_email(sb, email)
    except Exception as exc:  # noqa: BLE001
        print(f"[provision] WARN: no pude listar usuarios ({exc}); intento crear")
    if existing is not None:
        print(f"[provision] usuario auth ya existe email={email} id={existing.id} — se reusa")
        if reset_link and not dry_run:
            link = _recovery_link(sb, email)
            return existing.id, None, link
        return existing.id, None, None

    if dry_run:
        print(f"[DRY-RUN] crearía usuario auth email={email}"
              f" ({'enlace de recuperación' if reset_link else 'contraseña temporal random'})")
        return "00000000-0000-0000-0000-000000000000", (None if reset_link else "<dry-run>"), None

    # Usuario nuevo: creamos con contraseña random fuerte (nunca se entrega si reset_link).
    temp_pw = secrets.token_urlsafe(24)
    created = sb.auth.admin.create_user({
        "email": email,
        "password": temp_pw,
        "email_confirm": True,  # admin-provisioned: confirmado; el owner cambia la contraseña al entrar
    })
    new_user = getattr(created, "user", None) or created
    if reset_link:
        link = _recovery_link(sb, email)
        return new_user.id, None, link
    return new_user.id, temp_pw, None


def _recovery_link(sb, email: str) -> str | None:
    """Genera un enlace de recuperación para que el owner fije su propia contraseña (no exponer secretos)."""
    try:
        res = sb.auth.admin.generate_link({"type": "recovery", "email": email})
    except Exception as exc:  # noqa: BLE001
        print(f"[provision] WARN: no pude generar enlace de recuperación ({exc}); usá el flujo 'Olvidé mi contraseña'")
        return None
    props = getattr(res, "properties", None) or (res.get("properties") if isinstance(res, dict) else None)
    if props is None:
        return getattr(res, "action_link", None)
    return getattr(props, "action_link", None) or (props.get("action_link") if isinstance(props, dict) else None)


def _owner_already_has_tenant(sb, owner_id: str) -> str | None:
    """Devuelve un tenant_id si el owner YA es owner activo de algún tenant, si no None.

    tenant_users.status puede no existir en esquemas viejos; el filtro por status se hace best-effort.
    """
    q = sb.table("tenant_users").select("tenant_id").eq("user_id", owner_id).eq("role", "owner")
    try:
        rows = q.eq("status", "active").execute().data
    except Exception:  # noqa: BLE001 — columna status ausente o filtro no soportado
        rows = q.execute().data
    if rows:
        return rows[0]["tenant_id"]
    return None


def _tenant_name_exists(sb, name: str) -> bool:
    rows = sb.table("tenants").select("id").eq("name", name.strip()).limit(1).execute().data
    return bool(rows)


def _write_audit(sb, *, tenant_id: str, owner_id: str, actor_email: str | None, plan: str, name: str) -> None:
    """Audit trail: quién provisionó qué y cuándo (public.audit_log). Best-effort — no rompe la provisión.

    service_role bypassa RLS, por eso escribimos directo. actor = quien corre el script (--actor-email).
    """
    try:
        sb.table("audit_log").insert({
            "tenant_id": tenant_id,
            "user_email": actor_email,
            "action": "tenant.provisioned",
            "entity_type": "tenant",
            "entity_id": tenant_id,
            "payload": {"owner_user_id": owner_id, "plan_code": plan, "tenant_name": name,
                        "via": "scripts/admin/provision_tenant.py"},
        }).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[provision] WARN: no pude escribir audit_log ({exc}); continúo")


def _print_credential_checklist(tenant_id: str) -> None:
    print("\nChecklist de credenciales por integración (el owner las captura desde su dashboard):")
    print("  WhatsApp (ADR-0023 Model B — SU PROPIA Meta App, 6 campos):")
    print("    [ ] app_id            (Meta App del tenant)")
    print("    [ ] app_secret        → Vault (HMAC del webhook)")
    print("    [ ] verify_token      (handshake GET del webhook; lo elige el tenant)")
    print("    [ ] phone_number_id")
    print("    [ ] waba_id")
    print("    [ ] access_token      (System User, never-expires) → Vault")
    print(f"    [ ] webhook en Meta App → URL per-tenant .../api/v1/whatsapp/webhook/{tenant_id}")
    print("        (la URL exacta la muestra el panel; el host lo define WHATSAPP_CONNECTOR_URL)")
    print("  Wompi:     [ ] private_key   [ ] events_key   [ ] webhook .../api/v1/webhooks/wompi")
    print("  Aveonline: [ ] credenciales carrier + origen de despacho")
    print("  Catálogo:  [ ] productos cargados   Agente IA: [ ] prompt + activo")
    print("  Guía tenant: docs/onboarding/whatsapp-tenant-setup.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Provisiona un tenant nuevo (admin-controlado, F3).")
    ap.add_argument("--tenant-name", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--owner-email", help="crea (o reusa) el usuario auth con este email y lo hace owner")
    g.add_argument("--owner-user-id", help="UUID de un usuario auth EXISTENTE para hacer owner")
    ap.add_argument("--plan", default="basic", choices=ALLOWED_PLANS)
    ap.add_argument("--reset-link", action="store_true",
                    help="entrega un enlace de recuperación en vez de imprimir una contraseña temporal")
    ap.add_argument("--actor-email", help="email de quien corre el onboarding (audit trail en audit_log)")
    ap.add_argument("--allow-multi-tenant", action="store_true",
                    help="[DEPRECADO — ADR-0030] membresía single-tenant es política; este flag hard-falla")
    ap.add_argument("--allow-duplicate-name", action="store_true",
                    help="permite un nombre de tenant ya existente (tenants.name no es UNIQUE)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    # ADR-0030: membresía single-tenant es política (UNIQUE(user_id) en
    # tenant_users, migración 20260704156200). El escape hatch --allow-multi-tenant
    # contradice esa política: crear una 2ª membresía dejaría el JWT no
    # determinístico Y bloquearía el apply de la migración F6 (su guard aborta si
    # hay duplicados). Se hard-falla en vez de silenciosamente permitir el drift.
    if args.allow_multi_tenant:
        raise SystemExit(
            "--allow-multi-tenant está deshabilitado por ADR-0030 (membresía "
            "single-tenant). Un usuario auth = un solo tenant. Si necesitás que "
            "opere en otro tenant, usá un usuario distinto. Ver docs/adr/"
            "0030-single-tenant-membership.md.")

    name = args.tenant_name.strip()
    if not name:
        raise SystemExit("--tenant-name no puede estar vacío")
    if args.owner_email and not _EMAIL_RE.match(args.owner_email):
        raise SystemExit(f"--owner-email inválido: {args.owner_email!r}")

    sb = _client()

    # Guard de nombre duplicado (best-effort; no bloquea si falla el lookup).
    if not args.dry_run and not args.allow_duplicate_name:
        try:
            if _tenant_name_exists(sb, name):
                raise SystemExit(
                    f"Ya existe un tenant con name={name!r}. Usá --allow-duplicate-name si es intencional.")
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"[provision] WARN: no pude verificar nombre duplicado ({exc}); continúo")

    owner_id, temp_pw, recovery_link = _resolve_owner(
        sb, email=args.owner_email, user_id=args.owner_user_id, dry_run=args.dry_run, reset_link=args.reset_link)

    # ADR-0030: membresía single-tenant. Guard SIEMPRE activo (no bypassable):
    # un usuario auth pertenece a un solo tenant. Coincide con UNIQUE(user_id) de
    # la migración 156200 y evita el JWT no determinístico
    # (custom_access_token_hook SELECT ... LIMIT 1).
    if not args.dry_run:
        try:
            existing_tid = _owner_already_has_tenant(sb, owner_id)
        except Exception as exc:  # noqa: BLE001
            existing_tid = None
            print(f"[provision] WARN: no pude verificar membresías previas del owner ({exc}); continúo")
        if existing_tid:
            raise SystemExit(
                f"El owner {owner_id} YA es miembro del tenant {existing_tid}. Membresía single-tenant "
                f"es política (ADR-0030): un usuario auth = un solo tenant. Usá un usuario distinto para "
                f"otro tenant.")

    if args.dry_run:
        print(f"[DRY-RUN] provision_tenant(name={name!r}, owner={owner_id}, plan={args.plan!r})")
        _print_credential_checklist("<tenant_id>")
        return

    res = sb.rpc("provision_tenant", {
        "p_tenant_name": name,
        "p_owner_user_id": owner_id,
        "p_plan_code": args.plan,
    }).execute()
    tenant_id = res.data

    # Stamp app_metadata.tenant_id + role en el registro auth del owner. El dashboard
    # (apps/web utils/supabase/cached-user.ts) lee getUser().app_metadata — que devuelve
    # raw_app_meta_data (registro DB), NO los claims que custom_access_token_hook inyecta
    # al token. Sin este stamp el owner ve "no tienda asignada" pese a tener la membresía
    # activa (el tenant se crea pero el owner no es usable en la consola). Los owners
    # reales YA están estampados; esto lo hace parte del flujo canónico de provisioning.
    sb.auth.admin.update_user_by_id(
        owner_id, {"app_metadata": {"tenant_id": tenant_id, "role": "owner"}})

    _write_audit(sb, tenant_id=tenant_id, owner_id=owner_id, actor_email=args.actor_email,
                 plan=args.plan, name=name)

    print("─" * 60)
    print(f"✅ Tenant provisionado: {name!r}")
    print(f"   tenant_id : {tenant_id}")
    print(f"   owner     : {owner_id}")
    print(f"   plan      : {args.plan}")
    if recovery_link:
        print("   🔗 Enlace de recuperación (entregáselo al owner; caduca según config Supabase Auth):")
        print(f"      {recovery_link}")
        print("      El owner fija su propia contraseña al abrirlo (no se expuso ningún secreto en stdout).")
    elif temp_pw:
        print(f"   ⚠️  Contraseña TEMPORAL del owner (entrégala y pídele cambiarla en primer login): {temp_pw}")
        print("      Recomendado: correr con --reset-link para no exponer contraseñas en stdout.")
    print("─" * 60)
    _print_credential_checklist(tenant_id)
    print("\nLa máquina multi-tenant ya lo aísla del resto. Verificación: el owner entra, ve su dashboard,")
    print("y ejecuta el checklist de integraciones de arriba. Runbook: docs/operations/onboarding-tenants.md")


if __name__ == "__main__":
    main()
