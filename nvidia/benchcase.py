#!/usr/bin/env python3
"""CT-only guarded caller for the NVIDIA RTX 5060 Ti Llama-2-7B Q4_0 queue (2 deep).

Reuses the bench house pattern (dualcard-run.sh GO gate + pins, nv-vk-bench.sh env/
offload/Xid recipe): this script runs on the CT, drives the bench host over SSH,
runs each queued case as ONE llama-bench submit, retains everything, and gives a
three-valued verdict (PASS / FAIL / UNCONFIRMED). It never downloads a model,
loads/unloads a driver, reboots, resets, or releases a hold.

usage: benchcase.py GO --entry ENTRY.md [--nvidia-lib DIR] [--host ALIAS]
                      [--lane-file PATH] [--out DIR] [--selftest]
Exit codes: 0 PASS, 3 FAIL, 4 UNCONFIRMED, 2 refused.
"""

import argparse
import configparser
import datetime
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from parse_llama_bench import evaluate  # noqa: E402

REPO = pathlib.Path(__file__).parent
LANE_DEFAULT = pathlib.Path.home() / ".config/coreglass/nvidia-lane.toml"
ART_DEFAULT = pathlib.Path.home() / ".local/share/apple-silicon-lab/artifacts/nvidia/llama2-queue2"
TIMEOUT_SSH = 30


def log(msg):
    print(f"[{datetime.datetime.now(datetime.UTC):%H:%M:%SZ}] {msg}", flush=True)


def sh(host, cmd, timeout=TIMEOUT_SSH):
    """Run a command on the bench host over SSH; return (rc, stdout, stderr)."""
    argv = ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={TIMEOUT_SSH}",
            "-o", "ServerAliveInterval=30", host, cmd]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", "ssh timeout"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_lane(path):
    """Read the private lane file (same key=value sections as lane.example.toml)."""
    cp = configparser.ConfigParser()
    if not cp.read(path):
        print(f"refusing: lane file {path} missing (copy nvidia/lane.example.toml there and fill it in)",
              file=sys.stderr)
        sys.exit(2)
    return {s: dict(cp[s]) for s in cp.sections()}


def preflight(host, lane, packet, nvidia_lib, receipt):
    """Identity and native-gate pins; returns failure reasons (empty = green)."""
    why = []
    bench = lane["lane"]["bench_path"]
    model = lane["lane"]["model_path"]
    icd = lane["lane"]["icd_path"]

    rc, out, _ = sh(host, f'sha256sum {shlex_q(bench)} {shlex_q(model)}')
    hashes = dict(line.split(None, 1)[::-1] for line in out.strip().splitlines() if line)
    if rc != 0 or not hashes:
        why.append("cannot hash binary/model on host")
    else:
        for key, lane_key in ((packet["binary"]["sha256"], bench),
                              (packet["model"]["sha256"], model)):
            got = hashes.get(lane_key.strip())
            if got != key:
                why.append(f"sha mismatch {lane_key}: got {got}")
    rc, out, _ = sh(host, f'git -C {shlex_q(lane["lane"]["llama_src"])} log -1 --format=%H')
    if rc != 0 or out.strip() != packet["binary"]["source_commit"]:
        why.append(f"source commit mismatch: {out.strip() or 'unreadable'}")
    rc, out, _ = sh(host, f'test -f {shlex_q(icd)} && echo ICD_OK')
    if "ICD_OK" not in out:
        why.append(f"ICD missing: {icd}")
    # native gate: the actual card at the declared PCI address, nvidia kernel driver in use
    pci = lane["lane"]["pci_addr"]
    devid = lane["lane"]["pci_id"]
    rc, out, _ = sh(host, f"lspci -s {pci} -nn -k")
    if rc != 0 or devid not in out:
        why.append(f"PCI gate: {devid} not at {pci}: {out.strip()[:120]!r}")
    elif "Kernel driver in use: nvidia" not in out:
        why.append("PCI gate: kernel driver in use is not nvidia")
    rc, out, _ = sh(host, "cut -d' ' -f1 /proc/loadavg")
    try:
        if float(out.strip()) >= 1.0:
            why.append(f"idle gate: load1={out.strip()}")
    except ValueError:
        why.append("idle gate: load1 unreadable")
    rc, out, _ = sh(host, "pgrep -x llama-bench")
    if rc == 0:
        why.append("a llama-bench is already running on the host")
    rc, out, err = sh(host, "sudo -n dmesg | grep -ac Xid || true", timeout=60)
    try:
        xid_before = int(out.strip())
    except ValueError:
        xid_before, _ = -1, why.append("Xid baseline unreadable")
    (receipt / "preflight.txt").write_text(
        "\n".join(why or ["PREFLIGHT GREEN"]) + f"\nnvidia_lib={nvidia_lib}\npci={pci}\nxid_before={xid_before}\n",
        encoding="utf-8")
    return why, xid_before


def shlex_q(s):
    return "'" + s.replace("'", "'\\''") + "'"


def _subst(value, subs):
    for k, v in subs.items():
        value = value.replace(k, v)
    return value


