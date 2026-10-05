"""Target hosts: preflight checks and scripted capture runs (`coreglass hosts`, `coreglass run`)."""

import json
import shlex
import subprocess
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from .live import Session

HOSTS_FILE = Path.home() / ".config/coreglass/hosts.toml"

PREFLIGHT = r"""
import fcntl, glob, json, os, platform, subprocess, sys
lock, mlx, patterns, unit = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
def held(p):
    if not p or not os.path.exists(p):
        return False
    with open(p) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
        except BlockingIOError:
            return True
busy = []
for d in os.listdir("/proc"):
    if d.isdigit() and int(d) != os.getpid():
        try:
            cmd = open(f"/proc/{d}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            continue
        if any(k in cmd for k in patterns + ["coreglass-spin"]):
            busy.append(" ".join(cmd.split())[:100])
model = open("/proc/device-tree/model").read().strip("\0\n") if os.path.exists("/proc/device-tree/model") else ""
stats = {name: any(os.access(p, os.R_OK) for p in glob.glob(pat)) for name, pat in
         (("agx_stats", "/sys/class/drm/card*/device/agx_stats"), ("ane_stats", "/sys/class/accel/accel*/device/ane_stats"))}
accel = sorted({os.path.basename(os.path.realpath(p)) for p in glob.glob("/sys/class/accel/accel*/device/driver")})
print(json.dumps({"hostname": platform.node(), "arch": platform.machine(), "model": model,
                  "kernel": platform.release(), "python": platform.python_version(),
                  "load1": os.getloadavg()[0], "gpu_lock_held": held(lock), "busy": busy[:3],
                  "mlx_python": bool(mlx) and os.access(mlx, os.X_OK), "stats": [k for k, v in stats.items() if v],
                  "accel": accel,
                  "yield_active": bool(unit) and subprocess.run(["systemctl", "is-active", "--quiet", unit]).returncode == 0}))
"""

SPIN = "for c in {cpus}; do timeout {secs} taskset -c $c sh -c 'while :; do :; done' coreglass-spin & done; wait || true"
MATMUL = """{py} - <<'PY'
import os, time
open("/tmp/coreglass-watch.pid", "w").write(str(os.getpid()))
import mlx.core as mx
a = mx.random.normal((4096, 4096)).astype(mx.float16)
b = mx.random.normal((4096, 4096)).astype(mx.float16)
mx.eval(a, b)
end, n = time.time() + {secs}, 0
while time.time() < end:
    mx.eval(a @ b)
    n += 1
print(f"matmuls={{n}} tflops={{n * 2 * 4096**3 / {secs} / 1e12:.2f}}", flush=True)
PY"""
ANE = """end=$(( $(date +%s) + {secs} )); n=0
while [ "$(date +%s)" -lt "$end" ]; do {lock}sh -c {cmd} >/dev/null || exit 3; n=$((n + 1)); done
echo ane_batches=$n"""
LLM = "{py} - {model} {prompt} {gen} <<'PY'\n{script}\nPY"
LLMSTEP = Path(__file__).with_name("llmstep.py")
SERVE = "{py} - {cmd} {model} {prompt} {gen} <<'PY'\n{script}\nPY"
SERVESTEP = Path(__file__).with_name("servestep.py")
# One request at a time and no cross-run cache, so every engine starts cold (Omarchy's launcher uses the same
# concurrency flags for mlx_lm.server).
SERVERS = {"mlx-lm": "{py} -m mlx_lm.server --model {model} --host 127.0.0.1 --port {{port}} "
                     "--decode-concurrency 1 --prompt-concurrency 1",
           "omlx": "{bin}/omlx serve --model-dir {model_dir} --host 127.0.0.1 --port {{port}} --no-cache"}
RESULT = '{"coreglass_result"'


def load_hosts():
    """Targets live only in the user's ~/.config/coreglass/hosts.toml (see hosts.example.toml)."""
    if not HOSTS_FILE.exists():
        return {}, HOSTS_FILE
    return {name: {"name": name, **cfg} for name, cfg in tomllib.loads(HOSTS_FILE.read_text()).items()}, HOSTS_FILE


