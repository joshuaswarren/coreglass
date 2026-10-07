# Daily performance ledger

Run every day at 10:00 UTC by `coreglass ledger run`; a ledger day runs from 10:00 to 10:00 UTC. The suite is frozen: Qwen3.8-2B 4-bit, Qwen3-4B 4-bit; engines mlx-lm, oMLX; one cold greedy request each (about 477 prompt + 128 generated tokens); median of 3 reps. Each cell is the median, then the change against the previous day and against the best earlier day, where positive is better. TTFT is lower-is-better.

Regressions over 1% against the previous day are listed under the table with the commit range that could explain them. One cold request per rep moves by a few percent from run to run, so check the min-max spread in `docs/ledger.json` before you act on a flag.

The REGRESSION column flags every metric where main is worse than the same Mac's release stack by more than twice the larger min-max spread of the two rows.

ANE jobs/s compares only Macs that run the same program: each cell names it. H13 (M1 family) and H14 (M2 family) add programs differ in shape and work per job, so their rates are not a chip comparison.

CORRECTNESS shows the greedy token digest of each check (GDN 1536-token prompt: 1536-token prompt, 64 tokens). Main must match the same Mac's release digest, and every rep of a stack must agree.

| Date | Mac | Stack | mlx | Vulkan driver | REGRESSION vs release | CORRECTNESS | Qwen3.8-2B 4-bit · mlx-lm · prefill tok/s | Qwen3.8-2B 4-bit · mlx-lm · TTFT ms | Qwen3.8-2B 4-bit · mlx-lm · decode tok/s | Qwen3.8-2B 4-bit · oMLX · prefill tok/s | Qwen3.8-2B 4-bit · oMLX · TTFT ms | Qwen3.8-2B 4-bit · oMLX · decode tok/s | Qwen3-4B 4-bit · mlx-lm · prefill tok/s | Qwen3-4B 4-bit · mlx-lm · TTFT ms | Qwen3-4B 4-bit · mlx-lm · decode tok/s | Qwen3-4B 4-bit · oMLX · prefill tok/s | Qwen3-4B 4-bit · oMLX · TTFT ms | Qwen3-4B 4-bit · oMLX · decode tok/s | GPU matmul TFLOPS | ANE jobs/s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-07 **(CONTAMINATED: GPU never quiet (last readings [99, 98, 98, 98, 98]% busy))** | M1 Ultra | macOS reference | `mlx 0.32.2` | `Metal (macOS 26.6.2)` |  |  | – | – | – | – | – | – | – | – | – | – | – | – | – | – |
| 2026-10-07 | M1 · T8103 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  | GDN 1536-token prompt `3448b4d8` | 404 (-0.5%, -0.5%) | 1,183 (-0.5%, -0.5%) | 43.0 (-0.5%, -0.5%) | 388 (-0.6%, -0.9%) | 1,229 (-0.6%, -0.9%) | 40.7 (-0.2%, -0.2%) | 174 (+0.1%, +0.1%) | 2,748 (+0.1%, +0.1%) | 17.0 (+0.0%, -0.6%) | 166 (-0.7%, -0.7%) | 2,874 (-0.7%, -0.7%) | 16.3 (-0.6%, -0.6%) | 0.60 (+22.4%, +22.4%) | 33,790 (-0.4%, -0.4%) · H13 add, 16 KiB |
| 2026-10-07 | M1 · T8103 | main | `0.32.4.dev202610071039+ef70b8c` | `fc8f604f68` | none | GDN 1536-token prompt `3448b4d8` | 449 (+12.0%, +12.0%) | 1,064 (+10.7%, +10.7%) | 43.2 (+0.7%, +0.7%) | 426 (+11.4%, +11.4%) | 1,120 (+10.3%, +10.3%) | 40.9 (+1.5%, +1.5%) | 178 (+6.3%, +6.3%) | 2,683 (+6.0%, +6.0%) | 16.8 (+0.6%, +0.6%) | 173 (+5.4%, +5.4%) | 2,752 (+5.1%, +5.1%) | 16.3 (+1.2%, +1.2%) | 1.94 (+295.9%, +223.3%) | 33,765 (-0.1%, -0.3%) · H13 add, 16 KiB |
| 2026-10-06 **(CONTAMINATED: macstudio GPU shared with the Claude desktop app and oMLX load (omarchy-cluster 9e2010d))** | M1 Ultra | macOS reference | `mlx 0.32.2` | `Metal (macOS 26.6.2)` |  | GDN 1536-token prompt `3eb8824c` | 1,153 (-40.6%, -40.6%) | 414 (-68.3%, -68.3%) | 88.7 (-25.6%, -25.6%) | 1,839 (-0.6%, -0.6%) | 259 (-0.7%, -0.7%) | 107 (+0.1%, +0.1%) | 465 (-44.3%, -44.3%) | 1,027 (-79.4%, -79.4%) | 61.1 (-12.7%, -12.7%) | 829 (+1.4%, +1.4%) | 575 (+1.4%, +1.4%) | 65.2 (-7.9%, -7.9%) | 13.1 (-0.1%, -0.1%) | – |
| 2026-10-06 (late) | M2 Max · T6021 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  | GDN 1536-token prompt `3448b4d8` | 1,608 (+1.2%, +1.2%) | 297 (+1.2%, +1.2%) | 96.6 (+0.0%, +0.0%) | 1,511 (+0.4%, +0.4%) | 316 (+0.4%, +0.4%) | 79.7 (+0.3%, +0.3%) | 725 (+0.1%, +0.1%) | 659 (+0.1%, +0.1%) | 49.9 (-0.2%, -0.2%) | 703 (-0.2%, -0.2%) | 678 (-0.2%, -0.2%) | 46.6 (-0.6%, -0.6%) | 2.82 (+1.8%, +1.8%) | – |
| 2026-10-06 (late) | M2 Max · T6021 | main | `0.32.4.dev202610061000+bf62cfb` | `01de0431ed` | **2B mlx-lm decode -2.7%; 2B oMLX decode -3.6%; 4B mlx-lm prefill -2.5%; 4B mlx-lm TTFT -2.6%; 4B mlx-lm decode -1.8%; 4B oMLX prefill -2.3%; 4B oMLX TTFT -2.4%** | GDN 1536-token prompt `3448b4d8` | 1,586 (+2.9%, +2.9%) | 301 (+2.9%, +2.9%) | 94.0 (+3.1%, +3.1%) | 1,484 (+1.1%, +1.1%) | 322 (+1.0%, +1.0%) | 76.8 (+3.2%, +3.2%) | 706 (-0.1%, -0.1%) | 676 (-0.0%, -0.0%) | 49.0 (+2.5%, +2.5%) | 687 (-0.6%, -0.6%) | 694 (-0.6%, -0.6%) | 46.2 (+2.2%, +2.2%) | 2.81 (+1.4%, +1.4%) | – |
| 2026-10-06 | M1 · T8103 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  | GDN 1536-token prompt `3448b4d8` | 406 (+0.3%, +0.3%) | 1,177 (+0.3%, +0.3%) | 43.2 (+0.0%, +0.0%) | 390 (-0.3%, -0.3%) | 1,222 (-0.3%, -0.3%) | 40.8 (+0.2%, +0.2%) | 174 (+0.1%, +0.1%) | 2,751 (+0.0%, +0.0%) | 17.0 (-0.6%, -0.6%) | 167 (+1.3%, +1.3%) | 2,853 (+1.3%, +1.3%) | 16.4 (+0.0%, +0.0%) | 0.49 (+2.1%, +2.1%) | 33,914 (+0.4%, +0.4%) · H13 add, 16 KiB |
| 2026-10-06 | M1 · T8103 | main | `0.32.4.dev202610061000+bf62cfb` | `01de0431ed` | **4B mlx-lm decode -1.8%; 4B oMLX decode -1.8%** | GDN 1536-token prompt `3448b4d8` | 401 (+2.3%, +2.3%) | 1,192 (+2.2%, +2.2%) | 42.9 (+0.2%, +0.2%) | 382 (+1.0%, +1.0%) | 1,248 (+0.9%, +0.9%) | 40.3 (+1.0%, +1.0%) | 167 (+1.3%, +1.3%) | 2,854 (+1.3%, +1.3%) | 16.7 (+0.6%, +0.6%) | 164 (+2.0%, +2.0%) | 2,902 (+2.0%, +2.0%) | 16.1 (+0.6%, +0.6%) | 0.49 (-18.3%, -18.3%) | 33,787 (-0.2%, -0.2%) · H13 add, 16 KiB |
| 2026-10-06 (late) | M1 Max · T6001 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  | GDN 1536-token prompt `3448b4d8` | 1,174 (–, –) | 407 (–, –) | 90.5 (–, –) | 1,099 (–, –) | 434 (–, –) | 79.9 (–, –) | 505 (–, –) | 945 (–, –) | 47.8 (–, –) | 488 (–, –) | 977 (–, –) | 44.8 (–, –) | 2.30 (–, –) | 23,318 (–, –) · H13 add, 16 KiB |
| 2026-10-06 (late) | M1 Max · T6001 | main | `0.32.4.dev202610061000+bf62cfb` | `01de0431ed` | **2B mlx-lm prefill -2.6%; 2B mlx-lm TTFT -2.7%; 2B mlx-lm decode -2.3%; 2B oMLX decode -3.6%; 4B mlx-lm decode -3.8%; 4B oMLX decode -3.3%** | GDN 1536-token prompt `3448b4d8` | 1,144 (–, –) | 418 (–, –) | 88.4 (–, –) | 1,081 (–, –) | 441 (–, –) | 77.0 (–, –) | 501 (–, –) | 953 (–, –) | 46.0 (–, –) | 479 (–, –) | 996 (–, –) | 43.3 (–, –) | 2.32 (–, –) | 23,326 (–, –) · H13 add, 16 KiB |
| 2026-10-05 | M1 Ultra | macOS reference | `mlx 0.32.2` | `Metal (macOS 26.6.2)` |  |  | 1,943 (–, –) | 246 (–, –) | 119 (–, –) | 1,851 (–, –) | 258 (–, –) | 107 (–, –) | 834 (–, –) | 573 (–, –) | 70.0 (–, –) | 818 (–, –) | 583 (–, –) | 70.8 (–, –) | 13.2 (–, –) | – |
| 2026-10-05 | M2 Max · T6021 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  |  | 1,590 (–, –) | 301 (–, –) | 96.6 (–, –) | 1,506 (–, –) | 317 (–, –) | 79.5 (–, –) | 724 (–, –) | 660 (–, –) | 50.0 (–, –) | 705 (–, –) | 677 (–, –) | 46.9 (–, –) | 2.77 (–, –) | 673 (–, –) · H14 add, 32 KiB |
| 2026-10-05 | M2 Max · T6021 | main | `0.32.4.dev202610052300+2540b10` | `6dc1fba8e9` | **2B mlx-lm decode -5.6%; 2B oMLX decode -6.4%; 4B mlx-lm decode -4.4%; 4B oMLX decode -3.6%** |  | 1,541 (–, –) | 310 (–, –) | 91.2 (–, –) | 1,468 (–, –) | 325 (–, –) | 74.4 (–, –) | 707 (–, –) | 676 (–, –) | 47.8 (–, –) | 691 (–, –) | 691 (–, –) | 45.2 (–, –) | 2.77 (–, –) | 675 (–, –) · H14 add, 32 KiB |
| 2026-10-05 | M1 · T8103 | release | `0.32.4.dev202610050725+5c15fba` | `e7631595df` |  |  | 405 (–, –) | 1,180 (–, –) | 43.2 (–, –) | 392 (–, –) | 1,218 (–, –) | 40.7 (–, –) | 174 (–, –) | 2,752 (–, –) | 17.1 (–, –) | 165 (–, –) | 2,890 (–, –) | 16.4 (–, –) | 0.48 (–, –) | 33,795 (–, –) · H13 add, 16 KiB |
| 2026-10-05 | M1 · T8103 | main | `0.32.4.dev202610052300+2540b10` | `6dc1fba8e9` | **2B mlx-lm prefill -3.2%; 2B mlx-lm TTFT -3.2%; 2B mlx-lm decode -0.9%; 2B oMLX decode -2.0%; 4B mlx-lm prefill -4.8%; 4B mlx-lm TTFT -5.1%; 4B mlx-lm decode -2.9%; 4B oMLX prefill -2.4%; 4B oMLX TTFT -2.5%; 4B oMLX decode -2.4%** |  | 392 (–, –) | 1,218 (–, –) | 42.8 (–, –) | 379 (–, –) | 1,260 (–, –) | 39.9 (–, –) | 165 (–, –) | 2,891 (–, –) | 16.6 (–, –) | 161 (–, –) | 2,962 (–, –) | 16.0 (–, –) | 0.60 (–, –) | 33,852 (–, –) · H13 add, 16 KiB |

