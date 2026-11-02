# NVIDIA Vulkan benchmark cases

The two cases run Llama-2-7B Q4_0 on an RTX 5060 Ti: prompt processing at 512 tokens and generation at 128 tokens. Each case takes three samples with 99 GPU layers and flash attention enabled.

At llama.cpp commit `65840ed53c8653bfbf3e9014d9cbf71ac8c08725`, `-p 512 -n 128` creates two independent cases. The packets select those cases separately. They add an explicit `Vulkan0` device selection under an exclusive NVIDIA ICD. They do not change the model, sample count, or timed shapes.

## Queue the cases

Use the existing host idle-guard queue and its validated appender. Append one row per case with the exact packet, runner, configuration, runtime, binary, model, and PCI requirements. The guard owns scheduling and exclusion. Do not run the benchmark through an SSH command or a second scheduler.

Inside that queued turn, invoke the target-local caller:

```sh
python3 benchcase.py --packet case-pp512.json \
  --lane-file /absolute/private/lane.toml \
  --runtime /absolute/private/runtime.json \
  --nvidia-lib /absolute/serving/library-directory \
  --out /absolute/new/receipt-directory
```

Use `case-tg128.json` in the second row. Keep the two receipt directories distinct. The caller refuses an existing output directory or execution outside an inherited GPU turn.

`lane.example.toml` defines the local paths. The runtime JSON binds `kernel`, `boot_id`, `nvidia_version`, `egl_vendor_json`, and `gpu_lock`. Its `files` map binds absolute runtime paths to SHA256 values. Include the selected ICD, serving libraries, headless EGL binding, and benchmark shared libraries. The caller requires matching loaded and userspace NVIDIA versions. Hashes from an older run do not establish the current runtime.

## Results and limits

The caller retains byte-exact stdout and stderr, process status, kernel logs, the selected command and environment, input bindings, and the final verdict. It writes the verdict before hashing all receipt files. Timeout handling keeps partial output and bounds TERM/KILL retirement of the owned process group. The benchmark inherits the held lock descriptor, so a child that cannot retire still holds the same lock. An unknown telemetry or retirement state cannot pass.

The parser checks the producer's `backends` field, the explicit device, both case dimensions, three finite positive samples, and device-error diagnostics. Default llama-bench suppresses model-loading messages, so the packets do not demand an offload message that it never prints. The explicit device, GPU-layer request, exclusive ICD, physical PCI gate, and native device diagnostic bind this benchmark to NVIDIA Vulkan. They do not establish independent numerical accuracy.

The historical table used a different sample count in one retained run. These packets fix three samples. Do not present that historical table as a matched before/after comparison.

Run local subprocess and parser checks with:

```sh
python3 -m unittest discover -s tests -p 'test_nvidia*.py'
```