def resolve(name):
    hosts, _ = load_hosts()
    return hosts.get(name) or next((h for h in hosts.values() if h["ssh"] == name), None) or {"name": name, "ssh": name}


def ssh(host, cmd, stdin="", timeout=120):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host["ssh"], cmd],
                          input=stdin, text=True, capture_output=True, timeout=timeout)


def preflight(host):
    args = " ".join(shlex.quote(host.get(k, "")) for k in ("gpu_lock", "mlx_python"))
    args += " " + shlex.quote(json.dumps(host.get("busy_patterns", []))) + " " + shlex.quote(host.get("yield_service", ""))
    try:
        p = ssh(host, f"python3 - {args}", PREFLIGHT, timeout=30)
    except subprocess.TimeoutExpired:
        return {"reachable": False, "error": "timeout"}
    if p.returncode:
        return {"reachable": False, "error": (p.stderr.strip().splitlines() or ["ssh failed"])[-1]}
    return {"reachable": True, **json.loads(p.stdout)}


def blockers(pf, host=None):
    """Reasons not to start a run. A held GPU lock does not block while the host's `yield_service` is active: that
    resident server owns the lock, and the run stops it first. An inactive unit means someone else holds the lock."""
    out = []
    if not pf["reachable"]:
        out.append(f"unreachable: {pf['error']}")
    else:
        if pf["gpu_lock_held"] and not ((host or {}).get("yield_service") and pf.get("yield_active")):
            out.append("GPU lock held by another job")
        if pf["load1"] >= 0.5:
            out.append(f"not quiet: load1 {pf['load1']:.2f} >= 0.5")
        if pf["busy"]:
            out.append(f"lab job running: {pf['busy'][0]}")
    return out


def hosts_cmd(names):
    hosts, path = load_hosts()
    if not hosts and not names:
        raise SystemExit(f"no targets: copy hosts.example.toml to {path} and edit it, or pass ssh aliases")
    print(f"hosts from {path}" if hosts else "hosts: ssh aliases from the command line")
    for name in names or list(hosts):
        h = resolve(name)
        pf = preflight(h)
        state = "; ".join(blockers(pf, h)) or "ready"
        if pf.get("gpu_lock_held") and pf.get("yield_active") and state == "ready":
            state = f"ready (run pauses {h['yield_service']})"
        if pf["reachable"]:
            print(f"{h['name']:<8} {h['ssh']:<14} {pf['arch']:<8} {pf['model'][:44]:<44} load1 {pf['load1']:.2f}  "
                  f"mlx {'yes' if pf['mlx_python'] else 'no':<3}  stats {','.join(pf['stats']) or '-':<19}  {state}")
        else:
            print(f"{h['name']:<8} {h['ssh']:<14} {state}")


def probe_steps(host, meta, secs):
    """Built-in steps: spin every P core, spin every E core, an MLX matmul under the GPU lock, one real LLM
    request per `llm_runs` entry (in process or through a server; default: in process with `mlx_python`), then
    the host's `ane_cmd` in a loop under the GPU lock (and `ane_lock`, when set)."""
    by = {c["label"]: c["cpus"] for c in meta["clusters"]}
    p = [c for lab, cs in by.items() if lab != "E" for c in cs]
    steps = [("P spin", SPIN.format(cpus=" ".join(map(str, p)), secs=secs), False)] if p and "E" in by else []
    if "E" in by:
        steps.append(("E spin", SPIN.format(cpus=" ".join(map(str, by["E"])), secs=secs), False))
    if not steps:
        steps.append(("CPU spin", SPIN.format(cpus=" ".join(map(str, p)), secs=secs), False))
    if host.get("mlx_python"):
        steps.append(("GPU matmul", MATMUL.format(py=host["mlx_python"], secs=secs + 5), True))
    if host.get("llm_model"):
        model = host["llm_model"]
        sizes = {"prompt": int(host.get("llm_prompt_tokens", 512)), "gen": int(host.get("llm_gen_tokens", 128))}
        for run in host.get("llm_runs") or [{"label": "LLM"}]:
            py, engine = run.get("python") or host["mlx_python"], run.get("engine", "in-process")
            env = "".join(f"{k}={shlex.quote(str(v))} " for k, v in run.get("env", {}).items())
            if engine == "in-process":
                cmd = LLM.format(py=env + py, model=shlex.quote(model), script=LLMSTEP.read_text(), **sizes)
            else:
                server = SERVERS[engine].format(py=py, bin=shlex.quote(str(Path(py).parent)), model=shlex.quote(model),
                                                model_dir=shlex.quote(str(Path(model).parent)))
                cmd = SERVE.format(py=py, cmd=shlex.quote(f"env {env}{server}" if env else server),
                                   model=shlex.quote(model), script=SERVESTEP.read_text(), **sizes)
            steps.append((run["label"], cmd, True))
    if host.get("ane_cmd"):
        lock = f"flock -w 60 {shlex.quote(host['ane_lock'])} " if host.get("ane_lock") else ""
        steps.append(("ANE", ANE.format(secs=secs, lock=lock, cmd=shlex.quote(host["ane_cmd"])), True))
    return steps


