"""CPU-only tests for the nvidia lane contract (no ssh, no GPU)."""

import json
import pathlib
import subprocess
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "nvidia"))

from parse_llama_bench import check_row, evaluate, parse  # noqa: E402

PACKETS = sorted((REPO / "nvidia").glob("case-*.json"))
STDERR_OK = (
    "llama_prepare_model_devices: using device Vulkan0 (NVIDIA GeForce RTX 5060 Ti) (0001:09:00.0) - 15912 MiB free\n"
    "load_tensors: offloaded 33/33 layers to GPU\n"
)


def fake_row(packet):
    expect = packet["expect"]["row"]
    row = {k: v for k, v in expect.items() if not k.endswith("_contains")}
    row.update({
        "build_commit": packet["binary"]["source_commit"],
        "gpu_info": "NVIDIA GeForce RTX 5060 Ti (16311 MiB)",
        "backends": "Vulkan",
        "model_filename": "llama-2-7b.Q4_0.gguf",
        "test_time": 1761999999,
        "avg_ns": 1000000,
        "stddev_ns": 1000,
        "avg_ts": 84.92,
        "stddev_ts": 0.07,
    })
    return row


class TestSplitSemantics(unittest.TestCase):
    def test_queue_is_exactly_two_packets(self):
        self.assertEqual(len(PACKETS), 2, "queue must be exactly 2 deep, no filler")
        orders = [json.loads(p.read_text())["queue_order"] for p in PACKETS]
        self.assertEqual(sorted(orders), [1, 2])

    def test_packets_are_the_two_split_cases(self):
        shapes = [json.loads(p.read_text())["shape"] for p in PACKETS]
        self.assertEqual(sorted(shapes), ["pp512", "tg128"])

    def test_split_argv_matches_combined_case(self):
        # source semantics at 65840ed53: (-p 512 -n 128) == case-pp512 + case-tg128
        by_shape = {json.loads(p.read_text())["shape"]: json.loads(p.read_text()) for p in PACKETS}
        for shape, p, n in (("pp512", "512", "0"), ("tg128", "0", "128")):
            argv = by_shape[shape]["input"]["argv"]
            self.assertIn("-p", argv)
            self.assertEqual(argv[argv.index("-p") + 1], p, f"{shape} -p must be {p}")
            self.assertEqual(argv[argv.index("-n") + 1], n, f"{shape} -n must be {n}")
            self.assertEqual(argv[argv.index("-r") + 1], "3")
            self.assertEqual(argv[argv.index("-ngl") + 1], "99")

    def test_packets_pin_same_model_binary_and_env(self):
        pkts = [json.loads(p.read_text()) for p in PACKETS]
        for key, path in (("model", ("sha256",)), ("binary", ("sha256",)), ("binary", ("source_commit",))):
            self.assertEqual(pkts[0][key][path[0]], pkts[1][key][path[0]])
        pins = [set(p["input"]["env_pins"]) for p in pkts]
        self.assertEqual(pins[0], pins[1])
        self.assertIn("GGML_VK_VISIBLE_DEVICES", pins[0])


class TestParser(unittest.TestCase):
    def test_parses_and_checks_good_row(self):
        for p in PACKETS:
            packet = json.loads(p.read_text())
            rows = parse(json.dumps([fake_row(packet)]))
            check_row(rows[0], packet["expect"]["row"])

    def test_rejects_combined_output(self):
        packet = json.loads(PACKETS[0].read_text())
        two_rows = [fake_row(packet), fake_row(json.loads(PACKETS[1].read_text()))]
        why = evaluate(packet, json.dumps(two_rows), STDERR_OK, 0, 0, 0)
        self.assertTrue(any("expected 1" in w for w in why), why)

    def test_rejects_non_json(self):
        with self.assertRaises(ValueError):
            parse("| llama 7B Q4_0 | not json |")

    def test_rejects_nan_metric(self):
        packet = json.loads(PACKETS[1].read_text())
        row = fake_row(packet)
        row["avg_ts"] = float("nan")
        with self.assertRaises(ValueError):
            check_row(row, packet["expect"]["row"])

    def test_rejects_cpu_fallback(self):
        packet = json.loads(PACKETS[0].read_text())
        why = evaluate(packet, json.dumps([fake_row(packet)]), "offloaded 3/33 layers to GPU", 0, 0, 0)
        self.assertTrue(any("offloaded" in w for w in why), why)

    def test_rejects_wrong_provider(self):
        packet = json.loads(PACKETS[0].read_text())
        row = fake_row(packet)
        row["backend"] = "CPU"
        why = evaluate(packet, json.dumps([row]), STDERR_OK, 0, 0, 0)
        self.assertTrue(any("backend" in w for w in why), why)

    def test_rejects_nonzero_rc_and_device_lost(self):
        packet = json.loads(PACKETS[0].read_text())
        why = evaluate(packet, json.dumps([fake_row(packet)]), STDERR_OK + "VK_ERROR_DEVICE_LOST", 1, 0, 0)
        self.assertTrue(any("nonzero" in w for w in why))
        self.assertTrue(any("device lost" in w for w in why))

    def test_rejects_xid_delta(self):
        packet = json.loads(PACKETS[0].read_text())
        why = evaluate(packet, json.dumps([fake_row(packet)]), STDERR_OK, 0, 0, 2)
        self.assertTrue(any("Xid" in w for w in why), why)

    def test_passes_clean_case(self):
        packet = json.loads(PACKETS[1].read_text())
        self.assertEqual(evaluate(packet, json.dumps([fake_row(packet)]), STDERR_OK, 0, 0, 0), [])


class TestCommand(unittest.TestCase):
    def test_selftest_passes_without_network(self):
        p = subprocess.run([sys.executable, str(REPO / "nvidia" / "benchcase.py"), "--selftest"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("SELFTEST_OK queue=2", p.stdout)

    def test_refuses_without_go(self):
        p = subprocess.run([sys.executable, str(REPO / "nvidia" / "benchcase.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("GO", p.stderr)

    def test_refuses_go_without_entry(self):
        p = subprocess.run([sys.executable, str(REPO / "nvidia" / "benchcase.py"), "GO"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 2)
        self.assertIn("--entry", p.stderr)

    def test_lane_example_is_loadable(self):
        import configparser
        cp = configparser.ConfigParser()
        self.assertTrue(cp.read(REPO / "nvidia" / "lane.example.toml"))
        self.assertEqual(sorted(cp["lane"]), sorted([
            "ssh_alias", "bench_path", "llama_src", "model_path", "icd_path", "pci_addr", "pci_id"]))


if __name__ == "__main__":
    unittest.main()
