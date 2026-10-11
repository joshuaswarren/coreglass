#!/usr/bin/env python3
"""Family `others` static assembler.

Reads the pinned upstream sources, resolves every metal_kernel() call site in
mlx-lm, mlx-examples, and mlx-audio into the complete MSL mlx would assemble at
runtime (header + template + signature + source + instantiation), writes one
.metal per resolved body, compiles it with tools/m2v-compile, and records every
result in results-others.tsv. Mirrors the assembler used by family mlx-batch in
sweep/mlx-batch/ (KernelBatch's directory): same row format, same compile
command, same naming convention (custom_kernel_<name>_<template_hash>_<in dtypes
suffixes>_<out dtypes>, where 0-d scalars get `s` and small arrays in mlx's
constant address space get `c`).

Pinned trees (read-only), $MLX_BATCH_SRC (default <home>/scratch/sweep/mlx-batch-src):
  mlx-lm        @ 2184db2
  mlx-examples  @ 796f5b5
  mlx-audio     @ 17001a6

Run from anywhere; pass --out DIR to choose the .metal + build dir
(defaults to ./build). m2v-compile lives at $SWEEP_ROOT/tools/m2v-compile;
the toolchain (CLANG, OPT, CLSPV, SPIRV_VAL) comes from the sweep env.sh.
"""
import argparse
import ast
import json
import os
import pathlib
import re
import subprocess
import sys
import textwrap

PINNED = pathlib.Path(os.environ.get("MLX_BATCH_SRC", pathlib.Path.home() / "scratch/sweep/mlx-batch-src"))
MLXLM = "mlx-lm@2184db2"
MLXEX = "mlx-examples@796f5b5"
MLXAU = "mlx-audio@17001a6"

# MLX get_type_string mapping, from mlx/mlx/backend/common/compiled.cpp
DTYPE_STR = {
    "float32": "float", "float16": "float16_t", "bfloat16": "bfloat16_t",
    "float64": "double", "complex64": "complex64_t", "bool": "bool",
    "int8": "int8_t", "int16": "int16_t", "int32": "int32_t", "int64": "int64_t",
    "uint8": "uint8_t", "uint16": "uint16_t", "uint32": "uint32_t", "uint64": "uint64_t",
}

# Attribute list and order from mlx's metal_kernel.cpp
ATTR_ORDER = [
    ("dispatch_quadgroups_per_threadgroup", "uint"),
    ("dispatch_simdgroups_per_threadgroup", "uint"),
    ("dispatch_threads_per_threadgroup", "uint3"),
    ("grid_origin", "uint3"),
    ("grid_size", "uint3"),
    ("quadgroup_index_in_threadgroup", "uint"),
    ("quadgroups_per_threadgroup", "uint"),
    ("simdgroup_index_in_threadgroup", "uint"),
    ("simdgroups_per_threadgroup", "uint"),
    ("thread_execution_width", "uint"),
    ("thread_index_in_quadgroup", "uint"),
    ("thread_index_in_simdgroup", "uint"),
    ("thread_index_in_threadgroup", "uint"),
    ("thread_position_in_grid", "uint3"),
    ("thread_position_in_threadgroup", "uint3"),
    ("threadgroup_position_in_grid", "uint3"),
    ("threadgroups_per_grid", "uint3"),
    ("threads_per_grid", "uint3"),
    ("threads_per_simdgroup", "uint"),
    ("threads_per_threadgroup", "uint3"),
]


def make_template_hash(template_def):
    """Reproduce mlx's make_template_hash: '<' and '>' -> '_', ', ' -> '_', pop last char.

    '<float, float, 8, 32, 2, 2>' -> '_float_float_8_32_2_2' (after pop_back)."""
    h = []
    i = 0
    s = template_def
    while i < len(s):
        c = s[i]
        if c == "<" or c == ">":
            h.append("_")
            i += 1
        elif c == "," and i + 1 < len(s) and s[i + 1] == " ":
            h.append("_")
            i += 2
        else:
            h.append(c)
            i += 1
    out = "".join(h)
    if out.endswith("_"):
        out = out[:-1]
    return out