def kernel_log(host, since):
    """Kernel warnings and errors since `since` (unix s) on the target, firewall noise dropped."""
    p = ssh(host, f"journalctl -k -q --no-pager -p warning --since @{int(since)} -o short-iso", timeout=30)
    return [ln for ln in p.stdout.splitlines() if "UFW BLOCK" not in ln][-20:]


def wait_ready(host, seconds, log, poll=60):
    """Poll the preflight until the host has no blockers or `seconds` pass. The run then checks again itself."""
    deadline, last = time.time() + seconds, None
    while time.time() < deadline:
        problems = blockers(preflight(host), host)
        if not problems:
            return
        if problems != last:
            log(f"waiting up to {(deadline - time.time()) / 60:.0f} min: {'; '.join(problems)}")
            last = problems
        time.sleep(min(poll, max(0.0, deadline - time.time())))


def run_cmd(name, steps, gpu_steps, probe, hz, port, serve, force, baseline, gap, secs, record,
            attach=None, log=lambda msg: print(msg, flush=True), cancel=None, wait=0):
    """Capture `name` while running marked steps. `attach(session)` lets a GUI show the stream;
    `cancel` (a threading.Event) stops before the next step; `wait` seconds lets a busy host become ready first."""
    host = resolve(name)
    if wait and not force:
        wait_ready(host, wait, log)
    unit = host.get("yield_service")
    stopped = False
    if unit:
        pf = preflight(host)
        problems = blockers(pf, host)
        if problems and (not force or not pf["reachable"]):
            raise SystemExit(f"{host['name']}: refusing to run: {'; '.join(problems)} (use --force to override)")
        if pf.get("yield_active"):
            log(f"stopping {unit} for the run")
            p = ssh(host, f"sudo -n systemctl stop {shlex.quote(unit)}", timeout=180)
            if p.returncode:
                raise SystemExit(f"{host['name']}: could not stop {unit}: {p.stderr.strip()[-200:]}")
            stopped = True
    try:
        return _run(host, steps, gpu_steps, probe, hz, port, serve, force, baseline, gap, secs, record, attach, log,
                    cancel)
    finally:
        if stopped:  # restore only what this run changed
            p = ssh(host, f"sudo -n systemctl start {shlex.quote(unit)}", timeout=300)
            log(f"started {unit} again: rc {p.returncode}")


