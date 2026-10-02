"""Six 1600x900 SVG frames. Each one stands alone as a shareable image.

Thumbnail rule: the headline number of every frame is >= 64 px, so it stays
legible when a feed shrinks the frame to 400 px wide.
"""

import base64
import html
import random
import textwrap
from pathlib import Path

from .model import findings, headlines

W, H = 1600, 900
BG, PANEL, EDGE, TEXT, DIM = "#05070b", "#0c1017", "#1c2433", "#eef2f8", "#8590a3"
LANE = {"gpu": "#2de2ff", "ane": "#ff4fd8", "cpu": "#ffb02e", "queue": "#9b87ff",
        "sync": "#ff5b6e", "mem": "#59f0a8"}
PROV = {"measured": "#3ddc97", "replay": "#5aa9ff", "modeled": "#ffb02e", "demo": "#ff4f6d"}
SANS = "Inter, 'SF Pro Display', 'Helvetica Neue', 'Liberation Sans', Arial, sans-serif"
MONO = "'JetBrains Mono', 'SF Mono', 'DejaVu Sans Mono', monospace"
CMAP = [(0.0, (10, 12, 24)), (0.2, (48, 14, 102)), (0.45, (150, 38, 129)),
        (0.7, (240, 96, 52)), (0.88, (252, 190, 50)), (1.0, (252, 255, 164))]
# Subset Inter + JetBrains Mono (OFL, coreglass/fonts/), embedded so SVG, PNG, and canvas exports match.
FONT_CSS = "".join(
    f"@font-face{{font-family:'{fam}';font-weight:100 900;src:url(data:font/woff2;base64,"
    f"{base64.b64encode((Path(__file__).with_name('fonts') / name).read_bytes()).decode()}) format('woff2')}}"
    for fam, name in (("Inter", "Inter.woff2"), ("JetBrains Mono", "JetBrainsMono.woff2")))


def esc(s):
    return html.escape(str(s), quote=True)


def t(x, y, s, size=20, fill=TEXT, w=400, anchor="start", mono=False, extra=""):
    fam = MONO if mono else SANS
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{esc(fam)}" font-size="{size}" '
            f'font-weight="{w}" fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>')


def r(x, y, w, h, fill, rx=0, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(w, 0):.1f}" height="{max(h, 0):.1f}" rx="{rx}" fill="{fill}" {extra}/>'


def line(x1, y1, x2, y2, stroke, sw=1, extra=""):
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}" {extra}/>'


def cmap(v):
    v = min(max(v, 0.0), 1.0)
    for (a, ca), (b, cb) in zip(CMAP, CMAP[1:]):
        if v <= b:
            k = (v - a) / (b - a)
            return "#%02x%02x%02x" % tuple(round(p + (q - p) * k) for p, q in zip(ca, cb))
    return "#fcffa4"


def wrap(s, n):
    return textwrap.wrap(s, n) or [""]


def chip(x, y, label, color, size=13):
    w = len(label) * size * 0.68 + 22
    return (r(x, y, w, size + 13, color + "1f", 6, f'stroke="{color}" stroke-width="1"')
            + t(x + w / 2, y + size + 4, label.upper(), size, color, 700, "middle", extra='letter-spacing="1.5"')), w


def panel(x, y, w, h, title=None):
    out = r(x, y, w, h, PANEL, 16, f'stroke="{EDGE}" stroke-width="1"')
    if title:
        out += t(x + 24, y + 38, title, 20, DIM, 600, extra='letter-spacing="0.5"')
    return out


def frame(fid, title, subtitle, body, b, provs, demo):
    host = b.get("host", {})
    pill = " · ".join(str(host[k]) for k in ("alias", "chip", "soc", "os", "kernel") if host.get(k))
    cap = b.get("capture")
    if cap and cap["host"] not in pill:
        pill += f"  +  live: {cap['host']}"
    used = sorted({p for p in provs if p} | ({"demo"} if demo else set()), key=list(PROV).index)
    foot, x = "", 60
    for p in used:
        c, w = chip(x, 858, p, PROV[p])
        foot += c
        x += w + 10
    return f'''<svg xmlns="http://www.w3.org/2000/svg" id="{fid}" class="frame" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<defs><style>{FONT_CSS}</style>
<radialGradient id="{fid}-g1" cx="12%" cy="0%" r="70%"><stop offset="0" stop-color="#1fb8ff" stop-opacity="0.20"/><stop offset="1" stop-color="#1fb8ff" stop-opacity="0"/></radialGradient>
<radialGradient id="{fid}-g2" cx="95%" cy="100%" r="70%"><stop offset="0" stop-color="#ff3fd0" stop-opacity="0.16"/><stop offset="1" stop-color="#ff3fd0" stop-opacity="0"/></radialGradient>
<pattern id="{fid}-grid" width="40" height="40" patternUnits="userSpaceOnUse"><path d="M40 0H0V40" fill="none" stroke="#ffffff" stroke-opacity="0.035"/></pattern>
<filter id="{fid}-glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="7" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<linearGradient id="{fid}-bar" x1="0" x2="1"><stop offset="0" stop-color="#1b6bff"/><stop offset="1" stop-color="#2de2ff"/></linearGradient>
</defs>
{r(0, 0, W, H, BG)}{r(0, 0, W, H, f"url(#{fid}-g1)")}{r(0, 0, W, H, f"url(#{fid}-g2)")}{r(0, 0, W, H, f"url(#{fid}-grid)")}
{t(60, 62, "CORE", 20, TEXT, 800, extra='letter-spacing="8"')}{t(152, 62, "GLASS", 20, LANE["gpu"], 800, extra='letter-spacing="8"')}
{t(W - 60, 62, pill, 18, DIM, 500, "end", mono=True)}
{t(60, 124, title, 52, TEXT, 800)}
{t(60, 162, subtitle, 22, DIM, 400)}
{body}
{line(60, 845, W - 60, 845, EDGE)}
{foot}
{t(W - 60, 881, f"bundle {b['digest']} · {b.get('title', '')}", 15, DIM, 400, "end", mono=True)}
</svg>'''