## Regressions

None.

## Server cells

Each cell starts a fresh server per variant, alternating the order across pairs, and runs c1 then c4 streamed requests. Only runs that passed the quiet gate (CPU idle >= 92%, PSI cpu some = 0) count. Values are medians, off -> on, with the change, where positive is better.

| Date | Mac | Cell | Gated runs | c1 TTFT ms | c1 aggregate tok/s | c1 server decode tok/s | c4 aggregate tok/s | c4 server decode tok/s | Greedy text (c1) |
|---|---|---|---|---|---|---|---|---|---|
| 2026-10-07 | M1 · T8103 | oMLX server · 2B · conv-fuse 0006 | 6/10 | 1,172 → 1,189 (-1.5%) | 31.0 → 31.1 (+0.3%) | 43.4 → 43.8 (+0.9%) | 35.4 → 36.0 (+1.6%) | 11.8 → 12.0 (+1.7%) | same off and on |
| 2026-10-06 (late) | M2 Max · T6021 | oMLX server · 2B · conv-fuse 0006 | 10/10 | 463 → 459 (+1.0%) | 64.2 → 68.0 (+5.8%) | 83.8 → 89.9 (+7.3%) | 61.1 → 62.5 (+2.2%) | 17.6 → 18.0 (+2.0%) | same off and on |
| 2026-10-06 | M1 · T8103 | oMLX server · 2B · conv-fuse 0006 | 9/10 | 1,408 → 1,376 (+2.2%) | 29.1 → 29.7 (+1.9%) | 42.9 → 43.5 (+1.4%) | 18.1 → 18.3 (+1.0%) | 5.25 → 5.30 (+1.0%) | same off and on |
| 2026-10-06 (late) | M1 Max · T6001 | oMLX server · 2B · conv-fuse 0006 | 9/10 | 610 → 607 (+0.5%) | 60.2 → 62.0 (+3.0%) | 84.3 → 87.9 (+4.3%) | 57.6 → 58.4 (+1.5%) | 17.1 → 17.4 (+2.1%) | same off and on |

