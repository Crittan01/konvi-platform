#!/usr/bin/env python3.11
"""
Rev. 79/91 — Conversational E2E master runner.

REFACTORIZADO en rev. 91: cada escenario vive en su propio archivo
self-contained en `scripts/uat/scenarios/sNN_*.py`. Este wrapper solo:
  • Importa las 16 funciones de escenario.
  • Mantiene el CLI `--only N` para subset.
  • Orquesta el cool-down entre escenarios (12s).
  • Renderiza el reporte md/json en docs/reports/rev79_conversation_run.*.

Para ejecutar UN escenario aislado SIN este wrapper:
    python3.11 scripts/uat/scenarios/s06_disordered_data.py [--phone X --tenant-id Y]

El harness compartido vive en `scripts/uat/lib/harness.py`.

Pre-requisitos:
  • Stack local up (connector en :8000).
  • Variables .env: META_APP_SECRET, SUPABASE_*, GEMINI_API_KEY.
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "uat"))

from lib.harness import (  # noqa: E402
    PASS, FAIL, SKIP, ScenarioResult,
    DEFAULT_PHONE, DEFAULT_TENANT_ID, stack_up,
)

# Importar todos los escenarios (cada uno es self-contained).
from scenarios.s01_first_contact import scenario as scenario_1
from scenarios.s02_catalog_query import scenario as scenario_2
from scenarios.s03_kb_citation import scenario as scenario_3
from scenarios.s04_out_of_domain import scenario as scenario_4
from scenarios.s05_photo_request import scenario as scenario_5
from scenarios.s06_disordered_data import scenario as scenario_6
from scenarios.s07_format_canonical import scenario as scenario_7
from scenarios.s08_revoke import scenario as scenario_8
from scenarios.s09_happy_path_full import scenario as scenario_9
from scenarios.s10_cancel_midflow import scenario as scenario_10
from scenarios.s11_human_escalation import scenario as scenario_11
from scenarios.s12_address_conjunto import scenario as scenario_12
from scenarios.s13_multi_product import scenario as scenario_13
from scenarios.s14_change_shipping import scenario as scenario_14
from scenarios.s15_payment_link_delivery import scenario as scenario_15
from scenarios.s16_wompi_approved_simulation import scenario as scenario_16
# Rev. 103 — escenarios SaaS B2B + Habeas Data extendido.
from scenarios.s17_consent_gating_for_unconsented_contact import scenario as scenario_17
from scenarios.s18_meli_contact_inbound_match import scenario as scenario_18
from scenarios.s19_renewed_consent_after_anonymization import scenario as scenario_19
from scenarios.s20_operator_delete_audit_immutable import scenario as scenario_20
from scenarios.s21_form_add_unconsented_operator import scenario as scenario_21
from scenarios.s22_consent_evidence_storage_in_person import scenario as scenario_22
from scenarios.s23_renewals_cap_50 import scenario as scenario_23


SCENARIOS: list[tuple[int, str, Callable]] = [
    (1, "scenario_1_first_contact", scenario_1),
    (2, "scenario_2_catalog_query", scenario_2),
    (3, "scenario_3_kb_citation", scenario_3),
    (4, "scenario_4_out_of_domain", scenario_4),
    (5, "scenario_5_photo_request", scenario_5),
    (6, "scenario_6_disordered_data", scenario_6),
    (7, "scenario_7_format_canonical", scenario_7),
    (8, "scenario_8_revoke", scenario_8),
    (9, "scenario_9_happy_path_full", scenario_9),
    (10, "scenario_10_cancel_midflow", scenario_10),
    (11, "scenario_11_human_escalation", scenario_11),
    (12, "scenario_12_address_conjunto", scenario_12),
    (13, "scenario_13_multi_product", scenario_13),
    (14, "scenario_14_change_shipping", scenario_14),
    (15, "scenario_15_payment_link_delivery", scenario_15),
    (16, "scenario_16_wompi_approved_simulation", scenario_16),
    (17, "scenario_17_consent_gating_unconsented", scenario_17),
    (18, "scenario_18_meli_inbound_match", scenario_18),
    (19, "scenario_19_renewed_consent_after_anonim", scenario_19),
    (20, "scenario_20_operator_delete_audit_immutable", scenario_20),
    (21, "scenario_21_form_add_unconsented", scenario_21),
    (22, "scenario_22_storage_in_person", scenario_22),
    (23, "scenario_23_renewals_cap_50", scenario_23),
]


def run_all(phone: str, tenant_id: str,
            only: list[int] | None) -> list[ScenarioResult]:
    if not stack_up():
        return [ScenarioResult(0, "Stack health", SKIP,
            "Connector :8000 no responde — escenarios skip todos")]
    results: list[ScenarioResult] = []
    for i, name, fn in SCENARIOS:
        if only and i not in only:
            continue
        print(f"\n[{i}] {name} ...", file=sys.stderr)
        try:
            res = fn(phone, tenant_id)
        except Exception as exc:
            res = ScenarioResult(i, name, FAIL,
                f"Excepción: {exc}", error=traceback.format_exc())
        print(f"    → {res.status}: {res.message}", file=sys.stderr)
        results.append(res)
        # Cool-down entre escenarios para que el worker drene la cola y
        # los rate limits del LLM se reseten. Crítico para harness real-LLM.
        time.sleep(12)
    return results


def render_md(results: list[ScenarioResult]) -> str:
    p = sum(1 for r in results if r.status == PASS)
    f = sum(1 for r in results if r.status == FAIL)
    s = sum(1 for r in results if r.status == SKIP)
    icon = {PASS: "✅", FAIL: "❌", SKIP: "⏭️"}
    lines = [
        f"# Rev. 79 — Conversational E2E ({datetime.now(timezone.utc).isoformat(timespec='seconds')})",
        "",
        f"**Resumen**: {p} PASS · {f} FAIL · {s} SKIP",
        "",
        "| # | Escenario | Status | Mensaje |",
        "|---|---|---|---|",
    ]
    for r in results:
        msg = r.message.replace("\n", " ")
        lines.append(f"| {r.number} | {r.name} | {icon[r.status]} {r.status} | {msg} |")
    lines.append("")
    for r in results:
        if r.evidence:
            lines.append(f"\n### S{r.number} — Evidence")
            lines.append("```json")
            import json as _json
            lines.append(_json.dumps(r.evidence, indent=2, ensure_ascii=False, default=str))
            lines.append("```")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default=DEFAULT_PHONE)
    ap.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    ap.add_argument("--only", type=int, nargs="*",
        help="Lista de números de escenarios a correr (default: todos).")
    args = ap.parse_args()
    results = run_all(args.phone, args.tenant_id, args.only)

    md_path = REPO_ROOT / "docs" / "reports" / "rev79_conversation_run.md"
    json_path = md_path.with_suffix(".json")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_md(results), encoding="utf-8")
    import json as _json
    json_path.write_text(
        _json.dumps([asdict(r) for r in results], indent=2,
                    ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print(render_md(results))
    print(f"\nReportes:\n  {md_path}\n  {json_path}", file=sys.stderr)
    fails = sum(1 for r in results if r.status == FAIL)
    return 0 if fails == 0 else fails


if __name__ == "__main__":
    sys.exit(main())
