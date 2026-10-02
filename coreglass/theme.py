"""One palette for frames, the live canvas, and the app.

`synthwave` is Coreglass's own look. `omarchy` follows the active Omarchy theme's colors.toml,
so the app retints with `omarchy-theme-set` like the rest of the desktop.
"""

import tomllib
from pathlib import Path

SYNTHWAVE = {
    "name": "synthwave", "mode": "dark",
    "bg": "#0b0420", "panel": "#140a33", "edge": "#2e1a5e", "text": "#fdf4ff", "dim": "#a99bd4",
    "sun_top": "#ffd319", "sun_mid": "#ff2a6d", "sun_low": "#9d2bff", "grid": "#ff2a6d",
    "glow1": "#00e5ff", "glow2": "#ff2a6d",
    "gpu": "#00e5ff", "ane": "#ff2ad8", "cpu": "#ffb52e", "e": "#ffe08a", "queue": "#9d7bff",
    "sync": "#ff4f6d", "mem": "#3dffb5",
    "measured": "#3dffb5", "replay": "#5ab0ff", "modeled": "#ffb52e", "demo": "#ff4f6d",
    "cmap": [(0.0, "#0c0624"), (0.2, "#3a0f7a"), (0.45, "#a3197f"), (0.7, "#ff3d5a"),
             (0.88, "#ffb52e"), (1.0, "#fff7a1")],
}

THEME_FILES = (Path.home() / ".local/state/omarchy/current/theme/colors.toml",
               Path.home() / ".config/omarchy/current/theme/colors.toml")


def _hex(c):
    return tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, f):
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * f) for x, y in zip(_hex(a), _hex(b)))


def omarchy_colors():
    path = next((p for p in THEME_FILES if p.exists()), None)
    if not path:
        return None, None
    name = path.parents[1].joinpath("theme.name")
    return tomllib.loads(path.read_text()), (name.read_text().strip() if name.exists() else path.parent.name)


def omarchy():
    """Map Omarchy's semantic palette onto Coreglass roles; None when no Omarchy theme is active."""
    c, name = omarchy_colors()
    if not c:
        return None
    g = lambda *keys: next((c[k] for k in keys if k in c), None)
    bg, fg = g("background", "bg"), g("foreground", "fg")
    accent = g("accent", "blue", "color4") or fg
    p = {
        "name": f"omarchy:{name}", "mode": c.get("mode", "dark"),
        "bg": g("darker_background", "darker_bg") or mix(bg, "#000000", 0.25),
        "panel": g("lighter_background", "lighter_bg") or mix(bg, fg, 0.06),
        "edge": g("muted", "color8") or mix(bg, fg, 0.2),
        "text": g("bright_foreground", "bright_fg") or fg, "dim": mix(fg, bg, 0.28),
        "gpu": g("cyan", "color6") or accent, "ane": g("magenta", "color5") or accent,
        "cpu": g("yellow", "color3") or accent, "queue": g("blue", "color4") or accent,
        "sync": g("red", "color1") or accent, "mem": g("green", "color2") or accent,
    }
    p.update({"e": mix(p["cpu"], p["text"], 0.45), "glow1": accent, "glow2": p["ane"], "grid": accent,
              "sun_top": p["cpu"], "sun_mid": p["sync"], "sun_low": p["ane"],
              "measured": p["mem"], "replay": p["queue"], "modeled": p["cpu"], "demo": p["sync"],
              "cmap": [(0.0, mix(p["bg"], "#000000", 0.2)), (0.25, mix(p["bg"], accent, 0.45)), (0.55, accent),
                       (0.8, p["cpu"]), (1.0, mix(p["cpu"], "#ffffff", 0.6))]})
    return p


def get(name="synthwave"):
    return (omarchy() or SYNTHWAVE) if name == "omarchy" else SYNTHWAVE


def css_vars(p):
    keys = ("bg", "panel", "edge", "text", "dim", "gpu", "ane", "cpu", "e", "queue", "sync", "mem",
            "glow1", "glow2", "grid", "sun_top", "sun_mid", "sun_low")
    return (":root{" + "".join(f"--{k.replace('_', '-')}:{p[k]};" for k in keys)
            + f"color-scheme:{'light' if p.get('mode') == 'light' else 'dark'}}}")


