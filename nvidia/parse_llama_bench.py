"""Cheap CPU parser/validator for llama-bench -o json output (stdlib only).

Loads the JSON array llama-bench prints (one object per test instance) and
validates a case packet's expectations against it. No subprocess, no GPU.
"""

import json
import math

# Fields llama-bench emits per row at 65840ed53; see tools/llama-bench/llama-bench.cpp get_fields().
ROW_KEYS = (
    "build_commit", "gpu_info", "backends", "model_filename", "n_batch", "n_ubatch",
    "n_threads", "type_k", "type_v", "n_gpu_layers", "split_mode", "main_gpu",
    "flash_attn", "n_prompt", "n_gen", "test_time", "avg_ns", "stddev_ns", "avg_ts", "stddev_ts",
)


def parse(data):
    """Parse llama-bench JSON text into a list of row dicts. Raises ValueError."""
    try:
        rows = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"llama-bench output is not valid JSON: {e}") from e
    if not isinstance(rows, list) or not rows:
        raise ValueError("llama-bench output must be a non-empty JSON array of rows")
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("row is not an object")
    return rows


def _finite(value, field):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field} missing or not numeric")
    if not math.isfinite(value):
        raise ValueError(f"{field} is not finite")


def check_row(row, expect):
    """Validate one row against the packet's expect.row block. Raises ValueError."""
    for key, want in expect.items():
        if key.endswith("_contains"):
            continue
        got = row.get(key)
        if got != want:
            raise ValueError(f"row {key}={got!r}, expected {want!r}")
    for key in ("gpu_info_contains",):
        want = expect.get(key)
        if want and want not in str(row.get(key[: -len("_contains")], "")):
            raise ValueError(f"row {key[: -len('_contains')]} does not name {want!r}")
    _finite(row.get("avg_ts"), "avg_ts")
    _finite(row.get("stddev_ts"), "stddev_ts")
    _finite(row.get("avg_ns"), "avg_ns")
    if row["avg_ts"] <= 0:
        raise ValueError("avg_ts must be > 0")
    if row["avg_ns"] <= 0:
        raise ValueError("avg_ns must be > 0")


def evaluate(packet, stdout_text, stderr_text, rc, xid_before, xid_after):
    """Pure gate check: returns list of human-readable gate failures (empty = PASS).

    No subprocess is launched; the caller supplies captured output.
    """
    why = []
    if rc != 0:
        why.append(f"rc={rc} nonzero")
    joined = stdout_text + stderr_text
    for marker in ("Device Lost", "DEVICE_LOST", "VK_ERROR_DEVICE_LOST"):
        if marker in joined:
            why.append(f"device lost marker: {marker}")
    if xid_after != xid_before:
        why.append(f"Xid delta {xid_after - xid_before}")
    for needle in packet["expect"]["stderr_contains"]:
        if needle not in stderr_text:
            why.append(f"stderr missing {needle!r}")
    try:
        rows = parse(stdout_text)
        if len(rows) != packet["expect"]["rows"]:
            why.append(f"{len(rows)} JSON rows, expected {packet['expect']['rows']}")
        for row in rows:
            check_row(row, packet["expect"]["row"])
    except ValueError as e:
        why.append(str(e))
    return why