def _run(host, steps, gpu_steps, probe, hz, port, serve, force, baseline, gap, secs, record, attach, log, cancel):
    pf = preflight(host)
    problems = blockers(pf)  # after a yield: a lock still held now is another job's
    if problems and (not force or not pf["reachable"]):
        raise SystemExit(f"{host['name']}: refusing to run: {'; '.join(problems)} (use --force to override)")
    stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    record = record or f"captures/{host['name']}-{stamp}.jsonl"
    session = Session(host["ssh"], hz, record, port if serve else None).start()
    if attach:
        attach(session)
    if serve:
        log(f"live: http://127.0.0.1:{port}/")
    plan = [(lab, cmd, False) for lab, cmd in steps] + [(lab, cmd, True) for lab, cmd in gpu_steps]
    if probe or not plan:
        plan = probe_steps(host, session.meta, secs) + plan
    done = []
    wait = (lambda s: cancel.wait(s)) if cancel else time.sleep
    try:
        log(f"baseline {baseline:g} s")
        wait(baseline)
        for label, cmd, gpu in plan:
            if cancel and cancel.is_set():
                log("cancelled")
                break
            if gpu and not host.get("gpu_lock"):
                raise SystemExit(f"{host['name']}: GPU step '{label}' needs gpu_lock in the hosts file")
            script = f"flock -w 60 {shlex.quote(host['gpu_lock'])} bash -s <<'COREGLASS'\n{cmd}\nCOREGLASS" if gpu else cmd
            log(f"{label} …")
            session.mark(label)
            t0, w0 = session.hub.t, time.time()
            p = ssh(host, "bash -s", script, timeout=3600)
            session.mark("idle")
            step = {"label": label, "gpu": gpu, "cmd": cmd[:400], "rc": p.returncode, "start_unix": w0,
                    "end_unix": time.time(), "t_start": t0, "t_end": session.hub.t,
                    "stdout_tail": p.stdout[-400:], "stderr_tail": p.stderr[-400:], "kernel": kernel_log(host, w0)}
            res = next((json.loads(ln) for ln in reversed(p.stdout.splitlines()) if ln.startswith(RESULT)), None)
            if res:
                step["result"] = res["coreglass_result"]
                start = session.meta["started"]
                session.hub.publish(json.dumps({"tokens": {"label": label, "t": [round(u - start, 3)
                                                                                  for u in res["token_unix"]]}}))
                step["stdout_tail"] = ""
            done.append(step)
            summary = " ".join(f"{k}={v}" for k, v in res["coreglass_result"].items()) if res else p.stdout.strip()[-120:]
            log(f"{label}: rc={p.returncode} {summary}" + (f" · {len(step['kernel'])} kernel warnings" if step["kernel"] else ""))
            wait(gap)
        wait(baseline)
    finally:
        session.stop()
    manifest = {"schema": "coreglass/run/v1", "host": host, "preflight": pf, "forced_over": problems,
                "capture": record, "samples": session.hub.count, "seconds": session.hub.t, "steps": done,
                "coreglass_commit": _commit()}
    Path(record).with_suffix(".run.json").write_text(json.dumps(manifest, indent=1))
    log(f"{record}: {session.hub.count} samples, {session.hub.t:.1f} s; manifest {Path(record).with_suffix('.run.json')}")
    return record


