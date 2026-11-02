"""Local subprocess checks; no SSH, driver, model, or user capture store."""

import importlib.util
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nvidia"))
spec = importlib.util.spec_from_file_location("benchcase_process", ROOT / "nvidia/benchcase.py")
assert spec is not None and spec.loader is not None
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class ProcessRetention(unittest.TestCase):
    def test_timeout_retains_both_raw_streams(self):
        with tempfile.TemporaryDirectory(prefix="coreglass-process-") as tmp:
            out = Path(tmp)
            script = out / "child with spaces.py"
            script.write_text(
                "import os,time\nos.write(1,b'partial\\xff\\r\\n')\nos.write(2,b'diagnostic\\xfe\\r')\ntime.sleep(30)\n"
            )
            result = bench.run_process([sys.executable, str(script)], dict(os.environ), out, 0.2)
            self.assertEqual(result["rc"], 124)
            self.assertTrue(result["retired"])
            self.assertEqual((out / "stdout.json").read_bytes(), b"partial\xff\r\n")
            self.assertEqual((out / "stderr.txt").read_bytes(), b"diagnostic\xfe\r")

    @unittest.skipUnless(sys.platform == "linux", "process-group retirement uses Linux procfs")
    def test_timeout_retires_descendant_after_parent_exits(self):
        with tempfile.TemporaryDirectory(prefix="coreglass-retirement-") as tmp:
            out = Path(tmp)
            script = out / "child.py"
            script.write_text(
                "import os,signal,time\n"
                "pid=os.fork()\n"
                "if pid==0:\n"
                " signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                " while True: time.sleep(.02)\n"
                "open('descendant.pid','w').write(str(pid))\n"
                "while True: time.sleep(.02)\n"
            )
            try:
                result = bench.run_process([sys.executable, str(script)], dict(os.environ), out, 0.2)
                self.assertEqual(result["rc"], 124)
                self.assertTrue(result["retired"])
                pid = int((out / "descendant.pid").read_text())
                status = Path(f"/proc/{pid}/stat")
                self.assertTrue(not status.exists() or status.read_text().split(") ", 1)[1][0] == "Z")
            finally:
                pidfile = out / "descendant.pid"
                if pidfile.exists():
                    try:
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_normal_exit_retains_original_bytes(self):
        with tempfile.TemporaryDirectory(prefix="coreglass-success-") as tmp:
            out = Path(tmp)
            result = bench.run_process(
                [sys.executable, "-c", "import os;os.write(1,b'OK\\xff\\r\\n');os.write(2,b'ERR\\xfe\\r')"],
                dict(os.environ),
                out,
                2,
            )
            self.assertEqual(result["rc"], 0)
            self.assertTrue(result["retired"])
            self.assertEqual((out / "stdout.json").read_bytes(), b"OK\xff\r\n")
            self.assertEqual((out / "stderr.txt").read_bytes(), b"ERR\xfe\r")

    def test_unguarded_cli_refuses_before_any_output(self):
        import subprocess

        with tempfile.TemporaryDirectory(prefix="coreglass-queue-refusal-") as tmp:
            out = Path(tmp) / "absent-output"
            env = {k: v for k, v in os.environ.items() if not k.startswith("GPU_TURN_")}
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "nvidia/benchcase.py"),
                    "--packet",
                    str(Path(tmp) / "not-read.json"),
                    "--lane-file",
                    str(Path(tmp) / "not-read.toml"),
                    "--runtime",
                    str(Path(tmp) / "not-read-runtime.json"),
                    "--nvidia-lib",
                    tmp,
                    "--out",
                    str(out),
                ],
                env=env,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(b"idle-guard", result.stderr)
            self.assertFalse(out.exists())

    def test_denied_kernel_log_retains_error_and_cannot_be_zero(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="coreglass-xid-") as tmp:
            out = Path(tmp)
            original = bench.run_process

            def denied(_argv, env, receipt, timeout):
                return original(
                    [sys.executable, "-c", "import os;os.write(2,b'permission denied\\r\\n');raise SystemExit(13)"],
                    env,
                    receipt,
                    timeout,
                )

            with patch.object(bench, "run_process", denied):
                with self.assertRaisesRegex(ValueError, "unconfirmed"):
                    bench.xid_count(out, "before")
            self.assertEqual((out / "before/stderr.txt").read_bytes(), b"permission denied\r\n")
            self.assertEqual(bench.json.loads((out / "before/process.json").read_text())["returncode"], 13)

    def test_failed_case_hashes_verdict_and_preserves_spaced_toml_path(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory(prefix="coreglass-failed-receipt-") as tmp:
            directory = Path(tmp)
            binary = directory / "binary with spaces"
            binary.write_bytes(b"not an executable")
            packet = directory / "packet.json"
            packet.write_text(
                bench.json.dumps({"binary": {"sha256": "0" * 64}, "model": {"sha256": "0" * 64, "bytes": 0}})
            )
            lane = directory / "lane.toml"
            lane.write_text(
                "[lane]\nbench_path = "
                + bench.json.dumps(str(binary))
                + "\nmodel_path = "
                + bench.json.dumps(str(binary))
                + "\n"
            )
            runtime = directory / "runtime.json"
            runtime.write_text("{}")
            out = directory / "receipt"
            argv = [
                "benchcase",
                "--packet",
                str(packet),
                "--lane-file",
                str(lane),
                "--runtime",
                str(runtime),
                "--nvidia-lib",
                tmp,
                "--out",
                str(out),
            ]
            handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
            try:
                with patch.object(bench, "in_turn", return_value=True), patch.object(sys, "argv", argv):
                    self.assertEqual(bench.main(), 4)
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
            verdict = bench.json.loads((out / "verdict.json").read_text())
            self.assertEqual(verdict["verdict"], "UNCONFIRMED")
            self.assertIn("bench_path hash mismatch", verdict["reasons"])
            entries = [line.split("  ", 1) for line in (out / "SHA256SUMS").read_text().splitlines()]
            self.assertIn("verdict.json", [name for _, name in entries])
            self.assertEqual({name for _, name in entries}, {p.name for p in out.iterdir() if p.name != "SHA256SUMS"})
            for digest, name in entries:
                self.assertEqual(bench.sha256(out / name), digest)

    def test_inherited_flock_descriptor_reaches_owned_child(self):
        import subprocess

        with tempfile.TemporaryDirectory(prefix="coreglass-held-turn-") as tmp:
            directory = Path(tmp)
            fixture = directory / "held-turn.py"
            source = ROOT / "nvidia/benchcase.py"
            lock = directory / "gpu.lock"
            fixture.write_text(
                "import importlib.util,os,pathlib,sys\n"
                f"spec=importlib.util.spec_from_file_location('case',{str(source)!r})\n"
                "case=importlib.util.module_from_spec(spec);spec.loader.exec_module(case)\n"
                f"fd=case.held_turn_fd({str(lock)!r})\n"
                "assert fd is not None\n"
                "code='import os;print(os.fstat('+str(fd)+').st_ino)'\n"
                f"result=case.run_process([sys.executable,'-c',code],dict(os.environ),pathlib.Path({tmp!r}),2,fd)\n"
                "assert result['rc']==0 and result['retired']\n"
                f"assert int(pathlib.Path({str(directory / 'stdout.json')!r}).read_text())==os.fstat(fd).st_ino\n"
            )
            result = subprocess.run(
                ["flock", str(lock), sys.executable, str(fixture)], capture_output=True, timeout=5, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(sys.platform == "linux", "house GPU turn uses Linux procfs and flock")
    def test_normal_queue_shim_admits_with_cleared_markers_and_held_lock(self):
        import subprocess

        with tempfile.TemporaryDirectory(prefix="coreglass-normal-turn-") as tmp:
            directory = Path(tmp)
            lock = directory / "gpu.lock"
            shim = directory / "gpu-turn-exec"
            shim.write_text(
                "unset GPU_TURN_TOOL GPU_TURN_PID GPU_TURN_M GPU_TURN_T0 GPU_TURN_CMD\nexec \"$@\"\n"
            )
            turn = directory / "gpu-turn"
            turn.write_text(
                "export GPU_TURN_TOOL=gpu-turn GPU_TURN_PID=$$\n"
                "flock \"$1\" bash \"$2\" \"$3\" \"$4\"\n"
                "rc=$?\nexit \"$rc\"\n"
            )
            fixture = directory / "check.py"
            fixture.write_text(
                "import importlib.util,os\n"
                f"spec=importlib.util.spec_from_file_location('case',{str(ROOT / 'nvidia/benchcase.py')!r})\n"
                "case=importlib.util.module_from_spec(spec);spec.loader.exec_module(case)\n"
                "assert 'GPU_TURN_TOOL' not in os.environ and 'GPU_TURN_PID' not in os.environ\n"
                "assert case.in_turn(), 'normal queue shim rejected'\n"
                f"assert case.held_turn_fd({str(lock)!r}) is not None, 'owned lock missing'\n"
            )
            result = subprocess.run(
                ["bash", str(turn), str(lock), str(shim), sys.executable, str(fixture)],
                capture_output=True, timeout=5, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
