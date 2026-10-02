# Coreglass: guide for agents

Coreglass shows where local inference loses speed on Apple Silicon under Linux. It records live
counters from target machines, runs marked workloads on them, and renders shareable 1600×900
frames plus a ranked summary (`summary.json`, `summary.md`) for LLMs.

Read `docs/DESIGN.md` for the bundle schema, frames, sampler fields, and the driver producer contract.

## Commands

Run from the repo root (`python3 -m coreglass …`) or after `uv tool install .` (`coreglass …`).
Python 3.11+, standard library only. Chrome or Chromium is needed only for `--png`.

| Goal | Command |
|---|---|
| Check every target (reachable, arch, load, GPU lock, MLX, driver stats) | `coreglass hosts` |
| Watch a target live (dashboard at http://127.0.0.1:8777/) | `coreglass live <target>` |
| Capture while running steps on a target | `coreglass run <target>` (built-in probe) or `--step 'LABEL=CMD'`, `--gpu-step 'LABEL=CMD'` |
| Per-phase means of a run (acceptance check) | `coreglass phases captures/<file>.jsonl` (add `--json` for machines) |
| Replay a capture in the dashboard | `coreglass live x --replay captures/<file>.jsonl --speed 4` |
| Parse lab receipts | `coreglass ingest-lab --root <artifacts dir> -o bundles/local/lab.json` |
| Render frames + summary | `coreglass build fixtures/apple-silicon-linux-2026-10-02.json captures/<file>.jsonl -o out/x --png` |
| Same, safe to post publicly | add `--anonymize` |
| Tests | `python3 -m unittest discover -s tests` |

Targets come from `~/.config/coreglass/hosts.toml` (format: `hosts.example.toml`). Each entry has
`ssh`, `gpu_lock`, and optional `mlx_python` and `busy_patterns`. A bare SSH alias also works.

## Rules for runs on shared machines

1. Run `coreglass hosts <target>` first. `coreglass run` refuses a target whose GPU lock is held,
   whose load1 is ≥ 0.5, or that runs a process matching `busy_patterns`. Do not pass `--force` over
   a GPU lock that another job holds.
2. GPU steps run under the target's `gpu_lock` (`flock -w 60`). Start GPU work only through
   `--gpu-step` or the built-in probe.
3. The sampler is read-only and needs no root. Do not add writes, root reads, or module-parameter
   changes to it.
4. Record each run in your lab's experiment log before it starts. Keep the capture and its
   `.run.json` manifest with the record.

## Rules for the code

- Every number in a bundle carries `prov`: `measured`, `replay`, `modeled`, or `demo`. A missing input
  renders as "not captured". Never fill it with a plausible value.
- Frames are fixed 1600×900 SVGs; keep headline numbers ≥ 64 px.
- The repository is public. Keep host names, SSH aliases, private paths, and lab records out of it:
  `captures/`, `bundles/local/`, and `out/` are git-ignored, targets live in the user's config, and
  committed images are built with `--anonymize`.
- To light up per-engine busy time, a driver exports `agx_stats` or `ane_stats` per the
  "Producer contract" in `docs/DESIGN.md`. The sampler and frames already read it.
