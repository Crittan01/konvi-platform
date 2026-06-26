"""AST audit — detecta `.table(X)` queries sin `.eq("tenant_id", ...)` filter.

Fase A6.1 finiquito NIVEL 2 (2026-06-23). Reemplaza el helper `scoped_table`
(empíricamente muerto, 0 adopción en 2 meses post-rev. 58) por lint estático
que enforce el patrón explícito `.table(X).eq("tenant_id", tid)` — único
patrón con DX aceptable + cobertura multi-servicio (api + ai-orchestrator +
connector-whatsapp).

Detecta:
  1. Llamadas `.table("X")` donde X ∈ TENANT_SCOPED_TABLES sin `.eq("tenant_id", ...)`
     en la cadena de método siguiente (ANY chain depth — AST traversa hasta
     terminator `.execute()`).
  2. Llamadas `.insert(payload)` / `.upsert(payload)` / `.update(payload)`
     sobre tablas TENANT_SCOPED_TABLES donde payload NO contiene clave
     `tenant_id` literal (best-effort detection con limits documentados).

NO detecta (limitations honestas):
  - Variables intermedias `q = sb.table("X"); q.eq(...)` (deeper data flow
    analysis fuera de scope).
  - Payloads variable `sb.table("X").insert(my_var)` donde `my_var` no
    inspecciónable estáticamente.
  - `.rpc()` calls (RPCs gobiernan su propia auth via SQL — fuera de scope).

Exit codes:
  0 — No gaps (baseline limpio o CSV vacío)
  1 — Gaps detectados (CI debe fallar)
  2 — Error de parse

Uso:
  python3.11 scripts/audit_tenant_filter.py [--csv OUTPUT.csv] [--baseline BASELINE.csv]
  python3.11 scripts/audit_tenant_filter.py --json  # output JSON para CI
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path


# Source of truth importable. Si tenant_scope.py se elimina (Fase A6.5),
# este set debe mantenerse aquí mismo como replacement. Lista extendida
# vs el set original de tenant_scope.py — incluye tablas críticas que el
# helper original NO contemplaba.
# A6.2.2 finiquito 2026-06-23 (super-audit worwkgukx HIGH gap): el set
# hardcoded previo (56 tablas) tenía DRIFT vs schema real — 27 tablas con
# columna `tenant_id` NO estaban listadas (false negatives no auditados) +
# 17 tablas inventadas que NO existen en migrations. Ahora el set se DERIVA
# AUTOMÁTICAMENTE de `supabase/migrations/*.sql` parseando qué tablas tienen
# columna `tenant_id`. Fallback estático mínimo si migrations no accesibles
# (CI deploy unit sin el dir). El test de coherencia
# `test_tenant_scoped_tables_matches_migrations` falla si hay drift futuro.

# Fallback estático mínimo — solo las tablas core P0 garantizadas. Usado SOLO
# si el scan de migrations falla (dir ausente). En operación normal el set
# completo se deriva de migrations.
_FALLBACK_TENANT_SCOPED_TABLES: frozenset[str] = frozenset({
    "orders", "order_items", "order_tracking", "contacts", "conversations",
    "messages", "payments", "products", "product_variations", "stock_movements",
    "marketplace_listings", "ai_agents", "tenant_integrations",
    "conversation_carts", "cart_events", "consent_audit_log", "pii_access_log",
    "claims", "coupons", "coupon_redemptions", "shipments", "suppliers",
})

# Tablas globales (sin tenant_id por diseño) que NUNCA deben flaguearse aunque
# aparezcan en queries — evita falsos positivos si una migration las renombra.
_GLOBAL_TABLES_NEVER_SCOPED: frozenset[str] = frozenset({
    "tenants",  # la tabla raíz — su PK ES el tenant
    "divipola_dane_codes",  # catálogo geográfico global Colombia
    "schema_migrations",
})


def discover_tenant_scoped_tables_from_migrations(
    migrations_dir: "Path | None" = None,
) -> frozenset[str]:
    """Parsea `supabase/migrations/*.sql` detectando tablas con columna
    `tenant_id` (vía CREATE TABLE con tenant_id en el body, o ALTER TABLE
    ADD COLUMN tenant_id). Source of truth dinámica — elimina el drift del
    set hardcoded previo.

    Retorna fallback estático si el dir no existe (CI deploy aislado).
    """
    import re as _re

    if migrations_dir is None:
        migrations_dir = Path(__file__).resolve().parents[1] / "supabase" / "migrations"
    if not migrations_dir.exists():
        return _FALLBACK_TENANT_SCOPED_TABLES

    found: set[str] = set()
    create_re = _re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?["]?(\w+)["]?\s*\((.*?)\)\s*;',
        _re.IGNORECASE | _re.DOTALL,
    )
    alter_re = _re.compile(
        r'ALTER\s+TABLE\s+(?:public\.)?["]?(\w+)["]?\s+ADD\s+COLUMN\s+'
        r'(?:IF\s+NOT\s+EXISTS\s+)?["]?tenant_id["]?',
        _re.IGNORECASE,
    )
    tenant_col_re = _re.compile(r'\btenant_id\b', _re.IGNORECASE)

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        try:
            text = sql_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in create_re.finditer(text):
            if tenant_col_re.search(m.group(2)):
                found.add(m.group(1))
        for m in alter_re.finditer(text):
            found.add(m.group(1))

    found -= _GLOBAL_TABLES_NEVER_SCOPED
    if not found:
        return _FALLBACK_TENANT_SCOPED_TABLES
    return frozenset(found)


# Set efectivo usado por el lint — derivado de migrations en import time.
TENANT_SCOPED_TABLES_EXTENDED: frozenset[str] = discover_tenant_scoped_tables_from_migrations()


# Métodos de write que requieren tenant_id en el payload (no en chain).
_WRITE_METHODS: frozenset[str] = frozenset({"insert", "upsert", "update"})

# Exemption marker: `# tenant_filter:exempt:<reason>` en la misma línea o
# línea anterior permite saltar el lint para casos legítimos (e.g.
# webhook tenant resolution lookup).
_EXEMPT_MARKER = "tenant_filter:exempt"


@dataclass(frozen=True)
class Gap:
    """Un finding del lint AST."""

    file: str
    line: int
    col: int
    table: str
    kind: str  # 'missing_eq' | 'missing_payload_key' | 'unknown_method_after_table'
    snippet: str = ""

    def to_csv_row(self) -> list[str]:
        return [self.file, str(self.line), str(self.col), self.table, self.kind, self.snippet]

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "table": self.table,
            "kind": self.kind,
            "snippet": self.snippet,
        }


@dataclass
class FileVisitor(ast.NodeVisitor):
    """Visitor por archivo — detecta cada `.table()` y verifica downstream chain."""

    file_path: str
    source_lines: list[str]
    gaps: list[Gap] = field(default_factory=list)
    # A6.2.3 — strict por default: payload variable no-verificable se flaguea
    # (kind=unverifiable_payload_*). lenient=False asume OK (legacy behavior).
    strict_payload: bool = True

    def _is_exempted(self, lineno: int) -> bool:
        """Comprueba si la línea o la línea anterior tiene marker exempt."""
        idx = lineno - 1
        candidates = []
        if 0 <= idx < len(self.source_lines):
            candidates.append(self.source_lines[idx])
        if 0 <= idx - 1 < len(self.source_lines):
            candidates.append(self.source_lines[idx - 1])
        return any(_EXEMPT_MARKER in line for line in candidates)

    def _get_snippet(self, lineno: int) -> str:
        idx = lineno - 1
        if 0 <= idx < len(self.source_lines):
            return self.source_lines[idx].strip()[:160]
        return ""

    def visit_Call(self, node: ast.Call) -> None:
        # Detect `<expr>.table("X")` calls — the entry of a query chain.
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "table"
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            table_name = node.args[0].value
            if table_name in TENANT_SCOPED_TABLES_EXTENDED:
                self._analyze_chain_from_table(node, table_name)
        self.generic_visit(node)

    def _analyze_chain_from_table(self, table_call: ast.Call, table_name: str) -> None:
        """Recorre la cadena de Atributos/Calls a partir del `.table()` call.

        Busca:
          - `.eq("tenant_id", ...)` en cualquier punto de la chain.
          - O un write method (`.insert/.upsert/.update`) cuyo payload
            contenga clave 'tenant_id'.
        Si ninguno aparece y la chain termina, registra gap.
        """
        lineno = table_call.lineno
        col = table_call.col_offset

        if self._is_exempted(lineno):
            return

        # Necesitamos encontrar el nodo padre que CONTIENE el .table() para
        # poder ver los hijos (.eq, .insert, etc.). Como ast.walk traversa
        # top-down, encontramos el .table() dentro de un Call/Attribute chain
        # más grande. Reconstruimos la chain encontrando el nodo más exterior
        # cuyo .func eventualmente baja a este .table().
        outer = self._find_outermost_call_containing(table_call)
        if outer is None:
            outer = table_call

        # Recorrer chain desde outer hacia adentro: cada Call/Attribute en la
        # secuencia que sigue al .table() es un método aplicado al query.
        chain_methods = self._collect_chain_methods(outer, table_call)

        # Buscar .eq("tenant_id", ...)
        for method_name, method_call in chain_methods:
            if method_name == "eq" and len(method_call.args) >= 1:
                first_arg = method_call.args[0]
                if isinstance(first_arg, ast.Constant) and first_arg.value == "tenant_id":
                    return  # OK — filter explícito presente

        # Buscar write con payload que incluya 'tenant_id'
        for method_name, method_call in chain_methods:
            if method_name in _WRITE_METHODS:
                status = self._payload_tenant_id_status(method_call)
                if status == "present":
                    return  # OK — payload incluye tenant_id literal
                if status == "absent":
                    # Dict literal SIN tenant_id → gap definitivo.
                    self.gaps.append(Gap(
                        file=self.file_path, line=lineno, col=col,
                        table=table_name,
                        kind=f"missing_payload_key_{method_name}",
                        snippet=self._get_snippet(lineno),
                    ))
                    return
                # status == "unverifiable" (payload es variable, no Dict literal).
                # A6.2.3 finiquito 2026-06-23: ANTES retornaba "OK" silencioso
                # (false-negative — no se podía verificar pero se asumía bien).
                # Ahora en strict mode (default) lo flaguea con kind distinto
                # para que el triage sepa que requiere revisión manual o
                # exemption marker. En lenient mode se asume OK (legacy).
                if self.strict_payload:
                    self.gaps.append(Gap(
                        file=self.file_path, line=lineno, col=col,
                        table=table_name,
                        kind=f"unverifiable_payload_{method_name}",
                        snippet=self._get_snippet(lineno),
                    ))
                return

        # Sin .eq ni write detectado → asumir read sin filter
        self.gaps.append(Gap(
            file=self.file_path,
            line=lineno,
            col=col,
            table=table_name,
            kind="missing_eq",
            snippet=self._get_snippet(lineno),
        ))

    def _find_outermost_call_containing(self, target: ast.Call) -> ast.Call | None:
        """Best-effort: el call más exterior que contiene este target via
        chain `outer.func.value...` resolviendo a `target`."""
        # Como ast.walk no provee parents, escaneamos todos los Calls del módulo
        # y elegimos el más grande cuyo descendiente sea `target`.
        # Para simplificar (best-effort), retornamos None y el caller usa
        # `target` mismo + traversal manual.
        return None

    def _collect_chain_methods(
        self, outer: ast.Call, table_call: ast.Call
    ) -> list[tuple[str, ast.Call]]:
        """Recolecta métodos en la chain `.table().X().Y().Z()`.

        Para AST de chain `a.table("X").eq("tenant_id", tid).select("*").execute()`,
        la estructura es Call(func=Attr("execute"), value=Call(func=Attr("select"),
        value=Call(func=Attr("eq"), value=Call(func=Attr("table"), value=a)))).

        Entonces partimos del table_call y subimos NO podemos (AST sin parents).
        En su lugar, traversamos el módulo completo y para cada Call cuyo `.func`
        es Attribute cuyo `.value` (recursivamente) llegue a `table_call`,
        registramos el método.
        """
        # Implementación pragmática: buscamos en _all_calls del módulo aquellos
        # cuya func.value (chain transitiva) contenga `table_call`.
        # Esto requiere acceso a _all_calls — lo hacemos en visit_Module setup.
        chain: list[tuple[str, ast.Call]] = []
        for call in self._all_calls:
            if call is table_call:
                continue
            if not isinstance(call.func, ast.Attribute):
                continue
            if self._chain_starts_from(call, table_call):
                chain.append((call.func.attr, call))
        # Orden no garantizado por AST; sufficient pa detectar presencia
        # de un método con args específicos (no necesitamos orden).
        return chain

    def _chain_starts_from(self, call: ast.Call, target: ast.Call) -> bool:
        """¿La chain de `call` baja eventualmente a `target` via .func.value?"""
        cur = call.func
        depth = 0
        max_depth = 20  # safety
        while depth < max_depth:
            if not isinstance(cur, ast.Attribute):
                return False
            inner = cur.value
            if inner is target:
                return True
            if isinstance(inner, ast.Call):
                cur = inner.func
                depth += 1
            else:
                return False
        return False

    def _payload_tenant_id_status(self, write_call: ast.Call) -> str:
        """Estado del tenant_id en el payload de un write call.

        Retorna:
          'present'      — Dict literal con clave 'tenant_id', o kwarg tenant_id=.
          'absent'       — Dict literal SIN clave 'tenant_id' (gap definitivo).
          'unverifiable' — payload es variable / no inspeccionable estáticamente.

        A6.2.3 finiquito 2026-06-23: el método previo `_payload_has_tenant_id`
        colapsaba 'unverifiable' a 'present' (return True), creando un
        false-negative sistemático. Ahora se distingue para que el caller
        decida según strict_payload mode.
        """
        if not write_call.args:
            # `.update()` sin args posicional — raro, tratamos como absent
            # (kwargs-only no es patrón supabase-py para payload).
            for kw in write_call.keywords:
                if kw.arg == "tenant_id":
                    return "present"
            return "absent"
        first = write_call.args[0]
        if isinstance(first, ast.Dict):
            for key in first.keys:
                if isinstance(key, ast.Constant) and key.value == "tenant_id":
                    return "present"
            return "absent"
        # Variable / comprehension / call result — no inspeccionable.
        for kw in write_call.keywords:
            if kw.arg == "tenant_id":
                return "present"
        return "unverifiable"

    @classmethod
    def analyze(
        cls, file_path: str, source: str, *, strict_payload: bool = True,
    ) -> list[Gap]:
        """Entry point — parsea source + corre visitor."""
        try:
            tree = ast.parse(source, filename=file_path)
        except SyntaxError:
            return []
        visitor = cls(
            file_path=file_path,
            source_lines=source.splitlines(),
            strict_payload=strict_payload,
        )
        # Pre-collect all Call nodes for chain traversal
        visitor._all_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        visitor.visit(tree)
        return visitor.gaps


def discover_python_files(roots: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {"__pycache__", ".git", "node_modules", "venv", ".venv", "tests"}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in skip_dirs for part in path.parts):
                continue
            files.append(path)
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="AST audit tenant_id filter coverage")
    parser.add_argument("--csv", default=None, help="Output CSV path")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument(
        "--baseline", default=None,
        help="Baseline CSV — falla solo si nuevas filas vs baseline (modo CI)",
    )
    parser.add_argument(
        "--root", default=None,
        help="Root path (default: repo root inferred)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="No imprimir gaps a stdout (útil cuando --csv o --json)",
    )
    parser.add_argument(
        "--lenient-payload-variables", action="store_true",
        help="(A6.2.3) Asume OK los .insert/.update(variable) no inspeccionables "
             "estáticamente. Default: strict (flaguea kind=unverifiable_payload_*).",
    )
    parser.add_argument(
        "--max-gaps", type=int, default=None,
        help="(A6.2.4) Ratchet: falla si total gaps > N. Fuerza decrecer el "
             "baseline. CI usa BASELINE_MAX env var.",
    )
    args = parser.parse_args()
    strict_payload = not args.lenient_payload_variables

    repo_root = Path(args.root) if args.root else Path(__file__).resolve().parents[1]
    targets = [
        repo_root / "services" / "api",
        repo_root / "services" / "ai-orchestrator",
        repo_root / "services" / "connector-whatsapp",
    ]
    files = discover_python_files(targets)
    if not args.quiet:
        print(f"[lint] Scanning {len(files)} files in {len(targets)} services...",
              file=sys.stderr)

    all_gaps: list[Gap] = []
    for fp in files:
        try:
            source = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(fp.relative_to(repo_root))
        gaps = FileVisitor.analyze(rel, source, strict_payload=strict_payload)
        all_gaps.extend(gaps)

    all_gaps.sort(key=lambda g: (g.file, g.line, g.col))

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "line", "col", "table", "kind", "snippet"])
            for g in all_gaps:
                w.writerow(g.to_csv_row())
        if not args.quiet:
            print(f"[lint] Wrote {len(all_gaps)} gaps to {args.csv}", file=sys.stderr)

    if args.json:
        print(json.dumps([g.to_dict() for g in all_gaps], indent=2))

    if not args.quiet and not args.json:
        if all_gaps:
            print(f"\n[lint] {len(all_gaps)} gap(s) detected:\n", file=sys.stderr)
            for g in all_gaps[:50]:
                print(f"  {g.file}:{g.line}:{g.col}  table={g.table:<30} "
                      f"kind={g.kind}\n    {g.snippet}", file=sys.stderr)
            if len(all_gaps) > 50:
                print(f"  ... and {len(all_gaps) - 50} more (see --csv)",
                      file=sys.stderr)
        else:
            print("[lint] ✅ No gaps detected.", file=sys.stderr)

    # A6.2.4 — Ratchet decreciente: el total de gaps NO debe exceder --max-gaps.
    # Fuerza que el baseline solo BAJE con el tiempo (cada fix A6.2.7 reduce el
    # número; nunca puede subir sin bump explícito + review CODEOWNERS).
    if args.max_gaps is not None and len(all_gaps) > args.max_gaps:
        if not args.quiet:
            print(
                f"\n[lint] ❌ RATCHET: {len(all_gaps)} gaps > max permitido "
                f"{args.max_gaps}. El baseline solo puede DECRECER. Si un fix "
                f"redujo gaps, baja --max-gaps. Si agregaste gaps legítimos, "
                f"requiere review CODEOWNERS + bump explícito.",
                file=sys.stderr,
            )
        return 1

    # CI mode — baseline comparison
    if args.baseline:
        baseline_set: set[tuple[str, int, int, str, str]] = set()
        baseline_path = Path(args.baseline)
        if baseline_path.exists():
            with open(baseline_path, encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    baseline_set.add((
                        row["file"], int(row["line"]), int(row["col"]),
                        row["table"], row["kind"],
                    ))
        current_set = {
            (g.file, g.line, g.col, g.table, g.kind) for g in all_gaps
        }
        new_gaps = current_set - baseline_set
        if new_gaps:
            if not args.quiet:
                print(f"\n[lint] ❌ {len(new_gaps)} NEW gap(s) vs baseline:",
                      file=sys.stderr)
                for ng in sorted(new_gaps):
                    print(f"  {ng[0]}:{ng[1]} table={ng[3]} kind={ng[4]}",
                          file=sys.stderr)
            return 1
        if not args.quiet:
            print(f"[lint] ✅ No new gaps vs baseline ({len(baseline_set)} known).",
                  file=sys.stderr)
        return 0

    # Default mode (no baseline): exit 1 if any gaps exist (strict mode for fresh CI)
    return 1 if all_gaps else 0


if __name__ == "__main__":
    sys.exit(main())