def format_template_arg(arg):
    """Render one template arg as it would appear in MSL: dtype -> type string, int -> str(int), bool -> 'true'/'false'."""
    if isinstance(arg, str) and arg in DTYPE_STR:
        return DTYPE_STR[arg]
    if isinstance(arg, bool):
        return "true" if arg else "false"
    return str(arg)


def mangle_name(name, template, inputs, outputs):
    """custom_kernel_<name> + '_' + <template_hash_or_empty> + per-input dtype + per-output dtype.

    0-d scalar inputs get an `s` suffix; small constant arrays get `c` (we don't reproduce mlx's exact
    size check, but the representative call is the source of truth - see spec notes)."""
    parts = ["custom_kernel_" + name]
    if template:
        tdef = "<" + ", ".join(format_template_arg(a) for _, a in template) + ">"
        parts.append("_" + make_template_hash(tdef))
    for inp in inputs:
        dt = inp["dtype"]
        parts.append("_" + DTYPE_STR.get(dt, dt))
        if inp.get("scalar"):
            parts.append("s")
        elif inp.get("constant") and not inp.get("shape"):
            parts.append("c")
    for out in outputs:
        parts.append("_" + DTYPE_STR.get(out["dtype"], out["dtype"]))
    return "".join(parts)


def make_template_decl(template):
    """Build 'template <typename T, int K, ...>' with dtypes as `typename T` and ints as `int K`."""
    if not template:
        return ""
    pieces = []
    for n, v in template:
        if isinstance(v, str) and v in DTYPE_STR:
            pieces.append(f"typename {n}")
        else:
            pieces.append(f"int {n}")
    return "template <" + ", ".join(pieces) + ">\n"


def emit_metal(spec, source, header=None):
    """Return the .metal file text for one kernel spec and its resolved source."""
    name = spec["name"]
    template = spec.get("template", [])
    inputs = spec["inputs"]
    outputs = spec["outputs"]
    origin = spec["origin"]
    rep = spec["representative"]
    grid = spec.get("grid", "(1,1,1)")
    tg = spec.get("threadgroup", "(1,1,1)")

    mangled = mangle_name(name, template, inputs, outputs)
    tmpl_decl = make_template_decl(template)

    # Header comment
    out = []
    out.append(f"// Origin: {origin['repo']}, {origin['file']}:{origin['line']}.")
    out.append(f"// Representative call: {rep}.")
    out.append(f"// Grid={grid}, threadgroup={tg}.")
    if template:
        tmpl_kv = ", ".join(f"{n}={v}" for n, v in template)
        out.append(f"// Templates {tmpl_kv}; concrete instantiation {mangled}.")
    out.append("")

    if header:
        out.append(textwrap.dedent(header).rstrip())
        out.append("")

    if tmpl_decl:
        out.append(tmpl_decl.rstrip())
    out.append(f"[[kernel]] void {mangled}(")

    # Build signature: inputs first (with optional _shape), then outputs
    lines = []
    bidx = 0
    for inp in inputs:
        dt = DTYPE_STR.get(inp["dtype"], inp["dtype"])
        nm = inp["name"]
        if inp.get("scalar"):
            lines.append(f"  const constant {dt}& {nm} [[buffer({bidx})]]")
        else:
            lines.append(f"  const device {dt}* {nm} [[buffer({bidx})]]")
        bidx += 1
        if inp.get("shape"):
            lines.append(f"  const constant int* {nm}_shape [[buffer({bidx})]]")
            bidx += 1
    for o in outputs:
        dt = DTYPE_STR.get(o["dtype"], o["dtype"])
        nm = o["name"]
        lines.append(f"  device {dt}* {nm} [[buffer({bidx})]]")
        bidx += 1

    # Scanned attributes, in mlx's fixed order, only those used in source
    src_text = source
    for attr, atype in ATTR_ORDER:
        if attr in src_text:
            lines.append(f"  {atype} {attr} [[{attr}]]")
    out.append(",\n".join(lines))
    out.append(") {")

    out.append(textwrap.dedent(source).rstrip("\n"))
    out.append("}")

    # Trailing instantiation for templated kernels
    if template:
        # mlx emits: template [[host_name("NAME")]] [[kernel]] decltype(NAME<args>) NAME<args>;
        # where NAME<args> means the template function mangled with concrete args.
        # The decltype is the SAME as the NAME, since NAME is the function template.
        targs = ", ".join(format_template_arg(a) for _, a in template)
        concrete = mangled + "<" + targs + ">"
        out.append("")
        out.append(
            f"template [[host_name(\"{mangled}\")]] [[kernel]] decltype({concrete}) {concrete};"
        )

    return "\n".join(out) + "\n", mangled


