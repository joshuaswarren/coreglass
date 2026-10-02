"""Coreglass bundle: load/merge receipts and rank where the speed is lost.

A bundle is plain JSON (schema "coreglass/v1"); see docs/DESIGN.md for the
field reference. Every number carries `prov` so a frame never passes a
modeled or demo value off as a measurement.
"""

import hashlib
import json
from pathlib import Path

SCHEMA = "coreglass/v1"
PROVENANCE = ("measured", "replay", "modeled", "demo")
LIST_KEYS = ("metrics", "kernels", "paired", "ablations", "queues", "limits", "power", "staircase", "sources")


def load(parts):
    """Merge bundles (paths or already-parsed dicts) left to right.

    Lists concatenate, and a later record with the same id/op/label replaces the earlier one,
    so a measured ingest overrides a replayed fixture. `host` updates; other keys are replaced.
    """
    merged = {"schema": SCHEMA}
    for src in parts:
        part = src if isinstance(src, dict) else json.loads(Path(src).read_text())
        if part.get("schema") != SCHEMA:
            raise ValueError(f"{src if not isinstance(src, dict) else 'bundle'}: schema is {part.get('schema')!r}")
        for key, value in part.items():
            if key in LIST_KEYS:
                old = merged.setdefault(key, [])
                new_ids = {_identity(v) for v in value} - {None}
                merged[key] = [v for v in old if _identity(v) not in new_ids] + value
            elif key == "host":
                merged["host"] = {**merged.get("host", {}), **value}
            else:
                merged[key] = value
    for key in LIST_KEYS:
        merged.setdefault(key, [])
    merged.setdefault("host", {})
    _check_prov(merged)
    merged["digest"] = hashlib.sha256(json.dumps(merged, sort_keys=True).encode()).hexdigest()[:12]
    return merged


def _identity(rec):
    return rec.get("id") or rec.get("op") or rec.get("label") if isinstance(rec, dict) else None


def anonymize(b):
    """Strip host names, kernel strings, and capture file names, for frames posted in public."""
    cap, host = b.get("capture") or {}, b.get("host", {})
    swaps = {host.get(k): "" for k in ("alias", "kernel", "runtime") if host.get(k)}
    if cap:
        swaps |= {cap["host"]: (cap.get("model") or "target").removeprefix("Apple "), cap["src"]: "capture"}
        swaps |= {cap["kernel"]: ""} if cap.get("kernel") else {}
    text = json.dumps(b)
    for old, new in sorted(swaps.items(), key=lambda kv: -len(kv[0])):
        text = text.replace(old, new)
    return json.loads(text)


