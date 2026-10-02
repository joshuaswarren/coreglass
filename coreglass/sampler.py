"""Read-only counter sampler. Runs on the target host: `ssh host python3 -u - --hz 10 < sampler.py`.

Stdlib only, no writes. Line 1 is {"meta": ...}; every later line is one sample.
Sources (all Linux procfs/sysfs, no root):
  cpu    per-core busy fraction from /proc/stat
  khz    current frequency per cpufreq policy (cluster)
  w, c   hwmon power rails (W) and temperatures (deg C)
  irq    interrupts/s for the GPU firmware mailbox and any ANE line (activity proxy, not busy time)
  psi    /proc/pressure some avg10; mem_gb = MemAvailable
"""

import glob
import json
import os
import re
import socket
import sys
import time


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def cpu_times():
    out = {}
    with open("/proc/stat") as f:
        for ln in f:
            if ln.startswith("cpu") and ln[3].isdigit():
                v = list(map(int, ln.split()[1:8]))
                out[int(ln.split()[0][3:])] = (sum(v), v[3] + v[4])
    return out


def clusters():
    have = set(cpu_times())
    pols = sorted(glob.glob("/sys/devices/system/cpu/cpufreq/policy*"), key=lambda p: int(p.rsplit("policy", 1)[1]))
    out = [{"name": os.path.basename(p), "cpus": [int(c) for c in read(p + "/related_cpus").split() if int(c) in have],
            "max_khz": int(read(p + "/cpuinfo_max_freq", "0") or 0), "path": p} for p in pols]
    out = [c for c in out if c["cpus"]]
    if len({c["max_khz"] for c in out}) > 1 and len(out) <= 4:
        low = min(c["max_khz"] for c in out)
        p = 0
        for c in out:
            c["label"] = "E" if c["max_khz"] == low else f"P{p}"
            p += c["max_khz"] != low
    else:
        for i, c in enumerate(out):
            c["label"] = f"C{i}"
    return out


def hwmon():
    rails = {}
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        name = read(h + "/name")
        for inp in glob.glob(h + "/power*_input") + glob.glob(h + "/temp*_input"):
            base = inp[: -len("_input")]
            label = read(base + "_label") or f"{name} {os.path.basename(base)}"
            kind = "w" if os.path.basename(base).startswith("power") else "c"
            rails[(kind, label)] = inp
    return rails


def irq_names():
    want = set()
    for card in glob.glob("/sys/class/drm/card*/device"):
        base = os.path.basename(os.path.realpath(card))
        m = re.match(r"([0-9a-f]+)\.gpu$", base)
        if m:
            want.add(f"{int(m.group(1), 16) + 0x8000:x}.mbox-recv")
    return want


def irq_counts(want):
    out = {}
    with open("/proc/interrupts") as f:
        ncpu = len(f.readline().split())
        for ln in f:
            parts = ln.split()
            if len(parts) < ncpu + 2:
                continue
            name = parts[-1]
            if name in want or re.search(r"(^|[.\-_])ane($|[.\-_])", name):
                out["gpu_fw" if name in want else name] = sum(int(x) for x in parts[1:ncpu + 1] if x.isdigit())
    return out


def psi():
    out = {}
    for k in ("cpu", "memory", "io"):
        m = re.search(r"some avg10=([\d.]+)", read(f"/proc/pressure/{k}"))
        if m:
            out[k] = float(m.group(1))
    return out


ENGINE_FILES = {"gpu": "/sys/class/drm/card*/device/agx_stats", "ane": "/sys/class/accel/accel*/device/ane_stats"}


def engines():
    """Driver busy-time files (docs/DESIGN.md "Producer contract"), when the drivers export them."""
    return {name: hits[0] for name, pat in ENGINE_FILES.items() if (hits := sorted(glob.glob(pat)))}


def read_kv(path):
    out = {}
    for ln in read(path).splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1].lstrip("-").isdigit():
            out[parts[0]] = int(parts[1])
    return out


def engine_delta(prev, cur, dt):
    """busy fraction and jobs/s from cumulative counters; gauges pass through."""
    out = {k: v for k, v in cur.items() if k not in ("busy_ns", "jobs")}
    if "busy_ns" in cur and "busy_ns" in prev:
        out["busy"] = round(min(max((cur["busy_ns"] - prev["busy_ns"]) / 1e9 / dt, 0.0), 1.0), 3)
    if "jobs" in cur and "jobs" in prev:
        out["jobs_s"] = round((cur["jobs"] - prev["jobs"]) / dt, 1)
    return out


def main():
    hz = float(sys.argv[sys.argv.index("--hz") + 1]) if "--hz" in sys.argv else 10.0
    cl, rails, want, eng = clusters(), hwmon(), irq_names(), engines()
    model = read("/proc/device-tree/model").rstrip("\x00") or read("/sys/devices/virtual/dmi/id/product_name")
    print(json.dumps({"meta": {
        "host": socket.gethostname(), "kernel": os.uname().release, "model": model, "hz": hz,
        "ncpu": len(cpu_times()), "clusters": [{k: c[k] for k in ("name", "label", "cpus", "max_khz")} for c in cl],
        "rails": sorted(label for kind, label in rails if kind == "w"),
        "temps": sorted(label for kind, label in rails if kind == "c"),
        "irq": sorted(irq_counts(want)), "engines": sorted(eng), "started": time.time(),
        "accel": sorted({os.path.basename(os.path.realpath(p)) for p in glob.glob("/sys/class/accel/accel*/device/driver")}),
    }}), flush=True)
    prev_cpu, prev_irq, prev_t = cpu_times(), irq_counts(want), time.monotonic()
    prev_eng = {name: read_kv(p) for name, p in eng.items()}
    t0 = prev_t
    while True:
        time.sleep(max(0.0, 1 / hz - (time.monotonic() - prev_t)))
        now, cpu, irq = time.monotonic(), cpu_times(), irq_counts(want)
        cur_eng = {name: read_kv(p) for name, p in eng.items()}
        dt = now - prev_t
        busy = []
        for i in sorted(cpu):
            tot, idle = cpu[i][0] - prev_cpu[i][0], cpu[i][1] - prev_cpu[i][1]
            busy.append(round(1 - idle / tot, 3) if tot > 0 else 0.0)
        sample = {
            "t": round(now - t0, 3), "cpu": busy,
            "khz": {c["label"]: int(read(c["path"] + "/scaling_cur_freq", "0") or 0) for c in cl},
            "w": {lab: round(int(read(p, "0") or 0) / 1e6, 2) for (k, lab), p in rails.items() if k == "w"},
            "c": {lab: round(int(read(p, "0") or 0) / 1e3, 1) for (k, lab), p in rails.items() if k == "c"},
            "irq": {k: round((v - prev_irq.get(k, v)) / dt, 1) for k, v in irq.items()},
            "psi": psi(),
            "mem_gb": round(int(re.search(r"MemAvailable:\s+(\d+)", read("/proc/meminfo")).group(1)) / 1048576, 2),
        }
        if eng:
            sample["eng"] = {name: engine_delta(prev_eng[name], cur_eng[name], dt) for name in eng}
        print(json.dumps(sample, separators=(",", ":")), flush=True)
        prev_cpu, prev_irq, prev_t, prev_eng = cpu, irq, now, cur_eng


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError):
        pass
