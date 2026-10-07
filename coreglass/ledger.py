"""Daily performance ledger (`coreglass ledger`): one frozen suite on every target, one row per Mac, stack, and day
in docs/LEDGER.md, with the change against the previous day and against the best day.

The suite lives in ~/.config/coreglass/ledger.toml (see ledger.example.toml): models, engines, stacks (venv +
Vulkan driver + optional mlx-lm overlay), targets (hosts.toml names), and an optional macOS reference reached over
SSH. Each rep on a Linux target is one `coreglass run` (one GPU turn): GPU matmul, every model × engine, and ANE.
"""

import fcntl
import hashlib
import json
import re
import shlex
import statistics
import threading
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import cells, remote

CONFIG = Path.home() / ".config/coreglass/ledger.toml"
DOCS = Path(__file__).resolve().parent.parent / "docs"
CAPTURES = Path.home() / ".local/share/coreglass/captures"
LLM_KEYS = (("prefill_tok_s", "prefill tok/s"), ("ttft_ms", "TTFT ms"), ("decode_tok_s", "decode tok/s"))
LOWER_IS_BETTER = ("TTFT ms",)
FLAG_PCT = 1.0
DAY_START_UTC_H = 10  # the daily run's hour: a rerun before the next 10:00 UTC still belongs to that run's day


def ledger_day(t):
    """Ledger day of a UTC time: days run from 10:00 UTC to 10:00 UTC the next day."""
    return f"{t - timedelta(hours=DAY_START_UTC_H):%Y-%m-%d}"


def metric_names(cfg):
    names = [f"{m['label']} · {e['label']} · {k}" for m in cfg["models"] for e in cfg["engines"] for _, k in LLM_KEYS]
    return names + ["GPU matmul TFLOPS", "ANE jobs/s"]


CHECK = "check · "


def llm_runs(cfg, base, stack):
    """The suite (every model x engine) plus the correctness checks: in-process greedy runs whose token digest must
    match across stacks (e.g. a prompt long enough for the T>=512 GDN route)."""
    overlay = {"env": {"PYTHONPATH": f"{base}/{stack['overlay']}"}} if stack.get("overlay") else {}
    runs = [{"label": f"{m['label']} · {e['label']}", "model": f"{base}/{m['dir']}",
             "engine": e.get("engine", "in-process"), **(overlay if e.get("overlay") else {})}
            for m in cfg["models"] for e in cfg["engines"]]
    return runs + [{"label": CHECK + c["label"], "model": f"{base}/{c['model']}", "engine": "in-process",
                    "prompt_tokens": c["prompt_tokens"], "gen_tokens": c["gen_tokens"], **overlay}
                   for c in cfg.get("checks", [])]


PROBE = ("import mlx.core as m; d = getattr(m, 'device_info', dict)(); "
         "print(m.__version__); print(d.get('driver_info', ''))")


def stack_info(host, python, driver):
    """mlx version, the Vulkan driver this stack's MLX process actually opened (mx.device_info driver_info, e.g.
    "Mesa 26.3.0-devel (git-6dc1fba8e9)"; vulkaninfo when MLX does not report it), and a short hash of the kernel
    release (the page names no kernels)."""
    icd = shlex.quote(f"{driver}/honeykrisp_icd.aarch64.json")
    p = remote.ssh(host, f"export VK_DRIVER_FILES={icd}; {shlex.quote(python)} -c {shlex.quote(PROBE)} && uname -r && "
                         "vulkaninfo --summary 2>/dev/null | sed -n 's/.*driverInfo *= *//p' | head -1", timeout=90)
    lines = [ln.strip() for ln in p.stdout.splitlines()] if p.returncode == 0 else []
    if len(lines) < 3:
        return None
    info = lines[1] or (lines[3] if len(lines) > 3 else "")
    if not info:
        return None
    sha = re.search(r"git-([0-9a-f]+)", info)
    return {"wheel": lines[0], "driver": sha[1] if sha else info, "driver_info": info,
            "kernel_id": hashlib.sha1(lines[2].encode()).hexdigest()[:8]}