# --- Source extraction ------------------------------------------------------

def _find_func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _get_source_or_header(func_node, var, subs=None):
    """Return the Constant value or evaluated JoinedStr for `var = ...` inside a FunctionDef body."""
    for stmt in func_node.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == var:
                    return _resolve_value(stmt.value, subs or {})
    return None


def _resolve_value(node, subs):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                inner = v.value
                if isinstance(inner, ast.Name):
                    out.append(str(subs.get(inner.id, "{" + inner.id + "}")))
                elif isinstance(inner, ast.Constant):
                    out.append(str(inner.value))
                else:
                    raise ValueError(f"unsupported FormattedValue: {ast.dump(inner)}")
            else:
                raise ValueError(f"unsupported JoinedStr value: {ast.dump(v)}")
        return "".join(out)
    raise ValueError(f"unsupported value node: {ast.dump(node)}")


def get_module_func_source(path, func_name, var="source", subs=None):
    tree = ast.parse(path.read_text())
    fn = _find_func(tree, func_name)
    if fn is None:
        raise RuntimeError(f"no function {func_name} in {path}")
    val = _get_source_or_header(fn, var, subs=subs)
    if val is None:
        raise RuntimeError(f"no {var} assignment in {func_name} of {path}")
    return val


def get_module_top_level(path, var="source"):
    tree = ast.parse(path.read_text())
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == var:
                    return _resolve_value(stmt.value, {})
    raise RuntimeError(f"no top-level {var} in {path}")


def get_notebook_source(ipynb_path):
    """Extract the `source = \"\"\"...\"\"\"` literal from a Jupyter notebook cell that calls metal_kernel."""
    import json as _json
    data = _json.loads(ipynb_path.read_text())
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if "mx.fast.metal_kernel" in src and 'name=' in src and 'source=' in src:
            m = re.search(r'source\s*=\s*"""(.*?)"""', src, re.S)
            if m:
                return textwrap.dedent(m.group(1))
    raise RuntimeError(f"no source in notebook {ipynb_path}")


# --- Specs ------------------------------------------------------------------

