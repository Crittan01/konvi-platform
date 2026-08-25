"""Juez LLM de calidad conversacional sobre transcripts dorados (B-3).

Evalúa cada turno OUTBOUND de un transcript dorado (fixtures de
`scripts/uat/golden_corpus/`) con un LLM juez (Gemini) bajo una rúbrica fija,
e imprime reporte por turno + agregado. Pensado como gate de calidad:

  • exit 0 — score medio ≥ umbral y ningún turno con verdad-dinero violada.
  • exit 1 — score medio < umbral (--threshold, default 0.7) O hay ≥1 turno
    con verdad_dinero = 0 (monto/descuento/total contradictorio o inventado).
  • exit 2 — error de configuración (sin API key sin --offline) o el juez no
    devolvió nada parseable (gate fail-closed ante juez caído).

Uso:
  python3.11 scripts/uat/llm_judge.py scripts/uat/golden_corpus/prd_4d608efd.json
  python3.11 scripts/uat/llm_judge.py fixture.json --threshold 0.8
  python3.11 scripts/uat/llm_judge.py fixture.json --offline   # gate sin key

Config:
  GEMINI_API_KEY  — env, o la de `.env.local` raíz (parseo KEY=VALUE simple,
                    mismo patrón que e2e_chat._load_env).
  JUDGE_MODEL     — modelo del juez (default: gemini-3.1-flash-lite).
  --offline       — si NO hay API key, imprime "SKIP — sin GEMINI_API_KEY" y
                    sale 0 (un gate sin key no falla; la cobertura se ve en el
                    log, no en el exit code).

Rúbrica por turno outbound (cada dimensión 0-2, JSON forzado):
  coherencia      — ¿responde a lo que el cliente dijo y mantiene el hilo?
  verdad_dinero   — montos/descuentos/totales consistentes con los previos del
                    transcript (si no hay montos: 2). 0 = violación.
  no_alucinacion  — no inventa políticas/datos/cupones no establecidos.
  tono            — profesional, no contradictorio.
  fallo           — string corto con el fallo detectado, o "".

Batch: ventanas de ~12 turnos por llamada para no exceder contexto; los scores
se agregan sobre todos los turnos evaluados. Timeout por llamada (90s) y
reintentos ×2 con backoff ante fallo del juez.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

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

DEFAULT_MODEL = "gemini-3.1-flash-lite"
DEFAULT_THRESHOLD = 0.7
WINDOW_SIZE = 12          # turnos por ventana de evaluación
CALL_TIMEOUT_MS = 90_000  # timeout por llamada al juez (ms — HttpOptions)
RETRIES = 2               # reintentos tras el intento inicial
BACKOFF_S = 2.0           # backoff base (×1, ×2 por reintento)

RUBRIC = ("coherencia", "verdad_dinero", "no_alucinacion", "tono")
MAX_DIM = 2  # cada dimensión puntúa 0..2

_JUDGE_INSTRUCTION = """\
Eres un juez ESTRICTO de calidad conversacional de un bot de ventas por \
WhatsApp (e-commerce colombiano, montos en COP). Se te da una ventana de la \
conversación; evalúa CADA mensaje del Bot marcado «← EVALUAR» en 4 dimensiones:

- coherencia (0-2): ¿responde a lo que el cliente dijo en el turno previo y \
mantiene el hilo? 2 = totalmente, 1 = parcial, 0 = ignora la pregunta o \
contradice el hilo.
- verdad_dinero (0-2): todo monto/descuento/total mencionado es consistente \
con los montos previos del transcript (precios, subtotal, descuento, envío, \
total). 0 = contradictorio o inventado (VIOLACIÓN de dinero), 1 = dudoso o \
incompleto, 2 = consistente. Si el turno no menciona montos: 2.
- no_alucinacion (0-2): no inventa políticas, datos, cupones ni capacidades \
no establecidas en el transcript. 0 = inventa, 1 = dudoso, 2 = nada inventado.
- tono (0-2): profesional, cordial, no contradictorio consigo mismo.