def chrome_css(p):
    """Shared look for the app, the live dashboard, and the report page: sunset glow, a rolling neon
    horizon grid, a chrome wordmark, glowing controls, and keycaps. Plain modern CSS, no build step."""
    return css_vars(p) + """
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:var(--bg);color:var(--text);font:15px/1.5 Inter,'Helvetica Neue','Liberation Sans',Arial,sans-serif;
  -webkit-font-smoothing:antialiased}
body::before{content:"";position:fixed;inset:0;z-index:-2;pointer-events:none;background:
  radial-gradient(55% 45% at 6% 0%,color-mix(in srgb,var(--glow1) 22%,transparent),transparent 70%),
  radial-gradient(55% 50% at 94% 0%,color-mix(in srgb,var(--glow2) 22%,transparent),transparent 70%),
  radial-gradient(70% 40% at 50% 100%,color-mix(in srgb,var(--sun-low) 32%,transparent),transparent 72%)}
body::after{content:"";position:fixed;left:-60%;right:-60%;bottom:0;height:30vh;z-index:-1;pointer-events:none;
  background-image:linear-gradient(var(--grid) 1.5px,transparent 1.5px),linear-gradient(90deg,var(--grid) 1.5px,transparent 1.5px);
  background-size:72px 72px;transform:perspective(360px) rotateX(64deg);transform-origin:bottom;
  -webkit-mask-image:linear-gradient(to top,#000 5%,transparent 92%);mask-image:linear-gradient(to top,#000 5%,transparent 92%);
  opacity:.5;animation:cg-grid 1.8s linear infinite}
@keyframes cg-grid{to{background-position:0 72px}}
@media (prefers-reduced-motion:reduce){body::after{animation:none}}
.mark{font-weight:900;letter-spacing:.42em;text-transform:uppercase;white-space:nowrap;
  background:linear-gradient(90deg,var(--sun-top),var(--sun-mid) 55%,var(--glow1));-webkit-background-clip:text;
  background-clip:text;color:transparent;filter:drop-shadow(0 0 9px color-mix(in srgb,var(--sun-mid) 55%,transparent))}
header.bar{position:sticky;top:0;z-index:5;display:flex;gap:10px;align-items:center;padding:12px 22px;
  background:color-mix(in srgb,var(--bg) 78%,transparent);backdrop-filter:blur(14px);
  border-bottom:1px solid color-mix(in srgb,var(--edge) 80%,transparent)}
button{background:color-mix(in srgb,var(--panel) 88%,transparent);color:var(--text);border:1px solid var(--edge);
  border-radius:10px;padding:7px 12px;font:inherit;font-size:14px;cursor:pointer;
  transition:border-color .15s,box-shadow .15s,transform .05s}
button:hover{border-color:var(--glow1);box-shadow:0 0 0 1px var(--glow1),0 0 18px color-mix(in srgb,var(--glow1) 35%,transparent)}
button:active{transform:translateY(1px)}
button:focus-visible{outline:2px solid var(--glow1);outline-offset:2px}
button.on,button.primary{background:linear-gradient(90deg,var(--sun-mid),var(--sun-low));border-color:transparent;
  color:#fff;font-weight:700;text-shadow:0 1px 0 #0006}
button:disabled{opacity:.4;cursor:not-allowed;box-shadow:none;border-color:var(--edge)}
kbd{font:600 11px 'JetBrains Mono','DejaVu Sans Mono',monospace;padding:1px 6px;border:1px solid var(--edge);
  border-bottom-width:2px;border-radius:5px;color:var(--dim);margin-left:7px;background:color-mix(in srgb,var(--bg) 60%,transparent)}
button.primary kbd,button.on kbd{color:#fff;border-color:#ffffff70;background:#00000030}
.hint{color:var(--dim);font-size:13px}.sp{flex:1}
"""