def _check_prov(node, where="bundle"):
    if isinstance(node, dict):
        if "prov" in node and node["prov"] not in PROVENANCE:
            raise ValueError(f"{where}: prov {node['prov']!r} not in {PROVENANCE}")
        for key, value in node.items():
            _check_prov(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            _check_prov(value, f"{where}[{i}]")


def _lever(rec, id, kind, component, what, factor, big, caption, proven=None):
    return {"id": id, "kind": kind, "component": component, "what": what, "factor": factor,
            "proven_factor": proven, "big": big, "caption": caption,
            "prov": rec["prov"], "src": rec.get("src", "")}


def findings(b):
    """Every lever with its factor (how much faster/smoother if closed), largest first.

    `big` and `caption` are the thumbnail-sized headline the hero frame shows.
    """
    out = []
    for m in b["metrics"]:
        if m.get("ceiling") and m["value"]:
            ref = m.get("ref")
            ref_txt = f" ({ref['label']} {ref['value']:g})" if ref else ""
            pct = m["unit"].startswith("%")
            out.append(_lever(
                m, m["id"], "headroom", m["component"],
                f"{m['label']}: {m['value']:g} of {m['ceiling']:g} {m['unit']}{ref_txt}",
                m["ceiling"] / m["value"],
                f"{m['value']:g}%" if pct else f"{m['value']:g} {m['unit']}",
                f"of {m['unit'][1:].strip()} · {m['label']}" if pct
                else f"{m['label']} · ceiling {m['ceiling']:g}{ref_txt}",
                ref["value"] / m["value"] if ref else None))
    for p in b["paired"]:
        gap = p["linux_ms"] / p["macos_ms"]
        out.append(_lever(
            p, p["id"], "os-gap", p["component"],
            f"{p['label']} on {p['host']}: Linux {p['linux_ms']:g} ms vs macOS {p['macos_ms']:g} ms",
            gap, f"{gap:.1f}×", f"{p['label']} slower than macOS · {p['host']}", gap))
    for k in b["kernels"]:
        if k.get("contig_gbs") and k.get("null_gbs"):
            out.append(_lever(
                k, f"kernel.{k['op']}", "geometry", "gpu",
                f"GEMV {k['op']}: real row geometry {k['null_gbs']:.0f} GB/s vs contiguous {k['contig_gbs']:.0f}",
                k["contig_gbs"] / k["null_gbs"], f"{k['null_gbs']:.0f} GB/s",
                f"GEMV {k['op']} row geometry · contiguous {k['contig_gbs']:.0f}"))
    t = b.get("token")
    if t:
        gpu_ms = sum(p["ms"] for p in t["parts"] if p["lane"] == "gpu")
        host_ms = t["total_ms"] - gpu_ms
        out.append(_lever(
            t, "token.host", "host-overhead", "cpu",
            f"Host share of each decode token: {host_ms:.2f} of {t['total_ms']:.2f} ms ({t['label']})",
            t["total_ms"] / gpu_ms, f"{100 * host_ms / t['total_ms']:.0f}%",
            f"of every decode token is host + submit · {t['total_ms']:.2f} ms/token"))
    for q in b["queues"]:
        out.append(_lever(
            q, q["id"], "constraint", q["component"],
            f"{q['label']}: {q['observed_ms']:g} ms observed vs {q['budget_ms']:g} ms budget",
            q["observed_ms"] / q["budget_ms"], f"{q['observed_ms']:g} ms",
            f"{q['label']} · budget {q['budget_ms']:g} ms"))
    for a in b["ablations"]:
        out.append(_lever(
            a, a["id"], "ablation", a["component"],
            f"{a['id']} {a['knob']} on {a['host']}: {a['delta_pct']:+g}% {a['metric']}"
            + (f". {a['takeaway']}" if a.get("takeaway") else ""),
            1 + abs(a["delta_pct"]) / 100, f"{a['delta_pct']:+g}%", f"{a['metric']} · {a['knob']}"))
    return sorted(out, key=lambda f: -f["factor"])


def headlines(found, n=4):
    """Best lever per kind, so the hero frame shows four different stories."""
    best = {}
    for f in found:
        if f["kind"] not in ("ablation", "geometry"):
            best.setdefault(f["kind"], f)
    return list(best.values())[:n]


def summary(b):
    """The structured view an LLM reads: host, ranked levers, open gaps in capture."""
    return {
        "schema": "coreglass/summary/v1",
        "title": b.get("title", ""),
        "bundle_digest": b["digest"],
        "host": b.get("host", {}),
        "findings": findings(b),
        "not_captured": b.get("not_captured", []),
        "sources": b["sources"],
        "legend": {
            "factor": "ceiling/achieved, Linux/macOS, contiguous/real, token/GPU-time, observed/budget",
            "proven_factor": "speedup already demonstrated on the same silicon (macOS reference)",
            "prov": "measured = parsed from a receipt here; replay = measured elsewhere, re-entered; "
                    "modeled = derived from measurements by a stated rule; demo = synthetic",
        },
    }


def markdown(s):
    rows = "\n".join(
        f"| {i} | {f['factor']:.2f}x | {f['kind']} | {f['component']} | {f['what']} | {f['prov']} |"
        for i, f in enumerate(s["findings"], 1)
    )
    host = s["host"]
    gaps = "\n".join(f"- {g}" for g in s["not_captured"]) or "- none listed"
    return (
        f"# Coreglass summary: {s['title']}\n\n"
        f"Host: {host.get('alias', '?')} ({host.get('chip', '?')}, {host.get('soc', '?')}), "
        f"bundle `{s['bundle_digest']}`.\n\n"
        "## Levers, largest factor first\n\n"
        "| # | factor | kind | component | finding | prov |\n|---|---|---|---|---|---|\n"
        f"{rows}\n\n## Not captured yet\n\n{gaps}\n\n"
        f"Factor key: {s['legend']['factor']}.\n"
    )