def capture_metrics(capture):
    """Metrics of one rep, its kernel warnings, failed steps, its idle-baseline power (W on the hottest rail the
    sampler sees; foreign GPU work shows up far above the Mac's clean idle), and its greedy token digests."""
    man = json.loads(Path(capture).with_suffix(".run.json").read_text())
    out, digests = {}, {}
    for s in man["steps"]:
        if s["rc"]:
            continue
        if s.get("result"):
            if s["result"].get("tokens_sha"):
                digests[s["label"]] = s["result"]["tokens_sha"]
            if not s["label"].startswith(CHECK):
                for key, name in LLM_KEYS:
                    out[f"{s['label']} · {name}"] = s["result"][key]
        elif s["label"] == "GPU matmul" and (m := re.search(r"tflops=([\d.]+)", s["stdout_tail"])):
            out["GPU matmul TFLOPS"] = float(m[1])
    phases = {p["phase"]: p for p in remote.phases(capture)["phases"]}
    if phases.get("ANE", {}).get("ane_jobs_s"):
        out["ANE jobs/s"] = phases["ANE"]["ane_jobs_s"]
    idle_w = phases["idle"].get("heatpipe_w") or 0.0
    failed = [s["label"] for s in man["steps"] if s["rc"]]
    return out, sum(len(s["kernel"]) for s in man["steps"]), failed, idle_w, digests


def digest_sets(dicts):
    """{label: sorted unique digests} over reps: more than one digest for a label means a nondeterministic run."""
    out = {}
    for d in dicts:
        for label, sha in d.items():
            out.setdefault(label, set()).add(sha)
    return {k: sorted(v) for k, v in out.items()}


def valid(target, idle_w):
    """A rep counts only when its idle baseline is clean (`idle_w_max` per target in ledger.toml)."""
    return idle_w <= target.get("idle_w_max", float("inf"))


def summarize(reps):
    keys = sorted({k for r in reps for k in r})
    return {k: {"median": round(statistics.median(vs), 2), "min": min(vs), "max": max(vs), "n": len(vs)}
            for k in keys if (vs := [r[k] for r in reps if k in r])}


def baseline_for(cfg, target):
    """Idle seconds before a rep's timed block: a target's `cool_s` (a chip that throttles under continuous GPU load,
    the M2 Max drops 16-20% within 30 s and recovers after 60 s idle) else the suite's `baseline_s`."""
    return target.get("cool_s", cfg.get("baseline_s", 4))


def measure_linux(cfg, target, stack, log):
    host = remote.resolve(target["host"])
    base = target.get("base", cfg["base"])
    python, driver = f"{base}/{stack['venv']}/bin/python", f"{base}/{stack['driver']}"
    info = stack_info(host, python, driver)
    if not info:
        log(f"{host['name']} {stack['label']}: stack missing ({python}, {driver}); skipped")
        return None
    over = {"mlx_python": python, "llm_runs": llm_runs(cfg, base, stack), "cpu_steps": False,
            "env": {**host.get("env", {}), "VK_DRIVER_FILES": f"{driver}/honeykrisp_icd.aarch64.json"}}
    if host.get("gpu_turn") and cfg.get("turn_minutes"):
        over["gpu_turn"] = re.sub(r"-m \d+", f"-m {cfg['turn_minutes']}", host["gpu_turn"])
    reps, warnings, failed, rejected, digests = [], 0, [], [], []
    want = cfg.get("reps", 3)
    for i in range(want + 2):  # two spare attempts for reps rejected as contaminated
        if len(reps) == want:
            break
        stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        record = str(CAPTURES / f"ledger-{host['name']}-{stack['label']}-{stamp}.jsonl")
        try:  # each rep is one gpu_turn ticket whose command is the GPU work itself
            remote.run_cmd(target["host"], [], [], True, 10, None, False, False, baseline_for(cfg, target), 2, 10,
                           record, log=log, wait=remote_wait(cfg), overrides=over)
        except SystemExit as e:
            log(f"{host['name']} {stack['label']} attempt {i + 1}: {e}")
            continue
        metrics, warn, bad, idle_w, sha = capture_metrics(record)
        if not valid(target, idle_w):
            log(f"{host['name']} {stack['label']} attempt {i + 1} rejected: idle {idle_w:.1f} W > "
                f"{target['idle_w_max']} W (other GPU work during the rep)")
            rejected.append(round(idle_w, 1))
            continue
        reps.append(metrics)
        digests.append(sha)
        warnings += warn
        failed += bad
    if not reps:
        return None
    return {"chip": host.get("chip", host["name"]), "os": "linux", "stack": stack["label"], **info,
            "ane_workload": ane_workload(host.get("ane_cmd", "")), "reps": len(reps), "rejected_idle_w": rejected,
            "kernel_warnings": warnings, "failed_steps": sorted(set(failed)), "metrics": summarize(reps),
            "digests": digest_sets(digests)}


