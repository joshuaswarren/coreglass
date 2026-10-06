"""Ledger server cells: A/B an environment switch on a live OpenAI-compatible server, e.g. oMLX with one patch on
and off. Each pair starts a fresh server per variant, sends c1 then c4 streamed requests through a benchmark script,
and reads the server's own decode rate from its log. A quiet gate (CPU idle >= 92%, PSI cpu some avg10 = 0) runs
before every measurement; ungated runs do not count. A CPU-only dry run checks every path before the GPU ticket.
"""

import json
import re
import shlex
import statistics

from . import remote

MARK = "@@cell"
QUIET = r"""qgate=$(mktemp /tmp/coreglass-quiet.XXXX.py)
cat > $qgate <<'PY'
import time
def idle():
    v = list(map(int, open("/proc/stat").readline().split()[1:]))
    return v[3] + v[4], sum(v)
a, ta = idle(); time.sleep(1.0); b, tb = idle()
cpu_idle = (b - a) / max(1, tb - ta)
psi = 0.0
try:
    psi = float(open("/proc/pressure/cpu").readline().split()[1].split("=")[1])
except OSError:
    pass
print(int(cpu_idle >= 0.92 and psi == 0.0), round(cpu_idle, 3), psi)
PY
quiet() { python3 $qgate; }
qwait() {  # up to ~45 s for PSI's 10 s average to settle after a model load or the previous run
  for _ in $(seq 1 22); do g=$(quiet); [ "${g%% *}" = 1 ] && break; sleep 1; done; echo "$g"
}
"""


def cell_script(cell, base, stack, driver, dry):
    """Remote bash for one cell: the dry run checks everything without the GPU; the run does `pairs` A/B pairs."""
    py, omlx = f"{base}/{stack['venv']}/bin/python", f"{base}/{stack['venv']}/bin/omlx"
    pythonpath = ":".join(p for p in (f"{base}/{cell['shadow']}" if cell.get("shadow") else "",
                                      f"{base}/{stack['overlay']}" if stack.get("overlay") else "") if p)
    model = f"{base}/{cell['model']}"
    model_dir, model_id = model.rsplit("/", 1)
    bench, prompt = f"{base}/{cell['bench']}", f"{base}/{cell['prompt']}"
    off = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in cell["env_off"].items())
    levels = " ".join(str(c) for c in cell.get("concurrency", [1, 4]))
    head = f"""set -u
export VK_DRIVER_FILES={shlex.quote(driver + '/honeykrisp_icd.aarch64.json')} PYTHONPATH={shlex.quote(pythonpath)}
export HF_HUB_OFFLINE=1
""" + QUIET
    if dry:
        return head + f"""for f in {py} {omlx} {bench} {prompt} {model}/config.json; do [ -e "$f" ] || {{ echo "{MARK} missing $f"; exit 1; }}; done
{py} -c "import omlx.patches.mlx_lm_mtp.qwen35_model as m, sys; t = open(m.__file__).read(); \
print('{MARK} shadow', m.__file__, 'MLX_OMARCHY_OMLX_CONV_FUSE' in t)"
{py} {bench} --help >/dev/null && echo "{MARK} bench ok"
echo "{MARK} prompt $(sha256sum {prompt} | cut -c1-16)"
echo "{MARK} quiet $(quiet)"
rm -f $qgate
"""
    return head + f"""work=$(mktemp -d /tmp/coreglass-cell.XXXX)
server=
trap '[ -n "$server" ] && kill $server 2>/dev/null; rm -r "$work"; rm -f $qgate' EXIT
for p in $(seq 1 {int(cell.get('pairs', 5))}); do
  if [ $((p % 2)) = 1 ]; then order="off on"; else order="on off"; fi
  for v in $order; do
    port=$({py} -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
    mkdir -p $work/$p-$v/base $work/$p-$v/home
    printf '{{"version":1,"models":{{"%s":{{"mtp_enabled":false}}}}}}\\n' {model_id} > $work/$p-$v/base/model_settings.json
    envs=""; [ $v = off ] && envs="{off}"
    env $envs HOME=$work/$p-$v/home {omlx} serve --model-dir {model_dir} --host 127.0.0.1 --port $port \\
      --base-path $work/$p-$v/base --no-cache --max-concurrent-requests 8 --log-level info > $work/$p-$v/log 2>&1 &
    server=$!
    for _ in $(seq 1 240); do curl -fsS http://127.0.0.1:$port/v1/models >/dev/null 2>&1 && break; sleep 0.25; done
    curl -fsS http://127.0.0.1:$port/v1/chat/completions -H 'Content-Type: application/json' -d \\
      '{{"model":"{model_id}","messages":[{{"role":"user","content":"warm up"}}],"max_tokens":1,"temperature":0,"enable_thinking":false}}' >/dev/null
    echo "{MARK} run $p $v gate $(qwait)"
    {py} {bench} --endpoint http://127.0.0.1:$port/v1/chat/completions --model {model_id} --prompt-file {prompt} \\
      --max-tokens 128 --timeout 300 --repeats 1 --concurrency {levels} | sed 's/^/{MARK} bench /'
    grep 'Chat completion: .* 128 tokens' $work/$p-$v/log | sed 's/^/{MARK} log /'
    kill $server; wait $server 2>/dev/null; server=
  done
done
"""


