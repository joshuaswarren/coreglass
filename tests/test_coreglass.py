import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from coreglass import build, cells, compare, ingest, ledger, model, remote, sampler, theme, views

FIXTURE = build.REFERENCE


def write(tmp, name, obj):
    path = Path(tmp) / name
    path.write_text(json.dumps(obj))
    return path


class Merge(unittest.TestCase):
    def test_measured_record_replaces_replay_with_same_id_and_host_merges(self):
        with tempfile.TemporaryDirectory() as tmp:
            lab = write(tmp, "lab.json", {
                "schema": "coreglass/v1", "host": {"kernel": "7.1"},
                "paired": [{"id": "ane.encoder.m2max", "component": "ane", "host": "m2", "label": "enc",
                            "linux_ms": 200, "macos_ms": 89, "prov": "measured"}]})
            b = model.load([FIXTURE, lab])
        m2 = [p for p in b["paired"] if p["id"] == "ane.encoder.m2max"]
        self.assertEqual([p["prov"] for p in m2], ["measured"])
        self.assertEqual(b["host"]["chip"], "M1 Max")
        self.assertEqual(b["host"]["kernel"], "7.1")

    def test_unknown_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = write(tmp, "bad.json", {"schema": "coreglass/v1",
                                          "metrics": [{"id": "x", "value": 1, "prov": "guess"}]})
            with self.assertRaises(ValueError):
                model.load([bad])


class Findings(unittest.TestCase):
    def test_factors_and_ranking(self):
        found = model.findings(model.load([FIXTURE]))
        by_id = {f["id"]: f for f in found}
        self.assertAlmostEqual(by_id["gpu.decode_bw"]["factor"], 309 / 150)
        self.assertAlmostEqual(by_id["gpu.decode_bw"]["proven_factor"], 235 / 150)
        self.assertAlmostEqual(by_id["ane.encoder.m1max"]["factor"], 438 / 138)
        self.assertAlmostEqual(by_id["token.host"]["factor"], 9.141 / 4.719)
        self.assertEqual([f["factor"] for f in found], sorted((f["factor"] for f in found), reverse=True))
        kinds = [f["kind"] for f in model.headlines(found)]
        self.assertEqual(len(kinds), len(set(kinds)))