## Linux as a percentage of the macOS reference

The reference is upstream MLX and mlx-lm on macOS on M1 Ultra. It is a different chip from the Linux Macs, so the percentage is a fixed yardstick, not parity on equal hardware. The reference Mac also serves live models, so its row uses the best of its reps (the highest rate, the lowest TTFT) when `stat = "best"`: contention only ever slows a rep.

| Date | Mac | Stack | Qwen3.8-2B 4-bit · mlx-lm · prefill tok/s | Qwen3.8-2B 4-bit · mlx-lm · decode tok/s | Qwen3.8-2B 4-bit · oMLX · prefill tok/s | Qwen3.8-2B 4-bit · oMLX · decode tok/s | Qwen3-4B 4-bit · mlx-lm · prefill tok/s | Qwen3-4B 4-bit · mlx-lm · decode tok/s | Qwen3-4B 4-bit · oMLX · prefill tok/s | Qwen3-4B 4-bit · oMLX · decode tok/s |
|---|---|---|---|---|---|---|---|---|---|---|
| 2026-10-05 | M2 Max · T6021 | release | 82% | 81% | 81% | 74% | 87% | 71% | 86% | 66% |
| 2026-10-05 | M2 Max · T6021 | main | 79% | 77% | 79% | 70% | 85% | 68% | 84% | 64% |
| 2026-10-05 | M1 · T8103 | release | 21% | 36% | 21% | 38% | 21% | 24% | 20% | 23% |
| 2026-10-05 | M1 · T8103 | main | 20% | 36% | 20% | 37% | 20% | 24% | 20% | 23% |
