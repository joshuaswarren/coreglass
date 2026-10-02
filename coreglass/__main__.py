"""coreglass app | build | compare | ingest-lab | live | hosts | run | phases   (python -m coreglass --help)"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import app, build as builder, compare, ingest, live, remote


def build(args):
    r = builder.build(args.bundles, args.out, args.demo, args.png, args.scale, args.anonymize, args.theme)
    print(f"{r['out']}/index.html  ({len(r['frames'])} frames, {r['findings']} findings, bundle {r['digest']})")
    print(r["markdown"] if args.print else f"{r['out']}/summary.md")


def ingest_lab(args):
    bundle = ingest.ingest(args.root, args.host_profile, args.gemv, args.ane, ane_macos_ms=args.ane_macos_ms,
                           ane_label=args.ane_label, ane_host=args.ane_host, ane_id=args.ane_id)
    text = json.dumps(bundle, indent=1)
    if args.out == "-":
        sys.stdout.write(text + "\n")
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text)
        print(f"{args.out}: {', '.join(bundle['sources']) or 'no receipts found'}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="coreglass", description="Apple-Silicon inference studio for Linux. "
                                 "Run with no command to open the app.")
    sub = ap.add_subparsers()
    ap.set_defaults(fn=lambda a: app.run())

    a = sub.add_parser("app", help="open the Coreglass app window (default)")
    a.add_argument("--port", type=int, default=8777)
    a.add_argument("--no-window", action="store_true", help="serve only; open http://127.0.0.1:<port>/ yourself")
    a.set_defaults(fn=lambda a: app.run(a.port, not a.no_window))

    ins = sub.add_parser("install", help="add Coreglass to the app launcher (desktop entry + icon)")
    ins.set_defaults(fn=lambda a: app.install_desktop())

    b = sub.add_parser("build", help="render bundles to out/index.html, frames/*.svg|png, summary.{json,md}")
    b.add_argument("bundles", nargs="+", help="`reference`, coreglass/v1 JSON bundles, and *.jsonl captures, merged in order")
    b.add_argument("--theme", choices=("synthwave", "omarchy"), default="synthwave")
    b.add_argument("-o", "--out", default="out")
    b.add_argument("--demo", action="store_true", help="add synthetic per-core texture; every frame is stamped DEMO")
    b.add_argument("--png", action="store_true", help="also screenshot each frame with headless Chrome")
    b.add_argument("--scale", type=float, default=2, help="PNG device scale (2 = 3200x1800)")
    b.add_argument("--print", action="store_true", help="print the markdown summary to stdout")
    b.add_argument("--anonymize", action="store_true", help="drop host names, kernel strings, and capture file names "
                                                            "(for frames posted in public)")
    b.set_defaults(fn=build)

    c = sub.add_parser("compare", help="one shareable frame comparing 2-4 LLM results: engines in one run, or the "
                                       "same step across runs (versions, before/after a code change)")
    c.add_argument("specs", nargs="+", metavar="CAPTURE[#STEP][=LABEL]",
                   help="a capture adds every LLM result it has; #STEP picks one (e.g. '#serve omlx'); =LABEL names it")
    c.add_argument("-o", "--out", default="out/compare")
    c.add_argument("--title", help="frame title (default: 'Inference engines on Linux' or 'Before and after')")
    c.add_argument("--theme", choices=("synthwave", "omarchy"), default="synthwave")
    c.add_argument("--png", action="store_true", help="also write compare.png (3200x1800) with headless Chrome")
    c.add_argument("--anonymize", action="store_true", help="show chip names instead of host names and kernels")
    c.set_defaults(fn=lambda a: print(compare.compare(a.specs, a.out, a.title, a.png, 2.0, a.anonymize, a.theme)))

    i = sub.add_parser("ingest-lab", help="parse lab-notebook artifacts into a measured bundle")
    i.add_argument("-o", "--out", default="bundles/local/lab.json", help="'-' for stdout")
    i.add_argument("--root", help=f"lab artifacts directory (default: ${ingest.LAB_ROOT_ENV})")
    i.add_argument("--host-profile", help="HostProfile run dir (default: newest with host-split.json)")
    i.add_argument("--gemv", help="GemvBw window dir (default: newest with q.ndjson)")
    i.add_argument("--ane", help="ANE run dir with enc-*.log (needs --ane-macos-ms)")
    i.add_argument("--ane-macos-ms", type=float)
    i.add_argument("--ane-label", default="ANE encoder")
    i.add_argument("--ane-host", default="?")
    i.add_argument("--ane-id", help="record id; reuse a fixture id (e.g. ane.encoder.m2max) to replace that replay")
    i.set_defaults(fn=ingest_lab)

    lv = sub.add_parser("live", help="stream counters from a host (or replay a capture) into the live dashboard")
    lv.add_argument("host", help="hosts.toml name, ssh alias, or 'local'; ignored with --replay")
    lv.add_argument("--hz", type=float, default=10)
    lv.add_argument("--record", help="capture path (default captures/<host>-<UTC>.jsonl)")
    lv.add_argument("--port", type=int, default=8777)
    lv.add_argument("--seconds", type=float, help="stop after this many seconds")
    lv.add_argument("--headless", action="store_true", help="record only, no dashboard")
    lv.add_argument("--replay", help="play a recorded capture .jsonl through the dashboard instead")
    lv.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    lv.set_defaults(fn=lambda a: live.run(
        "local" if a.host == "local" else remote.resolve(a.host)["ssh"], a.hz,
        a.record or f"captures/{a.host}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.jsonl",
        a.port, a.seconds, not a.headless, a.replay, a.speed))

    hs = sub.add_parser("hosts", help="preflight each target: reachable, arch, model, quiet, GPU lock, MLX")
    hs.add_argument("names", nargs="*", help="hosts.toml names or ssh aliases (default: every configured host)")
    hs.set_defaults(fn=lambda a: remote.hosts_cmd(a.names))

    rn = sub.add_parser("run", help="capture a host while running steps on it; refuses unless the host is quiet")
    rn.add_argument("host", help="hosts.toml name or ssh alias")
    rn.add_argument("--step", action="append", default=[], metavar="LABEL=CMD", help="shell step on the target")
    rn.add_argument("--gpu-step", action="append", default=[], metavar="LABEL=CMD", help="step run under the GPU lock")
    rn.add_argument("--probe", action="store_true", help="add the built-in P/E spin + MLX matmul steps (default "
                                                         "when no steps are given)")
    rn.add_argument("--seconds", type=float, default=10, help="length of each built-in probe step")
    rn.add_argument("--baseline", type=float, default=8, help="idle seconds before the first and after the last step")
    rn.add_argument("--gap", type=float, default=4, help="idle seconds between steps")
    rn.add_argument("--hz", type=float, default=10)
    rn.add_argument("--port", type=int, default=8777)
    rn.add_argument("--headless", action="store_true")
    rn.add_argument("--force", action="store_true", help="run even if the host is busy or its GPU lock is held")
    rn.add_argument("--record", help="capture path (default captures/<host>-<UTC>.jsonl)")
    rn.set_defaults(fn=lambda a: remote.run_cmd(
        a.host, [s.split("=", 1) for s in a.step], [s.split("=", 1) for s in a.gpu_step], a.probe, a.hz, a.port,
        not a.headless, a.force, a.baseline, a.gap, a.seconds, a.record))

    ph = sub.add_parser("phases", help="per-phase means of a capture (idle baseline + each run step): CPU, GPU, "
                                       "engine busy, power; the producer acceptance check")
    ph.add_argument("capture", help="captures/<file>.jsonl (uses <file>.run.json for step windows when present)")
    ph.add_argument("--json", action="store_true")
    ph.set_defaults(fn=lambda a: remote.phases_cmd(a.capture, a.json))

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