def ane_workload(cmd):
    """'H13 add, 16 KiB' from an ane_cmd: ANE jobs/s compares only between Macs that run the same program."""
    prog, size = re.search(r"fixtures/(h\d+)-anec/(\w+)/", cmd), re.search(r"head -c (\d+)", cmd)
    if not prog:
        return ""
    return f"{prog[1].upper()} {prog[2]}" + (f", {int(size[1]) // 1024} KiB" if size else "")


def vs_release(rows, cfg, stable="release", candidate="main"):
    """Per (date, chip): metrics where `candidate` is worse than `stable` by more than twice the larger rep spread
    (max - min) of the two rows. Returns {(date, chip): [(metric, change %)]}."""
    by = {(r["date"], r["chip"], r["stack"]): r for r in rows}
    out = {}
    for (date, chip, stack), cand in by.items():
        base = by.get((date, chip, stable))
        if stack != candidate or not base:
            continue
        flags = []
        for name in metric_names(cfg):
            a, b = base["metrics"].get(name), cand["metrics"].get(name)
            if not a or not b or min(a.get("n", 1), b.get("n", 1)) < 2:
                continue
            spread = max(a["max"] - a["min"], b["max"] - b["min"])
            worse = (b["median"] - a["median"]) if name.endswith(LOWER_IS_BETTER) else (a["median"] - b["median"])
            if worse > 2 * spread:
                flags.append((name, pct(b["median"], a["median"], name)))
        out[(date, chip)] = flags
    return out


def correctness(rows, stable="release"):
    """{(date, chip, stack): [problems]} for the check digests: reps of one stack that disagree, and any stack on
    a Mac whose digest differs from that Mac's `stable` stack on the same day."""
    by = {(r["date"], r["chip"], r["stack"]): r for r in rows}
    out = {}
    for (date, chip, stack), r in by.items():
        base = by.get((date, chip, stable), {}).get("digests", {})
        for label, shas in r.get("digests", {}).items():
            if not label.startswith(CHECK):
                continue
            name = label[len(CHECK):]
            if len(shas) > 1:
                out.setdefault((date, chip, stack), []).append(f"{name}: reps disagree {'/'.join(s[:8] for s in shas)}")
            elif stack != stable and base.get(label) and base[label] != shas:
                out.setdefault((date, chip, stack), []).append(
                    f"{name}: {shas[0][:8]} differs from {stable} {'/'.join(s[:8] for s in base[label])}")
    return out


def mac_gpu_busy(host):
    """macOS GPU Device Utilization % from ioreg (None when unreadable)."""
    p = remote.ssh(host, "ioreg -r -d 1 -c IOAccelerator | grep -oE '\"Device Utilization %\"=[0-9]+' | head -1",
                   timeout=30)
    m = re.search(r"=(\d+)", p.stdout)
    return int(m[1]) if m else None


def mac_wait_quiet(host, limit, seconds, log, polls=3):
    """Wait up to `seconds` for `polls` readings in a row at or below `limit` % GPU use. Returns the last reading
    and whether the GPU was quiet."""
    deadline, streak, busy = time.time() + seconds, 0, None
    while True:
        busy = mac_gpu_busy(host)
        streak = streak + 1 if busy is not None and busy <= limit else 0
        if streak >= polls:
            return busy, True
        if time.time() >= deadline:
            return busy, False
        time.sleep(10)


