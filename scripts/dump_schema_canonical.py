#!/usr/bin/env python3.11
"""
Dump canonical schema desde DB live → JSON fixture.

Rev. 72 — fuente de verdad documental para los tests de coherencia y el doc
`.context/07-schema-canonical.md`. NO depende de las migraciones (que son
history reproducible, no spec).

Uso:
    python3.11 scripts/dump_schema_canonical.py [--out PATH] [--diff]

Si --diff: compara el output actual contra el fixture y reporta diferencias
(útil en CI / pre-deploy para detectar drift inesperado).

Requiere `supabase db query --linked` configurado (auth + project linked).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO / "tests" / "fixtures" / "db_schema_canonical.json"

# Tablas que el plan considera "core" — cambios aquí siempre deben revisarse.
CORE_TABLES = [
    "tenants",
    "ai_agents",
    "kb_documents",
    "contacts",
    "conversations",
    "messages",
    "conversation_carts",       # ADR-0026 cart-as-SoT (faltaba en el fixture)
    "conversation_cart_items",  # ADR-0026 cart-as-SoT
    "products",
    "product_variations",
    "product_categories",       # ADR-0027 Pieza 1 categorías per-tenant (faltaba)
    "stock_movements",
    "stock_reservations",
    "orders",
    "order_items",
    "payments",
    "claims",
    "shipments",
    "order_tracking",
    "marketplace_listings",
    "tenant_integrations",
    "notification_settings",
    "suppliers",
    "purchase_orders",
    "purchase_order_items",
    "expenses",
    "coupons",                  # F2.2 router coupons — escrituras auditadas
    "coupon_redemptions",       # F2.2 — DELETE condicional verifica este conteo
    "product_attribute_definitions",  # ADR-0029 F1 — contrato de atributos per-tenant (capa VIVA)
    "audit_log",
    "bot_source_log",
]

DUMP_SQL_TEMPLATE = """
SELECT jsonb_build_object(
  'tables', (
    SELECT jsonb_agg(t ORDER BY t.table_name)
    FROM (
      SELECT
        c.table_name,
        (SELECT count(*) FROM information_schema.columns c2
          WHERE c2.table_schema='public' AND c2.table_name = c.table_name) AS column_count,
        (
          SELECT jsonb_agg(
            jsonb_build_object(
              'col', column_name,
              'type', data_type,
              'nullable', is_nullable,
              'default', column_default
            ) ORDER BY ordinal_position
          )
          FROM information_schema.columns c3
          WHERE c3.table_schema='public' AND c3.table_name = c.table_name
        ) AS columns
      FROM information_schema.columns c
      WHERE c.table_schema='public'
        AND c.table_name = ANY(ARRAY[{tables_list}])
      GROUP BY c.table_name
    ) t
  )
) AS dump;
"""


def _format_sql(tables: list[str]) -> str:
    quoted = ", ".join(f"'{t}'" for t in tables)
    return DUMP_SQL_TEMPLATE.format(tables_list=quoted)


def _run_sql(sql: str) -> dict:
    """Ejecuta SQL via supabase CLI y retorna el JSON dump."""
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write(sql)
        sql_path = f.name
    try:
        result = subprocess.run(
            ["supabase", "db", "query", "--linked", "-f", sql_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"supabase CLI falló: {result.stderr}")
        # supabase CLI envuelve en boundary JSON; extraemos la fila única.
        try:
            envelope = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"Output no parseable: {result.stdout[:500]}")
        rows = envelope.get("rows") or []
        if not rows:
            return {"tables": []}
        return rows[0].get("dump") or {"tables": []}
    finally:
        os.unlink(sql_path)


def _normalize_for_diff(payload: dict) -> dict:
    """Sort keys recursively for stable diff."""
    if isinstance(payload, dict):
        return {k: _normalize_for_diff(v) for k, v in sorted(payload.items())}
    if isinstance(payload, list):
        return [_normalize_for_diff(x) for x in payload]
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--diff", action="store_true",
                        help="Compara contra el fixture existente y reporta diferencias.")
    args = parser.parse_args()

    sql = _format_sql(CORE_TABLES)
    live = _normalize_for_diff(_run_sql(sql))

    if args.diff:
        try:
            with open(args.out) as f:
                fixture = _normalize_for_diff(json.load(f))
        except FileNotFoundError:
            print(f"❌ Fixture no existe en {args.out}. Genera primero sin --diff.")
            return 2
        if live == fixture:
            print(f"✅ Schema live coincide con fixture ({len(live.get('tables', []))} tablas).")
            return 0
        print("❌ DRIFT detectado — schema live difiere del fixture.")
        live_names = {t["table_name"] for t in live.get("tables", [])}
        fixture_names = {t["table_name"] for t in fixture.get("tables", [])}
        added = live_names - fixture_names
        removed = fixture_names - live_names
        if added:
            print(f"  Tablas nuevas en live: {sorted(added)}")
        if removed:
            print(f"  Tablas eliminadas en live: {sorted(removed)}")
        # Diff por columna en tablas comunes.
        live_by = {t["table_name"]: t for t in live.get("tables", [])}
        fixture_by = {t["table_name"]: t for t in fixture.get("tables", [])}
        for name in sorted(live_names & fixture_names):
            l_cols = {c["col"]: c for c in live_by[name].get("columns") or []}
            f_cols = {c["col"]: c for c in fixture_by[name].get("columns") or []}
            col_added = set(l_cols) - set(f_cols)
            col_removed = set(f_cols) - set(l_cols)
            if col_added or col_removed:
                print(f"  {name}: +{sorted(col_added)} -{sorted(col_removed)}")
        return 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(live, f, indent=2, ensure_ascii=False, sort_keys=True)
    print(f"✅ Schema canonical escrito en {args.out} ({len(live.get('tables', []))} tablas).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
