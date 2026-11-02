#!/usr/bin/env python3
"""Run one NVIDIA benchmark case locally inside the existing idle-guard turn."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parse_llama_bench import evaluate


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def live_group(pgid):
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            try:
                fields = (entry / "stat").read_text().rsplit(") ", 1)[1].split()
                if int(fields[2]) == pgid and fields[0] not in ("Z", "X"):
                    return True
            except (OSError, ValueError, IndexError):
                continue
    return False


def signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def drain_group(pgid, seconds):
    deadline = time.monotonic() + seconds
    while live_group(pgid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not live_group(pgid)


def run_process(argv, env, receipt, timeout, held_fd=None):
    retired = False
    child = None
    capped = False
    with (receipt / "stdout.json").open("xb") as stdout, (receipt / "stderr.txt").open("xb") as stderr:
        try:
            child = subprocess.Popen(
                argv,
                env=env,
                cwd=receipt,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                pass_fds=() if held_fd is None else (held_fd,),
            )
            try:
                rc = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                capped = True
                rc = 124
        finally:
            if child is not None:
                if live_group(child.pid):
                    signal_group(child.pid, signal.SIGTERM)
                    if not drain_group(child.pid, 1):
                        signal_group(child.pid, signal.SIGKILL)
                retired = drain_group(child.pid, 1)
                try:
                    child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    retired = False
                save(
                    receipt / "process.json",
                    {
                        "pid": child.pid,
                        "pgid": child.pid,
                        "capped": capped,
                        "retired": retired,
                        "returncode": child.returncode,
                    },
                )
    return {"rc": rc, "capped": capped, "retired": retired}


def xid_count(receipt, name):
    directory = receipt / name
    directory.mkdir()
    result = run_process(["dmesg"], {"PATH": "/usr/bin:/bin", "LANG": "C"}, directory, 10)
    if result["rc"] != 0 or not result["retired"]:
        raise ValueError("kernel log unavailable; Xid gate is unconfirmed")
    return sum(b"Xid" in line for line in (directory / "stdout.json").read_bytes().splitlines())


def preflight(lane, packet, runtime):
    for key, expected in (("bench_path", packet["binary"]["sha256"]), ("model_path", packet["model"]["sha256"])):
        if sha256(lane[key]) != expected:
            raise ValueError(key + " hash mismatch")
    if Path(lane["model_path"]).stat().st_size != packet["model"]["bytes"]:
        raise ValueError("model size mismatch")
    if not runtime["files"] or lane["icd_path"] not in runtime["files"]:
        raise ValueError("ICD/runtime file pins missing")
    for path, digest in runtime["files"].items():
        if sha256(path) != digest:
            raise ValueError("runtime file hash mismatch: " + path)
    if runtime["boot_id"] != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        raise ValueError("boot identity changed")
    if runtime["kernel"] != os.uname().release:
        raise ValueError("kernel changed")
    pci = Path("/sys/bus/pci/devices") / lane["pci_addr"]
    if ((pci / "vendor").read_text().strip(), (pci / "device").read_text().strip()) != ("0x10de", "0x2d04"):
        raise ValueError("wrong physical device")
    if (pci / "driver").resolve(strict=True).name != "nvidia":
        raise ValueError("wrong kernel driver")
    version = runtime["nvidia_version"]
    if not version or version not in Path("/proc/driver/nvidia/version").read_text():
        raise ValueError("loaded NVIDIA version changed")
    icd_library = Path(json.loads(Path(lane["icd_path"]).read_text())["ICD"]["library_path"])
    if str(icd_library) not in runtime["files"] or version not in str(icd_library.resolve(strict=True)):
        raise ValueError("ICD does not bind the matching NVIDIA userspace")
    egl = runtime["egl_vendor_json"]
    if egl not in runtime["files"]:
        raise ValueError("headless EGL binding missing")
    egl_library = json.loads(Path(egl).read_text())["ICD"]["library_path"]
    if egl_library not in runtime["files"]:
        raise ValueError("headless EGL library pin missing")


def in_turn():
    if os.environ.get("GPU_TURN_TOOL") != "gpu-turn":
        return False
    try:
        owner = int(os.environ["GPU_TURN_PID"])
        pid = os.getpid()
        while pid > 1:
            if pid == owner:
                return b"gpu-turn" in Path(f"/proc/{pid}/cmdline").read_bytes()
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
            pid = int(fields[1])
    except (OSError, ValueError, KeyError, IndexError):
        return False
    return False


def interrupt(signum, _frame):
    raise InterruptedError("interrupted by signal " + str(signum))


def held_turn_fd(lock_path):
    target = Path(lock_path).stat()
    for entry in Path("/proc/self/fd").iterdir():
        try:
            descriptor = int(entry.name)
            current = os.fstat(descriptor)
            info = Path(f"/proc/self/fdinfo/{descriptor}").read_text()
            if (current.st_dev, current.st_ino) == (target.st_dev, target.st_ino) and "FLOCK" in info:
                return descriptor
        except (OSError, ValueError):
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--lane-file", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--nvidia-lib", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not in_turn():
        parser.error("refusing: execute through the existing idle-guard GPU turn")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupt)
    packet = json.loads(args.packet.read_text())
    lane = tomllib.loads(args.lane_file.read_text())["lane"]
    runtime = json.loads(args.runtime.read_text())
    args.out.mkdir(parents=True, exist_ok=False)
    receipt = args.out.resolve()
    save(receipt / "packet.json", packet)
    save(receipt / "runtime.json", runtime)
    save(receipt / "lane.json", lane)
    verdict, reasons, rc = "UNCONFIRMED", [], 4
    try:
        preflight(lane, packet, runtime)
        libraries = [Path(path) for path in runtime["files"] if Path(path).parent == args.nvidia_lib]
        if not libraries or not args.nvidia_lib.is_dir():
            raise ValueError("serving NVIDIA library directory has no file pins")
        held_fd = held_turn_fd(runtime["gpu_lock"])
        if held_fd is None:
            raise ValueError("inherited GPU lock descriptor unavailable; refuse execution")
        before = xid_count(receipt, "kernel-before")
        env = {"PATH": "/usr/bin:/bin", "LANG": "C", "HOME": str(receipt), "TMPDIR": str(receipt)}
        substitutions = {
            "{icd_path}": lane["icd_path"],
            "{nvidia_lib}": str(args.nvidia_lib),
            "{bench_dir}": str(Path(lane["bench_path"]).parent),
        }
        for key, value in packet["input"]["env_pins"].items():
            for old, new in substitutions.items():
                value = value.replace(old, new)
            env[key] = value
        env["__EGL_VENDOR_LIBRARY_FILENAMES"] = runtime["egl_vendor_json"]
        argv = [lane["bench_path"]] + [
            value.replace("{model_path}", lane["model_path"]) for value in packet["input"]["argv"]
        ]
        save(receipt / "command.json", {"argv": argv, "env": env})
        process = run_process(argv, env, receipt, packet["caps"]["submit_timeout_s"], held_fd)
        after = xid_count(receipt, "kernel-after")
        reasons = evaluate(
            packet,
            (receipt / "stdout.json").read_text(errors="replace"),
            (receipt / "stderr.txt").read_text(errors="replace"),
            process["rc"],
            before,
            after,
        )
        if not process["retired"]:
            reasons.append("owned process group remains; retirement unconfirmed")
        verdict, rc = ("FAIL", 3) if reasons else ("PASS", 0)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        reasons.append(str(error))
    finally:
        save(receipt / "verdict.json", {"verdict": verdict, "reasons": reasons})
        with (receipt / "SHA256SUMS").open("x") as stream:
            for path in sorted(receipt.rglob("*")):
                if path.is_file() and path != receipt / "SHA256SUMS":
                    stream.write(sha256(path) + "  " + str(path.relative_to(receipt)) + "\n")
    print(verdict + ": " + "; ".join(reasons), flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