def _noise(seed, rows, cols):
    rnd = random.Random(seed)
    base = [[rnd.random() for _ in range(cols)] for _ in range(rows)]
    return [[(base[i][j] + base[i][j - 1] + base[i - 1][j]) / 3 for j in range(cols)] for i in range(rows)]


def heatmap(x, y, w, h, groups, cols, fn, demo):
    """groups: [(label, color, rows, key)]; fn(key, row, col) -> 0..1. Runs of equal cells merge."""
    total = sum(g[2] for g in groups) + 0.6 * (len(groups) - 1)
    rh, cw = h / total, w / cols
    noise = _noise(7, sum(g[2] for g in groups), cols) if demo else None
    out, yy, gi = "", y, 0
    for label, color, rows, key in groups:
        out += t(x - 16, yy + rows * rh / 2 + 7, label, 18, color, 700, "end")
        for row in range(rows):
            vals = []
            for col in range(cols):
                v = fn(key, row, col)
                if noise and v > 0:
                    v *= 0.7 + 0.6 * noise[gi][col]
                vals.append(round(min(v, 1.0), 2))
            col = 0
            while col < cols:
                end = col
                while end + 1 < cols and vals[end + 1] == vals[col]:
                    end += 1
                out += r(x + col * cw, yy + row * rh, (end - col + 1) * cw + 0.4, rh - 1.5, cmap(vals[col]))
                col = end + 1
            gi += 1
        yy += rows * rh + 0.6 * rh
    return out


def colorbar(x, y, w, label):
    out = "".join(r(x + i * w / 40, y, w / 40 + 0.5, 12, cmap(i / 39)) for i in range(40))
    return out + t(x, y + 32, "0%", 14, DIM, mono=True) + t(x + w, y + 32, "100%", 14, DIM, anchor="end", mono=True) \
        + t(x + w / 2, y + 32, label, 14, DIM, anchor="middle")


def metric(b, mid):
    return next((m for m in b["metrics"] if m["id"] == mid), None)


def capture_heat(b, x, y, w, h):
    """Measured per-core heatmap from a `coreglass live` capture."""
    cap = b["capture"]
    rows = cap["rows"]
    groups, by = [], {}
    for r in rows:
        if not groups or groups[-1][3] != r["group"]:
            groups.append([r["group"], LANE[r["lane"]], 0, r["group"]])
        groups[-1][2] += 1
        by.setdefault(r["group"], []).append(r["values"])
    cols = max(len(r["values"]) for r in rows)
    hx, hw, lane = x + 90, w - 90, 26 if cap["marks"] else 0
    out = heatmap(hx, y + lane, hw, h - 46 - lane, [tuple(g) for g in groups], cols,
                  lambda k, row, col: by[k][row][col] if col < len(by[k][row]) else 0.0, False)
    free_x = hx
    for m in cap["marks"]:
        mx = hx + m["t"] / max(cap["seconds"], 1e-9) * hw
        out += line(mx, y, mx, y + h - 46, TEXT, 2)
        if mx + 6 >= free_x:
            out += t(mx + 6, y + 14, m["label"], 14, TEXT, 700, mono=True)
            free_x = mx + 6 + len(m["label"]) * 8.6 + 10
    out += t(hx, y + h - 14, f"{cap['seconds']:g} s · {cap['n']} samples @ {cap['hz']:g} Hz · {cap['host']}", 15, DIM, mono=True)
    gpu = next((r for r in rows if r["group"] == "GPU"), None)
    if gpu and "p95_per_s" in gpu:
        out += t(x + w, y + h - 14, f"GPU row = firmware IRQ rate ÷ p95 {gpu['p95_per_s']:.0f}/s (activity proxy)", 15, DIM, anchor="end")
    elif gpu:
        out += t(x + w, y + h - 14, "GPU row = driver busy time (agx_stats busy_ns)", 15, DIM, anchor="end")
    return out