def measure_macos(cfg, ref, log):
    base = ref["base"]
    host = {"name": "reference", "ssh": ref["ssh"], "mlx_python": f"{base}/{ref['venv']}/bin/python",
            "llm_runs": llm_runs(cfg, base, {})}
    steps = [s for s in remote.probe_steps(host, {"clusters": []}, 10) if s[2]]
    reps, digests, skipped = [], [], []
    limit = ref.get("gpu_busy_max")
    for i in range(ref.get("reps", cfg.get("reps", 3))):
        if limit is not None:  # the reference Mac serves other work: measure only on a quiet GPU
            busy, quiet = mac_wait_quiet(host, limit, ref.get("quiet_wait_s", 600), log)
            if not quiet:
                log(f"reference rep {i + 1} skipped: GPU {busy}% busy (limit {limit}%)")
                skipped.append(busy)
                continue
        out, sha = {}, {}
        for label, cmd, _ in steps:
            p = remote.ssh(host, "bash -s", cmd, timeout=1800)
            res = next((json.loads(ln) for ln in reversed(p.stdout.splitlines()) if ln.startswith(remote.RESULT)), None)
            if res:
                r = res["coreglass_result"]
                if r.get("tokens_sha"):
                    sha[label] = r["tokens_sha"]
                if not label.startswith(CHECK):
                    for key, name in LLM_KEYS:
                        out[f"{label} · {name}"] = r[key]
            elif m := re.search(r"tflops=([\d.]+)", p.stdout):
                out["GPU matmul TFLOPS"] = float(m[1])
            else:
                log(f"reference {label} rep {i + 1}: rc {p.returncode} {p.stderr.strip()[-160:]}")
        reps.append(out)
        digests.append(sha)
    p = remote.ssh(host, f"{shlex.quote(host['mlx_python'])} -c 'import mlx.core as m; print(m.__version__)'; "
                         "sw_vers -productVersion", timeout=60)
    ver, os_ver = (p.stdout.split() + ["-", "-"])[:2]
    metrics = summarize(reps)
    if ref.get("stat") == "best":  # a shared Mac: contention only slows a rep, so the best rep is the yardstick
        for name, m in metrics.items():
            m["median"] = m["min"] if name.endswith(LOWER_IS_BETTER) else m["max"]
    row = {"chip": ref["chip"], "os": "macos", "stack": "macOS reference", "wheel": f"mlx {ver}",
           "driver": f"Metal (macOS {os_ver})", "kernel_id": "-", "reps": len(reps), "kernel_warnings": 0,
           "failed_steps": [], "stat": "best" if ref.get("stat") == "best" else "median", "metrics": metrics,
           "digests": digest_sets(digests), "skipped_busy": skipped}
    if limit is not None and not reps:
        row["contaminated"] = f"GPU never quiet (last readings {skipped}% busy)"
    return row


def remote_wait(cfg):
    return float(cfg.get("wait_seconds", 3 * 3600))


def pct(new, old, name):
    """Signed change in percent, positive = better."""
    if not old:
        return None
    change = (new - old) / old * 100
    return -change if name.endswith(LOWER_IS_BETTER) else change


def compare(rows, cfg):
    """Per row: the change of every metric against the previous day and the best earlier day, and regressions.
    A regression must be worse than FLAG_PCT and than twice the larger rep spread of the two days, so a metric
    that moves between modes from rep to rep does not raise a flag. Contaminated rows are never a baseline."""
    out = []
    for r in rows:
        earlier = sorted((x for x in rows if (x["chip"], x["stack"]) == (r["chip"], r["stack"])
                          and x["date"] < r["date"] and not x.get("contaminated")), key=lambda x: x["date"])
        prev = earlier[-1] if earlier else None
        cells, regressions = {}, []
        for name in metric_names(cfg):
            m = r["metrics"].get(name)
            if not m or m.get("median") is None:
                continue
            v = m["median"]
            past = [x["metrics"][name]["median"] for x in earlier if name in x["metrics"]]
            best = (min if name.endswith(LOWER_IS_BETTER) else max)(past) if past else None
            p = prev["metrics"].get(name) if prev else None
            d_prev = pct(v, p["median"], name) if p else None
            cells[name] = (v, d_prev, pct(v, best, name) if best is not None else None)
            spread = max(m.get("max", v) - m.get("min", v), p.get("max", 0) - p.get("min", 0)) if p else 0
            if d_prev is not None and d_prev < -FLAG_PCT and abs(v - p["median"]) > 2 * spread:
                regressions.append((name, d_prev))
        out.append((r, prev, cells, regressions))
    return out


