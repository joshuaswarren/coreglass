"""Adapters: receipts -> coreglass/v1 bundle (prov "measured").

Formats parsed (all real, see docs/DESIGN.md):
  HostProfile run dir   hp-<label>.json, host-split.json, staircase.jsonl
  GemvBw window dir     <op>.ndjson ("pat" records: null_* vs contiguous_* arms), env.txt
  ANE run dir           enc-*.log lines "exec ms over N calls: min .. median .. max .."
  Live capture          captures/*.jsonl written by `coreglass live` (sampler.py lines)
"""

import json
import os
import re
import statistics
from pathlib import Path

LAB_ROOT_ENV = "COREGLASS_LAB_ROOT"


def newest(root, pattern):
    hits = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime)
    return hits[-1].parent if hits else None


def _bins(values, cols):
    n = len(values)
    if n <= cols:
        return values
    return [sum(values[n * i // cols:n * (i + 1) // cols]) / max(n * (i + 1) // cols - n * i // cols, 1)
            for i in range(cols)]


def capture(path, cols=320):
    """A `coreglass live` capture -> measured per-core rows, marks, and power series."""
    lines = [json.loads(ln) for ln in Path(path).read_text().splitlines() if ln.strip()]
    meta = next(m["meta"] for m in lines if "meta" in m)
    samples = [m for m in lines if "cpu" in m]
    if not samples:
        raise SystemExit(f"{path}: no samples")
    rows = []
    for c in sorted(meta["clusters"], key=lambda c: -c["max_khz"]):
        rows += [{"label": f"{c['label']}·{cpu}", "group": c["label"], "lane": "cpu",
                  "values": _bins([s["cpu"][cpu] for s in samples], cols)} for cpu in c["cpus"]]
    k = max(round(meta["hz"]), 1)
    engines = meta.get("engines", [])
    for e in engines:
        rows.append({"label": f"{e.upper()} busy", "group": e.upper(), "lane": e,
                     "values": _bins([s.get("eng", {}).get(e, {}).get("busy", 0.0) for s in samples], cols)})
    for name in meta["irq"]:
        if name == "gpu_fw" and "gpu" in engines:
            continue
        raw = [s["irq"].get(name, 0.0) for s in samples]
        rate = [sum(raw[max(0, i - k + 1):i + 1]) / len(raw[max(0, i - k + 1):i + 1]) for i in range(len(raw))]
        top = max(sorted(rate)[int(0.95 * (len(rate) - 1))], 30.0)
        rows.append({"label": "GPU fw" if name == "gpu_fw" else name, "group": "GPU" if name == "gpu_fw" else "ANE",
                     "lane": "gpu" if name == "gpu_fw" else "ane",
                     "values": _bins([min(r / top, 1.0) for r in rate], cols), "p95_per_s": top})
    t0 = samples[0]["t"]
    src = Path(path).name
    step = max(len(samples) // 300, 1)
    rails = [r for r in meta["rails"] if any(s["w"].get(r, 0.0) > 0 for s in samples)][:4]
    power = [{"label": f"{rail} · {meta['host']}", "component": "soc", "unit": "W",
              "metric": "hwmon power (live capture)", "host": meta["host"],
              "series": [[round(s["t"] - t0, 2), s["w"].get(rail, 0.0)] for s in samples[::step]],
              "prov": "measured", "src": src} for rail in rails]

    def peak(series):
        sm = [sum(series[max(0, i - k + 1):i + 1]) / len(series[max(0, i - k + 1):i + 1]) for i in range(len(series))]
        return round(max(sm), 3)

    groups = {c["label"]: c["cpus"] for c in meta["clusters"]}
    p_cpus = [c for lab, cs in groups.items() if lab != "E" for c in cs]
    e_cpus = groups.get("E", [])
    mean = lambda s, cs: sum(s["cpu"][c] for c in cs) / len(cs)
    stats = {
        "p_busy": peak([mean(s, p_cpus) for s in samples]) if p_cpus else None,
        "e_busy": peak([mean(s, e_cpus) for s in samples]) if e_cpus else None,
        "gpu_irq": peak([s["irq"].get("gpu_fw", 0.0) for s in samples]) if "gpu_fw" in meta["irq"] else None,
        "gpu_busy": peak([s.get("eng", {}).get("gpu", {}).get("busy", 0.0) for s in samples]) if "gpu" in engines
        else None,
        "rails": {r: peak([s["w"].get(r, 0.0) for s in samples]) for r in rails},
        "temp_max": max((v for s in samples for v in s["c"].values()), default=None),
    }
    return {"schema": "coreglass/v1", "power": power, "sources": [src], "capture": {
        "host": meta["host"], "model": meta.get("model", ""), "kernel": meta["kernel"], "hz": meta["hz"],
        "seconds": round(samples[-1]["t"] - t0, 1), "n": len(samples), "rows": rows, "stats": stats,
        "clocks": {c["label"]: _bins([s["khz"].get(c["label"], 0) / 1e6 for s in samples], cols)
                   for c in sorted(meta["clusters"], key=lambda c: -c["max_khz"])[:4]},
        "max_ghz": max(c["max_khz"] for c in meta["clusters"]) / 1e6,
        "marks": [{"t": round(m["t"] - t0, 2), "label": m["mark"]} for m in lines if "mark" in m],
        "prov": "measured", "src": src}}


def host_profile(run, root):
    out, src = {}, str(run.relative_to(root))
    hp = run / "hp-sanity.json"
    if not hp.exists():
        hp = max(run.glob("hp-*.json"), key=lambda p: p.stat().st_size, default=None)
    if hp:
        d = json.loads(hp.read_text())
        p = d["per_prompt"][0]
        corpus = Path(d["protocol"]["prompts_file"]).stem.replace("-prompts", "")
        out["host"] = {"kernel": d["meta"].get("kernel", ""), "runtime": d["meta"].get("mlx_dist_version", "")}
        out["request"] = {
            "label": f"{corpus} · {p['prompt_tokens']} prompt tok · {p['generated_tokens']} new tok ({d['meta']['label']})",
            "caption": "end to end",
            "phases": [
                {"name": "prefill + first token", "lane": "gpu", "ms": p["ttft_s"] * 1000, "prov": "measured",
                 "note": f"{p['ttft_tok_rate']:.0f} tok/s"},
                {"name": f"decode {p['generated_tokens']} tok", "lane": "gpu", "ms": p["decode_s"] * 1000,
                 "prov": "measured", "note": f"{p['decode_tok_rate']:.1f} tok/s"},
            ],
            "src": f"{src}/{hp.name}",
        }
    split = run / "host-split.json"
    if split.exists():
        s = json.loads(split.read_text())
        out["token"] = {
            "label": f"{run.parent.name} {run.name}", "total_ms": s["token_ms"], "n": s["n"],
            "parts": [{"name": "build", "lane": "cpu", "ms": s["build_ms"]},
                      {"name": "submit", "lane": "queue", "ms": s["submit_ms"]},
                      {"name": "GPU wait", "lane": "gpu", "ms": s["wait_ms"]}],
            "prov": "measured", "src": f"{src}/host-split.json",
        }
    stair = run / "staircase.jsonl"
    if stair.exists():
        out["staircase"] = [{"d1_ms": r["d1_ms"], "token_ms": r["token_ms"], "prov": "measured",
                             "src": f"{src}/staircase.jsonl"}
                            for r in map(json.loads, stair.read_text().splitlines()) if r]
    return out


def gemv_window(win, root):
    src = str(win.relative_to(root))
    kernels = []
    for f in sorted(win.glob("*.ndjson")):
        arms = {}
        for rec in map(json.loads, filter(None, f.read_text().splitlines())):
            if rec.get("k") == "pat":
                arms["null" if rec["arm"].startswith("null") else "contig"] = rec["med_wall_gb_s"]
        if "null" in arms and "contig" in arms:
            ratio = arms["contig"] / arms["null"]
            kernels.append({"op": f.stem, "null_gbs": arms["null"], "contig_gbs": arms["contig"],
                            "bound": "row geometry" if ratio > 1.15 else "near contiguous",
                            "prov": "measured", "src": f"{src}/{f.name}"})
    limits = []
    env = win / "env.txt"
    if env.exists():
        loads = [float(m) for m in re.findall(r"load1=([\d.]+)", env.read_text())]
        psi = [float(m) for m in re.findall(r"psi_cpu_avg10=([\d.]+)", env.read_text())]
        if loads:
            limits.append({"label": "Quiet-box load1 (max)", "value": max(loads), "limit": 0.5, "unit": "",
                           "prov": "measured", "src": f"{src}/env.txt"})
        if psi:
            limits.append({"label": "PSI cpu avg10 (max)", "value": max(psi), "limit": 1.0, "unit": "",
                           "prov": "measured", "src": f"{src}/env.txt"})
    return {"kernels": kernels, "limits": limits}


EXEC = re.compile(r"exec ms over (\d+) calls: .*?median ([\d.]+)")


def ane_run(run, root, macos_ms, label, host, rec_id=None):
    medians = [float(m.group(2)) for f in sorted(run.glob("enc-*.log"))
               for m in EXEC.finditer(f.read_text())]
    if not medians:
        raise SystemExit(f"{run}: no 'exec ms over N calls' lines in enc-*.log")
    src = str(run.relative_to(root))
    power = []
    for f in sorted(run.glob("power-*.tsv")):
        rows = [list(map(float, ln.split())) for ln in f.read_text().splitlines() if ln.strip()]
        if rows:
            step = max(len(rows) // 200, 1)
            power.append({"label": f.stem.removeprefix("power-"), "component": "soc",
                          "series": [[round(r[0] - rows[0][0], 3), round(r[1] / 1e6, 3)] for r in rows[::step]],
                          "unit": "W", "metric": "hwmon total power", "host": host,
                          "prov": "measured", "src": f"{src}/{f.name}"})
    return {"paired": [{"id": rec_id or f"ane.{run.name}", "component": "ane", "host": host, "label": label,
                        "linux_ms": round(statistics.median(medians), 3), "macos_ms": macos_ms,
                        "note": f"median of {len(medians)} run medians; macOS {macos_ms:g} ms from --ane-macos-ms",
                        "prov": "measured", "src": f"{src}/enc-*.log"}],
            "power": power}


def ingest(root=None, host_profile_dir=None, gemv_dir=None, ane_dir=None,
           ane_macos_ms=None, ane_label="ANE encoder", ane_host="?", ane_id=None):
    root = root or os.environ.get(LAB_ROOT_ENV)
    if not root:
        raise SystemExit(f"ingest-lab needs --root <artifacts dir> or ${LAB_ROOT_ENV}")
    root = Path(root).expanduser()
    hp = Path(host_profile_dir) if host_profile_dir else newest(root, "*HostProfile*/*/host-split.json")
    gw = Path(gemv_dir) if gemv_dir else newest(root, "*GemvBw*/**/q.ndjson")
    bundle = {"schema": "coreglass/v1", "sources": []}
    for found, part in ((hp, lambda d: host_profile(d, root)), (gw, lambda d: gemv_window(d, root))):
        if found:
            for key, value in part(found.resolve()).items():
                bundle[key] = bundle.get(key, []) + value if isinstance(value, list) else value
            bundle["sources"].append(str(found.resolve().relative_to(root)))
    if ane_dir:
        if ane_macos_ms is None:
            raise SystemExit("--ane needs --ane-macos-ms: a Linux latency is only a gap next to its macOS pair")
        bundle.update(ane_run(Path(ane_dir).resolve(), root, ane_macos_ms, ane_label, ane_host, ane_id))
        bundle["sources"].append(str(Path(ane_dir).resolve().relative_to(root)))
    return bundle
