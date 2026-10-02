# Coreglass

Coreglass shows where local inference loses speed on Apple Silicon under Linux.
It records live counters from the target laptops, runs marked workloads on them, and renders shareable frames.
It also writes a ranked summary that an LLM can read.

![Coreglass hero frame](docs/hero.png)

## Install

Python 3.11 or later. No dependencies. The viewer runs on x86_64 and arm64 Linux.
Chrome or Chromium is optional and only makes PNG files.

```sh
git clone https://github.com/joshuaswarren/coreglass ~/src/coreglass
uv tool install ~/src/coreglass        # or: cd ~/src/coreglass && python3 -m coreglass …
```

The viewer reaches each target by SSH alias. Targets need Python 3 only; nothing is installed on them.
List your targets in `~/.config/coreglass/hosts.toml`. Start from [hosts.example.toml](hosts.example.toml).

## Quick start

```sh
coreglass hosts                      # reachable? arch, model, load, GPU lock, MLX per target
coreglass live m2max                 # live dashboard at http://127.0.0.1:8777/
coreglass run m2max                  # capture + P-core, E-core, and MLX GPU probe steps, with marks
coreglass phases captures/<capture>.jsonl                      # per-phase means of that run
coreglass build fixtures/apple-silicon-linux-2026-10-02.json captures/<capture>.jsonl -o out/x --png
coreglass live x --replay captures/<capture>.jsonl --speed 4   # play a capture back
```

`coreglass run` refuses a busy target. Busy means a held GPU lock, load above 0.5, or a running benchmark.
Add your own steps with `--step 'LABEL=CMD'`. A `--gpu-step` runs under the host GPU lock.
Each run writes the capture and a `.run.json` manifest. The manifest holds step times, exit codes, and preflight state.

## Live capture

The live view streams per-core CPU load, cluster clocks, power rails, temperatures, and GPU activity.
It samples at 10 Hz.
The sampler is read-only and needs no root. Press `m` to mark an event, `p` to save the dashboard as a 3200×1800 PNG.

![Capture on an M2 Max: P-core load, E-core load, then an MLX matmul on the GPU](docs/capture.png)

Today the GPU row is the firmware interrupt rate. That shows activity, not busy time.
Drivers that export `agx_stats` or `ane_stats` switch the rows to measured busy time.
[docs/DESIGN.md](docs/DESIGN.md) has the producer contract and the reasons the data is missing today.

## Output

| File | Reader | Content |
|---|---|---|
| `index.html` | human | all frames, PNG/SVG export, ranked lever table |
| `frames/*.svg`, `frames/*.png` | social, docs | one 1600×900 frame each (`--png --scale 2` gives 3200×1800) |
| `summary.json` | LLM, scripts | `coreglass/summary/v1`: host, ranked findings, gaps in capture |
| `summary.md` | LLM, chat | the same ranking as a Markdown table |

Frames: `hero` · `time` · `bandwidth` · `util` · `flow` · `gaps`. A build with a live capture adds `capture`.
Every number carries provenance: `measured`, `replay`, `modeled`, or `demo`.
`--demo` adds synthetic per-core texture to modeled heatmaps and stamps every frame `DEMO`.
`--anonymize` removes host names, kernel strings, and capture file names before you post frames in public.

Fonts: Inter and JetBrains Mono, subset and embedded (SIL Open Font License, `coreglass/fonts/`).

## Tests

```sh
python3 -m unittest discover -s tests
```

Agents: read [AGENTS.md](AGENTS.md).