def run_case(host, lane, packet, nvidia_lib, receipt, timeout, xid_before):
    """One single-submit llama-bench case; returns (verdict, why)."""
    cid = packet["case_id"]
    bench = lane["lane"]["bench_path"]
    subs = {"{icd_path}": lane["lane"]["icd_path"], "{nvidia_lib}": nvidia_lib,
            "{bench_dir}": str(pathlib.PurePosixPath(bench).parent)}
    env = " ".join(k + "=" + _subst(v, subs) for k, v in packet["input"]["env_pins"].items())
    argv = " ".join(packet["input"]["argv"]).replace("{model_path}", lane["lane"]["model_path"])
    cmd = f"sudo -n env {env} timeout {packet['caps']['submit_timeout_s']} {shlex_q(bench)} {argv}"
    (receipt / f"{cid}.cmd").write_text(cmd + "\n", encoding="utf-8")
    log(f"{cid}: submit ({packet['shape']})")
    rc, out, err = sh(host, cmd, timeout=timeout)
    (receipt / f"{cid}.stdout.json").write_text(out, encoding="utf-8")
    (receipt / f"{cid}.stderr.txt").write_text(err, encoding="utf-8")
    rc2, xout, _ = sh(host, "sudo -n dmesg | grep -ac Xid || true", timeout=60)
    try:
        xid_after = int(xout.strip())
    except ValueError:
        xid_after = None
    why = evaluate(packet, out, err, rc, xid_before if xid_before >= 0 else 0, xid_after or 0)
    verdict = "PASS" if not why and xid_after is not None and xid_before >= 0 else (
        "UNCONFIRMED" if xid_after is None or xid_before < 0 else "FAIL")
    return verdict, why


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("go", nargs="?", help="must be the literal GO")
    ap.add_argument("--entry", help="pre-registered notebook entry this run belongs to")
    ap.add_argument("--nvidia-lib", help="serving NVIDIA userspace lib dir for this window")
    ap.add_argument("--host")
    ap.add_argument("--lane-file", type=pathlib.Path, default=LANE_DEFAULT)
    ap.add_argument("--out", type=pathlib.Path, default=ART_DEFAULT)
    ap.add_argument("--selftest", action="store_true", help="CPU-only packet/self checks, no ssh")
    args = ap.parse_args()

    if args.selftest:
        lane = load_lane(REPO / "lane.example.toml")
        packets = sorted(REPO.glob("case-*.json"))
        assert len(packets) == 2, f"queue must be exactly 2 deep, found {len(packets)}"
        print("SELFTEST_OK queue=2 packets=", ",".join(p.name for p in packets))
        return 0

    if args.go != "GO":
        ap.error("refusing: first argument must be GO (house pattern)")
    if not args.entry or not pathlib.Path(args.entry).is_file():
        ap.error("refusing: --entry must point to the pre-registered notebook entry")
    lane = load_lane(args.lane_file)
    host = args.host or lane["lane"]["ssh_alias"]
    if not shutil.which("ssh"):
        sys.exit("refusing: ssh not found")
    if not args.nvidia_lib:
        ap.error("refusing: --nvidia-lib (which NVIDIA userspace this window serves) is required; "
                 "record, never guess")

    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
    receipt = args.out / stamp
    receipt.mkdir(parents=True, exist_ok=False)
    packets = sorted(REPO.glob("case-*.json"), key=lambda p: json.loads(p.read_text())["queue_order"])
    if [json.loads(p.read_text())["queue_order"] for p in packets] != [1, 2]:
        sys.exit("refusing: queue is not exactly the two declared cases (no filler allowed)")
    for p in packets:
        shutil.copy(p, receipt / p.name)
    (receipt / "entry.txt").write_text(str(args.entry) + "\n", encoding="utf-8")

    rc_id, boot, _ = sh(host, "uname -r; cat /proc/sys/kernel/random/boot_id; cat /proc/cmdline; nvidia-smi | head -4")
    (receipt / "boot.txt").write_text(boot, encoding="utf-8")

    verdict = "PASS"
    for packet_file in packets:
        packet = json.loads(packet_file.read_text())
        why, xid_before = preflight(host, lane, packet, args.nvidia_lib, receipt)
        if why:
            verdict = "UNCONFIRMED" if "cannot" in " ".join(why) else "FAIL"
            log(f"{packet['case_id']}: PREFLIGHT FAIL: {'; '.join(why)}")
            break
        v, why = run_case(host, lane, packet, args.nvidia_lib, receipt,
                          timeout=packet["caps"]["submit_timeout_s"] + TIMEOUT_SSH, xid_before=xid_before)
        log(f"{packet['case_id']}: {v}" + (f" ({'; '.join(why)})" if why else ""))
        if v != "PASS":
            verdict = v
            break

    # final receipt hashes (house pattern: SHA256SUMS over everything, itself last)
    files = sorted(f for f in receipt.rglob("*") if f.is_file() and f.name != "SHA256SUMS")
    sums = "".join(f"{sha256(f)}  ./{f.relative_to(receipt)}\n" for f in files)
    (receipt / "SHA256SUMS").write_text(sums, encoding="utf-8")
    (receipt / "VERDICT").write_text(verdict + "\n", encoding="utf-8")
    log(f"queue verdict {verdict}, receipt {receipt}")
    return {"PASS": 0, "FAIL": 3}.get(verdict, 4)


if __name__ == "__main__":
    sys.exit(main())
