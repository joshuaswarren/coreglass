"""CPU schema fixtures follow llama-bench 65840ed JSON fields, not packet copies."""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bench_parser_test", ROOT / "nvidia/parse_llama_bench.py")
assert spec is not None and spec.loader is not None
parser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parser)
evaluate = parser.evaluate

PACKET = json.loads((ROOT / "nvidia/case-pp512.json").read_text())
DEVICE_LOG = (
    "ggml_vulkan: Found 1 Vulkan devices:\nggml_vulkan: 0 = NVIDIA GeForce RTX 5060 Ti (NVIDIA) | uma: 0 | fp16: 1\n"
)


def row():
    return {
        "build_commit": "65840ed",
        "gpu_info": "NVIDIA GeForce RTX 5060 Ti",
        "backends": "Vulkan",
        "model_filename": "llama-2-7b.Q4_0.gguf",
        "n_prompt": 512,
        "n_gen": 0,
        "n_gpu_layers": 99,
        "n_cpu_moe": 0,
        "no_op_offload": 0,
        "devices": "Vulkan0",
        "flash_attn": 1,
        "split_mode": "layer",
        "avg_ns": 1000000000,
        "stddev_ns": 0,
        "avg_ts": 512.0,
        "stddev_ts": 0.0,
        "samples_ns": [1000000000] * 3,
        "samples_ts": [512.0] * 3,
    }


class Parser(unittest.TestCase):
    def test_real_schema_accepts_complete_case(self):
        self.assertEqual(evaluate(PACKET, json.dumps([row()]), DEVICE_LOG, 0, 0, 0), [])

    def test_rejects_partial_wrong_device_or_nonfinite_output(self):
        for changes in (
            {"samples_ns": [1000000000]},
            {"devices": "CPU"},
            {"backends": "CPU"},
            {"gpu_info": "Intel Arc B60"},
            {"avg_ts": float("nan")},
            {"stddev_ns": -1},
            {"build_commit": "0000000"},
            {"n_prompt": 256},
        ):
            with self.subTest(changes=changes):
                value = row() | changes
                self.assertTrue(evaluate(PACKET, json.dumps([value]), DEVICE_LOG, 0, 0, 0))

    def test_rejects_nonzero_device_loss_and_multiple_cases(self):
        for stderr, rc, count, xid in (
            (DEVICE_LOG, 1, 1, 0),
            (DEVICE_LOG + "vk::DeviceLostError", 0, 1, 0),
            (DEVICE_LOG, 0, 2, 0),
            (DEVICE_LOG, 0, 1, 1),
        ):
            self.assertTrue(evaluate(PACKET, json.dumps([row()] * count), stderr, rc, 0, xid))


if __name__ == "__main__":
    unittest.main()
