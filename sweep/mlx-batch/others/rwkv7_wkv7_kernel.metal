// Origin: mlx-lm@2184db2, mlx_lm/models/rwkv7.py:114.
// Representative call: r/w/k/v/a/b [B=1,T=4,H=2,D=64] float32, state_in [B,H,D,D] float32, T int32 scalar; InT=float,H=2,D=64.
// Grid=(32, D, B*H), threadgroup=(32, 4, 1).
// Templates InT=float32, H=2, D=64; concrete instantiation custom_kernel_wkv7_kernel__float_2_64_float_float_float_float_float_float_float_int32_ts_float_float.

template <typename InT, int H, int D>
[[kernel]] void custom_kernel_wkv7_kernel__float_2_64_float_float_float_float_float_float_float_int32_ts_float_float(
  const device float* r [[buffer(0)]],
  const device float* w [[buffer(1)]],
  const device float* k [[buffer(2)]],
  const device float* v [[buffer(3)]],
  const device float* a [[buffer(4)]],
  const device float* b [[buffer(5)]],
  const device float* state_in [[buffer(6)]],
  const constant int32_t& T [[buffer(7)]],
  device float* y [[buffer(8)]],
  device float* state_out [[buffer(9)]],
  uint thread_index_in_simdgroup [[thread_index_in_simdgroup]],
  uint3 thread_position_in_grid [[thread_position_in_grid]],
  uint3 thread_position_in_threadgroup [[thread_position_in_threadgroup]]
) {

auto n = thread_position_in_grid.z;
auto b_idx = n / H;
auto h_idx = n % H;
constexpr int n_per_t = D / 32;

// [B, T, H, D]
auto r_ = r + b_idx * T * H * D + h_idx * D;
auto w_ = w + b_idx * T * H * D + h_idx * D;
auto k_ = k + b_idx * T * H * D + h_idx * D;
auto v_ = v + b_idx * T * H * D + h_idx * D;
auto a_ = a + b_idx * T * H * D + h_idx * D;
auto b_ = b + b_idx * T * H * D + h_idx * D;
y += b_idx * T * H * D + h_idx * D;

auto dk_idx = thread_position_in_threadgroup.x;
auto dv_idx = thread_position_in_grid.y;

// state_in, state_out: [B, H, D, D]
auto i_state = state_in  + (n * D + dv_idx) * D;
auto o_state = state_out + (n * D + dv_idx) * D;

float state[n_per_t];
for (int i = 0; i < n_per_t; ++i) {
  auto s_idx = n_per_t * dk_idx + i;
  state[i] = static_cast<float>(i_state[s_idx]);
}

for (int t = 0; t < T; ++t) {
  float sa = 0.0f;
  for (int i = 0; i < n_per_t; ++i) {
    auto s_idx = n_per_t * dk_idx + i;
    sa += state[i] * a_[s_idx];
    state[i] = state[i] * w_[s_idx];
  }
  sa = simd_sum(sa);

  float out = 0.0f;
  for (int i = 0; i < n_per_t; ++i) {
    auto s_idx = n_per_t * dk_idx + i;
    state[i] = state[i] + k_[s_idx] * v_[dv_idx] + sa * b_[s_idx];
    out += state[i] * r_[s_idx];
  }
  out = simd_sum(out);
  if (thread_index_in_simdgroup == 0) {
    y[dv_idx] = static_cast<InT>(out);
  }

  // Increment data pointers to next time step
  r_ += H * D;
  w_ += H * D;
  k_ += H * D;
  v_ += H * D;
  a_ += H * D;
  b_ += H * D;
  y  += H * D;
}
for (int i = 0; i < n_per_t; ++i) {
  auto s_idx = n_per_t * dk_idx + i;
  o_state[s_idx] = static_cast<InT>(state[i]);
}
}

template [[host_name("custom_kernel_wkv7_kernel__float_2_64_float_float_float_float_float_float_float_int32_ts_float_float")]] [[kernel]] decltype(custom_kernel_wkv7_kernel__float_2_64_float_float_float_float_float_float_float_int32_ts_float_float<float, 2, 64>) custom_kernel_wkv7_kernel__float_2_64_float_float_float_float_float_float_float_int32_ts_float_float<float, 2, 64>;