def _commit():
    try:
        return subprocess.run(["git", "-C", str(Path(__file__).parent), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def phases(capture):
    """Per-phase means of a capture: the idle baseline, then each step of its .run.json (or each mark span),
    plus each step's workload result with derived energy, bandwidth, and host cost per token.

    This is the mechanical check for the producer acceptance items in docs/DESIGN.md.
    """
    lines = [json.loads(ln) for ln in Path(capture).read_text().splitlines() if ln.strip()]
    meta = next(m["meta"] for m in lines if "meta" in m)
    samples = [m for m in lines if "cpu" in m]
    tokens = {m["tokens"]["label"]: m["tokens"]["t"] for m in lines if "tokens" in m}
    manifest = Path(capture).with_suffix(".run.json")
    steps = json.loads(manifest.read_text())["steps"] if manifest.exists() else []
    if steps:
        spans = [(s["label"], s["t_start"], s["t_end"]) for s in steps]
    else:
        marks = [m for m in lines if "mark" in m]
        ends = [m["t"] for m in marks[1:]] + [samples[-1]["t"]]
        spans = [(m["mark"], m["t"], z) for m, z in zip(marks, ends) if m["mark"] != "idle"]
    by = {c["label"]: c["cpus"] for c in meta["clusters"]}
    p_cpus = [c for lab, cs in by.items() if lab != "E" for c in cs]
    rail = next((r for r in meta["rails"] if "heatpipe" in r.lower()), None)
    system = next((r for key in ("total system", "ac input", "heatpipe") for r in meta["rails"] if key in r.lower()), None)

    def mean(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 3) if xs else None

    def within(a, z, pad=0.5):
        return [s for s in samples if a + pad < s["t"] < z - pad]

    def summarize(label, a, z):
        ss = within(a, z)
        sy = lambda k: mean([s.get("sys", {}).get(k) for s in ss])
        pr = lambda k: mean([s.get("proc", {}).get(k) for s in ss])
        row = {"phase": label, "n": len(ss), "seconds": round(z - a, 1),
               "p_busy": mean([mean([s["cpu"][i] for i in p_cpus]) for s in ss]),
               "e_busy": mean([mean([s["cpu"][i] for i in by["E"]]) for s in ss]) if "E" in by else None,
               "gpu_fw_irq_s": mean([s["irq"].get("gpu_fw", 0.0) for s in ss]) if "gpu_fw" in meta["irq"] else None,
               "heatpipe_w": mean([s["w"].get(rail, 0.0) for s in ss]) if rail else None,
               "ctx_s": sy("ctx_s"), "run_q": sy("run"), "disk_rd_mb_s": sy("rd_mb_s"), "majflt_s": sy("majflt_s"),
               "proc_cpu": pr("cpu"), "proc_wait": pr("wait")}
        for e in meta.get("engines", []):
            row[f"{e}_busy"] = mean([s.get("eng", {}).get(e, {}).get("busy", 0.0) for s in ss])
            row[f"{e}_jobs_s"] = mean([s.get("eng", {}).get(e, {}).get("jobs_s", 0.0) for s in ss])
        return row

    results = []
    for s in steps:
        if "result" not in s:
            continue
        r, t = dict(s["result"]), tokens.get(s["label"], [])
        dec = within(t[1], t[-1], pad=0) if len(t) > 2 else []
        tps = r.get("decode_tok_s") or 0
        watts = mean([x["w"].get(system) for x in dec]) if system else None
        cpu = mean([x.get("proc", {}).get("cpu") for x in dec])
        r.update({"label": s["label"], "kernel_warnings": len(s.get("kernel", [])), "decode_samples": len(dec),
                  "system_w": watts, "j_per_token": round(watts / tps, 3) if watts and tps else None,
                  "host_cpu_ms_per_token": round(cpu / tps * 1000, 2) if cpu is not None and tps else None,
                  "weights_gb_s_modeled": round(r["weights_gb"] * tps, 1) if r.get("weights_gb") and tps else None,
                  # A server that packs several tokens per chunk has chunk gaps, not token gaps.
                  "token_gap_ms_p50_p99": None if r.get("stream_chunks", len(t)) < 0.9 * r.get("gen_tokens", len(t))
                  else _pcts([(b - a) * 1000 for a, b in zip(t[1:], t[2:])])})
        results.append(r)
    first = spans[0][1] if spans else samples[-1]["t"]
    return {"host": meta["host"], "engines": meta.get("engines", []), "system_rail": system,
            "phases": [summarize("idle", samples[0]["t"], first)] + [summarize(*s) for s in spans], "results": results}


def _pcts(xs):
    if not xs:
        return None
    xs = sorted(xs)
    return [round(xs[len(xs) // 2], 1), round(xs[min(len(xs) - 1, int(len(xs) * 0.99))], 1)]


def phases_cmd(capture, as_json):
    out = phases(capture)
    if as_json:
        print(json.dumps(out, indent=1))
        return
    keys = [k for k in out["phases"][0] if k not in ("phase", "n", "seconds")
            and any(r[k] is not None for r in out["phases"])]
    print(f"{out['host']}  engines: {', '.join(out['engines']) or 'none (GPU = firmware IRQ proxy)'}")
    print(f"{'phase':<14} {'n':>4} {'sec':>6} " + " ".join(f"{k:>13}" for k in keys))
    for r in out["phases"]:
        print(f"{r['phase'][:14]:<14} {r['n']:>4} {r['seconds']:>6} "
              + " ".join(f"{'-' if r[k] is None else r[k]:>13}" for k in keys))
    res = out["results"]
    if res:
        keys = list(dict.fromkeys(k for r in res for k in r if k != "label"))
        print(f"\nLLM results (energy from {out['system_rail'] or 'no system rail'}):")
        print(f"{'':<24}" + "".join(f"{r['label'][:18]:>20}" for r in res))
        for k in keys:
            print(f"{k:<24}" + "".join(f"{str(r.get(k, '-')):>20}" for r in res))
