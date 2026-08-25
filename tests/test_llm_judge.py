"""B-3 2026-08-23 — juez LLM de calidad conversacional (llm_judge.py).

Cubre el núcleo PURO sin llamadas reales al LLM: parser de la respuesta del
juez (JSON plano, con fences, basura), normalización de ambos formatos de
fixture, agregación, umbral/exit code, modo offline y el flujo completo con
call_fn inyectado (LLM mockeado).
"""
import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "uat"))

import llm_judge  # noqa: E402


def _verdict(n, coh=2, din=2, alu=2, tono=2, fallo=""):
    return {"turno": n, "coherencia": coh, "verdad_dinero": din,
            "no_alucinacion": alu, "tono": tono, "fallo": fallo}


def _fixture_dir_format():
    """Fixture formato mensajes crudos: 2 intercambios evaluables."""
    return {
        "id": "test_dir",
        "turns": [
            {"ts": "t1", "dir": "inbound", "text": "Hola"},
            {"ts": "t2", "dir": "outbound", "text": "Buenas! En qué te ayudo?"},
            {"ts": "t3", "dir": "inbound", "text": "cuanto vale el sérum?"},
            {"ts": "t4", "dir": "inbound", "text": "el de 15ml"},
            {"ts": "t5", "dir": "outbound", "text": "El de 15ml vale $52.000 COP"},
        ],
    }


def _write_tmp(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    return path


def _args(transcript: str, threshold: float = 0.7, offline: bool = False):
    return argparse.Namespace(transcript=transcript, threshold=threshold,
                              offline=offline)


class NormalizePairsTests(unittest.TestCase):
    def test_formato_dir_agrupa_inbounds_consecutivos(self):
        pairs = llm_judge.normalize_pairs(_fixture_dir_format())
        self.assertEqual(len(pairs), 2)
        # El segundo intercambio junta los dos inbounds en el contexto.
        self.assertEqual(pairs[1]["n"], 2)
        self.assertIn("cuanto vale el sérum?", pairs[1]["inbound"])
        self.assertIn("el de 15ml", pairs[1]["inbound"])
        self.assertEqual(pairs[1]["outbound"], "El de 15ml vale $52.000 COP")

    def test_formato_tabla_e2e(self):
        data = {"id": "t", "turns": [
            {"n": 1, "inbound": "hola", "outbound": "buenas",
             "veredicto": "ok", "nota": ""},
            {"n": 2, "inbound": "precio?", "outbound": "$10.000",
             "veredicto": "hallazgo", "nota": "H1"},
        ]}
        pairs = llm_judge.normalize_pairs(data)
        self.assertEqual([p["n"] for p in pairs], [1, 2])
        self.assertEqual(pairs[1]["outbound"], "$10.000")


class ParseJudgeResponseTests(unittest.TestCase):
    def test_parse_json_plano(self):
        raw = json.dumps([_verdict(1, tono=1, fallo="tono brusco"), _verdict(2)])
        out = llm_judge.parse_judge_response(raw, {1, 2})
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["tono"], 1)
        self.assertEqual(out[0]["fallo"], "tono brusco")

    def test_parse_con_fences_markdown(self):
        raw = "```json\n" + json.dumps([_verdict(3)]) + "\n```"
        out = llm_judge.parse_judge_response(raw, {3})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["turno"], 3)

    def test_parse_basura_lanza_valueerror(self):
        with self.assertRaises(ValueError):
            llm_judge.parse_judge_response("no json at all", {1})

    def test_parse_clampea_y_filtra(self):
        raw = json.dumps([
            _verdict(1, coh=5, din=-3, alu="x"),   # fuera de rango / inválido
            _verdict(99),                           # turno no esperado
            {"sin_turno": True},                    # sin clave turno
        ])
        out = llm_judge.parse_judge_response(raw, {1})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["coherencia"], 2)     # clamp a 2
        self.assertEqual(out[0]["verdad_dinero"], 0)  # clamp a 0
        self.assertIsNone(out[0]["no_alucinacion"])   # inválido → None


