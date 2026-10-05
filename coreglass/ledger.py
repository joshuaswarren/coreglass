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
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import remote

CONFIG = Path.home() / ".config/coreglass/ledger.toml"
DOCS = Path(__file__).resolve().parent.parent / "docs"
CAPTURES = Path.home() / ".local/share/coreglass/captures"
LLM_KEYS = (("prefill_tok_s", "prefill tok/s"), ("ttft_ms", "TTFT ms"), ("decode_tok_s", "decode tok/s"))
LOWER_IS_BETTER = ("TTFT ms",)
FLAG_PCT = 1.0


def metric_names(cfg):
    names = [f"{m['label']} · {e['label']} · {k}" for m in cfg["models"] for e in cfg["engines"] for _, k in LLM_KEYS]
    return names + ["GPU matmul TFLOPS", "ANE jobs/s"]


def llm_runs(cfg, base, stack):
    runs = []
    for m in cfg["models"]:
        for e in cfg["engines"]:
            run = {"label": f"{m['label']} · {e['label']}", "model": f"{base}/{m['dir']}",
                   "engine": e.get("engine", "in-process")}
            if e.get("overlay") and stack.get("overlay"):
                run["env"] = {"PYTHONPATH": f"{base}/{stack['overlay']}"}
            runs.append(run)
    return runs


def stack_info(host, python, driver):
    """mlx version, the Vulkan driver the loader actually picks for this stack (vulkaninfo driverInfo, e.g.
    "Mesa 26.3.0-devel (git-6dc1fba8e9)"), and a short hash of the kernel release (the page names no kernels)."""
    icd = shlex.quote(f"{driver}/honeykrisp_icd.aarch64.json")
    p = remote.ssh(host, f"{shlex.quote(python)} -c 'import mlx.core as m; print(m.__version__)' && uname -r && "
                         f"VK_DRIVER_FILES={icd} vulkaninfo --summary 2>/dev/null | sed -n 's/.*driverInfo *= *//p' "
                         "| head -1", timeout=60)
    lines = p.stdout.splitlines() if p.returncode == 0 else []
    if len(lines) < 3 or not lines[2].strip():
        return None
    info = lines[2].strip()
    sha = re.search(r"git-([0-9a-f]+)", info)
    return {"wheel": lines[0].strip(), "driver": sha[1] if sha else info, "driver_info": info,
            "kernel_id": hashlib.sha1(lines[1].strip().encode()).hexdigest()[:8]}


def capture_metrics(capture):
    man = json.loads(Path(capture).with_suffix(".run.json").read_text())
    out = {}
    for s in man["steps"]:
        if s["rc"]:
            continue
        if s.get("result"):
            for key, name in LLM_KEYS:
                out[f"{s['label']} · {name}"] = s["result"][key]
        elif s["label"] == "GPU matmul" and (m := re.search(r"tflops=([\d.]+)", s["stdout_tail"])):
            out["GPU matmul TFLOPS"] = float(m[1])
    ane = next((p for p in remote.phases(capture)["phases"] if p["phase"] == "ANE"), None)
    if ane and ane.get("ane_jobs_s"):
        out["ANE jobs/s"] = ane["ane_jobs_s"]
    return out, sum(len(s["kernel"]) for s in man["steps"]), [s["label"] for s in man["steps"] if s["rc"]]


def summarize(reps):
    keys = sorted({k for r in reps for k in r})
    return {k: {"median": round(statistics.median(vs), 2), "min": min(vs), "max": max(vs), "n": len(vs)}
            for k in keys if (vs := [r[k] for r in reps if k in r])}


