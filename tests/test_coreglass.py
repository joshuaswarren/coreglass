import contextlib
import base64
import hashlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from coreglass import __main__ as cli
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

    def test_preflight_script_records_loaded_kernel_modules(self):
        """The manifest keeps preflight, so the loaded modules (ane, pmp_overlay) land in every run.json."""
        import subprocess, sys
        p = subprocess.run([sys.executable, "-", "", "", "[]"], input=remote.PREFLIGHT, text=True, capture_output=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout)["modules"]
        mods = Path("/proc/modules")
        names = sorted(ln.split()[0] for ln in mods.read_text().splitlines()) if mods.exists() else []
        self.assertEqual(got, names)

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

    def test_ledger_idle_before_a_rep_is_the_targets_cool_down_else_the_suite_baseline(self):
        self.assertEqual(ledger.baseline_for({"baseline_s": 4}, {"host": "m1"}), 4)
        self.assertEqual(ledger.baseline_for({"baseline_s": 4}, {"host": "m2", "cool_s": 60}), 60)
        self.assertEqual(ledger.baseline_for({}, {"host": "m1"}), 4)

    def test_ledger_quiet_window_clears_the_host_after_a_failed_rep_and_skips_unset_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "order"
            target = {"host": "m2", "quiet_set": f"echo set >> {log}", "quiet_clear": f"echo clear >> {log}"}
            with self.assertRaises(SystemExit), ledger.quiet_window(target, lambda m: None):
                raise SystemExit("rep failed")
            self.assertEqual(log.read_text().split(), ["set", "clear"])
            with ledger.quiet_window({"host": "m1"}, lambda m: None):
                pass
            self.assertEqual(log.read_text().split(), ["set", "clear"])

    def test_ledger_quiet_window_runs_the_rep_and_the_release_when_the_reservation_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "order"
            target = {"host": "m2", "quiet_set": "sleep 5", "quiet_clear": f"echo clear >> {log}"}
            seen = []
            with ledger.quiet_window(target, seen.append, set_timeout=1):
                seen.append("rep")
            self.assertEqual(log.read_text().split(), ["clear"])
            self.assertEqual(seen[1], "rep")
            self.assertIn("quiet_set failed: TimeoutExpired", seen[0])

    def test_ledger_run_with_stacks_measures_those_stacks_and_no_cells_else_the_cells_too(self):
        cfg = {"stacks": [{"label": "release"}, {"label": "main"}], "cells": [{"label": "cell"}],
               "targets": [{"host": "m2"}]}
        seen = []
        for stacks, want in ((["main"], ["stack main"]), ([], ["stack release", "stack main", "cell cell"])):
            seen.clear()
            with mock.patch.object(ledger, "load_config", return_value=cfg), \
                 mock.patch.object(ledger, "merger", return_value=lambda row: None), \
                 mock.patch.object(ledger, "load_rows", return_value=[]), \
                 mock.patch.object(ledger, "summary", return_value=[]), \
                 mock.patch.object(ledger, "measure_linux", lambda _c, _t, s, _say: seen.append("stack " + s["label"])), \
                 mock.patch.object(ledger, "measure_cell", lambda _c, _t, cell, _say: seen.append("cell " + cell["label"])):
                ledger.run_cmd([], False, stacks)
            self.assertEqual(seen, want)

    def test_ledger_run_refuses_stack_together_with_cells_only(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, mock.patch.object(ledger, "run_cmd") as run, \
             self.assertRaises(SystemExit) as raised:
            cli.main(["ledger", "run", "--stack", "main", "--cells-only"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("not allowed with", err.getvalue())
        run.assert_not_called()

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

    def test_ledger_reads_the_smc_power_rails_of_a_capture_and_leaves_a_chip_without_them_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            def capture(name, rails, watts):
                lines = [{"meta": {"rails": rails}}] + [
                    {"cpu": [0], "t": i, "w": {r: w for r in rails}} for i, w in enumerate(watts)]
                path = Path(tmp) / name
                path.write_text("\n".join(json.dumps(m) for m in lines) + "\n")
                return path
            rails = ["Total System Power", "AC Input Power", "Heatpipe Power", "3.8 V Rail Power"]
            got = ledger.rail_loaded_w(capture("a.jsonl", rails, [10, 10, 70, 80]))
            self.assertEqual(got, {"System power W": 75.0, "AC input W": 75.0, "Heatpipe W": 75.0})
            self.assertEqual(ledger.rail_loaded_w(capture("b.jsonl", ["cpu temp"], [10, 80])), {})

    def test_ledger_marks_a_row_noisy_when_its_reps_ran_in_two_power_states(self):
        def fields(*watts):
            return ledger.power_fields(ledger.summarize([{"System power W": w} for w in watts]))
        self.assertEqual(fields(76.8, 76.6, 77.2), {"power_state": "one state 76.8 W"})
        two = fields(76.8, 44.8, 76.6)
        self.assertEqual(two["power_state"], "two states 44.8 / 76.8 W")
        self.assertEqual(two["noisy"], two["power_state"])
        self.assertEqual(fields(76.8, 64.0), {"power_state": "one state 70.4 W"})  # exactly 1.2 apart is one state
        self.assertEqual(ledger.power_fields({}), {})

    def test_ledger_never_compares_against_or_flags_a_noisy_row(self):
        cfg = {"models": [{"label": "M"}], "engines": [{"label": "E"}]}
        dec = "M · E · decode tok/s"

        def row(date, d, **extra):
            return {"date": date, "chip": "C", "stack": "s", "wheel": "0+a", "driver": "x", "kernel_id": "k",
                    "os": "linux", "metrics": {dec: {"median": d, "min": d, "max": d}}, **extra}
        rows = [row("2026-10-01", 100.0), row("2026-10-02", 60.0, noisy="two states 44 / 77 W"),
                row("2026-10-03", 99.0)]
        by = {r["date"]: (prev, regs) for r, prev, _, regs in ledger.compare(rows, cfg)}
        self.assertEqual(by["2026-10-02"][1], [])  # a 40% drop on a noisy row is not a regression
        self.assertEqual(by["2026-10-03"][0]["date"], "2026-10-01")  # and the noisy day is not the baseline
        page = ledger.render(rows, {**cfg, "checks": []})
        self.assertIn("| Power state |", page)
        self.assertIn("2026-10-02 **(NOISY: two states 44 / 77 W)**", page)

    def test_a_noisy_same_day_rerun_does_not_replace_a_clean_row(self):
        cfg = {"models": [{"label": "M"}], "engines": [{"label": "E"}], "checks": []}
        dec = "M · E · decode tok/s"

        def row(d, **extra):
            return {"chip": "C", "stack": "s", "wheel": "0+a", "driver": "x", "kernel_id": "k", "os": "linux", "reps": 3,
                    "metrics": {dec: {"median": d, "min": d, "max": d}}, **extra}
        noisy = "two states 44 / 77 W"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(ledger, "DOCS", Path(tmp)):
            merge = ledger.merger(cfg, "2026-10-15", log=lambda msg: None)
            merge(row(100.0))
            merge(row(60.0, noisy=noisy))  # a noisy rerun of a clean day is kept out
            self.assertEqual([r["metrics"][dec]["median"] for r in ledger.load_rows()], [100.0])
            merge(row(101.0))  # a clean rerun still replaces a clean row
            self.assertEqual([r["metrics"][dec]["median"] for r in ledger.load_rows()], [101.0])
            merge(row(61.0, noisy=noisy))  # still kept out: the earlier row is clean
            self.assertEqual([r["metrics"][dec]["median"] for r in ledger.load_rows()], [101.0])
            later = ledger.merger(cfg, "2026-10-16", log=lambda msg: None)
            later(row(60.0, noisy=noisy))
            later(row(62.0, noisy=noisy))  # a noisy row may be replaced by another noisy one
            later(row(100.0))  # and by a clean one
            self.assertEqual(sorted(r["metrics"][dec]["median"] for r in ledger.load_rows()), [100.0, 101.0])

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


class CellArtifacts(unittest.TestCase):
    """A server cell keeps its full raw output — the benchmark's stdout and stderr, the server's log, and the
    transport stream — in the house captures dir, also when the run fails or the transport dies mid-stream.
    The real cell script runs under local bash with fixture child processes; the ssh stub stays on the machine
    (no remote host, no provider, no server beyond the script's own port pick)."""

    BENCH_RESULT = json.dumps({"type": "result", "concurrency": 1, "aggregate_tok_s": 42.5,
                               "request_results": [{"ttft_ms": 12.5, "completion_text_sha256": "a" * 64}]})
    SERVER_LINE = "Chat completion: model=m, prompt=8, 128 tokens in 2.0s (100.0 tok/s)"

    def fixtures(self, tmp):
        base, bin = Path(tmp) / "base", Path(tmp) / "bin"
        (base / "venv/bin").mkdir(parents=True)
        (base / "venv/bin/python").symlink_to(sys.executable)
        (base / "shadow/omlx/patches/mlx_lm_mtp").mkdir(parents=True)
        (base / "shadow/omlx/patches/mlx_lm_mtp/qwen35_model.py").write_text("MLX_OMARCHY_OMLX_CONV_FUSE = True\n")
        (base / "model").mkdir()
        (base / "model/config.json").write_text("{}")
        (base / "prompt.txt").write_text("fixture prompt for the cell\n")
        (base / "bench.py").write_text(f"""#!/usr/bin/env python3
import sys
from pathlib import Path
base = Path(__file__).resolve().parent
print("bench fixture noise: raw stdout before any result")
if "--help" in sys.argv:
    raise SystemExit(0)
if (base / "bench-dies").exists():
    sys.stderr.write("bench boom: connection reset\\n")
    raise SystemExit(3)
if (base / "bench-slow").exists():
    import time
    time.sleep(30)
print({self.BENCH_RESULT!r})
if (base / "bench-fails").exists():
    print("partial line after the result")
    sys.stderr.write("bench boom: connection reset\\n")
    raise SystemExit(3)
""")
        (base / "venv/bin/omlx").write_text(f"""#!/bin/sh
echo $$ > "$(dirname "$0")/../../omlx.pid"
echo "fixture omlx serving: $*"
echo "{self.SERVER_LINE}"
d="$(dirname "$0")/../.."
if [ -e "$d/omlx-ignores-term" ]; then
  trap '' TERM   # only SIGKILL can stop this server
elif [ -e "$d/omlx-shutdown" ]; then
  trap 'sleep 0.4; echo "fixture omlx shutdown drained"; kill $child 2>/dev/null; exit 0' TERM
  sleep 300 &
  child=$!
  wait
  exit 0
fi
exec sleep 300
""")
        bin.mkdir()
        (bin / "curl").write_text("#!/bin/sh\nexit 0\n")
        (bin / "python3").write_text("#!/bin/sh\n"
                                     f'case "$1" in {base}/coreglass-quiet.*) echo "1 0.99 0.0";; '
                                     f'*) exec {sys.executable} "$@";; esac\n')
        (bin / "mktemp").write_text("#!/bin/sh\n"
                                    f'if [ "$1" = -d ]; then exec /usr/bin/mktemp -d {base}/coreglass-cell.XXXX; '
                                    f'else exec /usr/bin/mktemp {base}/coreglass-quiet.XXXX.py; fi\n')
        for p in (base / "bench.py", base / "venv/bin/omlx", bin / "curl", bin / "python3", bin / "mktemp"):
            p.chmod(0o755)
        return base, bin

    def cell(self):
        return {"label": "fixture cell", "stack": "release", "shadow": "shadow", "model": "model",
                "bench": "bench.py", "prompt": "prompt.txt", "env_off": {"CG_FIXTURE_OFF": "1"},
                "concurrency": [1], "pairs": 1}

    @contextlib.contextmanager
    def patched(self, base, bin):
        """Every storage global and the transport stay inside this test: no ssh binary, no user capture store."""
        def local(host, cmd, stdin="", timeout=120, text=True):
            return subprocess.run(["bash", "-c", cmd], input=stdin if text else stdin.encode(), text=text,
                                  capture_output=True, timeout=timeout,
                                  env={**os.environ, "PATH": f"{bin}:{os.environ['PATH']}"})

        with mock.patch.object(remote, "ssh", local), \
             mock.patch.object(remote, "resolve", lambda n: {"name": "fixture", "ssh": "fixture-alias-never-dialed",
                                                             "gpu_lock": f"{base}/gpu.lock"}):
            yield local

    def run_cell(self, base, bin, caps, transport=None, identifiers=None):
        target = {"host": "fixture", "base": str(base)}
        before, logs = self.tmp_snapshot(base), []
        with self.patched(base, bin) as local:
            with mock.patch.object(remote, "ssh", transport(local) if transport else local):
                out = cells.measure({"base": str(base)}, target, self.cell(), {"venv": "venv", "driver": "vulkan"},
                                    str(base / "vulkan"), logs.append, Path(caps), identifiers=identifiers)
        return out, logs, local, target, before

    def manifest(self, caps):
        path = next(Path(caps).glob("cells-*.run.json"))
        return json.loads(path.read_text()), path.parent / path.name[:-len(".run.json")]

    @staticmethod
    def tmp_snapshot(base):
        return {p.name for p in base.glob("coreglass-*")}

    def assert_no_leftovers(self, base, before):
        after = self.tmp_snapshot(base)
        self.assertTrue(after <= before, f"new fixture leftovers: {sorted(after - before)}")
        pid = base / "omlx.pid"
        if pid.exists():  # the fixture server's own pid: the exec'd child must be gone, not merely renamed
            pid = int(pid.read_text())
            try:
                os.kill(pid, 0)
                self.assertNotIn(b"sleep", Path(f"/proc/{pid}/cmdline").read_bytes(), "fixture server survived")
            except ProcessLookupError:
                pass

    def test_a_clean_cell_run_keeps_exact_raw_bytes_and_the_row_keeps_a_safe_reference(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, bin = self.fixtures(tmp)
            ids = {"wheel": "mlx 0.29.0", "driver": "cafe1234", "driver_info": "Mesa 26.3.0-devel",
                   "kernel_id": "deadbeef"}
            out, logs, local, target, before = self.run_cell(base, bin, caps, identifiers=ids)
            self.assertEqual((out["gated_runs"], out["runs"]), (2, 2))  # one pair, both variant runs gated
            self.assertEqual(out["run_rc"], 0)
            self.assertEqual(out["metrics"]["off · c1 aggregate tok/s"]["median"], 42.5)
            self.assertEqual(out["metrics"]["on · c1 server decode tok/s"]["median"], 100.0)
            self.assertEqual(out["metrics"]["off · c1 TTFT ms"]["median"], 12.5)
            self.assertTrue(out["text_parity"])
            stem = out["artifacts"][:-len(".run.json")]
            raw = Path(caps) / stem
            self.assertEqual((raw / "p1-off-bench.out").read_bytes(),
                             f"bench fixture noise: raw stdout before any result\n{self.BENCH_RESULT}\n".encode())
            self.assertEqual((raw / "p1-off-bench.err").read_bytes(), b"")
            server = (raw / "p1-on-server.log").read_text().splitlines()
            self.assertEqual(server[1], self.SERVER_LINE)
            self.assertTrue(server[0].startswith("fixture omlx serving: serve --model-dir "))
            transport = (raw / "transport.out").read_text()
            self.assertIn("@@cell artifact 1 off bench.out", transport)  # the whole marked stream is kept
            self.assertIn(self.SERVER_LINE, transport)
            man = json.loads((Path(caps) / out["artifacts"]).read_text())
            self.assertEqual((man["rc"], man["interrupted"], man["identifiers"]), (0, False, ids))
            self.assertEqual(man["invalid_parts"], [])
            self.assertEqual(man["coreglass_commit"], remote._commit())  # source binding, house pattern
            self.assertIn("flock", man["command"])  # the declared exact execution context
            self.assertIn("gpu.lock", man["command"])
            self.assertEqual(man["script_sha256"],
                             hashlib.sha256(cells.cell_script(
                                 self.cell(), str(base), {"venv": "venv", "driver": "vulkan"},
                                 str(base / "vulkan"), dry=False).encode()).hexdigest())
            self.assertEqual(sorted(man["parts"]),
                             sorted(f"p1-{v}-{p}" for v in ("off", "on")
                                    for p in ("bench.err", "bench.out", "server.log")))
            for name, part in man["parts"].items():
                data = (raw / name).read_bytes()
                self.assertEqual((part["status"], part["size"], part["declared"]), ("ok", len(data), len(data)))
                self.assertEqual(hashlib.sha256(data).hexdigest(), part["sha256"])
            self.assert_no_leftovers(base, before)
            docs = Path(tmp) / "docs"
            docs.mkdir()
            cfg = {"stacks": [{"label": "release", "venv": "venv", "driver": "vulkan"}], "base": str(base),
                   "models": [], "engines": [], "checks": []}
            with mock.patch.object(ledger, "stack_info", lambda *a: ids), \
                 mock.patch.object(ledger, "DOCS", docs), \
                 mock.patch.object(ledger, "CAPTURES", Path(caps)), \
                 mock.patch.object(remote, "ssh", local), \
                 mock.patch.object(remote, "resolve", lambda n: {"name": "fixture", "ssh": "fixture-alias-never-dialed",
                                                                 "gpu_lock": f"{base}/gpu.lock"}):
                row = ledger.measure_cell(cfg, target, self.cell(), lambda msg: None)
                ledger.merger(cfg, "2026-11-01", log=lambda msg: None)(row)
            rows = json.loads((docs / "ledger.json").read_text())
            self.assertEqual(rows[0]["run_rc"], 0)
            self.assertIn(rows[0]["artifacts"], {p.name for p in Path(caps).iterdir()})  # ref survives the caller
            blob = (docs / "ledger.json").read_text() + (docs / "LEDGER.md").read_text()
            self.assertNotIn("fixture-alias", blob)  # the row's reference must be capture-store-relative
            self.assertNotIn(str(base), blob)

    def test_the_manifest_identifies_the_cell_without_its_environment_values(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as live:
            base, bin = self.fixtures(tmp)
            cfg = {"stacks": [{"label": "release", "venv": "venv", "driver": "vulkan"}], "base": str(base),
                   "models": [], "engines": [], "checks": []}
            target = {"host": "fixture", "base": str(base)}
            cell = {**self.cell(), "env_off": {"CG_FIXTURE_OFF": "1", "CG_TOPSECRET_TOKEN": "do-not-ship-hunter2"}}
            with self.patched(base, bin), mock.patch.object(ledger, "CAPTURES", Path(live)), \
                 mock.patch.object(ledger, "stack_info",
                                   lambda *a: {"wheel": "mlx fixed", "driver": "fix", "driver_info": "Mesa fixed",
                                               "kernel_id": "fixed0"}):
                row = ledger.measure_cell(cfg, target, cell, lambda msg: None)  # caller and producer, one path
            man, raw = self.manifest(live)
            blob = "\n".join(p.read_text(errors="surrogateescape") for p in raw.rglob("*") if p.is_file())
            self.assertNotIn("do-not-ship-hunter2", blob)  # the env value lands nowhere in the kept evidence
            self.assertNotIn("CG_TOPSECRET_TOKEN", blob)
            self.assertNotIn("env_off", man["cell"])       # omitted by allowlist, not secret-scrubbed by name
            self.assertEqual((man["cell"]["label"], man["cell"]["model"], man["cell"]["bench"],
                              man["cell"]["concurrency"]), ("fixture cell", "model", "bench.py", [1]))
            self.assertEqual(man["script_sha256"],         # the exact env still binds via the script hash
                             hashlib.sha256(cells.cell_script(cell, str(base), {"venv": "venv", "driver": "vulkan"},
                                                              str(base / "vulkan"), dry=False).encode()).hexdigest())
            self.assertEqual(row["metrics"]["off · c1 aggregate tok/s"]["median"], 42.5)  # outcome unchanged
            self.assertIn(row["artifacts"], {p.name for p in Path(live).iterdir()})  # artifact ref survives
            self.assertEqual(man["parts"]["p1-off-bench.out"]["status"], "ok")

    def test_a_broken_bench_keeps_its_partial_bytes_and_stderr_but_records_no_row(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, bin = self.fixtures(tmp)
            (base / "bench-dies").write_text("")
            out, logs, local, target, before = self.run_cell(base, bin, caps)
            self.assertIsNone(out)  # no metrics: exactly the old outcome, but the evidence stays
            man, raw = self.manifest(caps)
            self.assertEqual((man["rc"], man["interrupted"]), (0, False))
            self.assertEqual((raw / "p1-off-bench.err").read_bytes(), b"bench boom: connection reset\n")
            self.assertEqual((raw / "p1-on-bench.out").read_bytes(),
                             b"bench fixture noise: raw stdout before any result\n")
            self.assertIn(self.SERVER_LINE, (raw / "p1-on-server.log").read_text())
            self.assertTrue(any("captures/" in m for m in logs))
            self.assert_no_leftovers(base, before)

    def test_a_bench_that_fails_after_its_result_still_merges_the_same_row_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, bin = self.fixtures(tmp)
            (base / "bench-fails").write_text("")
            out, logs, local, target, before = self.run_cell(base, bin, caps)
            self.assertEqual(out["metrics"]["on · c1 aggregate tok/s"]["median"], 42.5)  # semantics unchanged
            self.assertEqual(out["run_rc"], 0)  # the script's own exit status, as before the change
            _, raw = self.manifest(caps)
            self.assertEqual((raw / "p1-off-bench.err").read_bytes(), b"bench boom: connection reset\n")
            self.assertTrue((raw / "p1-off-bench.out").read_bytes().endswith(b"partial line after the result\n"))
            self.assert_no_leftovers(base, before)

    def test_a_dead_transport_keeps_the_partial_stream_and_marks_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, bin = self.fixtures(tmp)
            partial = (f"@@cell run 1 off gate 1 0.99 0.0\n@@cell bench {self.BENCH_RESULT}\n"
                       '@@cell artifact 1 off bench.out 64\nQQ')

            def dead(local):
                def ssh(host, cmd, stdin="", timeout=120, text=True):
                    if "coreglass-cell" in stdin:
                        raise subprocess.TimeoutExpired(cmd, timeout, output=partial.encode(),
                                                        stderr=b"transport diagnostic\xff\r\n")
                    return local(host, cmd, stdin, timeout)
                return ssh

            out, logs, local, target, before = self.run_cell(base, bin, caps, transport=dead)
            self.assertTrue(out["interrupted"])  # partial evidence survives, visibly marked, never silently
            self.assertIsNone(out["run_rc"])     # the transport died: there is no exit status to claim
            self.assertEqual(out["gated_runs"], 1)
            man, raw = self.manifest(caps)
            self.assertTrue(man["interrupted"])
            self.assertIsNone(man["rc"])
            self.assertEqual((raw / "transport.out").read_bytes(), partial.encode())
            self.assertEqual((raw / "transport.err").read_bytes(), b"transport diagnostic\xff\r\n")
            self.assertEqual((raw / "p1-off-bench.out").read_bytes(), b"A")  # the cut section keeps what arrived
            self.assertEqual(man["parts"]["p1-off-bench.out"]["status"], "truncated")
            self.assert_no_leftovers(base, before)

    def test_the_ledger_caller_records_its_own_evidence_and_a_fixed_clock_rerun_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as live:
            base, bin = self.fixtures(tmp)
            cfg = {"stacks": [{"label": "release", "venv": "venv", "driver": "vulkan"}], "base": str(base),
                   "models": [], "engines": [], "checks": []}
            target = {"host": "fixture", "base": str(base)}

            class FixedUTC(datetime):
                @classmethod
                def now(cls, tz=None):  # both runs collide on the stamp: allocation must still be unique
                    return datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)

            with self.patched(base, bin), mock.patch.object(ledger, "CAPTURES", Path(live)), \
                 mock.patch.object(ledger, "stack_info", lambda *a: {"wheel": "mlx fixed", "driver": "fix",
                                                                     "driver_info": "Mesa fixed",
                                                                     "kernel_id": "fixed0"}), \
                 mock.patch.object(cells, "datetime", FixedUTC):
                row = ledger.measure_cell(cfg, target, self.cell(), lambda msg: None)  # caller = only producer
                stem = row["artifacts"][:-len(".run.json")]
                self.assertTrue((Path(live) / stem).is_dir())  # evidence under the caller's own store
                first = (Path(live) / stem / "p1-off-bench.out").read_bytes()
                (base / "bench-fails").write_text("")  # the rerun still merges: fails after its result
                rerun = ledger.measure_cell(cfg, target, self.cell(), lambda msg: None)
            stems = {p.name for p in Path(live).iterdir() if p.is_dir()}
            self.assertEqual(len(stems), 2)  # same stamp: unique allocation, no overwrite of run 1
            self.assertNotEqual(row["artifacts"], rerun["artifacts"])
            self.assertEqual((Path(live) / stem / "p1-off-bench.out").read_bytes(), first)  # run 1 intact
            self.assertNotEqual(first, (Path(live) / rerun["artifacts"][:-len(".run.json")] /
                                        "p1-off-bench.out").read_bytes())
            for name in (row["artifacts"], rerun["artifacts"]):
                self.assertTrue((Path(live) / name).is_file())  # both manifests stay readable

    def signal_transport(self, bin, procs, env=None):
        """Kill the cell script's whole session with SIGTERM mid-bench — a real local signal, no ssh binary.
        The variant is running when the gate marker arrives; `procs` collects the script process."""
        def interrupting(local):
            def ssh(host, cmd, stdin="", timeout=120, text=True):
                if "coreglass-cell" not in stdin:
                    return local(host, cmd, stdin, timeout)
                p = subprocess.Popen(["bash", "-c", cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, start_new_session=True,
                                     env={**os.environ, "PATH": f"{bin}:{os.environ['PATH']}", **(env or {})})
                procs.append(p)
                p.stdin.write(stdin)
                p.stdin.close()
                p.stdin = None
                head = []
                for _ in range(200):
                    ln = p.stdout.readline()
                    if not ln:
                        break
                    head.append(ln)
                    if ln.startswith("@@cell") and " gate " in ln:  # the variant is running: TERM mid-bench
                        time.sleep(0.5)
                        os.killpg(p.pid, signal.SIGTERM)
                        break
                try:
                    rest_out, rest_err = p.communicate(timeout=25)
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.communicate(timeout=5)
                    raise
                return SimpleNamespace(returncode=p.returncode, stdout="".join(head) + rest_out,
                                       stderr=rest_err)
            return ssh
        return interrupting

    def test_a_signalled_run_flushes_what_is_on_disk_before_cleanup_and_really_kills_the_child(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, bin = self.fixtures(tmp)
            (base / "bench-slow").write_text("")
            procs = []
            out, logs, local, target, before = self.run_cell(base, bin, caps,
                                                             transport=self.signal_transport(bin, procs))
            self.assertIsNone(out)  # the bench never finished: no metrics, exactly as before
            man, raw = self.manifest(caps)
            self.assertFalse(man["interrupted"])  # a real local signal, not the injected timeout path
            # the killed client reports death by signal; the flush in the script's own trap is the proof it ran
            self.assertEqual((man["rc"], [q.returncode for q in procs]), (-15, [-15]))
            self.assertEqual((raw / "p1-off-bench.out").read_bytes(),
                             b"bench fixture noise: raw stdout before any result\n")  # flushed mid-run
            self.assertIn(self.SERVER_LINE, (raw / "p1-off-server.log").read_text())
            self.assertIn("@@cell artifact 1 off bench.out", (raw / "transport.out").read_text())
            self.assertIn("@@cell artifact 1 off bench.err", (raw / "transport.out").read_text())
            self.assert_no_leftovers(base, before)

    def test_a_successful_run_keeps_the_exact_transport_bytes_through_the_real_ssh_helper(self):
        """Byte mode: the measure run's stream is not always text. The real remote.ssh executes with an `ssh`
        stub on PATH, and a stream carrying bytes outside UTF-8 must land exactly and still merge a row."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, _bin = self.fixtures(tmp)
            noise = b"bench \xff\x00 raw \xfe bytes\r\nbare\rend\n"
            diagnostic = b"diagnostic \x80\xff bytes\r\nbare\rend\n"

            def section(v, name, data):
                return (f"@@cell artifact 1 {v} {name} {len(data)}\n".encode() + base64.b64encode(data) + b"\n")

            stream = b""
            for v in ("off", "on"):
                stream += (f"@@cell run 1 {v} gate 1 0.99 0.0\n@@cell bench {self.BENCH_RESULT}\n"
                           f"@@cell log {self.SERVER_LINE}\n").encode()
                if v == "on":
                    stream += noise  # raw transport bytes between the marked lines
                for name, data in (("bench.out", noise), ("bench.err", diagnostic), ("log", noise)):
                    stream += section(v, name, data)
            stub = Path(tmp) / "sshbin"
            stub.mkdir()
            (stub / "ssh").write_text(  # the dry script gets a shadow line; the cell script gets the bytes
                "#!/bin/sh\n"
                'case "$(cat)" in\n'
                '  *coreglass-cell*) cat "$0.bin"; cat "$0.err" >&2 ;;\n'
                "  plain) printf 'plain\\r\\nline\\rend\\n'; printf 'error\\r\\nline\\rend\\n' >&2 ;;\n"
                "  *) echo '@@cell shadow shadow/qwen35_model.py True' ;;\n"
                "esac\n")
            (stub / "ssh").chmod(0o755)
            (stub / "ssh.bin").write_bytes(stream)
            (stub / "ssh.err").write_bytes(diagnostic)
            before = self.tmp_snapshot(base)
            logs = []
            with mock.patch.object(remote, "resolve",
                                   lambda n: {"name": "fixture", "ssh": "fixture-alias-never-dialed",
                                              "gpu_lock": f"{base}/gpu.lock"}), \
                 mock.patch.dict(os.environ, {"PATH": f"{stub}:{os.environ['PATH']}"}):
                out = cells.measure({"base": str(base)}, {"host": "fixture", "base": str(base)}, self.cell(),
                                    {"venv": "venv", "driver": "vulkan"}, str(base / "vulkan"), logs.append,
                                    Path(caps))
                plain = remote.ssh({"ssh": "fixture-alias-never-dialed"}, "unused", stdin="plain")
            self.assertEqual((plain.stdout, plain.stderr), ("plain\nline\nend\n", "error\nline\nend\n"))
            self.assertEqual((out["gated_runs"], out["runs"]), (2, 2))
            self.assertEqual(out["run_rc"], 0)
            raw = Path(caps) / out["artifacts"][:-len(".run.json")]
            self.assertEqual((raw / "transport.out").read_bytes(), stream)  # exact bytes, byte for byte
            self.assertEqual((raw / "transport.err").read_bytes(), diagnostic)
            self.assertEqual((raw / "p1-off-bench.err").read_bytes(), diagnostic)
            self.assertEqual((raw / "p1-off-bench.out").read_bytes(), noise)
            self.assertEqual((raw / "p1-on-server.log").read_bytes(), noise)
            man = json.loads((Path(caps) / out["artifacts"]).read_text())
            self.assertEqual((man["rc"], man["interrupted"], man["invalid_parts"]), (0, False, []))
            self.assertEqual(sorted(man["parts"]),
                             sorted(f"p1-{v}-{n}" for v in ("off", "on")
                                    for n in ("bench.err", "bench.out", "server.log")))
            self.assertEqual([p["status"] for p in man["parts"].values()], ["ok"] * 6)
            self.assert_no_leftovers(base, before)

    def test_shutdown_diagnostics_after_term_are_drained_before_the_flush_keeps_them(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as caps:
            base, bin = self.fixtures(tmp)
            (base / "bench-slow").write_text("")  # the variant is still running when the TERM arrives
            (base / "omlx-shutdown").write_text("")  # the server answers TERM with one last log line, late
            procs = []
            out, logs, local, target, before = self.run_cell(base, bin, caps,
                                                             transport=self.signal_transport(bin, procs))
            self.assertIsNone(out)  # the bench never finished: no metrics, exactly as before
            man, raw = self.manifest(caps)
            self.assertFalse(man["interrupted"])  # a real local signal, not the injected timeout path
            self.assertEqual([q.returncode for q in procs], [-15])
            # the writer's late shutdown line must be in the kept log, not lost to a flush that raced it
            self.assertIn("fixture omlx shutdown drained", (raw / "p1-off-server.log").read_text())
            self.assert_no_leftovers(base, before)

    def test_shutdown_bound_expiry_preserves_unfinalized_files_and_marks_the_capture_incomplete(self):
        for deny_kill in (False, True):
            with self.subTest(deny_kill=deny_kill), tempfile.TemporaryDirectory() as tmp, \
                    tempfile.TemporaryDirectory() as caps:
                base, bin = self.fixtures(tmp)
                (base / "bench-slow").write_text("")
                (base / "omlx-ignores-term").write_text("")
                env = {}
                if deny_kill:
                    shell_env = base / "deny-kill.bash"
                    shell_env.write_text('kill() { [ "$1" != -9 ] && builtin kill "$@"; }\n')
                    env["BASH_ENV"] = str(shell_env)
                procs = []
                started = time.monotonic()
                try:
                    out, logs, local, target, _before = self.run_cell(
                        base, bin, caps, transport=self.signal_transport(bin, procs, env))
                    self.assertIsNone(out)
                    man, raw = self.manifest(caps)
                    self.assertEqual((man["interrupted"], [q.returncode for q in procs]), (False, [-15]))
                    preserved = Path(man["preserved_work"])
                    self.assertEqual(preserved.parent, base)
                    self.assertTrue(man["incomplete"])
                    self.assertEqual(man["parts"], {})
                    self.assertEqual((preserved / "1-off/bench.out").read_bytes(),
                                     b"bench fixture noise: raw stdout before any result\n")
                    self.assertIn(self.SERVER_LINE, (preserved / "1-off/log").read_text())
                    self.assertIn(str(preserved).encode(), (raw / "transport.out").read_bytes())
                    self.assertLess(time.monotonic() - started, 22)
                    pid = int((base / "omlx.pid").read_text())
                    cmdline = Path(f"/proc/{pid}/cmdline")
                    running = cmdline.exists() and b"sleep" in cmdline.read_bytes()
                    self.assertEqual(running, deny_kill)
                finally:
                    pid_file = base / "omlx.pid"
                    if pid_file.exists():
                        try:
                            os.kill(int(pid_file.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_off_protocol_and_malformed_sections_are_refused_and_transport_bytes_land_first(self):
        with tempfile.TemporaryDirectory() as caps:
            stream = ("@@cell artifact 1 off bench.out 3\nYWJj\n"        # ok: abc
                      "@@cell artifact 1 off ../../evil 3\nUVZa\n"       # traversal: refused
                      "@@cell artifact 9 sideways bench.out 3\nUVZa\n"   # off-protocol variant: refused
                      "@@cell artifact 1 on bench.err 3\n!!!!\n"         # malformed base64: kept as-is, marked
                      "@@cell artifact 1 on bench.out 999\nUVFV\n"       # cut short: truncated
                      "@@cell artifact 1 off bench.err 3\nYWFhYQ==\n")   # 3 declared, 4 decoded: size mismatch
            run = SimpleNamespace(returncode=2, stdout=stream, stderr="boom")
            cells.save_artifacts(run, {"label": "fixture cell"}, Path(caps), "flock cmd", "set -u")
            man, raw = self.manifest(caps)
            self.assertEqual((raw / "transport.out").read_text(), stream)  # exact transport bytes, first
            self.assertEqual((raw / "transport.err").read_text(), "boom")
            self.assertEqual((raw / "p1-off-bench.out").read_bytes(), b"abc")
            self.assertEqual(man["parts"]["p1-on-bench.err"]["status"], "malformed")
            self.assertEqual((raw / "p1-on-bench.err").read_bytes(), b"!!!!")
            self.assertEqual(man["parts"]["p1-on-bench.out"]["status"], "truncated")
            self.assertEqual((raw / "p1-on-bench.out").read_bytes(), b"QQU")  # truncated: what arrived, decoded
            self.assertEqual(man["parts"]["p1-off-bench.err"],          # oversized: malformed, real bytes kept
                             {"pair": "1", "variant": "off", "part": "bench.err", "status": "malformed",
                              "size": 4, "declared": 3, "sha256": hashlib.sha256(b"aaaa").hexdigest()})
            self.assertEqual((raw / "p1-off-bench.err").read_bytes(), b"aaaa")
            self.assertEqual((man["rc"], man["invalid_parts"]),
                             (2, ["@@cell artifact 1 off ../../evil 3", "@@cell artifact 9 sideways bench.out 3"]))
            self.assertEqual(sorted(p.name for p in raw.iterdir()),
                             ["p1-off-bench.err", "p1-off-bench.out", "p1-on-bench.err", "p1-on-bench.out",
                              "transport.err", "transport.out"])  # nothing escaped the stem, nothing was created outside
            self.assertEqual(man["command"], "flock cmd")
            self.assertEqual(man["script_sha256"], hashlib.sha256(b"set -u").hexdigest())


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