def token_train(b, x, y, w, h, demo, tokens=12, cols=192):
    """Modeled occupancy of one decode-token train from the measured per-token split."""
    tk = b.get("token")
    host = b.get("host", {})
    if not tk:
        return panel(x, y, w, h) + t(x + w / 2, y + h / 2, "token split not captured", 22, DIM, anchor="middle")
    bw = metric(b, "gpu.decode_bw")
    gpu_level = bw["value"] / bw["ceiling"] if bw else 1.0
    period = tk["total_ms"]
    edges, acc = [], 0.0
    for p in tk["parts"]:
        edges.append((acc, acc + p["ms"], p["lane"]))
        acc += p["ms"]

    def lane_at(col):
        tau = (col + 0.5) / cols * tokens * period % period
        return next((ln for a, z, ln in edges if a <= tau < z), "gpu")

    lanes = [lane_at(c) for c in range(cols)]

    def fn(key, row, col):
        ln = lanes[col]
        if key == "cpu_p":
            return 1.0 if row == host.get("cpu_p", 8) // 2 and ln in ("cpu", "queue") else 0.0
        if key == "gpu":
            return gpu_level if ln == "gpu" else 0.0
        return 0.0

    gpu_rows = host.get("gpu_cores") or (32 if demo else 8)
    groups = [("CPU P", LANE["cpu"], host.get("cpu_p", 8), "cpu_p"), ("CPU E", LANE["cpu"], host.get("cpu_e", 2), "cpu_e"),
              ("GPU", LANE["gpu"], gpu_rows, "gpu"), ("ANE", LANE["ane"], host.get("ane_cores", 16), "ane")]
    out = heatmap(x + 90, y, w - 90, h - 46, groups, cols, fn, demo)
    rh = (h - 46) / (sum(g[2] for g in groups) + 0.6 * (len(groups) - 1))
    ane_mid = y + (sum(g[2] for g in groups[:3]) + 1.8 + groups[3][2] / 2) * rh
    out += t(x + 90 + (w - 90) / 2, ane_mid + 8, "ANE idle during LLM decode", 22, LANE["ane"], 700, "middle",
             extra='opacity="0.75"')
    for i in range(tokens + 1):
        xx = x + 90 + i * (w - 90) / tokens
        out += line(xx, y - 6, xx, y + h - 46, "#ffffff", 1, 'stroke-opacity="0.10"')
    out += t(x + 90, y + h - 14, f"{tokens} tokens · {tokens * period:.0f} ms", 15, DIM, mono=True)
    note = "rows per core: demo texture" if demo else (
        f"GPU rows = aggregate ({'per-core not captured' if not host.get('gpu_cores') else 'per core'})"
        f" · level = {gpu_level:.0%} of BW ceiling")
    out += t(x + w, y + h - 14, note, 15, DIM, anchor="end")
    return out


def view_hero(b, demo):
    found = findings(b)
    body, provs = "", []
    for i, f in enumerate(headlines(found)):
        x, y, cw = 60 + i * 375, 196, 355
        c = LANE.get(f["component"], TEXT)
        body += panel(x, y, cw, 236) + r(x, y, cw, 4, c, 2)
        body += t(x + 26, y + 104, f["big"], min(76, int(300 / (0.6 * len(f["big"])))), c, 800,
                  extra='filter="url(#hero-glow)"')
        for j, ln in enumerate(wrap(f["caption"], 30)[:3]):
            body += t(x + 26, y + 146 + j * 25, ln, 19, TEXT if j == 0 else DIM, 500 if j == 0 else 400)
        body += chip(x + 26, y + 196, f"{f['factor']:.1f}× lever · {f['prov']}", PROV[f["prov"]])[0]
        provs.append(f["prov"])
    if b.get("capture"):
        body += panel(60, 462, 940, 370, f"Live capture · {b['capture']['host']} · per-core occupancy")
        body += capture_heat(b, 80, 518, 900, 300)
        provs.append("measured")
    else:
        body += panel(60, 462, 940, 370, "Decode token train · where each core spends its time")
        body += token_train(b, 80, 518, 900, 300, demo)
        if b.get("token"):
            provs.append("modeled")
    body += panel(1030, 462, 510, 370, "Biggest levers")
    for i, f in enumerate(found[:6]):
        y = 528 + i * 50
        c = LANE.get(f["component"], TEXT)
        body += t(1054, y + 6, f"{f['factor']:.1f}×", 24, c, 800, mono=True)
        body += r(1150, y - 12, min(f["factor"], 4) / 4 * 140, 16, c, 4, 'opacity="0.85"')
        name = f["what"].split(":")[0]
        body += t(1302, y + 4, name if len(name) <= 27 else name[:26] + "…", 16, TEXT)
        body += t(1302, y + 24, f["kind"], 13, DIM, mono=True)
    return frame("hero", "Where the speed goes", "Local inference on Apple Silicon under Linux · every lever, ranked",
                 body, b, provs, demo)


