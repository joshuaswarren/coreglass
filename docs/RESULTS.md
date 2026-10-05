# Results

## 2026-10-05: three Macs, one software stack

The same model, the same prompt, and the same four LLM engines ran on an M1, an M1 Max, and an M2 Max.
Each Mac ran Omarchy with the same kernel build. One unattended `coreglass run <target> --headless --wait 1h`
captured each Mac.

Stack on every Mac:

- MLX: the released mlx-omarchy v0.7.28 wheel (`0.32.4.dev202610050725+5c15fba`), in a self-contained venv.
- Vulkan driver: Honeykrisp from Mesa `e7631595df` (the `omarchy-mlx-vulkan` build), pinned for every step
  with the host `env` key `VK_DRIVER_FILES`.
- mlx-lm: oMLX's pin `94cdcae`. The "Omarchy patches" rows add omarchy-mlx's mlx-lm 0.32 patch series on top.
- oMLX 0.7.0 with `--no-cache`. mlx_lm.server ran with `--decode-concurrency 1 --prompt-concurrency 1`.
- Model: Qwen3.8-2B-mlx-4Bit, 477 prompt tokens and 128 generated tokens, one cold request per engine.
- ANE: `ane-run` from omarchy-ane `259ba06` with that chip's add fixture.

| | M1 | M1 Max | M2 Max |
|---|---|---|---|
| mlx-lm · Omarchy patches: decode tok/s | 43.1 | 90.5 | 97.1 |
| mlx-lm · Omarchy patches: TTFT ms | 1,177 | 404 | 352 |
| mlx-lm · Omarchy patches: J/token | 0.36 | 0.36 | 0.33 |
| mlx_lm.server · Omarchy patches: decode tok/s | 11.8 | 29.0 | 36.7 |
| mlx_lm.server · Omarchy patches: TTFT ms | 2,012 | 753 | 610 |
| mlx_lm.server · Omarchy patches: J/token | 0.66 | 1.18 | 1.03 |
| oMLX · Omarchy patches: decode tok/s | 40.5 | 79.3 | 79.7 |
| oMLX · Omarchy patches: TTFT ms | 1,220 | 432 | 317 |
| oMLX · Omarchy patches: J/token | 0.39 | 0.39 | 0.37 |
| oMLX · upstream mlx-lm: decode tok/s | 26.6 | 50.9 | 49.9 |
| oMLX · upstream mlx-lm: TTFT ms | 7,584 | 3,362 | 3,253 |
| oMLX · upstream mlx-lm: J/token | 0.57 | 1.05 | 1.05 |
| GPU matmul TFLOPS (fp16 4096²) | 0.60 | 2.30 | 2.81 |
| ANE busy, jobs/s (add fixture) | 59%, 33,750 | 62%, 23,292 | 99%, 675 |
| steps rc 0 / kernel warnings | all / 0 | all / 2 | all / 0 |

How to read it:

- Each cell is one request. A gap under 3% is a tie; one request cannot show run-to-run noise.
- J/token is energy from the Total System Power rail over the decode window, divided by tokens.
- The Omarchy patch series is the largest single factor on every chip. oMLX goes from 26.6 to 40.5 tok/s on the
  M1 and from 49.9 to 79.7 on the M2 Max, and its TTFT falls by 6x to 10x.
- The ANE row is not a chip comparison. The M1 and M1 Max ran the H13 add program on 16 KiB tiles. The M2 Max ran
  the H14 add program on 32 KiB surfaces, and each of its jobs does far more work.
- The two M1 Max kernel warnings were Wi-Fi scan messages (`brcmf_cfg80211_escan_handler`), not GPU or ANE.

### The Vulkan driver matters more than the MLX build

The first pass used each Mac's system driver. The freshly installed M1 Max had stock Mesa 26.2.2 and no
`omarchy-mlx-vulkan`. Its prefill was 184 tok/s with a 2.6 s TTFT. Three alternating runs on that Mac, same venv,
same kernel:

| M1 Max Vulkan driver | prefill tok/s | TTFT ms | decode tok/s |
|---|---|---|---|
| stock Mesa 26.2.2 | 183.7 to 184.4 | 2,587 to 2,598 | 84.4 to 85.8 |
| Honeykrisp `e7631595df` | 1,079.7 to 1,187.7 | 402 to 442 | 91.2 to 91.6 |

Two MLX wheels (v0.7.26 and v0.7.28) gave the same slow prefill on the stock driver, so the driver was the cause.
Install `omarchy-mlx-vulkan`, or set `VK_DRIVER_FILES` in the host's `env`, before you compare Macs.