def measure_linux(cfg, target, stack, log):
    host = remote.resolve(target["host"])
    base = target.get("base", cfg["base"])
    python, driver = f"{base}/{stack['venv']}/bin/python", f"{base}/{stack['driver']}"
    info = stack_info(host, python, driver)
    if not info:
        log(f"{host['name']} {stack['label']}: stack missing ({python}, {driver}); skipped")
        return None
    over = {"mlx_python": python, "llm_runs": llm_runs(cfg, base, stack),
            "env": {**host.get("env", {}), "VK_DRIVER_FILES": f"{driver}/honeykrisp_icd.aarch64.json"}}
    if host.get("gpu_turn") and cfg.get("turn_minutes"):
        over["gpu_turn"] = re.sub(r"-m \d+", f"-m {cfg['turn_minutes']}", host["gpu_turn"])
    turn = None
    if host.get("gpu_turn"):  # one ticket for all reps: a queue full of long tickets would multiply the wait
        try:
            turn = remote.acquire({**host, **over}, remote_wait(cfg), log)
        except SystemExit as e:
            log(f"{host['name']} {stack['label']}: {e}")
            return None
    reps, warnings, failed = [], 0, []
    try:
        for i in range(cfg.get("reps", 3)):
            stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
            record = str(CAPTURES / f"ledger-{host['name']}-{stack['label']}-{stamp}.jsonl")
            try:
                remote.run_cmd(target["host"], [], [], True, 10, None, False, False, 8, 4, 10, record, log=log,
                               wait=remote_wait(cfg), overrides=over, turn=turn)
            except SystemExit as e:
                log(f"{host['name']} {stack['label']} rep {i + 1}: {e}")
                continue
            metrics, warn, bad = capture_metrics(record)
            reps.append(metrics)
            warnings += warn
            failed += bad
    finally:
        if turn:
            remote.release(host, turn)
    if not reps:
        return None
    return {"chip": host.get("chip", host["name"]), "os": "linux", "stack": stack["label"], **info,
            "reps": len(reps), "kernel_warnings": warnings, "failed_steps": sorted(set(failed)),
            "metrics": summarize(reps)}


def measure_macos(cfg, ref, log):
    base = ref["base"]
    host = {"name": "reference", "ssh": ref["ssh"], "mlx_python": f"{base}/{ref['venv']}/bin/python",
            "llm_runs": llm_runs(cfg, base, {})}
    steps = [s for s in remote.probe_steps(host, {"clusters": []}, 10) if s[2]]
    reps = []
    for i in range(cfg.get("reps", 3)):
        out = {}
        for label, cmd, _ in steps:
            p = remote.ssh(host, "bash -s", cmd, timeout=1800)
            res = next((json.loads(ln) for ln in reversed(p.stdout.splitlines()) if ln.startswith(remote.RESULT)), None)
            if res:
                for key, name in LLM_KEYS:
                    out[f"{label} · {name}"] = res["coreglass_result"][key]
            elif m := re.search(r"tflops=([\d.]+)", p.stdout):
                out["GPU matmul TFLOPS"] = float(m[1])
            else:
                log(f"reference {label} rep {i + 1}: rc {p.returncode} {p.stderr.strip()[-160:]}")
        reps.append(out)
    p = remote.ssh(host, f"{shlex.quote(host['mlx_python'])} -c 'import mlx.core as m; print(m.__version__)'; "
                         "sw_vers -productVersion", timeout=60)
    ver, os_ver = (p.stdout.split() + ["-", "-"])[:2]
    return {"chip": ref["chip"], "os": "macos", "stack": "macOS reference", "wheel": f"mlx {ver}",
            "driver": f"Metal (macOS {os_ver})", "kernel_id": "-", "reps": len(reps), "kernel_warnings": 0,
            "failed_steps": [], "metrics": summarize(reps)}


def remote_wait(cfg):
    return float(cfg.get("wait_seconds", 3 * 3600))


def pct(new, old, name):
    """Signed change in percent, positive = better."""
    if not old:
        return None
    change = (new - old) / old * 100
    return -change if name.endswith(LOWER_IS_BETTER) else change


