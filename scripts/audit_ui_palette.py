"""UI palette ratchet — impide NUEVAS clases de paleta light-only (FASE 2).

FASE 2 (2026-08-30): el remap dark interino de globals.css murió y las
familias de paleta (amber/red/emerald/blue/violet/slate…) se migraron a
tokens semánticos de status (`bg-warning-bg text-warning-fg border-warning-
border`, `danger-*`, `success-*`, `info-*`, `ai-*`; neutrales → `muted`/
`border`). Este lint evita la reintroducción de clases que solo se ven bien
en light (el bug que motivó la fase: texto invisible en dark).

Detecta en apps/web/{app,components} (*.ts/.tsx, NO *.test.*):
  (bg|text|border)-{amber|yellow|orange|red|rose|emerald|green|teal|blue|
  sky|cyan|violet|indigo|purple|slate|gray|zinc}-{50|100|200|300|600|700|
  800|900} (con o sin opacidad /N, con o sin variantes hover:/sm:/…)

NO flaguea:
  - Ocurrencias con `dark:` en la cadena de variantes (son dark-específicas,
    nunca dependieron del remap).
  - Shades 400/500/950 y opacidades sobre ellos (translúcidos o vivos —
    tema-independientes, correctos en ambos temas por construcción).
  - Ejes from/to/via/fill/stroke/ring/shadow (nunca matchean el patrón).
  - ALLOWLIST explícita (abajo) — cada entrada lleva justificación.

Exit codes: 0 limpio · 1 clases nuevas detectadas (CI falla) · 2 error.

Uso:
  python3.11 scripts/audit_ui_palette.py           # reporte + exit code
  python3.11 scripts/audit_ui_palette.py --json    # salida JSON
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / 'apps/web/app', ROOT / 'apps/web/components']

FAMILIES = (
    'amber|yellow|orange|red|rose|emerald|green|teal|blue|sky|cyan|'
    'violet|indigo|purple|slate|gray|zinc'
)
SHADES = '50|100|200|300|600|700|800|900'

# Segmento de variante Tailwind: `hover:`, `max-sm:`, `[&>svg]:`, …
_SEG = r'(?:[a-zA-Z0-9_-]+(?:\[[^\]\n]*\])?|\[[^\]\n]*\]):'
_RE = re.compile(
    r'(?<![a-zA-Z0-9_:/\-])'
    r'(?P<prefix>(?:' + _SEG + r')*)'
    r'(?P<axis>bg|text|border)-(?P<fam>' + FAMILIES + r')-(?P<shade>' + SHADES + r')'
    r'(?P<op>/\d+|/\[[^\]\n]*\])?'
    r'(?![a-zA-Z0-9_\-\[\]/.%])'
)

# Token sugerido por familia (mensaje de fix).
SUGGEST = {
    **{f: ('warning', 'bg-warning-bg / text-warning-fg / border-warning-border')
       for f in ('amber', 'yellow', 'orange')},
    **{f: ('danger', 'bg-danger-bg / text-danger-fg / border-danger-border')
       for f in ('red', 'rose')},
    **{f: ('success', 'bg-success-bg / text-success-fg / border-success-border')
       for f in ('emerald', 'green', 'teal')},
    **{f: ('info', 'bg-info-bg / text-info-fg / border-info-border')
       for f in ('blue', 'sky', 'cyan')},
    **{f: ('ai', 'bg-ai-bg / text-ai-fg / border-ai-border')
       for f in ('violet', 'indigo', 'purple')},
    **{f: ('neutral', 'bg-muted / text-muted-foreground / border-border')
       for f in ('slate', 'gray', 'zinc')},
}

# ── Allowlist (archivo, axis-familia-shade) — TODA entrada justificada ───────
# Clave: (path relativo al repo, "axis-familia-shade") — matchea con cualquier
# variante/opacidad. Para añadir una entrada exige justificación en comentario.
ALLOWLIST: frozenset[tuple[str, str]] = frozenset({
    # Sidebar = superficie oscura FIJA (tokens --sidebar-*); el badge de rol
    # `text-amber-200` vive siempre sobre oscuro — no es light-only.
    ('apps/web/app/dashboard/sidebar-client.tsx', 'text-amber-200'),

    # Botones de acción sólidos + text-white: tema-independientes (nunca
    # dependieron del remap), AA verificado FASE 2 (700/800 ≥4.5:1; amber-700
    # = 4.0:1 documentado como deuda pre-existente, igual en light y dark).
    ('apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx', 'bg-emerald-600'),
    ('apps/web/app/dashboard/(sales)/claims/_components/claims-manager.tsx', 'bg-emerald-700'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx', 'bg-red-700'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx', 'bg-red-800'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx', 'bg-emerald-700'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/contacts-manager.tsx', 'bg-emerald-800'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/habeas-data-actions.tsx', 'bg-amber-700'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/habeas-data-actions.tsx', 'bg-amber-800'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/habeas-data-actions.tsx', 'bg-emerald-700'),
    ('apps/web/app/dashboard/(sales)/contacts/_components/habeas-data-actions.tsx', 'bg-emerald-800'),
    ('apps/web/app/dashboard/(sales)/promotions/_components/promotions-manager.tsx', 'bg-emerald-700'),
    ('apps/web/app/dashboard/(sales)/promotions/_components/promotions-manager.tsx', 'bg-emerald-800'),
    ('apps/web/app/dashboard/(settings-group)/settings/account-closure/_components/closure-form.tsx', 'bg-red-700'),
    ('apps/web/app/dashboard/(settings-group)/settings/account-closure/_components/closure-form.tsx', 'bg-red-800'),
    ('apps/web/app/dashboard/(settings-group)/team/inactivate-member-button.tsx', 'bg-amber-700'),
    ('apps/web/app/dashboard/(settings-group)/team/inactivate-member-button.tsx', 'bg-amber-800'),
    ('apps/web/app/dashboard/finance/_components/expenses-manager.tsx', 'bg-red-700'),
    ('apps/web/app/dashboard/finance/_components/expenses-manager.tsx', 'bg-red-800'),
    ('apps/web/app/dashboard/purchases/_components/purchase-orders-manager.tsx', 'bg-emerald-700'),
    ('apps/web/app/dashboard/purchases/_components/purchase-orders-manager.tsx', 'bg-emerald-800'),
    ('apps/web/app/dashboard/inbox/_components/conversation-notes.tsx', 'bg-amber-600'),
    ('apps/web/app/dashboard/inbox/_components/conversation-notes.tsx', 'bg-amber-700'),

    # Dots del timeline de envíos: multi-hue por estado (purple≠indigo≠blue) —
    # mapear a tokens colapsaría la distinción; sólidos tema-independientes,
    # ≥3:1 (non-text) sobre ambos canvas.
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-amber-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-blue-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-purple-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-indigo-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-emerald-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-orange-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-rose-700'),
    ('apps/web/app/dashboard/(sales)/shipping/shipment-timeline.tsx', 'bg-red-700'),

    # Botones de marca (color de identidad del proveedor, no status):
    # WhatsApp green / Aveonline cyan / Wompi violet — tema-independientes.
    ('apps/web/app/dashboard/(settings-group)/integrations/_components/integrations-manager.tsx', 'bg-green-600'),
    ('apps/web/app/dashboard/(settings-group)/integrations/_components/integrations-manager.tsx', 'bg-cyan-600'),
    ('apps/web/app/dashboard/(settings-group)/integrations/_components/integrations-manager.tsx', 'bg-violet-600'),

    # security-form.tsx — CTAs SÓLIDOS de confirmación MFA (tema-independientes):
    # blanco sobre amber-800 ≈ 5.9:1 y sobre red-800 ≈ 6.6:1 (AA en ambos temas;
    # el wash de tokens no aplica a botones sólidos). Subidos desde 700/800 por AA.
    ('apps/web/app/dashboard/(settings-group)/settings/security/_components/security-form.tsx', 'bg-amber-800'),
    ('apps/web/app/dashboard/(settings-group)/settings/security/_components/security-form.tsx', 'bg-amber-900'),
    ('apps/web/app/dashboard/(settings-group)/settings/security/_components/security-form.tsx', 'bg-red-800'),
    ('apps/web/app/dashboard/(settings-group)/settings/security/_components/security-form.tsx', 'bg-red-900'),
})

# Archivos completamente exentos (superficie deliberada):
EXEMPT_FILES: frozenset[str] = frozenset({
    # Superficies dark fijas del patrón auth (`.light` forzado sobre canvas
    # oscuro hardcodeado — §1.8 UX-UI).
    'apps/web/components/auth/auth-scene.tsx',
    'apps/web/components/auth/aurora-canvas.tsx',
})


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    cls: str        # clase completa con variantes (p.ej. hover:bg-amber-50)
    suggestion: str


def scan_file(path: Path, rel: str) -> list[Finding]:
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []
    findings: list[Finding] = []
    for m in _RE.finditer(text):
        prefix = m.group('prefix') or ''
        if 'dark:' in prefix:
            continue  # dark-específica — correcta por construcción
        key = (rel, f"{m.group('axis')}-{m.group('fam')}-{m.group('shade')}")
        if key in ALLOWLIST:
            continue
        line = text.count('\n', 0, m.start()) + 1
        findings.append(Finding(
            file=rel, line=line, cls=m.group(0),
            suggestion=SUGGEST[m.group('fam')][1],
        ))
    return findings


def main() -> int:
    as_json = '--json' in sys.argv
    findings: list[Finding] = []
    n_files = 0
    for base in TARGETS:
        for path in sorted(base.rglob('*')):
            if path.suffix not in {'.ts', '.tsx'} or '.test.' in path.name:
                continue
            rel = str(path.relative_to(ROOT))
            if rel in EXEMPT_FILES:
                continue
            n_files += 1
            findings.extend(scan_file(path, rel))

    if as_json:
        print(json.dumps([f.__dict__ for f in findings], indent=2,
                         ensure_ascii=False))
    else:
        print(f'[palette-ratchet] {n_files} archivos escaneados '
              f'(allowlist: {len(ALLOWLIST)} entradas, '
              f'{len(EXEMPT_FILES)} archivos exentos)', file=sys.stderr)
        if findings:
            print(f'\n[palette-ratchet] ❌ {len(findings)} clase(s) de paleta '
                  f'light-only NUEVA(S):\n', file=sys.stderr)
            for f in findings:
                print(f'  {f.file}:{f.line}  {f.cls}\n'
                      f'    → usar tokens: {f.suggestion}', file=sys.stderr)
            print('\n  Si el caso es legítimo (botón sólido text-white, marca '
                  'de proveedor, superficie dark fija), añade entrada con '
                  'justificación a ALLOWLIST en scripts/audit_ui_palette.py.',
                  file=sys.stderr)
        else:
            print('[palette-ratchet] ✅ 0 clases light-only fuera de allowlist.',
                  file=sys.stderr)
    return 1 if findings else 0


if __name__ == '__main__':
    raise SystemExit(main())
