"""Comparison frames: one shareable 1600x900 image that puts two to four variants of an LLM run side by side.

A variant is one LLM result from a capture: an engine in a single run (mlx-lm in process, mlx_lm.server, oMLX),
or the same step across runs (version A vs B, before vs after a code change). The first variant is the baseline;
every other one shows its change against it.
"""

import hashlib
import json
import re
from pathlib import Path

from . import remote, theme, views
from .views import panel, r, t

METRICS = [("decode_tok_s", "Decode", "tok/s", max), ("ttft_ms", "Time to first token", "ms", min),
           ("prefill_tok_s", "Prefill", "tok/s", max), ("j_per_token", "Energy", "J per token", min),
           ("host_cpu_ms_per_token", "Host CPU", "ms per token", min)]
CHIP = re.compile(r"\bM\d+(?: (?:Pro|Max|Ultra))?\b")


def variants(specs, anonymize=False):
    """`capture.jsonl[#step][=label]` per spec. Without #step a capture adds every LLM result it has."""
    out = []
    for spec in specs:
        spec, _, label = spec.partition("=")
        path, _, step = spec.partition("#")
        run = remote.phases(path)
        meta = json.loads(Path(path).read_text().split("\n", 1)[0])["meta"]
        results = [x for x in run["results"] if not step or x["label"] == step]
        if not results:
            raise SystemExit(f"{path}: no LLM result{f' for step {step!r}' if step else ''}")
        chip_name = (CHIP.search(meta.get("model", "")) or [None])[0] or "target"
        for x in results:
            name = x["label"]
            out.append({**x, "variant": f"{label} · {name}" if label and len(results) > 1 else label or name,
                        "chip": chip_name, "host": chip_name if anonymize else run["host"],
                        "kernel": "" if anonymize else meta.get("kernel", ""), "capture": Path(path).name})
    if not 2 <= len(out) <= 4:
        raise SystemExit(f"compare needs 2 to 4 variants; got {len(out)}")
    return out


def deltas(vs):
    """Per metric: each variant's value, its change against the baseline (first variant), and the best one."""
    rows = []
    for key, name, unit, best in METRICS:
        vals = [v.get(key) for v in vs]
        nums = [x for x in vals if isinstance(x, (int, float))]
        if len(nums) < 2:
            continue
        base = vals[0]
        rows.append({"metric": key, "name": name, "unit": unit, "better": "higher" if best is max else "lower",
                     "values": vals, "best": vals.index(best(nums)),
                     "change_pct": [None if not base or x is None else round((x - base) / base * 100, 1) for x in vals]})
    return rows


NOISE_PCT = 3


def headline(vs, rows):
    """The big claim: who wins decode, and by how much against the baseline (or the runner-up). One request
    per variant cannot show run-to-run noise, so a gap under NOISE_PCT is called a tie."""
    m = next((x for x in rows if x["metric"] == "decode_tok_s"), rows[0])
    vals, i = m["values"], m["best"]
    if i == 0:
        others = [x for x in vals[1:] if x is not None]
        rival = max(others) if m["better"] == "higher" else min(others)
        pct = abs(vals[0] / rival - 1) * 100
        claim = f"{vs[0]['variant']} leads on {m['name'].lower()}"
    else:
        pct = abs(m["change_pct"][i])
        claim = f"{vs[i]['variant']}: {m['name'].lower()} {'faster' if m['better'] == 'higher' else 'lower'} than {vs[0]['variant']}"
    if pct < NOISE_PCT:
        return f"No clear {m['name'].lower()} difference (within {NOISE_PCT}%)", "≈"
    return claim, f"{pct:.0f}%" if i == 0 else f"{m['change_pct'][i]:+.0f}%"


def pct_text(p):
    return "±0%" if round(p) == 0 else f"{p:+.0f}%"