def view_time(b, demo):
    body, provs = "", []
    req = b.get("request")
    body += panel(60, 196, 1480, 250, f"Request · {req['label']}" if req else "Request")
    if req:
        total = sum(p["ms"] for p in req["phases"])
        x0, ww, acc = 90, 1100, 0.0
        step = min(76, 150 / max(len(req["phases"]) - 1, 1))
        for i, p in enumerate(req["phases"]):
            c = LANE.get(p["lane"], TEXT)
            px, pw = x0 + acc / total * ww, max(p["ms"] / total * ww, 4)
            y = 262 + i * step
            body += r(px, y, pw, 48, c, 8, 'opacity="0.9"')
            if pw > 320:
                body += t(px + 14, y + 32, p["name"], 20, BG, 800)
                body += t(px + pw + 12, y + 32, f"{p['ms']:,.0f} ms", 20, c, 700, mono=True)
            else:
                body += t(px + pw + 12, y + 32, f"{p['name']} · {p['ms']:,.0f} ms", 20, c, 700)
            body += t(px + 14, y + 68, p.get("note", ""), 15, DIM)
            acc += p["ms"]
            provs.append(p["prov"])
        body += t(1510, 300, f"{total / 1000:.2f} s", 72, TEXT, 800, "end", extra='filter="url(#time-glow)"')
        body += t(1510, 336, req.get("caption", "end to end"), 20, DIM, anchor="end")
    tk = b.get("token")
    body += panel(60, 466, 1480, 190, f"One decode token · {tk['label']}" if tk else "One decode token")
    if tk:
        x0, ww, acc = 90, 1420, 0.0
        for p in tk["parts"]:
            c = LANE.get(p["lane"], TEXT)
            px, pw = x0 + acc / tk["total_ms"] * ww, p["ms"] / tk["total_ms"] * ww
            body += r(px + 1, 520, pw - 2, 58, c, 8)
            body += t(px + 14, 556, p["name"], 20, BG, 800)
            body += t(px + 14, 610 if pw > 170 else 634, f"{p['ms']:.2f} ms · {p['ms'] / tk['total_ms']:.0%}", 17, c, 700, mono=True)
            acc += p["ms"]
        body += t(1510, 640, f"{tk['total_ms']:.2f} ms/token · {1000 / tk['total_ms']:.0f} tok/s · n={tk.get('n', '?')}",
                  17, DIM, anchor="end", mono=True)
        provs.append(tk["prov"])
    st = b["staircase"]
    body += panel(60, 676, 1480, 160, "Host-delay staircase · token time vs injected host delay")
    if st:
        xs, ys = [p["d1_ms"] for p in st], [p["token_ms"] for p in st]
        lo, hi = min(ys) - 0.2, max(ys) + 0.2
        px = lambda v: 300 + (v - min(xs)) / ((max(xs) - min(xs)) or 1) * 1180
        py = lambda v: 820 - (v - lo) / (hi - lo) * 100
        pts = " ".join(f"{px(a):.1f},{py(z):.1f}" for a, z in zip(xs, ys))
        body += f'<polyline points="{pts}" fill="none" stroke="{LANE["cpu"]}" stroke-width="4" filter="url(#time-glow)"/>'
        body += "".join(f'<circle cx="{px(a):.1f}" cy="{py(z):.1f}" r="6" fill="{LANE["cpu"]}"/>' for a, z in zip(xs, ys))
        base = ys[0]
        knee = max(a for a, z in zip(xs, ys) if z <= base * 1.02)
        body += t(90, 760, f"{knee:g} ms slack", 34, LANE["cpu"], 800, mono=True, extra='filter="url(#time-glow)"')
        body += t(90, 790, f"token time flat ({base:.2f} ms) until d1 = {knee:g} ms", 16, DIM)
        body += t(90, 812, f"then {max(ys):.2f} ms at d1 = {max(xs):g} ms", 16, DIM)
        provs.append(st[0]["prov"])
    else:
        body += t(800, 770, "not captured · run coreglass ingest-lab against a HostProfile run", 20, DIM, anchor="middle")
    return frame("time", "Where time goes", "Prefill, first token, and the anatomy of one decode token", body, b, provs, demo)


def gauge(x, y, w, m, scale, fid):
    c = LANE.get(m["component"], TEXT)
    out = r(x, y, w, 30, "#ffffff10", 8) + r(x, y, m["value"] / scale * w, 30, f"url(#{fid}-bar)", 8, f'filter="url(#{fid}-glow)"')
    cx = x + m["ceiling"] / scale * w
    out += line(cx, y - 14, cx, y + 44, TEXT, 2, 'stroke-dasharray="4 4"') + t(cx, y - 20, f"ceiling {m['ceiling']:g}", 15, TEXT, 600, "middle", mono=True)
    if m.get("ref"):
        rx = x + m["ref"]["value"] / scale * w
        out += line(rx, y - 6, rx, y + 36, "#ffffff", 4) + t(rx, y + 62, f"{m['ref']['label']} {m['ref']['value']:g}", 16, TEXT, 700, "middle", mono=True)
    out += t(x, y + 62, f"Linux {m['value']:g} {m['unit']}", 16, c, 700, mono=True)
    return out