Responde SOLO con un JSON array — un objeto por turno evaluado, sin texto \
adicional:
[{"turno": <n>, "coherencia": 0-2, "verdad_dinero": 0-2, \
"no_alucinacion": 0-2, "tono": 0-2, "fallo": "<fallo corto o vacío>"}]\
"""


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


def resolve_api_key(creds: dict) -> str | None:
    """API key del juez: env GEMINI_API_KEY primero, luego la de .env.local."""
    return os.environ.get("GEMINI_API_KEY") or creds.get("GEMINI_API_KEY") or None


def load_transcript(path: str) -> dict:
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data.get("turns"):
        raise ValueError(f"{path}: fixture sin lista 'turns'")
    return data


def normalize_pairs(data: dict) -> list[dict]:
    """Normaliza un fixture dorado a pares evaluables [{n, inbound, outbound}].

    Dos formatos soportados:
      • Mensajes crudos (prd_4d608efd): turns {ts, dir, text}. Se agrupan los
        inbounds consecutivos con el outbound que les responde (un intercambio
        = un turno evaluable; n = ordinal del intercambio).
      • Tabla E2E (stg_e2e_*): turns {n, inbound, outbound, veredicto, nota}.
    """
    turns = data.get("turns") or []
    if turns and turns[0].get("dir"):
        pairs: list[dict] = []
        pending: list[str] = []
        for t in turns:
            text = str(t.get("text") or "")
            if t.get("dir") == "inbound":
                pending.append(text)
            elif t.get("dir") == "outbound":
                pairs.append({
                    "n": len(pairs) + 1,
                    "inbound": "\n".join(pending),
                    "outbound": text,
                })
                pending = []
        return pairs
    return [
        {
            "n": int(t.get("n") or i + 1),
            "inbound": str(t.get("inbound") or ""),
            "outbound": str(t.get("outbound") or ""),
        }
        for i, t in enumerate(turns)
    ]


def build_window_prompt(window: list[dict]) -> str:
    """Render de una ventana de turnos para el juez (marca qué líneas evaluar)."""
    lines: list[str] = []
    for p in window:
        lines.append(f"[Turno {p['n']} — Cliente]")
        lines.append(p["inbound"] or "(sin mensaje del cliente en este turno)")
        lines.append(f"[Turno {p['n']} — Bot]  ← EVALUAR")
        lines.append(p["outbound"])
        lines.append("")
    return "\n".join(lines).strip()


def _clamp_dim(value) -> int | None:
    """Coerce estricto a 0..MAX_DIM; None si el juez no puntuó la dimensión."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(MAX_DIM, v))