def fmt(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}"


def sign(p):
    return "–" if p is None else f"{p:+.1f}%"


def commit_of(wheel):
    return wheel.rsplit("+", 1)[-1] if "+" in wheel else wheel


def render(rows, cfg):
    names = metric_names(cfg)
    rows = sorted(rows, key=lambda r: (r["date"], r["os"], r["chip"], r["stack"]), reverse=True)
    lines = ["# Daily performance ledger", "",
             "Run every day at 10:00 UTC by `coreglass ledger run`; a ledger day runs from 10:00 to 10:00 UTC. "
             "The suite is frozen: "
             + ", ".join(m["label"] for m in cfg["models"]) + "; engines " + ", ".join(e["label"] for e in cfg["engines"])
             + f"; one cold greedy request each ({cfg.get('prompt_note', 'about 477 prompt + 128 generated tokens')}); "
             f"median of {cfg.get('reps', 3)} reps. Each cell is the median, then the change against the previous "
             "day and against the best earlier day, where positive is better. TTFT is lower-is-better.", "",
             f"Regressions over {FLAG_PCT:g}% against the previous day are listed under the table with the commit "
             "range that could explain them. One cold request per rep moves by a few percent from run to run, so "
             "check the min-max spread in `docs/ledger.json` before you act on a flag.", "",
             "The REGRESSION column flags every metric where main is worse than the same Mac's release stack by "
             "more than twice the larger min-max spread of the two rows.", "",
             "ANE jobs/s compares only Macs that run the same program: each cell names it. H13 (M1 family) and H14 "
             "(M2 family) add programs differ in shape and work per job, so their rates are not a chip comparison.",
             "", "CORRECTNESS shows the greedy token digest of each check (" + "; ".join(
                 f"{c['label']}: {c['prompt_tokens']}-token prompt, {c['gen_tokens']} tokens" for c in
                 cfg.get("checks", [])) + "). Main must match the same Mac's release digest, and every rep of a "
             "stack must agree.", "",
             "| Date | Mac | Stack | mlx | Vulkan driver | REGRESSION vs release | CORRECTNESS | "
             + " | ".join(names) + " |", "|" + "---|" * (7 + len(names))]
    compared = compare(rows, cfg)
    against = vs_release(rows, cfg)
    wrong = correctness(rows)
    for r, _, cells, _ in (c for c in compared if not c[0].get("cell")):
        vals = [f"{fmt(c[0])} ({sign(c[1])}, {sign(c[2])})" if (c := cells.get(n)) else "–" for n in names]
        if r.get("ane_workload") and cells.get("ANE jobs/s"):
            vals[-1] += f" · {r['ane_workload']}"
        flags = against.get((r["date"], r["chip"])) if r["stack"] == "main" else None
        flag = ("**" + "; ".join(f"{short(n)} {d:+.1f}%" for n, d in flags) + "**") if flags else (
            "none" if flags is not None else "")
        checks = {k[len(CHECK):]: v for k, v in r.get("digests", {}).items() if k.startswith(CHECK)}
        bad = wrong.get((r["date"], r["chip"], r["stack"]), [])
        ok = "; ".join(f"{k} `{'/'.join(s[:8] for s in v)}`" for k, v in checks.items())
        verdict = ("**" + "; ".join(bad) + "**") if bad else ok
        lines.append(f"| {day(r)} | {r['chip']} | {r['stack']} | `{r['wheel']}` | `{r['driver']}` | {flag} | "
                     f"{verdict} | " + " | ".join(vals) + " |")
    lines += ["", "## Regressions", ""]
    flagged = False
    for r, prev, _, regs in compared:
        for name, d in regs:
            flagged = True
            wheel = (f"[{commit_of(prev['wheel'])}...{commit_of(r['wheel'])}]"
                     f"(https://github.com/joshuaswarren/omarchy-mlx/compare/{commit_of(prev['wheel'])}..."
                     f"{commit_of(r['wheel'])})" if prev["wheel"] != r["wheel"] else "unchanged")
            driver = (f"[{prev['driver']}...{r['driver']}](https://github.com/joshuaswarren/mesa-1/compare/"
                      f"{prev['driver']}...{r['driver']})" if prev["driver"] != r["driver"] else "unchanged")
            kernel = "changed" if prev["kernel_id"] != r["kernel_id"] else "unchanged"
            lines.append(f"- {r['date']} {r['chip']} · {r['stack']}: {name} {d:+.1f}% (mlx {wheel}; driver {driver}; "
                         f"kernel {kernel})")
    if not flagged:
        lines.append("None.")
    lines += cell_section(rows) + parity(rows, cfg)
    return "\n".join(lines) + "\n"