def view_bandwidth(b, demo):
    body, provs = "", []
    host = b.get("host", {})
    bw = metric(b, "gpu.decode_bw")
    body += panel(60, 196, 1480, 220, "GPU decode bandwidth")
    if bw:
        scale = max(bw["ceiling"], host.get("dram_gbs_spec") or 0) * 1.04
        body += t(90, 336, f"{bw['value']:g}", 96, LANE["gpu"], 800, extra='filter="url(#bandwidth-glow)"')
        body += t(96 + len(f"{bw['value']:g}") * 58, 336, bw["unit"], 30, DIM, 600)
        body += t(90, 376, f"{bw['value'] / bw['ceiling']:.0%} of ceiling", 20, TEXT, 600)
        body += gauge(420, 290, 1060, bw, scale, "bandwidth")
        if host.get("dram_gbs_spec"):
            sx = 420 + host["dram_gbs_spec"] / scale * 1060
            body += t(sx, 250, f"spec {host['dram_gbs_spec']}", 14, DIM, 500, "end", mono=True)
        provs.append(bw["prov"])
    ks = sorted(b["kernels"], key=lambda k: -k["contig_gbs"] / k["null_gbs"] if k.get("null_gbs") else 1)
    body += panel(60, 436, 1010, 400, "Decode GEMV kernels · real row geometry vs contiguous (GB/s)")
    kscale = max([k.get("contig_gbs") or max(k.get("kernel_gbs") or [0]) for k in ks] + [bw["ceiling"] if bw else 1]) * 1.05
    rowh = min(52, 300 / max(len(ks), 1))
    bh = min(26, rowh - 10)
    for i, k in enumerate(ks):
        y = 482 + i * rowh
        x0, ww = 300, 460
        body += t(84, y + bh - 6, k["op"], 16, TEXT, 700, mono=True)
        body += r(x0, y, ww, bh, "#ffffff0a", 6)
        if k.get("contig_gbs"):
            body += r(x0, y, k["contig_gbs"] / kscale * ww, bh, "none", 6, f'stroke="{LANE["gpu"]}" stroke-dasharray="5 4" stroke-width="2"')
        if k.get("null_gbs"):
            body += r(x0, y, k["null_gbs"] / kscale * ww, bh, "url(#bandwidth-bar)", 6)
            body += t(x0 + ww + 12, y + bh - 6, f"{k['null_gbs']:.0f}" + (f" / {k['contig_gbs']:.0f}" if k.get("contig_gbs") else ""), 17, LANE["gpu"], 700, mono=True)
        if k.get("kernel_gbs"):
            lo, hi = k["kernel_gbs"]
            body += r(x0 + lo / kscale * ww, y, (hi - lo) / kscale * ww, bh, LANE["cpu"], 6, 'opacity="0.85"')
            body += t(x0 + ww + 12, y + bh - 6, f"{lo:g}–{hi:g}", 17, LANE["cpu"], 700, mono=True)
        body += t(x0 + ww + 128, y + bh - 7, k.get("bound", ""), 13, DIM)
        provs.append(k["prov"])
    body += t(84, 818, "solid = real row geometry · dashed = same bytes, contiguous · amber = measured kernel range", 14, DIM)
    body += panel(1090, 436, 450, 400, "Headroom")
    if bw:
        rows = [(f"{bw['ref']['value'] / bw['value']:.2f}×", f"proven by {bw['ref']['label']} · decode BW")] if bw.get("ref") else []
        rows.append((f"{bw['ceiling'] / bw['value']:.2f}×", "to the measured ceiling"))
        for i, (big, cap) in enumerate(rows):
            body += t(1114, 530 + i * 90, big, 56, LANE["gpu"], 800, extra='filter="url(#bandwidth-glow)"')
            body += t(1290, 520 + i * 90, cap, 17, TEXT)
    tk = b.get("token")
    if bw and bw.get("ref") and tk:
        gpu_ms = sum(p["ms"] for p in tk["parts"] if p["lane"] == "gpu")
        proj = tk["total_ms"] - gpu_ms + gpu_ms * bw["value"] / bw["ref"]["value"]
        body += t(1114, 676, f"→ {1000 / proj:.0f} tok/s from {1000 / tk['total_ms']:.0f}", 22, LANE["gpu"], 800, mono=True)
        body += t(1114, 700, f"GPU wait scaled to {bw['ref']['label']} bandwidth (modeled)", 14, DIM)
        provs.append("modeled")
    others = [m for m in b["metrics"] if m["id"] != "gpu.decode_bw" and m.get("ceiling")]
    for i, m in enumerate(others[:1 if tk else 2]):
        y = 760 + i * 60
        frac = m["value"] / m["ceiling"]
        c = LANE.get(m["component"], TEXT)
        body += t(1114, y + 10, f"{frac:.0%}", 40, c, 800)
        body += r(1240, y - 18, 270, 14, "#ffffff12", 5) + r(1240, y - 18, 270 * frac, 14, c, 5)
        body += t(1240, y + 14, wrap(m["label"], 34)[0], 15, TEXT)
        if m["unit"].startswith("%"):
            body += t(1240, y + 34, f"of {m['unit'][1:].strip()}", 14, DIM)
        provs.append(m["prov"])
    return frame("bandwidth", "Speed of every component", "Achieved vs proven (macOS) vs ceiling, down to each decode kernel",
                 body, b, provs, demo)