class Ingest(unittest.TestCase):
    def test_gemv_window_reads_null_and_contiguous_arms(self):
        with tempfile.TemporaryDirectory() as tmp:
            win = Path(tmp) / "GemvBw/w1"
            win.mkdir(parents=True)
            (win / "q.ndjson").write_text("\n".join(json.dumps(r) for r in (
                {"k": "dev"}, {"k": "peak", "tag": "read", "med_gb_s": 366.0},
                {"k": "pat", "arm": "null_q4_word_w2_r8", "med_wall_gb_s": 138.86},
                {"k": "pat", "arm": "contiguous_r8", "med_wall_gb_s": 222.25}, {"k": "done"})))
            (win / "env.txt").write_text("t label=a load1=0.15 psi_cpu_avg10=0.00\nt label=b load1=0.28 psi_cpu_avg10=0.10\n")
            out = ingest.gemv_window(win, Path(tmp))
        k = out["kernels"][0]
        self.assertEqual((k["op"], k["null_gbs"], k["contig_gbs"], k["bound"]), ("q", 138.86, 222.25, "row geometry"))
        self.assertEqual({lim["label"]: lim["value"] for lim in out["limits"]},
                         {"Quiet-box load1 (max)": 0.28, "PSI cpu avg10 (max)": 0.10})

    def test_ane_run_takes_median_and_power_in_watts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "AneSpeed/run1"
            run.mkdir(parents=True)
            for i, med in enumerate((250.0, 254.5, 260.0)):
                (run / f"enc-{i}.log").write_text(f"exec ms over 20 calls: min 1 p10 2 median {med} max 9\n")
            (run / "power-base.tsv").write_text("100.0 21671222 1\n100.5 20000000 1\n")
            out = ingest.ane_run(run, Path(tmp), 89, "enc", "m2", "ane.x")
        self.assertEqual(out["paired"][0]["linux_ms"], 254.5)
        self.assertEqual(out["paired"][0]["id"], "ane.x")
        self.assertEqual(out["power"][0]["series"], [[0.0, 21.671], [0.5, 20.0]])

    def test_capture_rows_order_marks_and_gpu_normalization(self):
        meta = {"meta": {"host": "m2", "kernel": "k", "hz": 1, "rails": ["Heatpipe Power"], "temps": [], "irq": ["gpu_fw"],
                         "clusters": [{"name": "policy0", "label": "E", "cpus": [0], "max_khz": 2424000},
                                      {"name": "policy4", "label": "P0", "cpus": [1], "max_khz": 3264000}]}}
        samples = [{"t": 1.0 + i / 10, "cpu": [0.1, 0.9], "irq": {"gpu_fw": 1000.0 if i == 0 else 40.0},
                    "khz": {"E": 2000000, "P0": 3000000}, "w": {"Heatpipe Power": 5.0}, "c": {}} for i in range(40)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cap.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in [meta, samples[0], {"mark": "go", "t": 1.5}, *samples[1:]]))
            b = ingest.capture(path)
        rows = b["capture"]["rows"]
        self.assertEqual([r["label"] for r in rows], ["P0·1", "E·0", "GPU fw"])
        self.assertEqual(rows[2]["p95_per_s"], 40.0)
        self.assertEqual(max(rows[2]["values"]), 1.0)
        self.assertEqual(b["capture"]["marks"], [{"t": 0.5, "label": "go"}])
        self.assertEqual(b["power"][0]["series"][0], [0.0, 5.0])

    def test_capture_prefers_driver_busy_over_irq_proxy_and_renders_capture_frame(self):
        meta = {"meta": {"host": "m2", "kernel": "k", "hz": 1, "rails": [], "temps": [], "irq": ["gpu_fw"],
                         "engines": ["gpu"], "clusters": [{"name": "p", "label": "C0", "cpus": [0], "max_khz": 1}]}}
        samples = [{"t": float(i), "cpu": [0.5], "irq": {"gpu_fw": 9.0}, "khz": {"C0": 1}, "w": {}, "c": {},
                    "eng": {"gpu": {"busy": 0.25 * (i % 5), "pstate": 3}}} for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cap.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in [meta, *samples]))
            b = model.load([FIXTURE, ingest.capture(path)])
        rows = b["capture"]["rows"]
        self.assertEqual([r["label"] for r in rows], ["C0·0", "GPU busy"])
        self.assertEqual(b["capture"]["stats"]["gpu_busy"], 1.0)
        frames = dict(views.render_all(b))
        self.assertIn("capture", frames)
        self.assertIn("driver busy time", frames["capture"])


class Sampler(unittest.TestCase):
    def test_engine_delta_turns_cumulative_counters_into_rates(self):
        prev = {"busy_ns": 1_000_000_000, "jobs": 10, "pstate": 2}
        cur = {"busy_ns": 1_050_000_000, "jobs": 15, "pstate": 4}
        self.assertEqual(sampler.engine_delta(prev, cur, 0.1), {"pstate": 4, "busy": 0.5, "jobs_s": 50.0})
        self.assertEqual(sampler.engine_delta(prev, {"busy_ns": 9_000_000_000}, 0.1)["busy"], 1.0)


