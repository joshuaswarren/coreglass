# NVIDIA case acceptance

Each queued case must pass all checks before it can report a benchmark result.

1. Run inside the existing idle-guard GPU turn. The controller owns queue admission and exclusion.
2. Match the binary, model, selected ICD and library hashes. Match the runtime boot and kernel bindings.
3. Bind the physical `10de:2d04` device and its `nvidia` driver. Select only the pinned NVIDIA ICD and `Vulkan0`.
4. Retain complete raw streams and process status. Require zero exit, bounded owned-group retirement, one genuine result, the exact shape and three finite positive samples.
5. Read both kernel logs successfully and require an unchanged Xid count. Unknown telemetry cannot pass.

Every receipt includes its packet, runtime and configuration, raw output, command, selected environment, process status, kernel logs and final verdict. `SHA256SUMS` covers all these files. Failed and partial runs keep their evidence. No hardware result follows from local fixture tests.