def view_util(b, demo):
    body, provs = "", []
    if b.get("capture"):
        body += panel(60, 196, 1480, 360, f"Live capture · {b['capture']['host']} · per-core occupancy (measured)")
        body += capture_heat(b, 90, 250, 1420, 296)
        provs.append("measured")
    else:
        body += panel(60, 196, 1480, 360, "Decode token train · core occupancy (modeled from the measured token split)")
        body += token_train(b, 90, 250, 1420, 296, demo, tokens=16, cols=320)
        if b.get("token"):
            provs += ["modeled", b["token"]["prov"]]
    anes = [p for p in b["paired"] if p["component"] == "ane"][:2]
    body += panel(60, 576, 1480, 260, "ANE · back-to-back encoder calls in one second, Linux vs macOS")
    x0, ww, y = 330, 1060, 622
    for ms_tick in range(0, 1001, 250):
        tx = x0 + ms_tick / 1000 * ww
        body += line(tx, y - 8, tx, y + 4 + len(anes) * 96, "#ffffff", 1, 'stroke-opacity="0.08"')
        body += t(tx, 828, f"{ms_tick} ms", 13, DIM, anchor="middle", mono=True)
    for p in anes:
        for name, ms, level in (("macOS", p["macos_ms"], 1.0), ("Linux", p["linux_ms"], 0.55)):
            body += t(316, y + 26, f"{p['host'].split(' · ')[0]} · {name}", 17, TEXT if name == "Linux" else DIM, 700, "end")
            done = 0.0
            while done < 1000:
                w = min(ms, 1000 - done) / 1000 * ww
                body += r(x0 + done / 1000 * ww + 1.5, y, w - 3, 38, cmap(level), 5,
                          'opacity="0.35"' if done + ms > 1000 else "")
                done += ms
            body += t(1510, y + 27, f"{1000 / ms:.1f}/s", 24, LANE["ane"] if name == "Linux" else TEXT, 800, "end", mono=True)
            y += 44
        y += 8
        provs += [p["prov"], "modeled"]
    if anes:
        body += t(84, 828, "modeled from measured latency", 13, DIM)
    body += colorbar(1240, 210, 260, "utilization")
    return frame("util", "GPU · ANE · CPU occupancy", "Which cores work, which wait, and how hard", body, b, provs, demo)


def node(x, y, w, h, name, sub, num, color):
    return (r(x, y, w, h, PANEL, 14, f'stroke="{color}" stroke-width="2" filter="url(#flow-glow)"')
            + t(x + 18, y + 36, name, 22, TEXT, 800) + t(x + 18, y + 62, sub, 15, DIM)
            + (t(x + 18, y + h - 18, num, 26, color, 800, mono=True) if num else ""))


def edge(x1, y1, x2, y2, color, width, label="", dashed=False, lx=None, ly=None):
    dash = 'stroke-dasharray="10 8"' if dashed else ""
    out = (f'<path class="flow" d="M{x1},{y1} C{(x1 + x2) / 2},{y1} {(x1 + x2) / 2},{y2} {x2},{y2}" fill="none" '
           f'stroke="{color}" stroke-width="{width:.1f}" stroke-linecap="round" {dash} opacity="0.9"/>')
    if label:
        out += t(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 12, label, 15, color, 700, "middle", mono=True)
    return out


def view_flow(b, demo):
    body, provs = "", []
    tk = b.get("token") or {"parts": [], "total_ms": 0}
    ms = {p["lane"]: p["ms"] for p in tk["parts"]}
    bw = metric(b, "gpu.decode_bw")
    ane = next((p for p in b["paired"] if p["component"] == "ane"), None)
    h196 = next((a for a in b["ablations"] if a["delta_pct"]), None)
    fmt = lambda lane: f"{ms[lane]:.2f} ms" if lane in ms else "not captured"
    body += node(60, 220, 280, 130, "Host · CPU P", "Python / MLX graph", fmt("cpu"), LANE["cpu"])
    q = next((q for q in b["queues"] if q["component"] == "gpu"), None)
    body += node(420, 220, 280, 130, "Vulkan submit", f"longest submit {q['observed_ms']:g} ms" if q else "queue · Honeykrisp",
                 fmt("queue"), LANE["queue"])
    body += node(780, 220, 340, 130, "GPU kernels", "dequant + GEMV per layer", fmt("gpu"), LANE["gpu"])
    body += node(1200, 220, 340, 130, "Sample", "logits → next token", fmt("sample"), LANE["sync"])
    body += edge(340, 285, 420, 285, LANE["cpu"], 6)
    body += edge(700, 285, 780, 285, LANE["queue"], 6)
    body += edge(1120, 285, 1200, 285, LANE["gpu"], 6)
    body += (f'<path class="flow" d="M1370,350 C1370,440 210,440 210,350" fill="none" stroke="{LANE["sync"]}" '
             f'stroke-width="3" stroke-dasharray="10 8" opacity="0.7"/>')
    body += t(560, 456, f"next token · {tk['total_ms']:.2f} ms loop" if tk["total_ms"] else "next token", 16, LANE["sync"], 700, "middle", mono=True)
    body += node(420, 500, 380, 130, "ANE", "encoders · DART-mapped", f"{ane['linux_ms']:g} ms · macOS {ane['macos_ms']:g}" if ane else "", LANE["ane"])
    body += node(60, 500, 280, 130, "CPU P-cluster", "idle states · cpuidle", f"{h196['delta_pct']:+g}% ANE" if h196 else "", LANE["cpu"])
    body += edge(340, 565, 420, 565, LANE["cpu"], 3, h196["id"] if h196 else "", dashed=True, ly=552)
    body += r(60, 700, 1480, 110, PANEL, 14, f'stroke="{LANE["mem"]}" stroke-width="2"')
    body += t(84, 744, "Unified memory · DRAM → MCC / DCS → fabric → SLC", 24, TEXT, 800)
    body += t(84, 776, "fabric and DART counters: not captured", 16, DIM)
    if bw:
        full = 40
        body += edge(950, 700, 950, 350, "#ffffff", full, dashed=False).replace('opacity="0.9"', 'opacity="0.08"')
        body += edge(950, 700, 950, 350, LANE["gpu"], full * bw["value"] / bw["ceiling"])
        body += t(990, 520, f"{bw['value']:g} GB/s", 44, LANE["gpu"], 800, extra='filter="url(#flow-glow)"')
        body += t(990, 552, f"of {bw['ceiling']:g} ceiling · pipe width = share used", 16, DIM)
        provs.append(bw["prov"])
    body += edge(610, 700, 610, 630, LANE["ane"], 4, dashed=True)
    body += t(1510, 744, f"{b['host'].get('dram_gbs_spec', '?')} GB/s spec", 24, LANE["mem"], 800, "end", mono=True)
    provs += [x["prov"] for x in (b.get("token"), ane, h196, q) if x]
    return frame("flow", "One decode token, end to end", "Data flow through host, queue, GPU, ANE, and unified memory",
                 body, b, provs, demo)