class Remote(unittest.TestCase):
    def test_blockers_refuse_busy_hosts(self):
        quiet = {"reachable": True, "gpu_lock_held": False, "load1": 0.1, "busy": []}
        self.assertEqual(remote.blockers(quiet), [])
        self.assertEqual(len(remote.blockers({**quiet, "gpu_lock_held": True, "load1": 2.0})), 2)
        self.assertTrue(remote.blockers({"reachable": False, "error": "timeout"})[0].startswith("unreachable"))
        held = {**quiet, "gpu_lock_held": True}
        self.assertEqual(remote.blockers(held, {"gpu_turn": "gpu-turn -m 6"}), [])  # the run queues instead
        self.assertEqual(remote.blockers(held, {}), ["GPU lock held by another job"])

    def test_wait_ready_polls_until_quiet_and_gives_up_at_deadline(self):
        loads, real = iter([2.0, 0.9, 0.1, 0.1]), remote.preflight
        remote.preflight = lambda h: {"reachable": True, "gpu_lock_held": False, "load1": next(loads), "busy": []}
        try:
            said = []
            remote.wait_ready({}, 60, said.append, poll=0)
            self.assertEqual(next(loads), 0.1)  # returned at the first quiet poll, not before
            self.assertEqual(len(said), 2)  # one line per change of reason
            remote.preflight = lambda h: {"reachable": False, "error": "timeout"}
            remote.wait_ready({}, 0.05, said.append, poll=0.01)  # returns at the deadline; the run then refuses
        finally:
            remote.preflight = real

    def test_probe_steps_follow_clusters_and_mlx(self):
        meta = {"clusters": [{"label": "E", "cpus": [0, 1]}, {"label": "P0", "cpus": [2, 3]}]}
        steps = remote.probe_steps({"mlx_python": "/x/python"}, meta, 10)
        self.assertEqual([(s[0], s[2]) for s in steps], [("P spin", False), ("E spin", False), ("GPU matmul", True)])
        self.assertIn("taskset -c $c", steps[0][1])
        self.assertIn("for c in 2 3;", steps[0][1])
        self.assertEqual([s[0] for s in remote.probe_steps({}, {"clusters": [{"label": "C0", "cpus": [0]}]}, 5)],
                         ["CPU spin"])

    def test_phases_use_manifest_windows_and_engine_busy(self):
        meta = {"meta": {"host": "m2", "hz": 1, "rails": ["Heatpipe Power"], "irq": ["gpu_fw"], "engines": ["gpu"],
                         "clusters": [{"label": "E", "cpus": [0]}, {"label": "P0", "cpus": [1]}]}}
        samples = [{"t": float(t), "cpu": [0.0, 1.0 if 10 <= t < 20 else 0.0], "irq": {"gpu_fw": 4.0},
                    "w": {"Heatpipe Power": 5.0}, "eng": {"gpu": {"busy": 0.95 if 30 <= t < 40 else 0.01}}}
                   for t in range(50)]
        steps = [{"label": "P spin", "t_start": 10.0, "t_end": 20.0}, {"label": "GPU", "t_start": 30.0, "t_end": 40.0}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cap.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in [meta, *samples]))
            path.with_suffix(".run.json").write_text(json.dumps({"steps": steps}))
            rows = {r["phase"]: r for r in remote.phases(path)["phases"]}
        self.assertEqual(list(rows), ["idle", "P spin", "GPU"])
        self.assertEqual((rows["P spin"]["p_busy"], rows["P spin"]["e_busy"]), (1.0, 0.0))
        self.assertEqual(rows["GPU"]["gpu_busy"], 0.95)
        self.assertEqual(rows["idle"]["gpu_busy"], 0.01)

    def test_llm_result_derives_per_token_cost_from_the_decode_window_only(self):
        meta = {"meta": {"host": "m1", "hz": 1, "rails": ["Heatpipe Power", "Total System Power"], "irq": [],
                         "clusters": [{"label": "P0", "cpus": [0]}]}}
        decode = lambda t: 21 < t < 30
        samples = [{"t": float(t), "cpu": [0.0], "irq": {},
                    "w": {"Heatpipe Power": 3.0, "Total System Power": 20.0 if decode(t) else 40.0},
                    "proc": {"cpu": 0.5 if decode(t) else 1.0, "wait": 0.0}} for t in range(50)]
        tokens = {"tokens": {"label": "LLM", "t": [float(t) for t in range(20, 31)]}}
        steps = [{"label": "LLM", "t_start": 10.0, "t_end": 31.0, "kernel": ["agx: fault"],
                  "result": {"decode_tok_s": 10.0, "weights_gb": 1.5}}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cap.jsonl"
            path.write_text("\n".join(json.dumps(x) for x in [meta, *samples, tokens]))
            path.with_suffix(".run.json").write_text(json.dumps({"steps": steps}))
            out = remote.phases(path)
        r = out["results"][0]
        self.assertEqual(out["system_rail"], "Total System Power")
        self.assertEqual((r["j_per_token"], r["host_cpu_ms_per_token"]), (2.0, 50.0))
        self.assertEqual((r["weights_gb_s_modeled"], r["token_gap_ms_p50_p99"], r["kernel_warnings"]),
                         (15.0, [1000.0, 1000.0], 1))

    def test_compare_marks_winner_change_and_calls_small_gaps_a_tie(self):
        vs = [{"variant": "A", "decode_tok_s": 40.0, "ttft_ms": 1000.0},
              {"variant": "B", "decode_tok_s": 50.0, "ttft_ms": 1100.0}]
        rows = {m["metric"]: m for m in compare.deltas(vs)}
        self.assertEqual((rows["decode_tok_s"]["best"], rows["decode_tok_s"]["change_pct"]), (1, [0.0, 25.0]))
        self.assertEqual(rows["ttft_ms"]["best"], 0)
        self.assertEqual(compare.headline(vs, list(rows.values()))[1], "+25%")
        vs[1]["decode_tok_s"] = 40.8
        self.assertEqual(compare.headline(vs, compare.deltas(vs))[1], "≈")

    def test_ledger_day_says_when_the_reference_row_has_fewer_reps(self):
        ref = {"date": "2026-10-07", "reps": 2, "skipped_busy": [98, 99, 98]}
        self.assertEqual(ledger.day(ref), "2026-10-07 (2 of 5 reps: GPU busy)")
        self.assertEqual(ledger.day({"date": "2026-10-07", "reps": 3, "skipped_busy": []}), "2026-10-07")

    def test_ledger_flags_regressions_by_direction_and_tracks_the_best_day(self):
        cfg = {"models": [{"label": "M"}], "engines": [{"label": "E"}]}
        dec, ttft = "M · E · decode tok/s", "M · E · TTFT ms"

        def row(date, d, t):
            return {"date": date, "chip": "C", "stack": "s", "wheel": "0+a", "driver": "x", "kernel_id": "k",
                    "os": "linux", "metrics": {dec: {"median": d}, ttft: {"median": t}}}
        rows = [row("2026-10-01", 100.0, 400.0), row("2026-10-02", 90.0, 300.0), row("2026-10-03", 89.5, 304.0)]
        last = {r["date"]: (cells, regs) for r, _, cells, regs in ledger.compare(rows, cfg)}
        cells, regs = last["2026-10-02"]
        self.assertAlmostEqual(cells[ttft][1], 25.0)  # TTFT 400 -> 300 ms is an improvement
        self.assertEqual([n for n, _ in regs], [dec])  # decode 100 -> 90 is a 10% regression
        cells, regs = last["2026-10-03"]
        self.assertAlmostEqual(cells[dec][2], -10.5)  # against the best day (100), not yesterday
        self.assertEqual([n for n, _ in regs], [ttft])  # -0.6% decode is under the flag; +1.3% TTFT is over
        mm = "GPU matmul TFLOPS"
        cfg2 = {"models": [], "engines": []}
        a = {**row("2026-10-01", 0, 0), "metrics": {mm: {"median": 0.60, "min": 0.60, "max": 0.60}}}
        b = {**row("2026-10-02", 0, 0), "metrics": {mm: {"median": 0.49, "min": 0.48, "max": 0.57}}}
        self.assertEqual(ledger.compare([a, b], cfg2)[1][3], [])  # -18% but inside 2x the 0.09 rep spread
        b["metrics"][mm] = {"median": 0.49, "min": 0.48, "max": 0.49}
        self.assertEqual([n for n, _ in ledger.compare([a, b], cfg2)[1][3]], [mm])

    def test_ledger_correctness_flags_digest_drift_and_disagreeing_reps(self):
        chk = ledger.CHECK + "GDN"

        def row(stack, shas):
            return {"date": "d", "chip": "C", "stack": stack, "digests": {chk: shas, "M · mlx-lm": ["x"]}}
        self.assertEqual(ledger.correctness([row("release", ["aaaa"]), row("main", ["aaaa"])]), {})
        bad = ledger.correctness([row("release", ["aaaa"]), row("main", ["bbbb"])])
        self.assertEqual(list(bad), [("d", "C", "main")])  # only the check counts, and only against release
        flaky = ledger.correctness([row("release", ["aaaa", "cccc"])])
        self.assertIn("reps disagree", flaky[("d", "C", "release")][0])

    def test_cell_parse_counts_only_gated_runs_and_reads_server_decode(self):
        def run(p, v, gate, c1, c4s, text):
            res = lambda c, tok: json.dumps({"type": "result", "concurrency": c, "aggregate_tok_s": tok,
                                             "request_results": [{"ttft_ms": 500.0, "completion_text_sha256": text}]})
            logs = [f"@@cell log x Chat completion: model=m, 128 tokens in 2s ({t} tok/s)" for t in [c1, *c4s]]
            return [f"@@cell run {p} {v} gate {gate} 0.99 0.0", f"@@cell bench {res(1, c1 - 10)}",
                    f"@@cell bench {res(4, 60.0)}", *logs]
        text = "\n".join(run(1, "off", 1, 87.0, [20, 21, 22, 23], "aa") + run(1, "on", 1, 93.0, [24] * 4, "aa")
                         + run(2, "on", 0, 10.0, [1] * 4, "bb"))  # ungated: must not count
        metrics, texts, gated, total = cells.parse(text, {"concurrency": [1, 4]})
        self.assertEqual((gated, total), (2, 3))
        self.assertEqual((metrics["off · c1 server decode tok/s"]["median"], metrics["on · c1 server decode tok/s"]["n"]),
                         (87.0, 1))
        self.assertEqual(metrics["off · c4 server decode tok/s"]["median"], 21.5)  # median of the 4 requests
        self.assertEqual(texts, {"off": ["aa"], "on": ["aa"]})


class Render(unittest.TestCase):
    def test_every_frame_is_valid_svg_and_demo_is_stamped(self):
        b = model.load([FIXTURE])
        for demo in (False, True):
            frames = views.render_all(b, demo=demo)
            self.assertEqual([n for n, _ in frames], ["hero", "time", "bandwidth", "util", "flow", "gaps"])
            for _, svg in frames:
                ET.fromstring(svg)
                self.assertEqual(">DEMO</text>" in svg, demo)

    def test_omarchy_theme_maps_colors_and_light_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "theme" / "colors.toml"
            path.parent.mkdir()
            path.write_text('mode = "light"\naccent = "#1e66f5"\nbackground = "#eff1f5"\nforeground = "#4c4f69"\n'
                            'cyan = "#179299"\nmagenta = "#ea76cb"\nyellow = "#df8e1d"\n')
            (Path(tmp) / "theme.name").write_text("catppuccin-latte")
            saved, theme.THEME_FILES = theme.THEME_FILES, (path,)
            try:
                p = theme.get("omarchy")
            finally:
                theme.THEME_FILES = saved
        self.assertEqual((p["name"], p["gpu"], p["ane"], p["cpu"]), ("omarchy:catppuccin-latte", "#179299", "#ea76cb", "#df8e1d"))
        self.assertIn("color-scheme:light", theme.css_vars(p))
        ET.fromstring(views.render_all(model.load([FIXTURE]), palette=p)[0][1])
        views.use(theme.SYNTHWAVE)

    def test_omarchy_falls_back_to_synthwave_without_a_theme(self):
        saved, theme.THEME_FILES = theme.THEME_FILES, (Path("/nonexistent/colors.toml"),)
        try:
            self.assertEqual(theme.get("omarchy")["name"], "synthwave")
        finally:
            theme.THEME_FILES = saved


if __name__ == "__main__":
    unittest.main()
