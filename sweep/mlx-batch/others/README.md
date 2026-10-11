# Family `others` - mlx-lm, mlx-examples, mlx-audio

Every `metal_kernel()` call site in the three trees under
the pinned scratch trees (`$MLX_BATCH_SRC`) that family `feat/mlx-batch` (KernelBatch) did
not already own. 17 resolved bodies, 14 distinct call sites, all 17 valid
(`m2v-compile` exit 0 and `spirv-val --target-env vulkan1.3` clean).

## Counts

- valid:        17 / 17
- failed:        0
- not assembled: 0
- call sites covered: 14 (gated_delta.py:130 is one site that yields four
  resolved bodies via `(has_mask, vectorized)`; the other 13 sites are
  one-body-per-site)

The remaining 7 rows in family `feat/mlx-batch`'s results.tsv that touch these
trees are: `bitlinear_matmul`, `ssm_kernel` (mlx-lm), `relu_squared`,
`fused_multiply_add`, `qk_relu_squared` (mlx-audio flash_attention),
`custom_depthwise_conv1d` (mlx-audio mossformer), `mlx_audio_phonon_unpack_base5_v1`.
The 14 sites this family owns are everything else in the three trees.

## Rows (origin → kernel → representative shapes → source SHA-256)

| kernel | origin | representative | source_sha256 (first 12) |
|---|---|---|---|
| kimi_k3_attnres_mix | mlx-lm@2184db2:mlx_lm/models/kimi_k3.py:269 | raw (2,4,64) float, eps (1,) c, N 0-d int32, K=2,D=64,THREADS=512 | daf7d2ee714f |
| rwkv7_wkv7_kernel | mlx-lm@2184db2:mlx_lm/models/rwkv7.py:114 | r/w/k/v/a/b [1,4,2,64] float, state_in [1,2,64,64] float, T 0-d int32; InT=float,H=2,D=64 | f34d6637be1c |
| gated_delta_step | mlx-lm@2184db2:mlx_lm/models/gated_delta.py:130 | q/k [1,4,2,128] float, v [1,4,2,128] float, g/beta float, T 0-d int32, scalar g | 83a79caeea44 |
| gated_delta_step_masked | mlx-lm@2184db2:mlx_lm/models/gated_delta.py:130 | +bool mask [B,T], scalar g | 5fbb2c7766b8 |
| gated_delta_step_vec | mlx-lm@2184db2:mlx_lm/models/gated_delta.py:130 | vectorized g [B,T,Hv,Dk] | 5730fa0f0ca6 |
| gated_delta_step_vec_masked | mlx-lm@2184db2:mlx_lm/models/gated_delta.py:130 | vectorized g + bool mask | 51292b26fbac |
| gated_delta_step_xtree | mlx-lm@2184db2:mlx_lm/models/gated_delta.py:225 | scalar g, unmasked, explicit shuffle_xor tree | 4869eb6abbfa |
| gated_delta_step_packed_btree | mlx-lm@2184db2:mlx_lm/models/gated_delta.py:352 | Dk=128, 8 rows/SIMD, scalar g | 0fffa9c6b488 |
| kl_forward | mlx-lm@2184db2:mlx_lm/tuner/losses.py:168 | logits_q/p float [...,V=8192], T=float,V=8192; 2 outputs | a30c61d33554 |
| kl_backward | mlx-lm@2184db2:mlx_lm/tuner/losses.py:329 | logits_q/p float [...,V=8192], cotan float, T=float,V=8192 | 78ff53b7e9eb |
| js_forward | mlx-lm@2184db2:mlx_lm/tuner/losses.py:564 | logits_q/p float [...,V=8192], 2 outputs float, T=float,V=8192 | e834b696935e |
| js_backward | mlx-lm@2184db2:mlx_lm/tuner/losses.py:735 | logits_q/p float, cotan+output_kl_q float, out_q float | 3fd1d7ba67b1 |
| encodec_lstm_examples | mlx-examples@796f5b5:encodec/encodec.py:14 | x/h_in/cell float (B=2,T=4,H*4=32,H=8), 3 int32 scalars; no template; header with `sigmoid<T>` | d85ea5583650 |
| wwdc25_myexp | mlx-examples@796f5b5:wwdc25/Get_started_with_MLX_for_Apple_silicon.ipynb:527 | x float [1,2,3]; trivial exp | 7a9d54607617 |
| mlx_audio_ssm_kernel | mlx-audio@17001a6:mlx_audio/lm/models/ssm.py:67 | vendored mlx-lm 0.31.3 ssm_kernel; X/A_log/B/C/D/dt/state_in float, n=1,h=2,d=8,hb=1,Ds=32; T=float,U=float,Dh=8,Ds=32,H=2,G=2 | e5c87e5f2472 |
| mlx_audio_ssm_initial_kernel | mlx-audio@17001a6:mlx_audio/lm/models/ssm.py:127 | n=1,l=2,h=2,d=8,groups=1,state_dim=32; sequence_length (1,) uint32 c | 432d640823a6 |
| mlx_audio_codec_encodec_lstm | mlx-audio@17001a6:mlx_audio/codec/models/encodec/encodec.py:89 | identical body to encodec_lstm_examples; same shapes | 1ccba380c6d6 |