class AggregateDecideExitTests(unittest.TestCase):
    def test_aggregate_promedios_y_peores(self):
        results = [_verdict(1), _verdict(2, coh=0, tono=0, fallo="ignora pregunta"),
                   _verdict(3, din=0, fallo="total inventado")]
        agg = llm_judge.aggregate(results)
        self.assertEqual(agg["n"], 3)
        self.assertEqual(agg["dinero_violado"], 1)
        # promedios redondeados a 3 decimales en aggregate()
        self.assertAlmostEqual(agg["promedios"]["verdad_dinero"], (2 + 2 + 0) / 3,
                               places=3)
        # Peor turno primero: el 3 (dinero 0 → score 0.75) luego el 2 (0.5).
        # turno 2: (0+2+2+0)/8 = 0.5; turno 3: (2+0+2+2)/8 = 0.75
        self.assertEqual(agg["peores"][0]["turno"], 2)
        self.assertEqual(agg["peores"][1]["turno"], 3)
        self.assertLess(agg["score_medio"], 1.0)

    def test_decide_exit_pasa(self):
        agg = llm_judge.aggregate([_verdict(1), _verdict(2)])
        self.assertEqual(llm_judge.decide_exit(agg, 0.7), 0)

    def test_decide_exit_falla_por_umbral(self):
        agg = llm_judge.aggregate([_verdict(1, coh=0, din=1, alu=0, tono=1)])
        # score = 2/8 = 0.25 < 0.7 (dinero 1: dudoso, no violación)
        self.assertEqual(agg["dinero_violado"], 0)
        self.assertEqual(llm_judge.decide_exit(agg, 0.7), 1)

    def test_decide_exit_falla_por_dinero_aunque_el_score_sea_alto(self):
        results = [_verdict(1) for _ in range(9)] + [_verdict(10, din=0)]
        agg = llm_judge.aggregate(results)
        self.assertGreaterEqual(agg["score_medio"], 0.7)
        self.assertEqual(llm_judge.decide_exit(agg, 0.7), 1)

    def test_decide_exit_sin_datos_es_2(self):
        self.assertEqual(llm_judge.decide_exit(llm_judge.aggregate([]), 0.7), 2)


class JudgePairsTests(unittest.TestCase):
    def test_reintenta_con_backoff(self):
        calls = {"n": 0}

        def flaky(prompt):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("cuota")
            return json.dumps([_verdict(1)])

        with mock.patch.object(llm_judge.time, "sleep") as sleep:
            out = llm_judge.judge_pairs([{"n": 1, "inbound": "h", "outbound": "b"}],
                                        flaky)
        self.assertEqual(len(out), 1)
        self.assertEqual(calls["n"], 3)          # 1 intento + 2 reintentos
        self.assertEqual(sleep.call_count, 2)    # backoff ×1, ×2

    def test_agota_reintentos_y_lanza(self):
        def siempre_falla(prompt):
            raise RuntimeError("caído")

        with mock.patch.object(llm_judge.time, "sleep"), \
                self.assertRaises(RuntimeError):
            llm_judge.judge_pairs([{"n": 1, "inbound": "h", "outbound": "b"}],
                                  siempre_falla)

    def test_batch_por_ventanas(self):
        pairs = [{"n": i, "inbound": "h", "outbound": "b"} for i in range(1, 26)]
        prompts = []

        def fake(prompt):
            prompts.append(prompt)
            # El fake puntúa solo los turnos de SU ventana (lee los marcadores).
            ns = [int(line.split("—")[0].strip().strip("[Turno "))
                  for line in prompt.splitlines() if "← EVALUAR" in line]
            return json.dumps([_verdict(n) for n in ns])

        out = llm_judge.judge_pairs(pairs, fake, window_size=12)
        self.assertEqual(len(prompts), 3)  # 12 + 12 + 1
        self.assertEqual(len(out), 25)


class RunFlowTests(unittest.TestCase):
    def test_offline_sin_key_skip_exit_0(self):
        path = _write_tmp(_fixture_dir_format())
        try:
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(llm_judge, "_load_env", return_value={}), \
                    redirect_stdout(io.StringIO()) as buf:
                code = llm_judge.run(_args(path, offline=True))
            self.assertEqual(code, 0)
            self.assertIn("SKIP — sin GEMINI_API_KEY", buf.getvalue())
        finally:
            os.unlink(path)

    def test_sin_key_sin_offline_es_error(self):
        path = _write_tmp(_fixture_dir_format())
        try:
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(llm_judge, "_load_env", return_value={}):
                code = llm_judge.run(_args(path, offline=False))
            self.assertEqual(code, 2)
        finally:
            os.unlink(path)

    def test_flujo_completo_llm_mockeado_pass(self):
        path = _write_tmp(_fixture_dir_format())
        try:
            fake = lambda prompt: json.dumps([_verdict(1), _verdict(2)])  # noqa: E731
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}, clear=True), \
                    redirect_stdout(io.StringIO()) as buf:
                code = llm_judge.run(_args(path), call_fn=fake)
            out = buf.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("VEREDICTO: PASS", out)
            self.assertIn("Score medio: 1.000", out)
        finally:
            os.unlink(path)

    def test_flujo_completo_dinero_violado_exit_1(self):
        path = _write_tmp(_fixture_dir_format())
        try:
            fake = lambda prompt: json.dumps(  # noqa: E731
                [_verdict(1), _verdict(2, din=0, fallo="total inventado")])
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "fake"}, clear=True), \
                    redirect_stdout(io.StringIO()) as buf:
                code = llm_judge.run(_args(path), call_fn=fake)
            out = buf.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("Verdad-dinero violada: 1", out)
            self.assertIn("VEREDICTO: FAIL", out)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