def view_gaps(b, demo):
    body, provs = "", []
    body += panel(60, 196, 860, 400, "Linux vs macOS · same silicon, same work")
    paired = b["paired"][:4]
    span = max([p["linux_ms"] for p in paired] + [1]) * 1.08
    for i, p in enumerate(paired):
        y = 300 + i * min(110, 280 / max(len(paired), 1))
        x0, ww = 300, 440
        mx, lx = x0 + p["macos_ms"] / span * ww, x0 + p["linux_ms"] / span * ww
        body += t(84, y - 4, p["label"], 18, TEXT, 700) + t(84, y + 20, p["host"], 15, DIM, mono=True)
        body += line(x0, y, x0 + ww, y, "#ffffff", 2, 'stroke-opacity="0.08"')
        body += line(mx, y, lx, y, LANE["ane"], 6, 'stroke-opacity="0.6"')
        body += f'<circle cx="{mx:.1f}" cy="{y}" r="11" fill="{TEXT}"/><circle cx="{lx:.1f}" cy="{y}" r="11" fill="{LANE["ane"]}" filter="url(#gaps-glow)"/>'
        body += t(mx, y - 18, f"{p['macos_ms']:.4g}", 14, TEXT, 600, "middle", mono=True) + t(lx, y - 18, f"{p['linux_ms']:.4g} ms", 14, LANE["ane"], 700, "middle", mono=True)
        body += t(896, y + 14, f"{p['linux_ms'] / p['macos_ms']:.1f}×", 40, LANE["ane"], 800, "end")
        provs.append(p["prov"])
    if paired:
        saved = sum(p["linux_ms"] - p["macos_ms"] for p in paired)
        body += line(84, 506, 896, 506, EDGE, 1)
        body += t(84, 566, f"{saved:,.0f} ms", 52, LANE["ane"], 800, extra='filter="url(#gaps-glow)"')
        body += t(370, 546, f"saved per run of these {len(paired)} calls if Linux matched macOS", 17, TEXT, 600)
        body += t(370, 572, "macOS proves it on the same silicon: no new hardware needed", 15, DIM)
    body += panel(940, 196, 600, 400, "Knob ablations")
    power = b["power"]
    if power:
        key = lambda p: (p.get("metric"), p.get("host"))
        power = [p for p in power if key(p) == key(power[0])]
    for i, a in enumerate(b["ablations"][:2 if power else 4]):
        y = 270 + i * 80
        c = LANE["sync"] if a["delta_pct"] > 0 else DIM
        body += t(964, y, f"{a['id']} · {a['knob']}", 17, TEXT, 700) + t(964, y + 22, f"{a['metric']} on {a['host']}", 14, DIM)
        body += r(1330, y - 16, max(abs(a["delta_pct"]) * 18, 3), 22, c, 4) + t(1516, y, f"{a['delta_pct']:+g}%", 22, c, 800, "end", mono=True)
        if a.get("takeaway"):
            body += t(964, y + 42, a["takeaway"], 14, LANE["cpu"])
        provs.append(a["prov"])
    if power:
        tmax = max(s["series"][-1][0] for s in power) or 1
        wmax = max(w for s in power for _, w in s["series"]) * 1.05
        colors = [LANE["mem"], LANE["cpu"], LANE["ane"], LANE["gpu"], LANE["queue"]]
        body += t(964, 440, f"Power · {power[0]['metric']} · {power[0]['host']}", 17, TEXT, 700)
        for i, s in enumerate(power[:5]):
            c = colors[i]
            pts = " ".join(f"{964 + ts / tmax * 552:.1f},{572 - w / wmax * 90:.1f}" for ts, w in s["series"])
            body += f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2.5" opacity="0.9"/>'
            avg = sum(w for _, w in s["series"]) / len(s["series"])
            body += t(964 + i * 112, 466, f"{s['label']} {avg:.1f}{s['unit']}", 14, c, 700, mono=True)
            provs.append(s["prov"])
        body += t(1516, 588, f"0–{tmax:.0f} s · peak {wmax / 1.05:.1f} W", 13, DIM, anchor="end", mono=True)
    body += panel(60, 616, 860, 220, "Limits and lab gates")
    for i, lim in enumerate(b["limits"][:4]):
        y = 680 + i * 40
        over = lim["value"] > lim["limit"]
        c = LANE["sync"] if over and not lim.get("status") else (LANE["mem"] if not over else DIM)
        body += t(84, y, lim["label"], 17, TEXT, 600)
        body += r(380, y - 15, 260, 16, "#ffffff10", 5) + r(380, y - 15, min(lim["value"] / lim["limit"], 1.2) / 1.2 * 260, 16, c, 5)
        body += line(380 + 260 / 1.2, y - 22, 380 + 260 / 1.2, y + 6, TEXT, 2)
        body += t(896, y, lim.get("status") or f"{lim['value']:g}{lim['unit']} / {lim['limit']:g}{lim['unit']}", 15, c, 700, "end", mono=True)
        provs.append(lim["prov"])
    body += panel(940, 616, 600, 220, "Not captured yet")
    for i, g in enumerate(b.get("not_captured", [])[:4]):
        body += t(964, 680 + i * 40, "◌ " + wrap(g, 58)[0], 16, DIM)
    return frame("gaps", "Gaps and constraints", "What macOS already proves, what our knobs did, what bounds us", body, b, provs, demo)


