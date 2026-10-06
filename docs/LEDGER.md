# Daily performance ledger

Run every day at 10:00 UTC by `coreglass ledger run`; a ledger day runs from 10:00 to 10:00 UTC. The suite is frozen: Qwen3.8-2B 4-bit, Qwen3-4B 4-bit; engines mlx-lm, oMLX; one cold greedy request each (about 477 prompt + 128 generated tokens); median of 3 reps. Each cell is the median, then the change against the previous day and against the best earlier day, where positive is better. TTFT is lower-is-better.

Regressions over 1% against the previous day are listed under the table with the commit range that could explain them. One cold request per rep moves by a few percent from run to run, so check the min-max spread in `docs/ledger.json` before you act on a flag.

The REGRESSION column flags every metric where main is worse than the same Mac's release stack by more than twice the larger min-max spread of the two rows.

ANE jobs/s compares only Macs that run the same program: each cell names it. H13 (M1 family) and H14 (M2 family) add programs differ in shape and work per job, so their rates are not a chip comparison.

| Date | Mac | Stack | mlx | Vulkan driver | REGRESSION vs release | Qwen3.8-2B 4-bit · mlx-lm · prefill tok/s | Qwen3.8-2B 4-bit · mlx-lm · TTFT ms | Qwen3.8-2B 4-bit · mlx-lm · decode tok/s | Qwen3.8-2B 4-bit · oMLX · prefill tok/s | Qwen3.8-2B 4-bit · oMLX · TTFT ms | Qwen3.8-2B 4-bit · oMLX · decode tok/s | Qwen3-4B 4-bit · mlx-lm · prefill tok/s | Qwen3-4B 4-bit · mlx-lm · TTFT ms | Qwen3-4B 4-bit · mlx-lm · decode tok/s | Qwen3-4B 4-bit · oMLX · prefill tok/s | Qwen3-4B 4-bit · oMLX · TTFT ms | Qwen3-4B 4-bit · oMLX · decode tok/s | GPU matmul TFLOPS | ANE jobs/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | M1 Ultra | macOS reference | `mlx 0.32.2` | `Metal (macOS 26.6.2)` |  | 1,943 (–, –) | 246 (–, –) | 119 (–, –) | 1,851 (–, –) | 258 (–, –) | 107 (–, –) | 834 (–, –) | 573 (–, –) | 70.0 (–, –) | 818 (–, –) | 583 (–, –) | 70.8 (–, –) | 13.2 (–, –) | – |
| 2026-10-05 | M2 Max · T6021 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  | 1,590 (–, –) | 301 (–, –) | 96.6 (–, –) | 1,506 (–, –) | 317 (–, –) | 79.5 (–, –) | 724 (–, –) | 660 (–, –) | 50.0 (–, –) | 705 (–, –) | 677 (–, –) | 46.9 (–, –) | 2.77 (–, –) | 673 (–, –) · H14 add, 32 KiB |
| 2026-10-05 | M2 Max · T6021 | main | `0.32.4.dev202610052300+2540b10` | `6dc1fba8e9` | **2B mlx-lm decode -5.6%; 2B oMLX decode -6.4%; 4B mlx-lm decode -4.4%; 4B oMLX decode -3.6%** | 1,541 (–, –) | 310 (–, –) | 91.2 (–, –) | 1,468 (–, –) | 325 (–, –) | 74.4 (–, –) | 707 (–, –) | 676 (–, –) | 47.8 (–, –) | 691 (–, –) | 691 (–, –) | 45.2 (–, –) | 2.77 (–, –) | 675 (–, –) · H14 add, 32 KiB |
| 2026-10-05 | M1 · T8103 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  | 405 (–, –) | 1,180 (–, –) | 43.2 (–, –) | 392 (–, –) | 1,218 (–, –) | 40.7 (–, –) | 174 (–, –) | 2,752 (–, –) | 17.1 (–, –) | 165 (–, –) | 2,890 (–, –) | 16.4 (–, –) | 0.48 (–, –) | 33,795 (–, –) · H13 add, 16 KiB |
| 2026-10-05 | M1 · T8103 | main | `0.32.4.dev202610052300+2540b10` | `6dc1fba8e9` | **2B mlx-lm prefill -3.2%; 2B mlx-lm TTFT -3.2%; 2B mlx-lm decode -0.9%; 2B oMLX decode -2.0%; 4B mlx-lm prefill -4.8%; 4B mlx-lm TTFT -5.1%; 4B mlx-lm decode -2.9%; 4B oMLX prefill -2.4%; 4B oMLX TTFT -2.5%; 4B oMLX decode -2.4%** | 392 (–, –) | 1,218 (–, –) | 42.8 (–, –) | 379 (–, –) | 1,260 (–, –) | 39.9 (–, –) | 165 (–, –) | 2,891 (–, –) | 16.6 (–, –) | 161 (–, –) | 2,962 (–, –) | 16.0 (–, –) | 0.60 (–, –) | 33,852 (–, –) · H13 add, 16 KiB |

## Regressions

None.

## Linux as a percentage of the macOS reference

The reference is upstream MLX and mlx-lm on macOS on M1 Ultra. It is a different chip from the Linux Macs, so the percentage is a fixed yardstick, not parity on equal hardware. The reference Mac also serves live models, so its row uses the best of its reps (the highest rate, the lowest TTFT) when `stat = "best"`: contention only ever slows a rep.

| Date | Mac | Stack | Qwen3.8-2B 4-bit · mlx-lm · prefill tok/s | Qwen3.8-2B 4-bit · mlx-lm · decode tok/s | Qwen3.8-2B 4-bit · oMLX · prefill tok/s | Qwen3.8-2B 4-bit · oMLX · decode tok/s | Qwen3-4B 4-bit · mlx-lm · prefill tok/s | Qwen3-4B 4-bit · mlx-lm · decode tok/s | Qwen3-4B 4-bit · oMLX · prefill tok/s | Qwen3-4B 4-bit · oMLX · decode tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | M2 Max · T6021 | release | 82% | 81% | 81% | 74% | 87% | 71% | 86% | 66% |
| 2026-10-05 | M2 Max · T6021 | main | 79% | 77% | 79% | 70% | 85% | 68% | 84% | 64% |
| 2026-10-05 | M1 · T8103 | release | 21% | 36% | 21% | 38% | 21% | 24% | 20% | 23% |
| 2026-10-05 | M1 · T8103 | main | 20% | 36% | 20% | 37% | 20% | 24% | 20% | 23% |