def compare(rows, cfg):
    """Per row: the change of every metric against the previous day and the best earlier day, and regressions."""
    out = []
    for r in rows:
        earlier = sorted((x for x in rows if (x["chip"], x["stack"]) == (r["chip"], r["stack"])
                          and x["date"] < r["date"]), key=lambda x: x["date"])
        prev = earlier[-1] if earlier else None
        cells, regressions = {}, []
        for name in metric_names(cfg):
            v = r["metrics"].get(name, {}).get("median")
            if v is None:
                continue
            past = [x["metrics"][name]["median"] for x in earlier if name in x["metrics"]]
            best = (min if name.endswith(LOWER_IS_BETTER) else max)(past) if past else None
            d_prev = pct(v, prev["metrics"][name]["median"], name) if prev and name in prev["metrics"] else None
            cells[name] = (v, d_prev, pct(v, best, name) if best is not None else None)
            if d_prev is not None and d_prev < -FLAG_PCT:
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
             "Run every day at 10:00 UTC by `coreglass ledger run`. The suite is frozen: "
             + ", ".join(m["label"] for m in cfg["models"]) + "; engines " + ", ".join(e["label"] for e in cfg["engines"])
             + f"; one cold greedy request each ({cfg.get('prompt_note', 'about 477 prompt + 128 generated tokens')}); "
             f"median of {cfg.get('reps', 3)} reps. Each cell is the median, then the change against the previous "
             "day and against the best earlier day, where positive is better. TTFT is lower-is-better.", "",
             f"Regressions over {FLAG_PCT:g}% against the previous day are listed under the table with the commit "
             "range that could explain them. One cold request per rep moves by a few percent from run to run, so "
             "check the min-max spread in `docs/ledger.json` before you act on a flag.", "",
             "| Date | Mac | Stack | mlx | Vulkan driver | " + " | ".join(names) + " |",
             "|" + "---|" * (5 + len(names))]
    compared = compare(rows, cfg)
    for r, _, cells, _ in compared:
        vals = [f"{fmt(c[0])} ({sign(c[1])}, {sign(c[2])})" if (c := cells.get(n)) else "–" for n in names]
        lines.append(f"| {r['date']} | {r['chip']} | {r['stack']} | `{r['wheel']}` | `{r['driver']}` | "
                     + " | ".join(vals) + " |")
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
    lines += parity(rows, cfg)
    return "\n".join(lines) + "\n"


def parity(rows, cfg):
    names = [f"{m['label']} · {e['label']} · {k}" for m in cfg["models"] for e in cfg["engines"]
             for k in ("prefill tok/s", "decode tok/s")]
    refs = {r["date"]: r for r in rows if r["os"] == "macos"}
    if not refs:
        return []
    out = ["", "## Linux as a percentage of the macOS reference", "",
           "The reference is upstream MLX and mlx-lm on macOS on " + ", ".join(sorted({r["chip"] for r in refs.values()}))
           + ". It is a different chip from the Linux Macs, so the percentage is a fixed yardstick, not parity on equal "
           "hardware.", "", "| Date | Mac | Stack | " + " | ".join(names) + " |", "|" + "---|" * (3 + len(names))]
    for r in rows:
        ref = refs.get(r["date"])
        if r["os"] != "linux" or not ref:
            continue
        cells = []
        for n in names:
            a, b = r["metrics"].get(n, {}).get("median"), ref["metrics"].get(n, {}).get("median")
            cells.append(f"{a / b * 100:.0f}%" if a and b else "–")
        out.append(f"| {r['date']} | {r['chip']} | {r['stack']} | " + " | ".join(cells) + " |")
    return out


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
    regs = [f"{c[0]['chip']} {c[0]['stack']} {name} {d:+.1f}%" for c in today for name, d in c[3]]
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


def run_cmd(only, reference, log=lambda msg: print(msg, flush=True)):
    """Every target and the reference in parallel (each Mac queues on its own GPU), stacks in order per target.
    Each finished row is merged into the ledger at once, so a late or failed target never loses the others."""
    cfg = load_config()
    date = f"{datetime.now(timezone.utc):%Y-%m-%d}"
    lock = threading.Lock()

    def merge(row):
        """Threads share `lock`; a second `coreglass ledger run` (a late Mac) shares the flock on ledger.lock."""
        with lock, open(DOCS / "ledger.lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            key = (date, row["chip"], row["stack"])
            save([r for r in load_rows() if (r["date"], r["chip"], r["stack"]) != key] + [{"date": date, **row}], cfg)

    def target_job(target):
        say = lambda msg: log(f"[{target['host']}] {msg}")
        for stack in cfg["stacks"]:
            if row := measure_linux(cfg, target, stack, say):
                merge(row)

    jobs = [lambda t=t: target_job(t) for t in cfg["targets"] if not only or t["host"] in only]
    if reference and cfg.get("reference"):
        jobs.append(lambda: merge(measure_macos(cfg, cfg["reference"], lambda msg: log(f"[reference] {msg}"))))
    with ThreadPoolExecutor(max_workers=len(jobs) or 1) as ex:
        for f in [ex.submit(j) for j in jobs]:
            f.result()
    for line in summary(load_rows(), cfg, date):
        print(line, flush=True)


def render_cmd():
    cfg = load_config()
    rows = load_rows()
    save(rows, cfg)
    print(DOCS / "LEDGER.md")
