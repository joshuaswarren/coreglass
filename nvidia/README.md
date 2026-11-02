# NVIDIA lane: RTX 5060 Ti Llama-2-7B Q4_0 benchmark contract

Owns the real-GPU benchmark contract for the RTX 5060 Ti Vulkan lane: same
llama-bench binary, same GGUF, same settings as the existing eGPU records,
re-expressed as a queue of exactly two independent single-submit cases.
Committed files are public-safe; the host alias and absolute paths live in the
private `~/.config/coreglass/nvidia-lane.toml` (format: `lane.example.toml`,
same policy as `hosts.example.toml` in the repo root).

## Split proof (why two cases, not fake rows)

llama-bench at source commit `65840ed53c8653bfbf3e9014d9cbf71ac8c08725`
(`tools/llama-bench/llama-bench.cpp`) builds its test list as:

- every `n_prompt != 0` value becomes one instance `(n_prompt, n_gen=0)` — a pp-only case;
- every `n_gen != 0` value becomes one instance `(n_prompt=0, n_gen)` — a tg-only case;
- `-p 0` / `-n 0` values are skipped (`continue`), so they add nothing.

The original record command `-p 512 -n 128 -r 3 -ngl 99` therefore produces
exactly the two instances `(512, 0)` and `(0, 128)`, and the split commands
`-p 512 -n 0` / `-p 0 -n 128` select those same instances one per process.
Each instance already gets its own fresh context, `llama_memory_clear`,
per-instance warmup (512-token prompt warmup for pp; 1-token gen warmup for
tg) and its `r` repetitions. The only differences in the split are an extra
untimed model load and the execution order — neither enters any metric. The
split is the same two independent cases; no duplicate run fills the queue.
The parser rejects a combined two-row output so the split cannot silently
regress into one process running both.

## Case packets (immutable)

| Queue slot | Packet | Submit (argv after `-m MODEL`) |
|---|---|---|
| 1 | `case-pp512.json` | `-ngl 99 -p 512 -n 0 -fa 1 -r 3 -o json` |
| 2 | `case-tg128.json` | `-ngl 99 -p 0 -n 128 -fa 1 -r 3 -o json` |

Each packet pins: model sha256 and size, binary sha256 and source commit,
exact argv and env pins, expected row fields, stderr markers, gates, and caps.
fa is fixed at 1 to match the record's primary Vulkan row pair; the fa=0 pair
would be a separate queue, deliberately not added here (no filler). The caller
copies the packets into the receipt and writes `SHA256SUMS` over the receipt
(house pattern), so a run's output hashes extend the packet without mutating
it.

## Custody (from receipts, not from names)

| Item | Identity | Source |
|---|---|---|
| GGUF `llama-2-7b.Q4_0.gguf` | 3,825,807,040 bytes, sha256 `78b8f9777dd620ad29cd2cffb6653b17fa8a5b1fddc1b8821180d60eedd24d48` | printed by the run itself in the 2026-10-24 receipt (`dualcard-20261024T205012Z/nvvk-*/log.txt`) |
| llama-bench binary | sha256 `5ec986362d0a11c813da31c4ffa3e2fb42d314ca4a3fa9c473829ce0e02b9119` | 2026-10-29 receipt (`nv-vk-headless-20261029/ticket-vkhl-r8.out`); same path the 10-24 run used |
| Source | `65840ed53c8653bfbf3e9014d9cbf71ac8c08725` | printed in both receipts; split proof fetched from upstream at this exact commit |
| Device | `10de:2d04`, GeForce RTX 5060 Ti, PCI `0001:09:00.0`, `Kernel driver in use: nvidia` | 2026-10-24 receipt `lspci-vvk-0001:09:00.0.txt`; PCI address is boot-dependent, so the caller re-gates it live and records what it saw |

Known discrepancy, disclosed: the published dual-card record says `-r 3`, but
the receipt matching its 5060 Ti Vulkan numbers ran `-r 5`. This contract
fixes `-r 3` as requested; the reference values below are shape references,
not matched-sample comparisons.

