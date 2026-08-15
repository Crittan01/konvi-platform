#!/usr/bin/env python3.11
"""F2 — Reorganiza los .env reales por secciones de proveedor (sin mostrar valores).

Lee cada .env real, agrupa sus KEY=VALUE por la sección del proveedor (mapa del
.env.example canónico), ELIMINA las vars marcadas [ELIMINAR] (0 usos en código,
verificado 2026-08-14) y los reescribe con comentarios de sección. Hace backup
previo (<archivo>.bak-f2). NUNCA imprime valores — solo conteos.
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

FILES = [
    REPO / ".env",
    REPO / ".env.prod",
    REPO / "apps" / "web" / ".env.local",
    REPO / "apps" / "web" / ".env.local.prod",
]

# Vars muertas (0 usos en código, verificado 2026-08-14) → se eliminan de TODOS.
DEAD = {
    "META_APP_SECRET", "META_VERIFY_TOKEN",
    "CUSTOMER_CONTEXT_ENABLED", "CUSTOMER_CONTEXT_MODE",
    "USE_NEW_ORCHESTRATOR", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "CART_RECOVERY_ENABLED", "CART_RECOVERY_LOOKBACK_DAYS",
}

# Orden de secciones + a qué sección va cada prefijo/var (mapa del .env.example).
SECTION_ORDER = [
    "Supabase", "Supabase Auth/JWT (legacy)", "Interno", "LLM", "Resend",
    "Mercado Libre", "Aveonline", "Wompi", "Telegram", "WhatsApp / Meta",
    "Seguridad / MFA", "Sentry", "Feature flags / tuning", "Dev local", "Scripts / operación",
]

def section_of(key: str) -> str:
    if key.startswith(("NEXT_PUBLIC_SUPABASE", "DATABASE_URL")):
        return "Supabase"
    if key in ("SUPABASE_SECRET_KEY", "SUPABASE_PROJECT_REF", "SUPABASE_DB_PASSWORD"):
        return "Supabase"
    if key.startswith(("SUPABASE_SERVICE_ROLE", "SUPABASE_JWT")):
        return "Supabase Auth/JWT (legacy)"
    if key.startswith(("INTERNAL_SERVICE", "API_URL", "APP_URL", "NEXT_PUBLIC_APP_URL", "PUBLIC_WEBHOOK_URL", "CONNECTOR_URL", "ORCHESTRATOR_URL", "NEXT_PUBLIC_CONNECTOR", "NEXT_PUBLIC_WEBHOOK", "NEXT_PUBLIC_API_URL")):
        return "Interno"
    if key.startswith(("GEMINI", "AGENTIC", "OPENAI", "ANTHROPIC", "LLM_", "WHISPER", "MULTIMODAL", "EMBEDDING_", "CATALOG_", "MAX_CATALOG", "MAX_VARIANTS", "CASE_D")):
        return "LLM"
    if key.startswith("RESEND"):
        return "Resend"
    if key.startswith("MELI"):
        return "Mercado Libre"
    if key.startswith("AVEONLINE"):
        return "Aveonline"
    if key.startswith("WOMPI"):
        return "Wompi"
    if key.startswith("TELEGRAM"):
        return "Telegram"
    if key.startswith(("META_", "WHATSAPP", "INBOX_MEDIA", "WA_")):
        return "WhatsApp / Meta"
    if key.startswith(("MFA_", "MAX_REQUEST_BODY", "ALLOWED_ORIGINS", "TRUSTED_CLIENT", "XFF_")):
        return "Seguridad / MFA"
    if key.startswith(("SENTRY", "NEXT_PUBLIC_SENTRY")):
        return "Sentry"
    if key.startswith("NGROK"):
        return "Dev local"
    if key.startswith(("RENDER", "DEBUG_", "KONVI_")) or key.startswith("WOMPI_"):
        return "Scripts / operación"
    return "Feature flags / tuning"


def reorganize(path: Path) -> dict:
    if not path.exists():
        return {"archivo": str(path), "estado": "no existe"}
    shutil.copy(path, str(path) + ".bak-f2")
    sections: dict[str, list[str]] = {s: [] for s in SECTION_ORDER}
    removed: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key in DEAD:
            removed.append(key)
            continue
        sections[section_of(key)].append(raw)
    out = ["# Reorganizado por scripts/_reorg_env_f2.py (F2) — secciones del .env.example canónico.",
           "# Valores preservados; vars muertas eliminadas (ver sección [ELIMINAR] del contrato).", ""]
    for sec in SECTION_ORDER:
        if sections[sec]:
            out.append(f"## {sec}")
            out.extend(sections[sec])
            out.append("")
    path.write_text("\n".join(out) + "\n")
    total = sum(len(v) for v in sections.values())
    return {"archivo": path.name, "vars": total, "eliminadas": removed}


def main() -> int:
    print("F2 — reorganización de .env reales (sin mostrar valores)")
    for f in FILES:
        r = reorganize(f)
        print(f"  {r}")
    print("\nBackups creados como <archivo>.bak-f2 (revisar antes de borrar).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