def cell_section(rows):
    """Server cells: each metric as off -> on with the change, per Mac and day."""
    rows = sorted((r for r in rows if r.get("cell")), key=lambda r: (r["date"], r["chip"]), reverse=True)
    if not rows:
        return []
    names = sorted({k.split(" · ", 1)[1] for r in rows for k in r["metrics"]})
    out = ["", "## Server cells", "",
           "Each cell starts a fresh server per variant, alternating the order across pairs, and runs c1 then c4 "
           "streamed requests. Only runs that passed the quiet gate (CPU idle >= 92%, PSI cpu some = 0) count. "
           "Values are medians, off -> on, with the change, where positive is better.", "",
           "| Date | Mac | Cell | Gated runs | " + " | ".join(names) + " | Greedy text (c1) |", "|" + "---|" * (5 + len(names))]
    for r in rows:
        vals = []
        for n in names:
            a, b = r["metrics"].get(f"off · {n}", {}).get("median"), r["metrics"].get(f"on · {n}", {}).get("median")
            vals.append(f"{fmt(a)} → {fmt(b)} ({sign(pct(b, a, n))})" if a and b else "–")
        text = "same off and on" if r.get("text_parity") else f"**differs**: off {r['texts'].get('off')} on " \
                                                                  f"{r['texts'].get('on')}"
        out.append(f"| {day(r)} | {r['chip']} | {r['stack']} | {r['gated_runs']}/{r['runs']} | "
                   + " | ".join(vals) + f" | {text} |")
    return out


def short(name):
    """'Qwen3-4B 4-bit · oMLX · decode tok/s' -> '4B oMLX decode'."""
    model, engine, metric = (name.split(" · ") + ["", ""])[:3]
    size = re.search(r"(\d+(?:\.\d+)?B)", model)
    return " ".join(x for x in (size[1] if size else model, engine, metric.split()[0] if metric else "") if x)


def parity(rows, cfg):
    names = [f"{m['label']} · {e['label']} · {k}" for m in cfg["models"] for e in cfg["engines"]
             for k in ("prefill tok/s", "decode tok/s")]
    refs = {r["date"]: r for r in rows if r["os"] == "macos" and not r.get("contaminated")}
    if not refs:
        return []
    out = ["", "## Linux as a percentage of the macOS reference", "",
           "The reference is upstream MLX and mlx-lm on macOS on " + ", ".join(sorted({r["chip"] for r in refs.values()}))
           + ". It is a different chip from the Linux Macs, so the percentage is a fixed yardstick, not parity on equal "
           "hardware. The reference Mac also serves live models, so its row uses the best of its reps (the highest "
           "rate, the lowest TTFT) when `stat = \"best\"`: contention only ever slows a rep.", "",
           "| Date | Mac | Stack | " + " | ".join(names) + " |", "|" + "---|" * (3 + len(names))]
    for r in rows:
        ref = refs.get(r["date"])
        if r["os"] != "linux" or r.get("cell") or not ref:
            continue
        cells = []
        for n in names:
            a, b = r["metrics"].get(n, {}).get("median"), ref["metrics"].get(n, {}).get("median")
            cells.append(f"{a / b * 100:.0f}%" if a and b else "–")
        out.append(f"| {day(r)} | {r['chip']} | {r['stack']} | " + " | ".join(cells) + " |")
    return out