## Declared lane requirements (local files; no target probe was made)

- Exclusive ICD pin: `VK_ICD_FILENAMES=<icd_path>` (`/usr/share/vulkan/icd.d/nvidia_icd.json`)
  plus `GGML_VK_VISIBLE_DEVICES=0`. With the system ICD set excluded by the pin,
  Vulkan device 0 is deterministic; no visible index is guessed under multi-ICD.
- NVIDIA userspace on the loader path: `LD_LIBRARY_PATH=<nvidia_lib>:<bench_dir>`
  (the recipe the records ran with). Known local-file candidates: the
  `nvidia-egpu-595.112.07/lib` dir (2026-10-24 receipt) and the 615.78.08
  overlay (`egl-overlay-615.tar`, 2026-10-29 receipt). The window owner passes
  `--nvidia-lib` explicitly; the caller records `nvidia-smi` output so the
  serving driver version is measured, never assumed. No CUDA and no other
  backend may substitute.
- Native gate, checked at run time from the host: `lspci` shows `10de:2d04` at
  the declared PCI address with `Kernel driver in use: nvidia`; stderr shows
  `using device Vulkan0 (NVIDIA GeForce RTX 5060 Ti) (0001:09:00.0)` and
  `offloaded 33/33 layers to GPU` (full offload; a CPU fallback fails the gate).
- Identity pins before any submit: binary and GGUF sha256, source commit, ICD
  file present, load1 < 1.0, no other llama-bench running, Xid baseline read.
- Caps: one submit per case, `timeout 900` (ordinary house cap — expected wall
  time is well under 20 s for both shapes; no cap extension, no force, no
  retries). The caller never downloads a model, loads/unloads a driver,
  reboots, resets, or releases a hold; the window and any hold belong to the
  parent.

## Gates

See `GATES.md` (house CHECK/EXPECT format) and `parse_llama_bench.evaluate`,
which implements them as a pure function: rc zero, identity pins, PCI native
gate, provider identity, no CPU fallback, no Device Lost marker, finite
positive metrics, Xid delta zero, one row with the exact `(n_prompt, n_gen)`,
`n_gpu_layers=99`, `flash_attn=1`, backend `Vulkan`, gpu_info naming the card.
Any miss is FAIL (or UNCONFIRMED when a check itself could not run) — nothing
is claimed from a rejected run.

## Running

```bash
python3 nvidia/benchcase.py GO --entry ~/.local/share/apple-silicon-lab/entries/nvidia/<entry>.md \
    --nvidia-lib /path/to/serving/nvidia/lib
```

Exit codes: 0 PASS, 3 FAIL, 4 UNCONFIRMED, 2 refused. Receipts land under
`~/.local/share/apple-silicon-lab/artifacts/nvidia/llama2-queue2/<UTC>/` with
packets, cmd, stdout JSON, stderr, preflight, boot/nvidia-smi capture,
`SHA256SUMS`, and a three-valued `VERDICT`. The parent alone stages windows
and appends results; CPU-only tests: `python3 -m unittest discover -s tests`
and `python3 nvidia/benchcase.py --selftest`.

## Host hash lookup needs (for the parent)

Nothing left to invent: both custody hashes above are receipt-sourced. At the
next control window, re-verify the two live values the receipts age-stamp
(2026-10-24 GGUF, 2026-10-29 binary) and the lane state:

```sh
ssh <alias> 'sha256sum /home/joshuawarren/src/llama.cpp/build-w7g-vulkan/bin/llama-bench \
  /home/joshuawarren/models/b60/llama-2-7b.Q4_0.gguf; \
  git -C /home/joshuawarren/src/llama.cpp log -1 --format=%H; \
  ls /usr/share/vulkan/icd.d/nvidia_icd.json; nvidia-smi | head -4'
```

The caller re-runs all of these as gates before any submit, so a stale window
refuses instead of claiming.
