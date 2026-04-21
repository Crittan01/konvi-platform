#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PASS_COUNT=0
FAIL_COUNT=0

run_step() {
  local label="$1"
  shift
  echo "\n[STEP] $label"
  if "$@"; then
    echo "[OK] $label"
    PASS_COUNT=$((PASS_COUNT+1))
  else
    echo "[FAIL] $label"
    FAIL_COUNT=$((FAIL_COUNT+1))
  fi
}

run_step "Unit tests Fase A + parser context" \
  python3.11 -m unittest \
    tests/test_catalog_tool_variants.py \
    tests/test_orchestrator_catalog_prompt.py \
    tests/test_orchestrator_takeover.py \
    tests/test_whatsapp_parser_context.py

run_step "Python compile check orchestrator + connector" \
  python3.11 -m py_compile \
    services/ai-orchestrator/orchestrator.py \
    services/ai-orchestrator/tools/catalog_tool.py \
    services/connector-whatsapp/services/parser.py \
    services/connector-whatsapp/services/db_persistence.py \
    services/connector-whatsapp/routers/webhook.py

run_step "DB contract: messages.payload exists" \
  supabase db query --linked \
    "select column_name,data_type from information_schema.columns where table_schema='public' and table_name='messages' and column_name='payload';"

run_step "DB signal: product variants available for UAT" \
  supabase db query --linked \
    "select count(*) as active_products_with_variants from public.products p where p.status='active' and exists (select 1 from public.product_variations v where v.product_id=p.id);"

run_step "Queue health snapshot" \
  supabase db query --linked \
    "select count(*) as pending_whatsapp_outbound from pgmq.q_whatsapp_outbound_messages where vt <= now();"

echo "\n===== RESUMEN FASE A (FREE FALLBACK) ====="
echo "PASSED: $PASS_COUNT"
echo "FAILED: $FAIL_COUNT"

if [[ "$FAIL_COUNT" -gt 0 ]]; then
  echo "ESTADO: NO APROBADO (corregir fallas antes de certificar)"
  exit 1
fi

echo "ESTADO: APROBADO TECNICO (pendiente UAT funcional de negocio)"