def parse(text, cell):
    """Per variant: medians over gated runs of server decode (c1, and c4 per request), aggregate tok/s, TTFT; and the
    c1 completion-text hashes (parity across variants means the switch keeps greedy output)."""
    runs, cur = [], None
    for ln in text.splitlines():
        if not ln.startswith(MARK):
            continue
        kind, _, rest = ln[len(MARK) + 1:].partition(" ")
        if kind == "run":
            p, v, _, ok, *_ = rest.split()
            cur = {"pair": int(p), "variant": v, "gated": ok == "1", "bench": {}, "server": []}
            runs.append(cur)
        elif kind == "bench" and cur and rest.startswith("{"):
            r = json.loads(rest)
            if r.get("type") == "result":
                cur["bench"][r["concurrency"]] = r
        elif kind == "log" and cur and (m := re.search(r"\(([\d.]+) tok/s\)", rest)):
            cur["server"].append(float(m[1]))
    out, texts = {}, {}
    for v in ("off", "on"):
        good = [r for r in runs if r["variant"] == v and r["gated"] and 1 in r["bench"]]
        series = {
            "c1 server decode tok/s": [r["server"][0] for r in good if r["server"]],
            "c1 aggregate tok/s": [r["bench"][1]["aggregate_tok_s"] for r in good],
            "c1 TTFT ms": [r["bench"][1]["request_results"][0]["ttft_ms"] for r in good],
        }
        for c in cell.get("concurrency", [1, 4]):
            if c != 1:
                series[f"c{c} aggregate tok/s"] = [r["bench"][c]["aggregate_tok_s"] for r in good if c in r["bench"]]
                series[f"c{c} server decode tok/s"] = [statistics.median(r["server"][1:1 + c]) for r in good
                                                       if len(r["server"]) >= 1 + c]
        for name, vs in series.items():
            if vs:
                out[f"{v} · {name}"] = {"median": round(statistics.median(vs), 2), "min": min(vs), "max": max(vs),
                                        "n": len(vs)}
        texts[v] = sorted({r["bench"][1]["request_results"][0]["completion_text_sha256"][:12] for r in good})
    return out, texts, sum(r["gated"] for r in runs), len(runs)


def measure(cfg, target, cell, stack, driver, log):
    """Dry run, then one GPU ticket (one ssh) for the whole cell. Returns the cell's row fields or None."""
    host = remote.resolve(target["host"])
    base = target.get("base", cfg["base"])
    dry = remote.ssh(host, "bash -s", cell_script(cell, base, stack, driver, dry=True), timeout=120)
    lines = [ln for ln in dry.stdout.splitlines() if ln.startswith(MARK)]
    log(f"{cell['label']} dry run: " + " | ".join(ln[len(MARK) + 1:] for ln in lines))
    if dry.returncode or not any(ln.endswith("True") for ln in lines if " shadow " in ln):
        log(f"{cell['label']}: dry run failed, no GPU ticket taken: {dry.stderr.strip()[-200:]}")
        return None
    script = cell_script(cell, base, stack, driver, dry=False)
    if host.get("gpu_turn"):
        wrap = re.sub(r"-m \d+", f"-m {cell.get('turn_minutes', 6)}", host["gpu_turn"]) + " -- bash -s"
    else:
        wrap = f"flock -w 900 {shlex.quote(host['gpu_lock'])} bash -s"
    run = remote.ssh(host, wrap, script, timeout=float(cfg.get("wait_seconds", 3 * 3600)) + 1800)
    metrics, texts, gated, total = parse(run.stdout, cell)
    log(f"{cell['label']}: {gated}/{total} runs gated quiet, rc {run.returncode}")
    if not metrics:
        return None
    return {"metrics": metrics, "texts": texts, "gated_runs": gated, "runs": total,
            "text_parity": len(set(texts.get("off", []) + texts.get("on", []))) == 1}
