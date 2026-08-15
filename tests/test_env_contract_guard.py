"""Guard del contrato de entorno (F3) — .env.example nunca se desactualiza.

Verifica en CI:
  (a) COBERTURA: toda env var que el CÓDIGO lee (os.getenv en services +
      process.env en apps/web + scripts) está documentada en .env.example
      (declarada o en el bloque de tuning — esas están listadas como comentario).
  (b) SIN BASURA: toda var VIVA documentada en .env.example es leída por el
      código (o está en la lista de tuning documentada con default en código).
      La sección [ELIMINAR] se ignora (es la lista de muertas a borrar).

Si añades una env var al código, declara su sección en .env.example o este
test falla en CI. Si retiras una var del código, márcala [ELIMINAR] ahí.
"""
import os
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / ".env.example"

PY_RE = re.compile(
    r"""os\.getenv\(\s*["']([A-Z_][A-Z0-9_]*)["']"""
    r"""|os\.environ\.get\(\s*["']([A-Z_][A-Z0-9_]*)["']"""
    r"""|os\.environ\[["']([A-Z_][A-Z0-9_]*)["']"""
    r"""|get_settings\(\)\.([A-Z_][A-Z0-9_]*)"""
)
TS_RE = re.compile(r"""process\.env\.([A-Z_][A-Z0-9_]*)|process\.env\[["']([A-Z_][A-Z0-9_]*)["']""")
MAKE_RE = re.compile(r"""([A-Z_][A-Z0-9_]*)""")


def _code_env_vars() -> set[str]:
    found: set[str] = set()
    for root, exts, pat in (
        ("services", (".py",), PY_RE),
        ("scripts", (".py",), PY_RE),
        ("apps/web", (".ts", ".tsx", ".js"), TS_RE),
    ):
        for p in (REPO / root).rglob("*"):
            sp = str(p)
            if p.suffix not in exts or "__pycache__" in sp or "node_modules" in sp or "/.next/" in sp or "/dist/" in sp:
                continue
            try:
                txt = p.read_text(errors="ignore")
            except Exception:
                continue
            for m in pat.finditer(txt):
                name = next((g for g in m.groups() if g), None)
                if name:
                    found.add(name)
    # .local/Makefile (túneles ngrok del entorno local)
    mk = REPO / ".local" / "Makefile"
    if mk.exists():
        txt = mk.read_text(errors="ignore")
        for m in re.finditer(r"NGROK_[A-Z_]+", txt):
            found.add(m.group(0))
    return found


def _example_vars() -> tuple[set[str], set[str], set[str], set[str]]:
    """(declaradas con KEY=, tuning-block, scripts/devlocal-comentario, muertas [ELIMINAR]).

    La sección [SCRIPTS] (operación humana — leen el archivo, no os.getenv) se
    tolera: el guard no exige que el código las lea por env.
    """
    declared, tuning, scripts, dead = set(), set(), set(), set()
    in_eliminar = False
    in_tuning = False
    in_scripts = False
    for raw in EXAMPLE.read_text().splitlines():
        line = raw.rstrip()
        if line.startswith("## ─── Feature flags / tuning"):
            in_tuning, in_eliminar, in_scripts = True, False, False
        elif line.startswith("## ─── Dev local") :
            in_tuning, in_eliminar, in_scripts = False, False, True  # toleradas como scripts
        elif line.startswith("## ─── Scripts"):
            in_tuning, in_eliminar, in_scripts = False, False, True
        elif line.startswith("## ─── MUERTAS"):
            in_tuning, in_eliminar, in_scripts = False, True, False
        elif line.startswith("## "):
            in_tuning, in_eliminar, in_scripts = False, False, False
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and not line.lstrip().startswith("#"):
            (scripts if in_scripts else declared).add(m.group(1))
            continue
        if in_tuning or in_eliminar or in_scripts:
            for name in re.findall(r"\b([A-Z_][A-Z0-9_]{1,})\b", line):
                (dead if in_eliminar else (scripts if in_scripts else tuning)).add(name)
    return declared, tuning, scripts, dead


# Vars toleradas fuera del contrato, con razón documentada.
_TOLERATED = {
    # Leída SOLO por scripts/admin/seed_konvi_dev_app_secret_vault.py (one-shot
    # histórico que sembró el Vault Model B en jun-2026). Muerta en runtime —
    # el seed ya se ejecutó; no es una var a documentar como viva.
    'META_APP_SECRET',
}


class EnvContractGuardTests(unittest.TestCase):
    def test_cobertura_toda_var_del_codigo_esta_en_el_contrato(self):
        code = _code_env_vars()
        declared, tuning, scripts, dead = _example_vars()
        documented = declared | tuning | scripts
        missing = sorted((code - documented) - _TOLERATED)
        self.assertEqual(
            missing, [],
            f"Vars que el código lee pero NO están en .env.example "
            f"(declararlas en su sección): {missing}",
        )

    def test_sin_basura_toda_var_viva_del_contrato_es_usada(self):
        code = _code_env_vars()
        declared, tuning, scripts, dead = _example_vars()
        # vars declaradas vivas (no tuning ni scripts-comentario) que el código no lee
        alive_unused = sorted(declared - tuning - scripts - code - dead)
        self.assertEqual(
            alive_unused, [],
            f"Vars declaradas en .env.example que el código NO lee "
            f"(moverlas a [ELIMINAR] o al bloque de tuning): {alive_unused}",
        )

    def test_muertas_no_estan_declaradas_vivas(self):
        """Las de la lista [ELIMINAR] no deben aparecer como KEY= viva en el ejemplo."""
        declared, tuning, scripts, dead = _example_vars()
        leaked = sorted(dead & declared)
        self.assertEqual(
            leaked, [],
            f"Vars en [ELIMINAR] que además están declaradas vivas (inconsistente): {leaked}",
        )


if __name__ == "__main__":
    unittest.main()