def parse_judge_response(raw: str, expected_ns: set[int]) -> list[dict]:
    """Parsea la respuesta del juez a registros por turno (pura, testeable).

    Tolera fences ```json ... ``` y texto alrededor del array. Solo conserva
    turnos esperados de la ventana. Lanza ValueError si no hay JSON parseable.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        # Quitar fence de apertura (```json) y de cierre (```).
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    i, j = text.find("["), text.rfind("]")
    if i == -1 or j <= i:
        raise ValueError("respuesta del juez sin JSON array")
    items = json.loads(text[i:j + 1])
    if not isinstance(items, list):
        raise ValueError("respuesta del juez no es una lista")
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        try:
            n = int(it.get("turno"))
        except (TypeError, ValueError):
            continue
        if n not in expected_ns:
            continue
        rec = {"turno": n, "fallo": str(it.get("fallo") or "")}
        for dim in RUBRIC:
            rec[dim] = _clamp_dim(it.get(dim))
        out.append(rec)
    return out


def turn_score(rec: dict) -> float | None:
    """Score normalizado 0..1 del turno sobre las dimensiones puntuadas."""
    vals = [rec[d] for d in RUBRIC if rec.get(d) is not None]
    if not vals:
        return None
    return sum(vals) / (MAX_DIM * len(vals))


def call_with_retries(call_fn, prompt: str, *, retries: int = RETRIES,
                      backoff: float = BACKOFF_S) -> str:
    """Llama al juez con reintentos ×N y backoff lineal. Agota → RuntimeError."""
    last_exc: Exception | None = None
    for attempt in range(1 + retries):
        try:
            return call_fn(prompt)
        except Exception as exc:  # red, cuota, JSON del SDK, etc.
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"juez LLM falló tras {1 + retries} intentos: {last_exc}")


def judge_pairs(pairs: list[dict], call_fn, *, window_size: int = WINDOW_SIZE,
                retries: int = RETRIES, backoff: float = BACKOFF_S) -> list[dict]:
    """Evalúa todos los pares por ventanas; devuelve registros del juez."""
    results: list[dict] = []
    for i in range(0, len(pairs), window_size):
        window = pairs[i:i + window_size]
        raw = call_with_retries(call_fn, build_window_prompt(window),
                                retries=retries, backoff=backoff)
        results.extend(parse_judge_response(raw, {p["n"] for p in window}))
    return results


def aggregate(results: list[dict]) -> dict:
    """Agregado puro sobre los registros del juez (testeable sin LLM)."""
    scored = [r for r in results if turn_score(r) is not None]
    promedios = {}
    for dim in RUBRIC:
        vals = [r[dim] for r in results if r.get(dim) is not None]
        promedios[dim] = round(sum(vals) / len(vals), 3) if vals else None
    scores = [(r["turno"], turn_score(r), r.get("fallo") or "") for r in scored]
    peores = sorted(scores, key=lambda s: (s[1], s[0]))[:5]
    return {
        "n": len(results),
        "promedios": promedios,
        "score_medio": (round(sum(s for _, s, _ in scores) / len(scores), 4)
                        if scores else None),
        "dinero_violado": sum(1 for r in results if r.get("verdad_dinero") == 0),
        "peores": [{"turno": n, "score": round(s, 4), "fallo": f}
                   for n, s, f in peores],
    }


def decide_exit(agg: dict, threshold: float) -> int:
    """0 = pasa el gate; 1 = calidad baja o dinero violado; 2 = sin datos."""
    if agg["n"] == 0 or agg["score_medio"] is None:
        return 2
    if agg["dinero_violado"] > 0:
        return 1
    return 0 if agg["score_medio"] >= threshold else 1


def _make_genai_call(api_key: str, model: str):
    """Construye el call_fn real (Gemini, JSON forzado, timeout por llamada).

    Import perezoso: el camino --offline y los tests no necesitan el SDK.
    """
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(
        api_key=api_key,
        http_options=genai_types.HttpOptions(timeout=CALL_TIMEOUT_MS),
    )

    def call(prompt: str) -> str:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                system_instruction=_JUDGE_INSTRUCTION,
                temperature=0.0,
                response_mime_type="application/json",
            ),
        )
        return (getattr(resp, "text", None) or "")

    return call


def render_report(results: list[dict], agg: dict, *, fixture_id: str,
                  model: str, threshold: float, n_pairs: int) -> str:
    """Tabla por turno + resumen (promedios y peores 5 turnos)."""
    lines = [f"=== LLM-judge — {fixture_id} (modelo {model}) ===",
             f"{'turno':>6} | {'coh':>3} | {'din':>3} | {'alu':>3} | {'tono':>4} "
             f"| {'score':>5} | fallo",
             "-" * 72]
    by_turno = {r["turno"]: r for r in results}
    for p_n in [r["turno"] for r in sorted(results, key=lambda r: r["turno"])]:
        r = by_turno[p_n]
        score = turn_score(r)
        cells = [f"{r[d]:>3}" if r.get(d) is not None else "  -" for d in RUBRIC]
        lines.append(f"{r['turno']:>6} | {cells[0]} | {cells[1]} | {cells[2]} "
                     f"| {cells[3]} | {score:>5.2f} | {r.get('fallo') or ''}")
    lines.append("-" * 72)
    prom = agg["promedios"]
    prom_txt = " · ".join(f"{d} {prom[d]:.2f}" if prom[d] is not None
                          else f"{d} -" for d in RUBRIC)
    lines.append(f"Turnos evaluados: {agg['n']}/{n_pairs}")
    lines.append(f"Promedios: {prom_txt}")
    sm = agg["score_medio"]
    lines.append(f"Score medio: {sm:.3f} (umbral {threshold:.2f})"
                 if sm is not None else "Score medio: -")
    lines.append(f"Verdad-dinero violada: {agg['dinero_violado']} turno(s)")
    if agg["peores"]:
        lines.append("Peores turnos (máx 5):")
        for w in agg["peores"]:
            lines.append(f"  turno {w['turno']} ({w['score']:.2f})"
                         + (f": {w['fallo']}" if w["fallo"] else ""))
    return "\n".join(lines)


def run(args, call_fn=None) -> int:
    """Flujo completo (IO orquestado; cómputo delegado a funciones puras)."""
    try:
        data = load_transcript(args.transcript)
    except (OSError, ValueError) as exc:
        print(f"ERROR leyendo fixture: {exc}", file=sys.stderr)
        return 2
    pairs = normalize_pairs(data)
    if not pairs:
        print("ERROR: el fixture no produce turnos evaluables", file=sys.stderr)
        return 2

    creds = _load_env()
    api_key = resolve_api_key(creds)
    if not api_key:
        if args.offline:
            print("SKIP — sin GEMINI_API_KEY")
            return 0
        print("ERROR: sin GEMINI_API_KEY (env ni .env.local). "
              "Para un gate sin key, pasá --offline (SKIP, exit 0).",
              file=sys.stderr)
        return 2

    model = os.environ.get("JUDGE_MODEL") or DEFAULT_MODEL
    if call_fn is None:
        call_fn = _make_genai_call(api_key, model)
    try:
        results = judge_pairs(pairs, call_fn)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if len(results) < len(pairs):
        missing = sorted({p["n"] for p in pairs} - {r["turno"] for r in results})
        print(f"AVISO: el juez omitió {len(missing)} turno(s): {missing}",
              file=sys.stderr)

    agg = aggregate(results)
    fixture_id = data.get("id") or os.path.basename(args.transcript)
    print(render_report(results, agg, fixture_id=fixture_id, model=model,
                        threshold=args.threshold, n_pairs=len(pairs)))
    code = decide_exit(agg, args.threshold)
    print(f"VEREDICTO: {'PASS' if code == 0 else 'FAIL' if code == 1 else 'SIN DATOS'}")
    return code


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Juez LLM sobre transcripts dorados (B-3)")
    ap.add_argument("transcript", help="fixture JSON de golden_corpus")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help=f"score medio mínimo (default {DEFAULT_THRESHOLD})")
    ap.add_argument("--offline", action="store_true",
                    help="sin GEMINI_API_KEY: imprime SKIP y sale 0 (gate tolerante)")
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