def render(vs, title=None, palette=None):
    views.use(palette or theme.SYNTHWAVE)
    rows = deltas(vs)
    one_capture = len({v["capture"] for v in vs}) == 1
    title = title or ("Inference engines on Linux" if one_capture else "Before and after")
    subtitle = (f"{vs[0]['model']} · {vs[0].get('prompt_tokens') or '?'} prompt + {vs[0].get('gen_tokens')} tokens"
                f" · {', '.join(dict.fromkeys(v['chip'] for v in vs))} · one request each · measured")
    claim, big = headline(vs, rows)
    P, colors = views.PAL, [views.PAL["queue"], views.PAL["gpu"], views.PAL["sync"], views.PAL["ane"]]
    body = panel(60, 196, 1480, 118)
    body += t(90, 286, big, 72, P["sun_top"], 900, extra='filter="url(#compare-glow)"')
    x0 = 90 + 54 * len(big) + 30
    body += t(x0, 244, claim, 28, views.TEXT, 700) + t(x0, 272, "baseline: " + vs[0]["variant"], 17, views.DIM, 500)
    lx = x0
    for i, v in enumerate(vs):
        body += r(lx, 287, 14, 14, colors[i], 3) + t(lx + 22, 299, v["variant"], 15, views.DIM, 600)
        lx += 22 + len(v["variant"]) * 8.2 + 34
    n, gap = len(rows), 20
    pw = (1480 - gap * (n - 1)) / n
    for j, m in enumerate(rows):
        x, y = 60 + j * (pw + gap), 334
        body += panel(x, y, pw, 492) + t(x + 22, y + 40, m["name"], 22, views.TEXT, 700)
        body += t(x + 22, y + 64, f"{m['unit']} · {m['better']} is better", 14, views.DIM, 500)
        top = max(x_ for x_ in m["values"] if isinstance(x_, (int, float))) or 1
        rh, vsize = (492 - 96) / len(vs), {2: 56, 3: 42}.get(len(vs), 34)
        for i, val in enumerate(m["values"]):
            yy = y + 96 + i * rh
            win = i == m["best"]
            c = colors[i]
            label = vs[i]["variant"]  # never cut: engine and patch names are the point of the frame
            body += t(x + 22, yy + 18, label, 14 if len(label) <= 24 else max(10, round(14 * 24 / len(label))),
                      views.DIM, 600)
            if val is None:
                body += t(x + 22, yy + 56, "not reported", 18, views.EDGE, 600)
                continue
            pct = m["change_pct"][i]
            if i and pct is not None:
                good = (pct > 0) == (m["better"] == "higher")
                tone = views.DIM if round(pct) == 0 else P["mem"] if good else P["sync"]
                body += t(x + pw - 22, yy + 18, pct_text(pct), 17, tone, 800, "end", mono=True)
            body += r(x + 22, yy + 28, pw - 44, 10, views.EDGE, 5) + r(x + 22, yy + 28, (pw - 44) * val / top, 10, c, 5)
            body += t(x + 22, yy + 46 + vsize * 0.85, f"{val:g}", vsize, c if win else views.TEXT, 800, mono=True,
                      extra='filter="url(#compare-glow)"' if win else "")
    hosts = " · ".join(dict.fromkeys(f"{v['host']} {v['kernel']}".strip() for v in vs))
    digest = hashlib.sha256(json.dumps(vs, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return views.frame("compare", title, subtitle, body, {"digest": digest, "title": "Apple Silicon on Linux"},
                       ["measured"], False, pill=hosts)


def markdown(vs, rows):
    head = "| metric | " + " | ".join(v["variant"] for v in vs) + " |\n|---|" + "---|" * len(vs) + "\n"
    body = "\n".join(f"| {m['name']} ({m['unit']}, {m['better']} is better) | " + " | ".join(
        "–" if val is None else f"{val:g}" + (f" ({pct:+.0f}%)" if i and pct is not None else "")
        for i, (val, pct) in enumerate(zip(m["values"], m["change_pct"]))) + " |" for m in rows)
    return f"# Coreglass comparison\n\nBaseline: {vs[0]['variant']}. Measured, one request per variant.\n\n{head}{body}\n"


def compare(specs, out, title=None, png=False, scale=2.0, anonymize=False, theme_name="synthwave"):
    from .build import shoot
    vs = variants(specs, anonymize)
    rows = deltas(vs)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    svg = out / "compare.svg"
    svg.write_text(render(vs, title, theme.get(theme_name)))
    (out / "compare.json").write_text(json.dumps({"schema": "coreglass/compare/v1", "baseline": vs[0]["variant"],
                                                  "variants": vs, "metrics": rows}, indent=1))
    (out / "compare.md").write_text(markdown(vs, rows))
    if png:
        shoot(svg, out / "compare.png", scale)
    return {"out": str(out), "svg": str(svg), "variants": [v["variant"] for v in vs]}
