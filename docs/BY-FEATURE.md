# By feature: Omarchy on Apple Silicon

This page lists each measured feature once. A row appears only when a driver commit and a source record exist.
Every number comes from a record in a public repository. The Source column names the record.

Read the share column as Linux divided by macOS. A share above 100% means Linux is faster.
A dash means no macOS run exists for that row.

## Linux against macOS on the same Mac

Both sides run MLX with mlx-lm 0.32.0 on one 13-inch M1 with 16 GB. The model is Qwen3.5-9B in 4-bit.
Both sides produce identical tokens, with output digest `80274aa7`.

| Feature | Linux | macOS | Share | Driver | Linux build | Source |
|---|---|---|---|---|---|---|
| Decode, tokens per second | 12.385 | 12.899 | 96% | Mesa `e7631595df` | `mlx-omarchy 0.32.4.dev202610100220+84b9175b` | omarchy-mlx records, A |
| Prefill of 512 tokens, tokens per second | 97.0 | 85.874 | 113% | Mesa `e7631595df` | `mlx-omarchy 0.32.4.dev202610100220+84b9175b` | omarchy-mlx records, A |

Each cell is the median of three runs. One decode run is the median over 10 greedy generations of 64 tokens.
One prefill run is the median over 5 runs of one 512-token prompt. The macOS side runs macOS 27.0 with MLX 0.32.3.
The driver is the packaged `omarchy-mlx-vulkan` 0.7.28-2, selected with no override.

Source A: [`receipts/2026-10-09-linux-vs-macos/m1-16gb/`](https://github.com/joshuaswarren/omarchy-mlx/tree/main/receipts/2026-10-09-linux-vs-macos/m1-16gb)
in omarchy-mlx. It holds `linux-dev-wheel/qwen35-9b-r1.json` to `r3.json` and `macos/qwen35-9b-r1.json` to `r3.json`.
The driver is named in [How close to macOS](https://github.com/joshuaswarren/omarchy-mlx/blob/main/docs/BENCHMARKS.md).

## Linux features measured every day

Coreglass measures these on three Macs each day. No macOS run exists for them.
The model is Qwen3.8-2B in 4-bit, run with mlx-lm. The prompt has 477 tokens and the reply has 128 tokens.
Each cell is the median of three reps. The release stack is v0.7.32. The main stack is the current omarchy-mlx main.

| Mac | Stack | Linux build | Driver | Decode, tokens per second | Prefill, tokens per second |
|---|---|---|---|---|---|
| 13-inch M1 | release | `0.32.4.dev202610101057+ae5d0950` | Mesa `e7631595df` | 43.6 | 428.0 |
| 13-inch M1 | main | `0.32.4.dev202610151008+4872e12` | Mesa `f144c7949b` | 41.6 | 425.5 |
| 16-inch M1 Max | release | `0.32.4.dev202610101057+ae5d0950` | Mesa `e7631595df` | 92.8 | 1330.4 |
| 16-inch M1 Max | main | `0.32.4.dev202610151008+4872e12` | Mesa `f144c7949b` | 96.9 | 1326.7 |
| 14-inch M2 Max | release | `0.32.4.dev202610101057+ae5d0950` | Mesa `e7631595df` | 96.8 | 1700.0 |
| 14-inch M2 Max | main | `0.32.4.dev202610151008+4872e12` | Mesa `f144c7949b` | 100.4 | 1714.4 |

Source: the 2026-10-15 rows of [`docs/ledger.json`](ledger.json), commit `a409d2c`. [LEDGER.md](LEDGER.md) shows the same rows.

## GPU kernels: translated from Metal against hand-written

This table compares Metal kernels that metal2vk translates to Vulkan with the hand-written omarchy-mlx kernels.
Both sides run on Linux on a 16-inch M1 Max with Mesa `6543eeb7df`. No macOS run exists for these rows.
Each cell is the time of one call. Lower is better. A ratio below 1 means the translated kernel is faster.
For activation, the hand side is the faster of MLX's fused kernel and its unfused form.

| Kernel | Translated | Hand-written | Ratio |
|---|---|---|---|
| Activation f32, 8M elements | 343.5 us | 739.4 us | 0.46 |
| Activation f16, 8M elements | 330.8 us | 211.4 us | 1.56 |
| Softmax f32, 4096 by 4096 | 742.3 us | 770.9 us | 0.96 |
| Softmax f16, 4096 by 4096 | 358.1 us | 410.9 us | 0.87 |
| Tile matmul f32, 256 cubed | 38.5 us | 12.3 us | 3.13 |
| Tile matmul f32, 1024 cubed | 2667.8 us | 530.9 us | 5.03 |

Source: [`bench/results-g13c-2026-10-09.json`](https://github.com/joshuaswarren/metal2vk/blob/main/bench/results-g13c-2026-10-09.json)
in metal2vk. Every translated result passed its numerical check against a reference.

## What this page leaves out

Rows with no recorded driver commit stay off this page. The full model tables, with every Linux and macOS cell,
are in [How close to macOS](https://github.com/joshuaswarren/omarchy-mlx/blob/main/docs/BENCHMARKS.md).
