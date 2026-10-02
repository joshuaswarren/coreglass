"""Server probe step. Runs on the target (stdlib only): `python3 - CMD MODEL_DIR PROMPT_TOKENS GEN_TOKENS`.

Starts an OpenAI-compatible server from CMD ({port} is filled in), points the sampler at its pid through
/tmp/coreglass-watch.pid, waits for /v1/models, sends one warmup and one measured streaming completion,
stops the server, and prints {"coreglass_result": {...}, "token_unix": [...]} like llmstep.py.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

cmd, model_dir, n_prompt, n_gen = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
SENTENCE = "Apple Silicon runs local language models on Linux through Vulkan and a reverse engineered GPU driver. "

with socket.socket() as s:
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
base = f"http://127.0.0.1:{port}/v1"
log = Path(f"/tmp/coreglass-serve-{port}.log")
hf_cache = Path.home() / ".local/share/coreglass/hf-cache"  # mlx_lm.server's /v1/models fails without one
hf_cache.mkdir(parents=True, exist_ok=True)
t0 = time.time()
server = subprocess.Popen("exec " + cmd.format(port=port), shell=True, stdout=log.open("w"),
                          stderr=subprocess.STDOUT, start_new_session=True,
                          env=os.environ | {"HF_HUB_CACHE": str(hf_cache)})
Path("/tmp/coreglass-watch.pid").write_text(str(server.pid))


def stop():
    if server.poll() is None:
        os.killpg(server.pid, signal.SIGTERM)
        try:
            server.wait(15)
        except subprocess.TimeoutExpired:
            os.killpg(server.pid, signal.SIGKILL)


def listed_model():
    """The model id to request once /v1/models answers, else None. mlx_lm.server serves its --model as
    "default_model" when the listing does not name it."""
    try:
        with urllib.request.urlopen(base + "/models", timeout=2) as r:
            ids = [m["id"] for m in json.load(r).get("data", [])]
    except Exception:
        return None
    return next((i for i in ids if Path(model_dir).name in i), "default_model")


def stream(prompt, max_tokens):
    body = {"model": model, "prompt": prompt, "max_tokens": max_tokens, "temperature": 0, "stream": True,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(base + "/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    stamps, usage = [], None
    with urllib.request.urlopen(req, timeout=600) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            msg = json.loads(line[5:])
            if any(c.get("text") for c in msg.get("choices", [])):
                stamps.append(time.time())
            usage = msg.get("usage") or usage
    return stamps, usage or {}


try:
    model = None
    while model is None:
        if server.poll() is not None:
            raise RuntimeError(f"server exited with {server.returncode} before it was ready")
        if time.time() - t0 > 300:
            raise RuntimeError("server not ready after 300 s")
        model = listed_model()
        if model is None:
            time.sleep(0.5)
    ready_s = time.time() - t0
    stream("Warm up the GPU.", 8)
    t = time.time()
    stamps, usage = stream(SENTENCE * max(1, round(n_prompt / 18)), n_gen)
    if len(stamps) < 2:
        raise RuntimeError(f"server streamed {len(stamps)} chunks")
except Exception as e:
    tail = log.read_text(errors="replace")[-1500:] if log.exists() else ""
    print(f"{type(e).__name__}: {e}\n--- server log tail ---\n{tail}", file=sys.stderr, flush=True)
    sys.exit(4)
finally:
    stop()
gen = usage.get("completion_tokens") or len(stamps)
prompt = usage.get("prompt_tokens")
ttft = stamps[0] - t
cfg = json.loads((Path(model_dir) / "config.json").read_text())
bits = (cfg.get("quantization") or {}).get("bits")
weights = sum(p.stat().st_size for p in Path(model_dir).glob("*.safetensors"))
print(json.dumps({"coreglass_result": {
    "model": f"{cfg.get('model_type', Path(model_dir).name)}{f' {bits}-bit' if bits else ''}",
    "load_s": round(ready_s, 2), "prompt_tokens": prompt,
    "prefill_tok_s": round(prompt / ttft, 1) if prompt else None, "ttft_ms": round(ttft * 1000, 1),
    "gen_tokens": gen, "stream_chunks": len(stamps),
    # Servers may pack several tokens into one chunk; drop the first chunk's share, not one token.
    "decode_tok_s": round((gen - gen / len(stamps)) / (stamps[-1] - stamps[0]), 1),
    "weights_gb": round(weights / 1e9, 3)},
    "token_unix": [round(s, 4) for s in stamps]}), flush=True)