def polyline(x, y, w, h, vals, color, vmax, width=2.5):
    if len(vals) < 2:
        return ""
    pts = " ".join(f"{x + i / (len(vals) - 1) * w:.1f},{y + h - min(v / vmax, 1) * h:.1f}" for i, v in enumerate(vals))
    return (f'<polygon points="{x:.1f},{y + h:.1f} {pts} {x + w:.1f},{y + h:.1f}" fill="{color}" opacity="0.12"/>'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"/>')


def view_capture(b, demo):
    """The live dashboard as a static frame: peaks, per-core heatmap, power, clocks."""
    cap, body = b["capture"], ""
    st = cap["stats"]
    rails = list(st["rails"])
    tiles = [("P cores · peak 1 s", st["p_busy"], lambda v: f"{100 * v:.0f}%", LANE["cpu"]),
             ("E cores · peak 1 s", st["e_busy"], lambda v: f"{100 * v:.0f}%", "#ffd27a"),
             ("GPU busy · peak 1 s", st["gpu_busy"], lambda v: f"{100 * v:.0f}%", LANE["gpu"])
             if st.get("gpu_busy") is not None else
             ("GPU fw events · peak", st["gpu_irq"], lambda v: f"{v:.0f}/s", LANE["gpu"])]
    tiles += [(f"{r.replace(' Power', '')} · peak", st["rails"][r], lambda v: f"{v:.1f} W", LANE["mem"]) for r in rails[:2]]
    tiles.append(("Hottest sensor", st["temp_max"], lambda v: f"{v:.1f}°C", LANE["sync"]))
    for i, (label, v, fmt, c) in enumerate(tiles[:6]):
        x = 60 + i * 250
        body += panel(x, 190, 232, 140) + r(x + 14, 190, 204, 3, c if v is not None else EDGE)
        body += t(x + 18, 220, label, 15, DIM, 600)
        body += (t(x + 18, 290, fmt(v), 50, c, 800, extra='filter="url(#capture-glow)"') if v is not None
                 else t(x + 18, 290, "n/a", 50, EDGE, 800) + t(x + 18, 316, "no source on this host", 13, DIM))
    body += panel(60, 350, 1480, 350, "Per-core occupancy (measured)")
    body += capture_heat(b, 80, 398, 1440, 296)
    body += panel(60, 716, 730, 124, "Power rails (W)") + panel(810, 716, 730, 124, "Cluster clocks (GHz)")
    mine = [p for p in b["power"] if p.get("host") == cap["host"] and "live capture" in p.get("metric", "")]
    pal = [LANE["mem"], LANE["gpu"], LANE["cpu"], LANE["ane"]]
    wmax = max([w for p in mine for _, w in p["series"]] + [1])
    for i, p in enumerate(mine[:4]):
        body += polyline(84, 764, 520, 66, [w for _, w in p["series"]], pal[i], wmax)
        body += t(770, 768 + i * 18, f"{p['label'].split(' · ')[0].replace(' Power', '')} {max(w for _, w in p['series']):.1f}",
                  12, pal[i], 700, "end", mono=True)
    for i, (lab, vals) in enumerate(cap["clocks"].items()):
        c = "#ffd27a" if lab == "E" else pal[(i + 1) % 4]
        body += polyline(834, 764, 520, 66, vals, c, cap["max_ghz"])
        body += t(1520, 768 + i * 18, f"{lab} max {max(vals):.2f}", 12, c, 700, "end", mono=True)
    return frame("capture", f"Live capture · {cap['host']}",
                 f"{cap['model']} · {cap['seconds']:g} s at {cap['hz']:g} Hz · {len(cap['marks'])} marks", body, b,
                 ["measured"], demo)


VIEWS = [("hero", view_hero), ("time", view_time), ("bandwidth", view_bandwidth),
         ("util", view_util), ("flow", view_flow), ("gaps", view_gaps)]


def render_all(b, demo=False):
    frames = [(name, fn(b, demo)) for name, fn in VIEWS]
    return frames + ([("capture", view_capture(b, demo))] if b.get("capture") else [])
