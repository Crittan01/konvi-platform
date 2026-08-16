#!/usr/bin/env python3.11
"""Filtro de env por servicio — homologación STG↔PRD (fase S7, plan segregación).

En PRD cada servicio Render recibe SOLO sus env vars (render.yaml: `envVars`
por servicio, las `sync: false` se setean en el dashboard de ESE servicio).
En local, históricamente, el Makefile hacía `source .env.local` completo para
los 4 servicios — el "megáfono": todos veían todo, y un var faltante en STG
podía pasar desapercibida (el código cae al default en ambos, pero la paridad
real es que el servicio local vea EXACTAMENTE lo que ve su contraparte PRD).

Este script genera el env file FILTRADO de un servicio:
  • conjunto de keys = el `envVars` de ESE servicio en render.yaml (incluye las
    sync:false — en PRD viven en el dashboard; en STG su valor sale del env-file)
  • valores = SIEMPRE del env-file local (`.env.local` raíz para los 3 servicios
    Python; `apps/web/.env.local` para web) — nunca del `value:` de render.yaml
    (esos apuntan a hosts PRD)
  • fail-closed: si una key de render.yaml no tiene valor en el env-file local,
    ABORTA (exit 1) listando las faltantes — en PRD ese servicio la tendría
    seteada; STG sin ella NO está homologado.
  • las keys del env-file que NO están en el set del servicio quedan fuera
    (silencio: son [SCRIPTS]/[STG] o de otro servicio — ver .env.example).

Uso:
    python3.11 scripts/dev_env_for_service.py api            # → stdout KEY=value
    python3.11 scripts/dev_env_for_service.py web --out .local/env/web.env

Exit: 0 = env file emitido · 1 = faltan keys (lista en stderr) · 2 = uso/archivo.
"""
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RENDER_YAML = REPO_ROOT / "render.yaml"

# servicio lógico → (nombre en render.yaml, env-file local default)
SERVICES = {
    "api": ("konvi-api", ".env.local"),
    "connector": ("konvi-connector", ".env.local"),
    "orchestrator": ("konvi-orchestrator", ".env.local"),
    "web": ("konvi-web", "apps/web/.env.local"),
}

# Vars de infraestructura que la plataforma inyecta fuera de envVars (PORT la
# asigna Render; local la fija el Makefile por --port). No se exigen ni se filtran.
_PLATFORM_PROVIDED = {"PORT"}

# Vars que la toolchain del web fija sola (next dev/build fuerza NODE_ENV;
# el flag de corepack solo aplica al buildpack de Render). No homologables por
# env file — se excluyen del set esperado de konvi-web.
_WEB_TOOLCHAIN = {"NODE_ENV", "COREPACK_ENABLE_DOWNLOAD_PROMPT"}

# ANCLADAS DE AMBIENTE: su valor de PRD en render.yaml NO debe heredarse jamás
# en STG (apuntarían a hosts prod o activarían comportamiento de prod). Deben
# venir del env-file local; ausencia = fail-closed.
_ENV_ANCHORED = {
    "APP_URL", "NEXT_PUBLIC_APP_URL", "API_URL", "PUBLIC_WEBHOOK_URL",
    "APP_ENV", "SENTRY_ENV",
    # Switch maestro de guías reales: en PRD es "true" (B1). Heredarlo en STG
    # dejaría la compuerta global ABIERTA en el ambiente de pruebas — el valor
    # local correcto es siempre false explícito.
    "AVEONLINE_GENERATE_REAL_GUIDES",
}

# DELTA STG DOCUMENTADO: sync:false en render.yaml (secretos de dashboard) que
# en STG legítimamente quedan vacíos hasta que su fase del plan se ejecute.
# Cada entrada está justificada — NO agregar más sin documentar la razón.
_STG_DELTA_OK = {
    # Sentry apagado en STG (sin DSN no hay reporting; los NEXT_PUBLIC_SENTRY_*
    # y ORG/PROJECT con value: se heredan pero son inertes sin DSN).
    "SENTRY_DSN", "SENTRY_AUTH_TOKEN",
    "NEXT_PUBLIC_SENTRY_DSN", "NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE", "NEXT_PUBLIC_SENTRY_ENV",
    # Providers LLM de fallback no usados en STG (Gemini es el primario).
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    # MeLi STG: pendiente fase S6 (app de prueba). MELI_WEBHOOK_ALLOWED_IPS
    # tiene default en código (meli_webhook.py) — el env es solo override.
    "MELI_CLIENT_ID", "MELI_CLIENT_SECRET", "MELI_REDIRECT_URI", "MELI_AUTH_URL",
    "MELI_OAUTH_STATE_SECRET", "MELI_WEBHOOK_ALLOWED_IPS",
    # Telegram STG: pendiente fase S5 (bot de prueba).
    "TELEGRAM_WEBHOOK_SECRET",
    # Anti-hibernación: obsoleto en plan Starter (PRD también lo tiene off).
    "ANTI_HIBERNATION_PING_URL",
    # MFA obligatorio: A1 sin flip — START solo tiene sentido con ENABLED=true.
    "MFA_MANDATORY_START",
}


