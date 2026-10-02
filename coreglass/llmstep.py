"""LLM probe step. Runs on the target under the host's MLX Python: `python - MODEL PROMPT_TOKENS GEN_TOKENS`.

Writes its pid to /tmp/coreglass-watch.pid so the sampler records its threads, warms up once, then runs
one measured request. The last stdout line is {"coreglass_result": {...}, "token_unix": [...]}.
"""

import json
import os
import sys
import time
from pathlib import Path

model_dir, n_prompt, n_gen = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
Path("/tmp/coreglass-watch.pid").write_text(str(os.getpid()))

import mlx.core as mx  # noqa: E402
from mlx_lm import load, stream_generate  # noqa: E402

t = time.time()
model, tok = load(model_dir)
load_s = time.time() - t
text = "Apple Silicon runs local language models on Linux through Vulkan and a reverse engineered GPU driver. "
ids = tok.encode(text * max(1, round(n_prompt / 18)))  # same text servestep.py sends, so every engine sees one prompt
for _ in stream_generate(model, tok, tok.encode("Warm up the GPU."), max_tokens=8):
    pass
mx.reset_peak_memory()
stamps, last, t = [], None, time.time()
for last in stream_generate(model, tok, ids, max_tokens=n_gen):
    stamps.append(time.time())
weights = sum(p.stat().st_size for p in Path(model_dir).glob("*.safetensors"))
cfg = json.loads((Path(model_dir) / "config.json").read_text())
bits = (cfg.get("quantization") or {}).get("bits")
print(json.dumps({"coreglass_result": {
    "model": f"{cfg.get('model_type', Path(model_dir).name)}{f' {bits}-bit' if bits else ''}",
    "load_s": round(load_s, 2), "prompt_tokens": last.prompt_tokens,
    "prefill_tok_s": round(last.prompt_tps, 1), "ttft_ms": round((stamps[0] - t) * 1000, 1),
    "gen_tokens": last.generation_tokens, "decode_tok_s": round(last.generation_tps, 1),
    "peak_mem_gb": round(last.peak_memory, 2), "weights_gb": round(weights / 1e9, 3)},
    "token_unix": [round(s, 4) for s in stamps]}), flush=True)
