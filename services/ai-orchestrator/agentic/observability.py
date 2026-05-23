"""Métricas de observabilidad del agentic — Rev. 107 deuda #5.

Lee `agentic_shadow_log` y computa ratios que permiten responder:

  • ¿Qué % de turnos agentic completan sin truncar ni errorear?
  • ¿Qué razones dominan los truncados (max_tool_turns vs max_tool_calls)?
  • ¿Qué tools se ejecutan más y cuáles tienen mayor latencia?
  • ¿Cuál es la distribución p50/p95 de elapsed_seconds?

Diseño:
  • Funciones puras read-only sobre supabase — no mutan estado.
  • Soportan filtro por `tenant_id` y `since_hours` (default 24h).
  • Pensadas para invocarse desde:
      - endpoint HTTP `/agentic/metrics` (FastAPI server.py)
      - cron diario que escribe agregados a tabla `agentic_metrics_daily`
      - CLI ops para troubleshooting puntual

NO usa numpy/pandas — agregaciones a mano para mantener dependencias mínimas.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _percentile(sorted_values: list[float], p: float) -> Optional[float]:
    """Percentil simple sobre lista ordenada. p ∈ [0,1]."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = max(0, min(len(sorted_values) - 1, int(round(p * (len(sorted_values) - 1)))))
    return sorted_values[idx]


def compute_agentic_metrics(
    supabase: Any,
    *,
    tenant_id: Optional[str] = None,
    since_hours: int = 24,
    limit: int = 5000,
) -> dict[str, Any]:
    """Agrega métricas del agentic_shadow_log en la ventana indicada.

    Args:
        supabase: cliente Supabase (service-role o tenant-scoped).
        tenant_id: opcional — si se pasa, filtra por tenant.
        since_hours: ventana hacia atrás (default 24h).
        limit: tope de filas a leer (defensivo — agentic_shadow_log puede
            crecer rápido en producción multi-tenant).

    Returns:
        dict con shape estable:
          {
            "window": {"since_hours": int, "from_iso": str, "row_count": int},
            "outcomes": {
              "success_rate": float,        # turnos sin truncar y sin error
              "truncated_rate": float,
              "errored_rate": float,
              "counts": {"success": int, "truncated": int, "errored": int},
            },
            "truncated_reasons": {reason: count},
            "tool_usage": {
              "total_calls": int,
              "avg_calls_per_turn": float,
              "by_name": {tool_name: count},   # top 20
            },
            "latency_seconds": {"p50": float, "p95": float, "max": float},
          }
    """
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    since_iso = since.isoformat()

    query = (
        supabase.table("agentic_shadow_log")
        .select(
            "tenant_id, mode, truncated, truncated_reason, error, "
            "tool_calls_executed, tool_call_log, elapsed_seconds, "
            "finish_reason, invariant_outcome, invariant_name, created_at",
        )
        .gte("created_at", since_iso)
        .limit(limit)
    )
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    rows = (query.execute().data) or []

    row_count = len(rows)
    success = truncated = errored = 0
    truncated_reasons: dict[str, int] = {}
    finish_reasons: dict[str, int] = {}
    invariant_outcomes: dict[str, int] = {}
    by_mode: dict[str, int] = {}
    total_tool_calls = 0
    by_tool_name: dict[str, int] = {}
    latencies: list[float] = []

    for r in rows:
        # Outcome categorization (mutually exclusive: error > truncated > success).
        if r.get("error"):
            errored += 1
        elif r.get("truncated"):
            truncated += 1
            reason = (r.get("truncated_reason") or "unknown").split("(")[0]
            truncated_reasons[reason] = truncated_reasons.get(reason, 0) + 1
        else:
            success += 1

        # Distribuciones de trazabilidad (rev. 107).
        mode = r.get("mode") or "shadow"
        by_mode[mode] = by_mode.get(mode, 0) + 1
        fr = r.get("finish_reason")
        if fr:
            finish_reasons[fr] = finish_reasons.get(fr, 0) + 1
        invo = r.get("invariant_outcome")
        if invo:
            invariant_outcomes[invo] = invariant_outcomes.get(invo, 0) + 1

        total_tool_calls += int(r.get("tool_calls_executed") or 0)
        elapsed = r.get("elapsed_seconds")
        if elapsed is not None:
            try:
                latencies.append(float(elapsed))
            except (TypeError, ValueError):
                pass

        # tool_call_log es JSON serializado (string) en la columna.
        raw_log = r.get("tool_call_log")
        if raw_log:
            try:
                parsed = json.loads(raw_log) if isinstance(raw_log, str) else raw_log
                for entry in parsed if isinstance(parsed, list) else []:
                    # `tool_call_log` rev. 107: cada entry usa key `tool`
                    # (no `name`). El shape histórico de la tabla puede tener
                    # `name`; aceptamos ambos para compat.
                    name = (entry or {}).get("tool") or (entry or {}).get("name")
                    if name:
                        by_tool_name[name] = by_tool_name.get(name, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass

    latencies.sort()
    top_tools = dict(
        sorted(by_tool_name.items(), key=lambda kv: kv[1], reverse=True)[:20],
    )

    def _rate(num: int) -> float:
        return round(num / row_count, 4) if row_count else 0.0

    return {
        "window": {
            "since_hours": since_hours,
            "from_iso": since_iso,
            "row_count": row_count,
            "tenant_id": tenant_id,
        },
        "by_mode": by_mode,
        "outcomes": {
            "success_rate": _rate(success),
            "truncated_rate": _rate(truncated),
            "errored_rate": _rate(errored),
            "counts": {
                "success": success,
                "truncated": truncated,
                "errored": errored,
            },
        },
        "truncated_reasons": truncated_reasons,
        "finish_reasons": finish_reasons,
        "invariant_outcomes": invariant_outcomes,
        "tool_usage": {
            "total_calls": total_tool_calls,
            "avg_calls_per_turn": round(total_tool_calls / row_count, 3)
            if row_count
            else 0.0,
            "by_name": top_tools,
        },
        "latency_seconds": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "max": latencies[-1] if latencies else None,
        },
    }