def service_spec(render_service: str) -> list[tuple[str, str | None]]:
    """[(key, value|None)] del `envVars` del servicio en render.yaml.

    value=None significa sync:false (el valor vive en el dashboard de Render;
    en STG debe salir del env-file local o del delta documentado).
    """
    doc = yaml.safe_load(RENDER_YAML.read_text())
    for svc in doc.get("services", []):
        if svc.get("name") == render_service:
            return [
                (v["key"], v.get("value"))
                for v in svc.get("envVars", [])
                if "key" in v
            ]
    raise KeyError(f"servicio {render_service} no encontrado en render.yaml")


def load_env_file(path: Path) -> dict[str, str]:
    """Parsea un .env a dict (sin tocar os.environ). Tolera comentarios/comillas."""
    creds: dict[str, str] = {}
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds


def build_service_env(service: str, env_file: Path) -> tuple[dict[str, str], list[str], list[str]]:
    """Retorna (env filtrado, faltantes fail-closed, heredados de render.yaml).

    Precedencia por key del servicio en render.yaml:
      1. valor del env-file local (si viene) — siempre gana;
      2. ancladas de ambiente sin valor local → FALTANTE (nunca heredar PRD);
      3. sync:false sin valor local → delta documentado (_STG_DELTA_OK) u omisión;
      4. value: de render.yaml → se HEREDA (tuning idéntico a PRD — homologación).
    """
    render_name, _ = SERVICES[service]
    spec = service_spec(render_name)
    local = load_env_file(env_file)
    env: dict[str, str] = {}
    missing: list[str] = []
    inherited: list[str] = []
    for key, render_value in spec:
        if key in _PLATFORM_PROVIDED or (service == "web" and key in _WEB_TOOLCHAIN):
            continue
        local_value = local.get(key, "")
        if local_value != "":
            env[key] = local_value
        elif key in _ENV_ANCHORED:
            missing.append(key)
        elif render_value is None:
            if key not in _STG_DELTA_OK:
                missing.append(key)
            # delta documentado: ausente en STG a propósito
        else:
            env[key] = render_value
            inherited.append(key)
    return env, missing, inherited


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("service", choices=sorted(SERVICES), help="servicio lógico (api|connector|orchestrator|web)")
    ap.add_argument("--env-file", default="", help="override del env-file local (default: el canónico del servicio)")
    ap.add_argument("--out", default="", help="escribir a archivo en vez de stdout")
    args = ap.parse_args()

    env_file = Path(args.env_file) if args.env_file else REPO_ROOT / SERVICES[args.service][1]
    if not env_file.exists():
        print(f"ABORTADO: no existe {env_file}", file=sys.stderr)
        return 2

    try:
        env, missing, inherited = build_service_env(args.service, env_file)
    except KeyError as e:
        print(f"ABORTADO: {e}", file=sys.stderr)
        return 2

    if missing:
        print(
            f"ABORTADO: {env_file.name} no tiene valores para {len(missing)} var(s) que "
            f"{SERVICES[args.service][0]} sí recibe en PRD (render.yaml):\n  "
            + "\n  ".join(missing)
            + "\nSTG no estaría homologado — agrega el valor STG al env-file.",
            file=sys.stderr,
        )
        return 1

    # shlex.quote: los valores con espacios/especiales (p.ej. RESEND_FROM_EMAIL=
    # "Konvi <onboarding@resend.dev>") rompen `source` si se emiten crudos —
    # bug detectado en la primera certificación live S7.
    body = "".join(f"{k}={shlex.quote(v)}\n" for k, v in env.items())
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body)
        print(
            f"{args.service}: {len(env)} vars → {out} "
            f"({len(inherited)} heredadas de render.yaml = tuning PRD)",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
