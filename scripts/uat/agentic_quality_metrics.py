"""Métricas SQL de calidad sobre `agentic_shadow_log` (B-3).

Reporte READ-only de la ventana reciente de turnos agentic: distribución de
modelos, tasa de error, finish_reason dominantes, bloqueos de invariantes,
latencia (avg/p50/p95) y tokens (incl. ratio cached/prompt — mide el implicit
caching de Gemini, insumo de la decisión pendiente de routing por estado).

Uso:
  python3.11 scripts/uat/agentic_quality_metrics.py                 # últimas 24h
  python3.11 scripts/uat/agentic_quality_metrics.py --hours 72
  python3.11 scripts/uat/agentic_quality_metrics.py --tenant-id d0000000-…-0001
  python3.11 scripts/uat/agentic_quality_metrics.py --json          # salida JSON

Credenciales: `.env.local` raíz (NEXT_PUBLIC_SUPABASE_URL + SUPABASE_SECRET_KEY),
mismo patrón que e2e_chat.py (`_load_env` + create_client).

Guard anti-prod (scripts/_env_guard.classify): es READ-only — no aborta por
destino, pero SIEMPRE imprime a qué apunta; si classify dice prod/prelaunch
exige el flag explícito `--prod-ok` (lectura auditable contra PRD).

Diseño: IO separado del cómputo — `compute(rows)` es pura y testeable sin DB
(tests/test_agentic_quality_metrics.py con rows sintéticos). Sin numpy/pandas:
agregaciones a mano (mismo criterio que agentic/observability.py).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
# Consolidación de ambientes (2026-08-14): el env real es .env.local (raíz);
# fallback .env por orden para no romper usos viejos (patrón e2e_chat.py).
for _candidate in (".env.local", ".env"):
    _p = os.path.join(REPO_ROOT, _candidate)
    if os.path.exists(_p):
        ENV_PATH = _p
        break
else:
    ENV_PATH = None

# Columnas reales de agentic_shadow_log que consume el reporte (audit B-3).
SELECT_COLS = (
    "created_at, tenant_id, conversation_id, mode, model_used, error, "
    "finish_reason, invariant_outcome, invariant_name, elapsed_seconds, "
    "total_tokens, prompt_tokens, cached_tokens, thoughts_tokens, truncated"
)
MAX_ROWS = 5000  # tope defensivo — agentic_shadow_log crece rápido en PRD


def _load_env() -> dict:
    """Parseo simple KEY=VALUE del .env.local raíz (patrón e2e_chat.py)."""
    creds: dict = {}
    if not ENV_PATH:
        return creds
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    return creds


def _percentile(sorted_values: list[float], p: float) -> float | None:
    """Percentil simple sobre lista ordenada. p ∈ [0,1] (mismo criterio que
    agentic/observability.py — nearest-rank redondeado)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = max(0, min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def fetch_rows(sb, *, hours: int, tenant_id: str | None = None,
               limit: int = MAX_ROWS) -> list[dict]:
    """IO — lee agentic_shadow_log en la ventana (READ-only)."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    # Analytics: filtra por tenant solo si se pasa --tenant-id; sin él agrega
    # cross-tenant POR DISEÑO (reporte ops de calidad del agentic).
    query = (
        sb.table("agentic_shadow_log")  # tenant_filter:exempt:analytics_optional_tenant_filter
        .select(SELECT_COLS)
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(limit)
    )
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    return query.execute().data or []


def compute(rows: list[dict], *, window_hours: int = 24) -> dict:
    """Cómputo PURO de métricas sobre rows de agentic_shadow_log (testeable).

    Shape estable del resultado:
      turnos, model_used {modelo: n}, errores, error_rate,
      finish_reason_top [[reason, n]…], invariant_blocks {nombre: n},
      elapsed {n, avg, p50, p95},
      tokens {total, prompt, cached, thoughts, cached_ratio, por_dia}.
    """
    n = len(rows)
    model_used: dict[str, int] = {}
    finish_reasons: dict[str, int] = {}
    invariant_blocks: dict[str, int] = {}
    errores = 0
    elapsed: list[float] = []
    tok_total = tok_prompt = tok_cached = tok_thoughts = 0

    for r in rows:
        model_used[r.get("model_used") or "(sin modelo)"] = \
            model_used.get(r.get("model_used") or "(sin modelo)", 0) + 1
        if r.get("error"):
            errores += 1
        fr = r.get("finish_reason")
        if fr:
            finish_reasons[fr] = finish_reasons.get(fr, 0) + 1
        # Bloqueos de invariant por nombre (solo outcome='block'; los 'rewrite'
        # o 'ok' no son bloqueos).
        if (r.get("invariant_outcome") or "") == "block":
            name = r.get("invariant_name") or "(sin nombre)"
            invariant_blocks[name] = invariant_blocks.get(name, 0) + 1
        try:
            if r.get("elapsed_seconds") is not None:
                elapsed.append(float(r["elapsed_seconds"]))
        except (TypeError, ValueError):
            pass
        tok_total += int(r.get("total_tokens") or 0)
        tok_prompt += int(r.get("prompt_tokens") or 0)
        tok_cached += int(r.get("cached_tokens") or 0)
        tok_thoughts += int(r.get("thoughts_tokens") or 0)

    elapsed.sort()
    days = window_hours / 24.0
    return {
        "turnos": n,
        "model_used": dict(sorted(model_used.items(), key=lambda kv: -kv[1])),
        "errores": errores,
        "error_rate": round(errores / n, 4) if n else 0.0,
        "finish_reason_top": sorted(finish_reasons.items(), key=lambda kv: -kv[1])[:5],
        "invariant_blocks": dict(sorted(invariant_blocks.items(), key=lambda kv: -kv[1])),
        "elapsed": {
            "n": len(elapsed),
            "avg": round(sum(elapsed) / len(elapsed), 3) if elapsed else None,
            "p50": _percentile(elapsed, 0.50),
            "p95": _percentile(elapsed, 0.95),
        },
        "tokens": {
            "total": tok_total,
            "prompt": tok_prompt,
            "cached": tok_cached,
            "thoughts": tok_thoughts,
            # Ratio cached/prompt: mide implicit caching de Gemini (decisión
            # pendiente del routing por estado — audit 2026-08-21 §3).
            "cached_ratio": round(tok_cached / tok_prompt, 4) if tok_prompt > 0 else None,
            "por_dia": round(tok_total / days, 1) if days > 0 else tok_total,
        },
    }


def render_text(m: dict, *, hours: int, tenant_id: str | None) -> str:
    """Reporte texto legible; degrada elegante si la ventana está vacía."""
    scope = f"tenant {tenant_id}" if tenant_id else "todos los tenants"
    lines = [f"=== Métricas agentic_shadow_log — últimas {hours}h ({scope}) ==="]
    if m["turnos"] == 0:
        lines.append("Sin filas en la ventana — nada que reportar.")
        return "\n".join(lines)

    lines.append(f"Turnos: {m['turnos']}  ·  errores: {m['errores']} "
                 f"(error_rate {m['error_rate']:.1%})")
    lines.append("")
    lines.append("Modelos usados:")
    for model, cnt in m["model_used"].items():
        lines.append(f"  {model}: {cnt} ({cnt / m['turnos']:.0%})")
    if m["finish_reason_top"]:
        lines.append("")
        lines.append("finish_reason (top 5):")
        for reason, cnt in m["finish_reason_top"]:
            lines.append(f"  {reason}: {cnt}")
    lines.append("")
    if m["invariant_blocks"]:
        lines.append("Bloqueos de invariant (outcome='block'):")
        for name, cnt in m["invariant_blocks"].items():
            lines.append(f"  {name}: {cnt}")
    else:
        lines.append("Bloqueos de invariant: ninguno en la ventana.")
    e = m["elapsed"]
    lines.append("")
    if e["n"]:
        lines.append(f"Latencia (s): avg {e['avg']:.2f} · p50 {e['p50']:.2f} "
                     f"· p95 {e['p95']:.2f}  (n={e['n']})")
    else:
        lines.append("Latencia: sin datos de elapsed_seconds.")
    t = m["tokens"]
    ratio = f"{t['cached_ratio']:.1%}" if t["cached_ratio"] is not None else "-"
    lines.append("")
    lines.append(f"Tokens: total {t['total']:,} · prompt {t['prompt']:,} "
                 f"· cached {t['cached']:,} · thoughts {t['thoughts']:,}")
    lines.append(f"  cached/prompt: {ratio} (implicit caching) "
                 f"· tokens/día: {t['por_dia']:,.0f}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Métricas de calidad sobre agentic_shadow_log (READ-only, B-3)")
    ap.add_argument("--hours", type=int, default=24, help="ventana hacia atrás (default 24h)")
    ap.add_argument("--tenant-id", default=None, help="filtrar por tenant (default: todos)")
    ap.add_argument("--json", action="store_true", help="salida JSON en vez de texto")
    ap.add_argument("--prod-ok", action="store_true",
                    help="permite apuntar a PRD (lectura auditable; classify=prod/prelaunch)")
    args = ap.parse_args(argv)

    creds = _load_env()
    url = creds.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
    key = creds.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        print("ERROR: faltan NEXT_PUBLIC_SUPABASE_URL o SUPABASE_SECRET_KEY "
              "en .env.local / env", file=sys.stderr)
        return 2

    # Guard anti-prod: READ-only → no aborta por defecto, pero el destino se
    # imprime SIEMPRE y prod/prelaunch exige --prod-ok explícito.
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    from _env_guard import classify
    kind = classify(creds)
    print(f"Destino: {kind} — {url}")
    if kind in ("prod", "prelaunch") and not args.prod_ok:
        print("ABORTADO: el destino es PRODUCCIÓN. Este reporte es READ-only, "
              "pero contra PRD exige el flag explícito --prod-ok (lectura auditable).",
              file=sys.stderr)
        return 2

    from supabase import create_client
    sb = create_client(url, key)
    try:
        rows = fetch_rows(sb, hours=args.hours, tenant_id=args.tenant_id)
    except Exception as exc:
        print(f"ERROR consultando agentic_shadow_log: {exc}", file=sys.stderr)
        return 2
    metrics = compute(rows, window_hours=args.hours)
    metrics["window"] = {"hours": args.hours, "tenant_id": args.tenant_id,
                         "destino": kind}
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(render_text(metrics, hours=args.hours, tenant_id=args.tenant_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
