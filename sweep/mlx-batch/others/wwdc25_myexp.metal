// Origin: mlx-examples@796f5b5, wwdc25/Get_started_with_MLX_for_Apple_silicon.ipynb:527.
// Representative call: x float32 [1.0, 2.0, 3.0]; trivial exp kernel.
// Grid=(x.size, 1, 1), threadgroup=(256, 1, 1).

[[kernel]] void custom_kernel_myexp_float_float(
  const device float* inp [[buffer(0)]],
  device float* out [[buffer(1)]],
  uint3 thread_position_in_grid [[thread_position_in_grid]]
) {

uint elem = thread_position_in_grid.x;
out[elem] = metal::exp(inp[elem]);
}