Full SHA-256s and per-row first_error / m2v_giveup / cause in
`results-others.tsv`.

## Assembler

`assemble.py` is the static assembler this family uses - it parses each
pinned `.py` (or `.ipynb` for the wwdc25 cell) with `ast`, pulls the `source`
literal out of the corresponding factory, evaluates any `JoinedStr` f-string
with a per-variant `subs` dict (gated_delta's four `(has_mask, vectorized)`
combinations), and emits one `.metal` per resolved body in the same shape
KernelBatch uses:

```
// Origin: <repo>@<sha>, <relpath>:<line>.
// Representative call: <desc>.
// Grid=<g>, threadgroup=<tg>.
// [Templates <k>=<v>, ...; concrete instantiation <mangled>.]
<header text, if any>
template <typename T, int K, ...>          # only for templated kernels
[[kernel]] void <mangled>(
  <inputs: const device|constant <T>*|& <name> [[buffer(N)]]
   plus _shape [[buffer(N+1)]] when source uses <name>_shape>
  <outputs: device <T>* <name> [[buffer(N)]>
  <used attributes in mlx-canonical order: thread_index_in_simdgroup, ...>
) {
<source text from the call site, verbatim>
}
template [[host_name("<mangled>")]] [[kernel]] decltype(<mangled><T1, ...>) <mangled><T1, ...>;
```

Mangled name mirrors `custom_kernel_<name>_<template_hash>_<in dtypes + s|c>_<out dtypes>`
as MLX's `metal_kernel` factory emits in `mlx/backend/common/metal_kernel.cpp`.

## Commands

Run from the worktree root:

```sh
export SWEEP_ROOT=<the feat/mlx-batch worktree>   # holds tools/m2v-compile
python3 sweep/mlx-batch/others/assemble.py \
  --out sweep/mlx-batch/others/build \
  --results sweep/mlx-batch/others/results-others.tsv
```

Per-kernel compile (what the assembler runs) is the same as family
`feat/mlx-batch` uses:

```sh
python3 $SWEEP_ROOT/tools/m2v-compile \
  --msl sweep/mlx-batch/others/build/<kernel>.metal \
  --out  sweep/mlx-batch/others/build/<kernel> \
  --json --timeout 180
```

`exit 0` + `--json` `status:"ok"` is the only success criterion
(`spirv-val --target-env vulkan1.3` is part of the pipeline and must be clean).

## What I did not verify

- The representative call shapes are hand-picked to cover the kernel's data
  path while staying small enough for the toolchain to handle; I did not run
  each compiled SPIR-V module against actual input arrays to confirm
  bit-identical output to mlx's Metal execution. That parity check is
  `sweep/parity_mlx.py`; out of scope here.
- The four gated_delta variants differ only in `{g_comment}/{g_setup}/{g_access}/{g_advance}`
  substitutions; I substituted the four `(has_mask, vectorized)` combinations
  but did not exhaust every combination the runtime can hit (e.g. vectorized
  + masked + non-trivial grids). The four I assembled cover the call sites
  that gated_delta.py actually invokes.
- Mask dtype is recorded as `bool` because the padding mask is built via
  `mx.ones(..., dtype=mx.bool_)` upstream; I did not verify that every caller
  of the masked variants in fact produces a `bool` mask - they all
  plumb the same `_gated_delta_step_ops` mask through, but a future caller
  with a non-bool mask would change the name suffix from `_bool` to the
  actual dtype.
- `kl_forward` and `js_forward` both emit two outputs whose shapes are
  `[... , V]` and `[]` respectively; the spec records `[logits_q.shape[:-1]]`
  for both `out` and `out_kl_q`. The compiler doesn't care - `out` is a
  1-D float pointer - but the runtime shape is `[n_outs]` not `[...]` for
  the reduced-out output, so two callers using the same compiled SPV must
  bind matching shapes. The TSV records what was compiled, not the two
  shape regimes.
- The `assemble.py` script's `KERNELS` list is the contract for this
  family; if a future mlx-lm/mlx-examples/mlx-audio release adds a new
  `metal_kernel()` call site, add a row to `KERNELS` and re-run.

## Origin provenance

Every `.metal` begins with a header `// Origin: <repo>@<sha>, <file>:<line>.`
where `<sha>` is the pinned commit of the source tree under
the pinned scratch trees (`$MLX_BATCH_SRC`). The `results-others.tsv` `origin` column
carries the same `<repo>@<sha>:<file>:<line>` for every row.
