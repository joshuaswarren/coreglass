"""Render bundles + captures to an output folder: index.html, frames/*.svg|png, summary.{json,md}."""

import json
import shutil
import subprocess
from pathlib import Path

from . import ingest, model, page, theme, views

CHROMES = ("chromium", "google-chrome", "google-chrome-stable", "chromium-browser")
REFERENCE = Path(__file__).with_name("fixtures") / "apple-silicon-linux-2026-10-02.json"


def browser():
    return next((shutil.which(c) for c in CHROMES if shutil.which(c)), None)


def shoot(svg, png, scale):
    chrome = browser()
    if not chrome:
        raise SystemExit("PNG export needs Chrome or Chromium on PATH")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                    f"--force-device-scale-factor={scale}", f"--window-size={views.W},{views.H}",
                    f"--screenshot={png}", Path(svg).resolve().as_uri()],
                   check=True, capture_output=True, timeout=60)


def resolve(item):
    """`reference` = the packaged measurement fixture; *.jsonl = a live capture; else a bundle path."""
    if item == "reference":
        return str(REFERENCE)
    return ingest.capture(item) if str(item).endswith(".jsonl") else item


def build(inputs, out, demo=False, png=False, scale=2.0, anonymize=False, theme_name="synthwave"):
    bundle = model.load([resolve(i) for i in inputs])
    if anonymize:
        bundle = model.anonymize(bundle)
    summary = model.summary(bundle)
    md = model.markdown(summary)
    palette = theme.get(theme_name)
    frames = views.render_all(bundle, demo=demo, palette=palette)
    out = Path(out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(page.render(frames, summary, md, palette))
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    (out / "summary.md").write_text(md)
    for name, svg in frames:
        path = out / "frames" / f"{name}.svg"
        path.write_text(svg)
        if png:
            shoot(path, out / "frames" / f"{name}.png", scale)
    return {"out": str(out), "frames": [name for name, _ in frames], "findings": len(summary["findings"]),
            "digest": bundle["digest"], "markdown": md, "theme": palette["name"]}
