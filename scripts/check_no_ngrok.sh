#!/usr/bin/env bash
# =============================================================================
# check_no_ngrok.sh — Gate anti-drift de webhooks (env audit 2026-07-17).
#
# El drift REAL fue en dashboards de proveedores (Meta/Wompi/MeLi apuntando a
# túneles ngrok dev en vez de onrender/konvi.co). Eso vive FUERA del repo y no
# se puede lintear. Pero este gate impide la CLASE de bug donde una URL ngrok
# queda hardcodeada como default/valor en código o config de PROD (render.yaml,
# services/, apps/) — un apuntamiento dev filtrado a producción.
#
# Alcance: solo archivos que se despliegan. docs/, scripts/uat/, .env de ejemplo
# pueden documentar túneles ngrok legítimamente → se excluyen.
# Exit 1 si encuentra ngrok en shippable; 0 si limpio.
# =============================================================================
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Matchea HOSTNAMES ngrok reales (con TLD), no la palabra suelta — así un
# comentario "no usar ngrok" no dispara falso positivo.
PATTERN='ngrok(-free)?\.(dev|app|io)'

hits_code=$(grep -rInE "$PATTERN" services apps \
  --include='*.py' --include='*.ts' --include='*.tsx' --include='*.js' \
  --include='*.mjs' --include='*.yaml' --include='*.yml' 2>/dev/null \
  | grep -viE '/(tests?|__pycache__|node_modules|\.next|uat|debug)/' || true)
hits_yaml=$(grep -InE "$PATTERN" render.yaml 2>/dev/null || true)

all=$(printf '%s\n%s\n' "$hits_code" "$hits_yaml" | grep -vE '^[[:space:]]*$' || true)

if [ -n "$all" ]; then
  echo "❌ URLs ngrok (túnel dev) en código/config de PROD — usar onrender/konvi.co:"
  echo "$all"
  exit 1
fi
echo "✓ sin URLs ngrok en código/config de prod (render.yaml + services/ + apps/)"
exit 0