def day(r):
    """The row's ledger day, marked when the row was measured after that day's run (a Mac that was out of service),
    found contaminated (another workload shared the machine), or taken from fewer reps than planned because the
    shared reference Mac's GPU was busy."""
    skipped = len(r.get("skipped_busy") or [])
    marks = (["late"] if r.get("late") else []) + (
        [f"CONTAMINATED: {r['contaminated']}"] if r.get("contaminated") else []) + (
        [f"{r['reps']} of {r['reps'] + skipped} reps: GPU busy"] if skipped and r.get("reps") else [])
    return r["date"] + "".join(f" **({m})**" if m.startswith("CONTAMINATED") else f" ({m})" for m in marks)


def mark_cmd(date, chip, stack, reason):
    """Mark one row contaminated: it stays on the page, flagged, and is never a baseline or a parity reference."""
    cfg, rows = load_config(), load_rows()
    hit = [r for r in rows if r["date"] == date and r["chip"] == chip and r["stack"] == stack]
    if not hit:
        raise SystemExit(f"no row {date} / {chip} / {stack}")
    hit[0]["contaminated"] = reason
    save(rows, cfg)
    print(DOCS / "LEDGER.md")


def summary(rows, cfg, date):
    """Five lines for the operator: what ran, one headline per Mac, and the regressions."""
    today = [c for c in compare(rows, cfg) if c[0]["date"] == date]
    head, eng = cfg["models"][0]["label"], cfg["engines"][0]["label"]
    n = f"{head} · {eng} · decode tok/s"
    lines = [f"ledger {date}: {len(today)} rows ({', '.join(sorted({c[0]['stack'] for c in today}))}), "
             f"median of {cfg.get('reps', 3)} reps"]
    for chip in sorted({c[0]["chip"] for c in today if c[0]["os"] == "linux"})[:3]:
        bits = [f"{r['stack']} {fmt(cells[n][0])} ({sign(cells[n][1])})" for r, _, cells, _ in today
                if r["chip"] == chip and n in cells]
        lines.append(f"{chip}: {head} {eng} decode tok/s " + ", ".join(bits))
    regs = [f"CORRECTNESS {chip} {stack}: {p}" for (day, chip, stack), problems in correctness(rows).items()
            if day == date for p in problems]
    regs += [f"{c[0]['chip']} {c[0]['stack']} {name} {d:+.1f}%" for c in today for name, d in c[3]]
    regs += [f"{chip} main<release {short(name)} {d:+.1f}%" for (day, chip), flags in vs_release(rows, cfg).items()
             if day == date for name, d in flags]
    lines.append(f"regressions >{FLAG_PCT:g}%: " + ("; ".join(regs[:4]) + (" …" if len(regs) > 4 else "")
                                                  if regs else "none"))
    return lines[:5]


def load_config(path=CONFIG):
    if not Path(path).exists():
        raise SystemExit(f"no ledger suite: copy ledger.example.toml to {path} and edit it")
    return tomllib.loads(Path(path).read_text())


def load_rows():
    return json.loads((DOCS / "ledger.json").read_text()) if (DOCS / "ledger.json").exists() else []


def save(rows, cfg):
    (DOCS / "ledger.json").write_text(json.dumps(rows, indent=1) + "\n")
    (DOCS / "LEDGER.md").write_text(render(rows, cfg))


def measure_cell(cfg, target, cell, log):
    """One server cell on one Mac (cells.py), as a ledger row keyed by the cell's label."""
    host = remote.resolve(target["host"])
    base = target.get("base", cfg["base"])
    stack = next(s for s in cfg["stacks"] if s["label"] == cell["stack"])
    driver = f"{base}/{stack['driver']}"
    info = stack_info(host, f"{base}/{stack['venv']}/bin/python", driver)
    if not info:
        log(f"{cell['label']}: stack {stack['label']} missing; skipped")
        return None
    out = cells.measure(cfg, target, cell, stack, driver, log)
    if not out:
        return None
    return {"chip": host.get("chip", host["name"]), "os": "linux", "stack": cell["label"], "cell": True, **info,
            "reps": out["gated_runs"], "kernel_warnings": 0, "failed_steps": [], **out}


