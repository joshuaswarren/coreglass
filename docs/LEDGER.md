# Daily performance ledger

Run every day at 10:00 UTC by `coreglass ledger run`; a ledger day runs from 10:00 to 10:00 UTC. The suite is frozen: Qwen3.8-2B 4-bit, Qwen3-4B 4-bit; engines mlx-lm, oMLX; one cold greedy request each (about 477 prompt + 128 generated tokens); median of 3 reps. Each cell is the median, then the change against the previous day and against the best earlier day, where positive is better. TTFT is lower-is-better.

Regressions over 1% against the previous day are listed under the table with the commit range that could explain them. One cold request per rep moves by a few percent from run to run, so check the min-max spread in `docs/ledger.json` before you act on a flag.

| Date | Mac | Stack | mlx | Vulkan driver | Qwen3.8-2B 4-bit · mlx-lm · prefill tok/s | Qwen3.8-2B 4-bit · mlx-lm · TTFT ms | Qwen3.8-2B 4-bit · mlx-lm · decode tok/s | Qwen3.8-2B 4-bit · oMLX · prefill tok/s | Qwen3.8-2B 4-bit · oMLX · TTFT ms | Qwen3.8-2B 4-bit · oMLX · decode tok/s | Qwen3-4B 4-bit · mlx-lm · prefill tok/s | Qwen3-4B 4-bit · mlx-lm · TTFT ms | Qwen3-4B 4-bit · mlx-lm · decode tok/s | Qwen3-4B 4-bit · oMLX · prefill tok/s | Qwen3-4B 4-bit · oMLX · TTFT ms | Qwen3-4B 4-bit · oMLX · decode tok/s | GPU matmul TFLOPS | ANE jobs/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | M1 Ultra | macOS reference | `mlx 0.32.2` | `Metal (macOS 26.6.2)` | 1,253 (–, –) | 381 (–, –) | 145 (–, –) | 942 (–, –) | 506 (–, –) | 47.6 (–, –) | 791 (–, –) | 603 (–, –) | 63.8 (–, –) | 357 (–, –) | 1,335 (–, –) | 56.7 (–, –) | 5.55 (–, –) | – |
| 2026-10-05 | M2 Max · T6021 | main | `0.32.4.dev202610052300+2540b10` | `6dc1fba8e9` | 1,541 (–, –) | 310 (–, –) | 91.2 (–, –) | 1,468 (–, –) | 325 (–, –) | 74.4 (–, –) | 707 (–, –) | 676 (–, –) | 47.8 (–, –) | 691 (–, –) | 691 (–, –) | 45.2 (–, –) | 2.77 (–, –) | 675 (–, –) |
| 2026-10-05 | M1 · T8103 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` | 405 (–, –) | 1,180 (–, –) | 43.2 (–, –) | 392 (–, –) | 1,218 (–, –) | 40.7 (–, –) | 174 (–, –) | 2,752 (–, –) | 17.1 (–, –) | 165 (–, –) | 2,890 (–, –) | 16.4 (–, –) | 0.48 (–, –) | 33,795 (–, –) |
| 2026-10-05 | M1 · T8103 | main | `0.32.4.dev202610052300+2540b10` | `6dc1fba8e9` | 392 (–, –) | 1,218 (–, –) | 42.8 (–, –) | 379 (–, –) | 1,260 (–, –) | 39.9 (–, –) | 165 (–, –) | 2,891 (–, –) | 16.6 (–, –) | 161 (–, –) | 2,962 (–, –) | 16.0 (–, –) | 0.60 (–, –) | 33,852 (–, –) |

## Regressions

None.

## Linux as a percentage of the macOS reference

The reference is upstream MLX and mlx-lm on macOS on M1 Ultra. It is a different chip from the Linux Macs, so the percentage is a fixed yardstick, not parity on equal hardware.

| Date | Mac | Stack | Qwen3.8-2B 4-bit · mlx-lm · prefill tok/s | Qwen3.8-2B 4-bit · mlx-lm · decode tok/s | Qwen3.8-2B 4-bit · oMLX · prefill tok/s | Qwen3.8-2B 4-bit · oMLX · decode tok/s | Qwen3-4B 4-bit · mlx-lm · prefill tok/s | Qwen3-4B 4-bit · mlx-lm · decode tok/s | Qwen3-4B 4-bit · oMLX · prefill tok/s | Qwen3-4B 4-bit · oMLX · decode tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | M2 Max · T6021 | main | 123% | 63% | 156% | 156% | 89% | 75% | 193% | 80% |
| 2026-10-05 | M1 · T8103 | release | 32% | 30% | 42% | 86% | 22% | 27% | 46% | 29% |
| 2026-10-05 | M1 · T8103 | main | 31% | 30% | 40% | 84% | 21% | 26% | 45% | 28% |