KERNELS = [
    # ---------- mlx-lm ----------
    {
        "id": "kimi_k3_attnres_mix",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/kimi_k3.py", "line": "269"},
        "name": "attnres_mix",
        "header": None,
        "template": [("InT", "float32"), ("K", 2), ("D", 64), ("THREADS", 512)],
        "inputs": [
            {"name": "raw", "dtype": "float32"},
            {"name": "inv_rms", "dtype": "float32"},
            {"name": "partial", "dtype": "float32"},
            {"name": "w_eff", "dtype": "float32"},
            {"name": "eps", "dtype": "float32", "constant": True},
            {"name": "N", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "out", "dtype": "float32"}],
        "grid": "(512, N, 1)", "threadgroup": "(512, 1, 1)",
        "representative": "raw (K, N, D)=(2, 4, 64) float32, inv_rms/partial/w_eff float32, eps float32 (1,) constant, N int32 0-d scalar; K=2,D=64,THREADS=512",
        "source_fn": lambda: get_module_top_level(PINNED / "mlx-lm/mlx_lm/models/kimi_k3.py", "_ATTN_RES_SOURCE"),
    },
    {
        "id": "rwkv7_wkv7_kernel",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/rwkv7.py", "line": "114"},
        "name": "wkv7_kernel",
        "template": [("InT", "float32"), ("H", 2), ("D", 64)],
        "inputs": [
            {"name": "r", "dtype": "float32"},
            {"name": "w", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "a", "dtype": "float32"},
            {"name": "b", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, D, B*H)", "threadgroup": "(32, 4, 1)",
        "representative": "r/w/k/v/a/b [B=1,T=4,H=2,D=64] float32, state_in [B,H,D,D] float32, T int32 scalar; InT=float,H=2,D=64",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/models/rwkv7.py", "_make_wkv7_kernel"),
    },
    # gated_delta: 4 variants of _make_gated_delta_kernel + xtree + packed = 6
    {
        "id": "gated_delta_step",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/gated_delta.py", "line": "130"},
        "name": "gated_delta_step",
        "template": [("InT", "float32"), ("StT", "float32"), ("Dk", 128), ("Dv", 128), ("Hk", 2), ("Hv", 2)],
        "inputs": [
            {"name": "q", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "g", "dtype": "float32"},
            {"name": "beta", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, Dv, B*Hv)", "threadgroup": "(32, 4, 1)",
        "representative": "q/k [B,T,Hk,Dk]=[1,4,2,128] float32, v [B,T,Hv,Dv]=[1,4,2,128], g/beta float32, state_in float32, T int32 scalar; scalar g path",
        "variant": {"has_mask": False, "vectorized": False},
    },
    {
        "id": "gated_delta_step_masked",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/gated_delta.py", "line": "130"},
        "name": "gated_delta_step_mask",
        "template": [("InT", "float32"), ("StT", "float32"), ("Dk", 128), ("Dv", 128), ("Hk", 2), ("Hv", 2)],
        "inputs": [
            {"name": "q", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "g", "dtype": "float32"},
            {"name": "beta", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
            {"name": "mask", "dtype": "bool"},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, Dv, B*Hv)", "threadgroup": "(32, 4, 1)",
        "representative": "same as gated_delta_step plus bool mask [B,T]; scalar g path",
        "variant": {"has_mask": True, "vectorized": False},
    },
    {
        "id": "gated_delta_step_vec",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/gated_delta.py", "line": "130"},
        "name": "gated_delta_step_vec",
        "template": [("InT", "float32"), ("StT", "float32"), ("Dk", 128), ("Dv", 128), ("Hk", 2), ("Hv", 2)],
        "inputs": [
            {"name": "q", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "g", "dtype": "float32"},
            {"name": "beta", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, Dv, B*Hv)", "threadgroup": "(32, 4, 1)",
        "representative": "vectorized g path; g [B,T,Hv,Dk] float32",
        "variant": {"has_mask": False, "vectorized": True},
    },
    {
        "id": "gated_delta_step_vec_masked",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/gated_delta.py", "line": "130"},
        "name": "gated_delta_step_vec_mask",
        "template": [("InT", "float32"), ("StT", "float32"), ("Dk", 128), ("Dv", 128), ("Hk", 2), ("Hv", 2)],
        "inputs": [
            {"name": "q", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "g", "dtype": "float32"},
            {"name": "beta", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
            {"name": "mask", "dtype": "bool"},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, Dv, B*Hv)", "threadgroup": "(32, 4, 1)",
        "representative": "vectorized g plus bool mask",
        "variant": {"has_mask": True, "vectorized": True},
    },
    {
        "id": "gated_delta_step_xtree",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/gated_delta.py", "line": "225"},
        "name": "gated_delta_step_xtree",
        "template": [("InT", "float32"), ("StT", "float32"), ("Dk", 128), ("Dv", 128), ("Hk", 2), ("Hv", 2)],
        "inputs": [
            {"name": "q", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "g", "dtype": "float32"},
            {"name": "beta", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, Dv, B*Hv)", "threadgroup": "(32, 4, 1)",
        "representative": "scalar g, unmasked, explicit-tree reduction (shuffle_xor 1,2,4,8,16)",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/models/gated_delta.py", "_make_gated_delta_kernel_xtree"),
    },
    {
        "id": "gated_delta_step_packed_btree",
        "origin": {"repo": MLXLM, "file": "mlx_lm/models/gated_delta.py", "line": "352"},
        "name": "gated_delta_step_packed_btree",
        "template": [("InT", "float32"), ("StT", "float32"), ("Dk", 128), ("Dv", 128), ("Hk", 2), ("Hv", 2)],
        "inputs": [
            {"name": "q", "dtype": "float32"},
            {"name": "k", "dtype": "float32"},
            {"name": "v", "dtype": "float32"},
            {"name": "g", "dtype": "float32"},
            {"name": "beta", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
            {"name": "T", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "y", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, Dv/8, B*Hv)", "threadgroup": "(32, 2, 1)",
        "representative": "scalar g, Dk=128, 8 rows per SIMD; lanes_per_row=4, values_per_lane=32",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/models/gated_delta.py", "_make_gated_delta_packed_kernel"),
    },
    {
        "id": "kl_forward",
        "origin": {"repo": MLXLM, "file": "mlx_lm/tuner/losses.py", "line": "168"},
        "name": "kl_forward",
        "template": [("T", "float32"), ("V", 8192)],
        "inputs": [
            {"name": "logits_q", "dtype": "float32"},
            {"name": "logits_p", "dtype": "float32"},
        ],
        "outputs": [{"name": "out", "dtype": "float32"}],
        "grid": "(1024, n_outs, 1)", "threadgroup": "(1024, 1, 1)",
        "representative": "logits_q/p float32 [..., V=8192] (full_blocks=2, extra=0); T=float, V=8192; n_outs=2",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/tuner/losses.py", "_make_kl_forward_kernel"),
    },
    {
        "id": "kl_backward",
        "origin": {"repo": MLXLM, "file": "mlx_lm/tuner/losses.py", "line": "329"},
        "name": "kl_backward",
        "template": [("T", "float32"), ("V", 8192)],
        "inputs": [
            {"name": "logits_q", "dtype": "float32"},
            {"name": "logits_p", "dtype": "float32"},
            {"name": "cotan", "dtype": "float32"},
        ],
        "outputs": [{"name": "out", "dtype": "float32"}],
        "grid": "(1024, cotan.size, 1)", "threadgroup": "(1024, 1, 1)",
        "representative": "logits_q/p float32 [..., V=8192], cotan float32; T=float, V=8192",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/tuner/losses.py", "_make_kl_backward_kernel"),
    },
    {
        "id": "js_forward",
        "origin": {"repo": MLXLM, "file": "mlx_lm/tuner/losses.py", "line": "564"},
        "name": "js_forward",
        "template": [("T", "float32"), ("V", 8192)],
        "inputs": [
            {"name": "logits_q", "dtype": "float32"},
            {"name": "logits_p", "dtype": "float32"},
        ],
        "outputs": [{"name": "out", "dtype": "float32"}, {"name": "out_kl_q", "dtype": "float32"}],
        "grid": "(1024, n_outs, 1)", "threadgroup": "(1024, 1, 1)",
        "representative": "logits_q/p float32 [..., V=8192], 2 outputs float32; T=float, V=8192",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/tuner/losses.py", "_make_js_forward_kernel"),
    },
    {
        "id": "js_backward",
        "origin": {"repo": MLXLM, "file": "mlx_lm/tuner/losses.py", "line": "735"},
        "name": "js_backward",
        "template": [("T", "float32"), ("V", 8192)],
        "inputs": [
            {"name": "logits_q", "dtype": "float32"},
            {"name": "logits_p", "dtype": "float32"},
            {"name": "cotan", "dtype": "float32"},
            {"name": "output_kl_q", "dtype": "float32"},
        ],
        "outputs": [{"name": "out_q", "dtype": "float32"}],
        "grid": "(1024, cotan.size, 1)", "threadgroup": "(1024, 1, 1)",
        "representative": "logits_q/p float32 [..., V=8192], cotan/output_kl_q float32, out_q float32",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-lm/mlx_lm/tuner/losses.py", "_make_js_backward_kernel"),
    },
    # ---------- mlx-examples ----------
    {
        "id": "encodec_lstm_examples",
        "origin": {"repo": MLXEX, "file": "encodec/encodec.py", "line": "14"},
        "name": "lstm",
        "header": """
        template <typename T>
        T sigmoid(T x) {
            auto y = 1 / (1 + metal::exp(-metal::abs(x)));
            return (x < 0) ? 1 - y : y;
        }
        """,
        "inputs": [
            {"name": "x", "dtype": "float32"},
            {"name": "h_in", "dtype": "float32"},
            {"name": "cell", "dtype": "float32"},
            {"name": "hidden_size", "dtype": "int32", "scalar": True},
            {"name": "time_step", "dtype": "int32", "scalar": True},
            {"name": "num_time_steps", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "hidden_state", "dtype": "float32"}, {"name": "cell_state", "dtype": "float32"}],
        "grid": "(B, H*4, 1)", "threadgroup": "(256, 1, 1)",
        "representative": "x/h_in/cell float32 (B=2, time_steps=4, H*4=32, hidden=8); 3 int32 scalars; no template",
        "source_fn": lambda: _extract_lstm_source(PINNED / "mlx-examples/encodec/encodec.py"),
    },
    {
        "id": "wwdc25_myexp",
        "origin": {"repo": MLXEX, "file": "wwdc25/Get_started_with_MLX_for_Apple_silicon.ipynb", "line": "527"},
        "name": "myexp",
        "inputs": [{"name": "inp", "dtype": "float32"}],
        "outputs": [{"name": "out", "dtype": "float32"}],
        "grid": "(x.size, 1, 1)", "threadgroup": "(256, 1, 1)",
        "representative": "x float32 [1.0, 2.0, 3.0]; trivial exp kernel",
        "source_fn": lambda: get_notebook_source(PINNED / "mlx-examples/wwdc25/Get_started_with_MLX_for_Apple_silicon.ipynb"),
    },
    # ---------- mlx-audio ----------
    {
        "id": "mlx_audio_ssm_kernel",
        "origin": {"repo": MLXAU, "file": "mlx_audio/lm/models/ssm.py", "line": "67"},
        "name": "ssm_kernel",
        "template": [("T", "float32"), ("U", "float32"), ("Dh", 8), ("Ds", 32), ("H", 2), ("G", 2)],
        "inputs": [
            {"name": "X", "dtype": "float32"},
            {"name": "A_log", "dtype": "float32"},
            {"name": "B", "dtype": "float32"},
            {"name": "C", "dtype": "float32"},
            {"name": "D", "dtype": "float32"},
            {"name": "dt", "dtype": "float32"},
            {"name": "state_in", "dtype": "float32"},
        ],
        "outputs": [{"name": "out", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, d, h*n)", "threadgroup": "(32, 8, 1)",
        "representative": "vendored from mlx-lm 0.31.3 ssm_kernel; X/A_log/B/C/D/dt/state_in float32 [n=1,h=2,d=8,hb=1,Ds=32]; T=float,U=float,Dh=8,Ds=32,H=2,G=2; grid=(32,8,2),tg=(32,8,1)",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-audio/mlx_audio/lm/models/ssm.py", "make_ssm_kernel"),
    },
    {
        "id": "mlx_audio_ssm_initial_kernel",
        "origin": {"repo": MLXAU, "file": "mlx_audio/lm/models/ssm.py", "line": "127"},
        "name": "ssm_initial_kernel",
        "template": [("T", "float32"), ("U", "float32"), ("Dh", 8), ("Ds", 32), ("H", 2), ("Ng", 1), ("HpG", 2)],
        "inputs": [
            {"name": "X", "dtype": "float32"},
            {"name": "decay", "dtype": "float32"},
            {"name": "B", "dtype": "float32"},
            {"name": "C", "dtype": "float32"},
            {"name": "D", "dtype": "float32"},
            {"name": "dt", "dtype": "float32"},
            {"name": "sequence_length", "dtype": "uint32", "constant": True},
        ],
        "outputs": [{"name": "out", "dtype": "float32"}, {"name": "state_out", "dtype": "float32"}],
        "grid": "(32, d, h*n)", "threadgroup": "(32, 8, 1)",
        "representative": "n=1,l=2,h=2,d=8,groups=1,state_dim=32; T=float,U=float,Dh=8,Ds=32,H=2,Ng=1,HpG=2; sequence_length uint32 (1,) constant",
        "source_fn": lambda: get_module_func_source(PINNED / "mlx-audio/mlx_audio/lm/models/ssm.py", "make_ssm_initial_kernel"),
    },
    {
        "id": "mlx_audio_codec_encodec_lstm",
        "origin": {"repo": MLXAU, "file": "mlx_audio/codec/models/encodec/encodec.py", "line": "89"},
        "name": "lstm",
        "header": """
        template <typename T>
        T sigmoid(T x) {
            auto y = 1 / (1 + metal::exp(-metal::abs(x)));
            return (x < 0) ? 1 - y : y;
        }
        """,
        "inputs": [
            {"name": "x", "dtype": "float32"},
            {"name": "h_in", "dtype": "float32"},
            {"name": "cell", "dtype": "float32"},
            {"name": "hidden_size", "dtype": "int32", "scalar": True},
            {"name": "time_step", "dtype": "int32", "scalar": True},
            {"name": "num_time_steps", "dtype": "int32", "scalar": True},
        ],
        "outputs": [{"name": "hidden_state", "dtype": "float32"}, {"name": "cell_state", "dtype": "float32"}],
        "grid": "(B, H*4, 1)", "threadgroup": "(256, 1, 1)",
        "representative": "identical body to encodec_lstm_examples; same representative shapes",
        "source_fn": lambda: _extract_lstm_source(PINNED / "mlx-audio/mlx_audio/codec/models/encodec/encodec.py"),
    },
]


def _extract_lstm_source(path):
    """The encodec lstm kernel is a module-level call: `name=..., input_names=..., output_names=..., header=\"\"\"...\"\"\", source=\"\"\"...\"\"\"`. Pull source string out of the call args via ast."""
    tree = ast.parse(path.read_text())
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_lstm_kernel":
                    val = stmt.value
                    if isinstance(val, ast.Call):
                        for kw in val.keywords:
                            if kw.arg == "source":
                                return _resolve_value(kw.value, {})
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == "_lstm_kernel":
            val = stmt.value
            if isinstance(val, ast.Call):
                for kw in val.keywords:
                    if kw.arg == "source":
                        return _resolve_value(kw.value, {})
    raise RuntimeError(f"no _lstm_kernel in {path}")


def _gated_delta_variant_subs(has_mask, vectorized):
    return {
        "mask_source": "mask[b_idx * T + t]" if has_mask else "true",
        "g_comment": "// g: [B, T, Hv, Dk]" if vectorized else "// g: [B, T, Hv]",
        "g_setup": "auto g_ = g + (b_idx * T * Hv + hv_idx) * Dk;" if vectorized else "auto g_ = g + b_idx * T * Hv;",
        "g_access": "g_[s_idx]" if vectorized else "g_[hv_idx]",
        "g_advance": "g_ += Hv * Dk;" if vectorized else "g_ += Hv;",
    }


# --- Runner ----------------------------------------------------------------

def run(outdir, m2v, results_path, m2v_cache=None, metals_dir=None):
    outdir = pathlib.Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    metals = pathlib.Path(metals_dir) if metals_dir else outdir
    metals.mkdir(parents=True, exist_ok=True)
    rows = []
    env = os.environ.copy()
    if m2v_cache:
        env["M2V_CACHE_DIR"] = str(m2v_cache)
    # Toolchain env for m2v-compile: CLANG, OPT, CLSPV, SPIRV_VAL must come from the
    # caller's environment (the sweep's env.sh); m2v-compile validates and fails fast.
    for spec in KERNELS:
        print(f"== {spec['id']} ==", file=sys.stderr)
        # Extract source
        if "variant" in spec:
            subs = _gated_delta_variant_subs(**spec["variant"])
            source = get_module_func_source(PINNED / "mlx-lm/mlx_lm/models/gated_delta.py",
                                            "_make_gated_delta_kernel", subs=subs)
        elif "source_fn" in spec:
            source = spec["source_fn"]()
        else:
            raise RuntimeError(f"no source extractor for {spec['id']}")
        metal, mangled = emit_metal(spec, source, header=spec.get("header"))
        metal_path = metals / f"{spec['id']}.metal"
        metal_path.write_text(metal)
        # Compile
        target = outdir / spec["id"]
        target.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, str(m2v), "--msl", str(metal_path), "--out", str(target), "--json", "--timeout", "180"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=600)
        except subprocess.TimeoutExpired as e:
            rows.append({"kernel": spec["id"], "origin": f"{spec['origin']['repo']}:{spec['origin']['file']}:{spec['origin']['line']}",
                         "source_sha256": hashlib.sha256(metal.encode()).hexdigest(),
                         "valid": "no", "first_error": "timeout", "m2v_giveup": "no",
                         "representative_call": spec["representative"], "cause": "timeout"})
            continue
        import hashlib
        ok = r.returncode == 0
        if ok:
            # m2v-compile prints JSON line on success
            j = None
            for line in r.stdout.splitlines():
                try:
                    j = json.loads(line)
                except Exception:
                    continue
            valid = "yes" if j and j.get("status") == "ok" else "no"
            err = "" if valid == "yes" else (j.get("detail") or j.get("status") if j else r.stderr)
        else:
            j = None
            for line in r.stdout.splitlines():
                try:
                    j = json.loads(line)
                except Exception:
                    continue
            valid = "no"
            err = (j or {}).get("detail") or r.stderr.splitlines()[0] if r.stderr else f"exit={r.returncode}"
        cause = ""
        if not ok:
            cause = _classify(j, r, spec)
        rows.append({"kernel": spec["id"], "origin": f"{spec['origin']['repo']}:{spec['origin']['file']}:{spec['origin']['line']}",
                     "source_sha256": hashlib.sha256(metal.encode()).hexdigest(),
                     "valid": valid, "first_error": err, "m2v_giveup": "no",
                     "representative_call": spec["representative"], "cause": cause,
                     "exit": r.returncode})
        print(f"  -> valid={valid} exit={r.returncode} cause={cause}", file=sys.stderr)
    # Write TSV
    cols = ["kernel", "origin", "source_sha256", "valid", "first_error", "m2v_giveup", "representative_call", "cause"]
    with open(results_path, "w") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
    print(f"wrote {results_path} ({len(rows)} rows)", file=sys.stderr)


def _classify(j, r, spec):
    if not j:
        return "compile error"
    if j.get("status") == "refused":
        return "refused: " + str(j.get("refused", "?"))
    if j.get("status") == "ok":
        return ""
    return j.get("status", "error")


if __name__ == "__main__":
    import hashlib
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="build", help="build artifact directory (.spv/.json)")
    ap.add_argument("--metals", default=None, help="where the .metal sources land (default: same as --out)")
    ap.add_argument("--results", default="results-others.tsv")
    ap.add_argument("--m2v", default=os.environ.get("SWEEP_ROOT", str(pathlib.Path.home() / "scratch/sweep/wt-kernel-batch")) + "/tools/m2v-compile")
    ap.add_argument("--cache", default=os.environ.get("M2V_CACHE_DIR", str(pathlib.Path.home() / ".cache/m2v-compile")))
    args = ap.parse_args()
    run(pathlib.Path(args.out), pathlib.Path(args.m2v), pathlib.Path(args.results), pathlib.Path(args.cache),
        metals_dir=args.metals)
