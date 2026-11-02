# Gates: NVIDIA RTX 5060 Ti Llama-2-7B Q4_0 queue (2 deep)

OWNS: nvidia/ (this directory). Checks run on the bench host via
`nvidia/benchcase.py`; EVIDENCE columns are filled by the run receipt, never
from memory. A gate that cannot run is UNCONFIRMED, not pass.

- [ ] G1: Identity pins — binary, GGUF, source commit, ICD file
  CHECK: benchcase preflight (sha256sum of bench+model, `git log -1 --format=%H`, `test -f <icd>`)
  EXPECT: binary `5ec986362d0a11c813da31c4ffa3e2fb42d314ca4a3fa9c473829ce0e02b9119`, model
  `78b8f9777dd620ad29cd2cffb6653b17fa8a5b1fddc1b8821180d60eedd24d48`, commit
  `65840ed53c8653bfbf3e9014d9cbf71ac8c08725`, ICD present
  EVIDENCE: pending run

- [ ] G2: Native PCI gate — the actual card, nvidia kernel driver
  CHECK: `lspci -s <pci_addr> -nn -k` on the host
  EXPECT: `10de:2d04` at the declared PCI address, `Kernel driver in use: nvidia`
  EVIDENCE: pending run

- [ ] G3: Idle and exclusive — no co-running bench, load gate
  CHECK: `cut -d' ' -f1 /proc/loadavg` < 1.0; `pgrep -x llama-bench` empty
  EXPECT: both green before any submit
  EVIDENCE: pending run

- [ ] G4: Provider identity — NVIDIA Vulkan device, full offload
  CHECK: case stderr retained by the caller
  EXPECT: `using device Vulkan0 (NVIDIA GeForce RTX 5060 Ti) (0001:09:00.0)` and
  `offloaded 33/33 layers to GPU` in both cases' stderr
  EVIDENCE: pending run

- [ ] G5: Result validity — one exact row per case, finite metrics
  CHECK: `parse_llama_bench.evaluate` on the captured `-o json` stdout
  EXPECT: rc 0; exactly one row; (n_prompt,n_gen) = (512,0) / (0,128); ngl 99; fa 1;
  backend Vulkan; gpu_info names RTX 5060 Ti; avg_ts/avg_ns finite > 0; no Device
  Lost marker; Xid delta 0
  EVIDENCE: pending run

- [ ] G6: Receipt integrity — everything retained and hashed
  CHECK: receipt dir after the queue drains
  EXPECT: packets, per-case cmd/stdout/stderr, preflight, boot/nvidia-smi capture,
  VERDICT, and SHA256SUMS covering all of it
  EVIDENCE: pending run