def merger(cfg, date, log=lambda msg: print(msg, flush=True)):
    lock = threading.Lock()

    def merge(row):
        """Threads share `lock`; a second `coreglass ledger` process shares the flock on ledger.lock. A rerun never
        replaces a clean row of the same day with one that has fewer good reps."""
        with lock, open(DOCS / "ledger.lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            key = (date, row["chip"], row["stack"])
            rows = load_rows()
            old = next((r for r in rows if (r["date"], r["chip"], r["stack"]) == key), None)
            if old and not old.get("contaminated") and old.get("reps", 0) > row.get("reps", 0):
                log(f"kept {key}: it has {old['reps']} good reps, the rerun {row.get('reps', 0)}")
                return
            save([r for r in rows if (r["date"], r["chip"], r["stack"]) != key] + [{"date": date, **row}], cfg)
    return merge


def run_cmd(only, reference, stacks=(), log=lambda msg: print(msg, flush=True), cells_only=False, late=False):
    """Every target and the reference in parallel (each Mac queues on its own GPU), stacks then server cells in order
    per target. Each finished row is merged into the ledger at once, so a late or failed target never loses others.
    `late` marks rows measured after the day's run (a Mac that was out of service at 10:00 UTC)."""
    cfg = load_config()
    date = ledger_day(datetime.now(timezone.utc))
    put = merger(cfg, date)
    merge = (lambda row: put({**row, "late": True})) if late else put

    def target_job(target):
        say = lambda msg: log(f"[{target['host']}] {msg}")
        for stack in [] if cells_only else cfg["stacks"]:
            if (not stacks or stack["label"] in stacks) and (row := measure_linux(cfg, target, stack, say)):
                merge(row)
        for cell in cfg.get("cells", []):
            if row := measure_cell(cfg, target, cell, say):
                merge(row)

    jobs = [lambda t=t: target_job(t) for t in cfg["targets"] if not only or t["host"] in only]
    if reference and cfg.get("reference") and not cells_only:
        jobs.append(lambda: merge(measure_macos(cfg, cfg["reference"], lambda msg: log(f"[reference] {msg}"))))
    with ThreadPoolExecutor(max_workers=len(jobs) or 1) as ex:
        for f in [ex.submit(j) for j in jobs]:
            f.result()
    for line in summary(load_rows(), cfg, date):
        print(line, flush=True)


def add_cmd(host_name, stack_label, captures):
    """Merge a row built from finished ledger captures (when a run measured but never merged), dated by capture."""
    cfg = load_config()
    stack = next(s for s in cfg["stacks"] if s["label"] == stack_label)
    target = next(t for t in cfg["targets"] if t["host"] == host_name)
    host, base = remote.resolve(host_name), target.get("base", cfg["base"])
    info = stack_info(host, f"{base}/{stack['venv']}/bin/python", f"{base}/{stack['driver']}")
    if not info:
        raise SystemExit(f"{host_name} {stack_label}: stack missing")
    measured = [capture_metrics(c) for c in captures]
    reps = [r for r in measured if valid(target, r[3])]
    rejected = [round(r[3], 1) for r in measured if not valid(target, r[3])]
    if not reps:
        raise SystemExit(f"{host_name} {stack_label}: every capture failed the idle check {rejected}")
    stamp = re.search(r"\d{8}T\d{6}Z", Path(captures[0]).name)[0]
    merger(cfg, ledger_day(datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")))(
        {"chip": host.get("chip", host["name"]), "os": "linux", "stack": stack_label, **info, "reps": len(reps),
         "rejected_idle_w": rejected, "kernel_warnings": sum(r[1] for r in reps),
         "failed_steps": sorted({b for r in reps for b in r[2]}), "metrics": summarize([r[0] for r in reps]),
         "digests": digest_sets([r[4] for r in reps])})
    print(DOCS / "LEDGER.md")


def render_cmd():
    cfg = load_config()
    rows = load_rows()
    save(rows, cfg)
    print(DOCS / "LEDGER.md")
