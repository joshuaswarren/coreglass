// Origin: mlx-lm@2184db2, mlx_lm/models/gated_delta.py:130.
// Representative call: same as gated_delta_step plus bool mask [B,T]; scalar g path.
// Grid=(32, Dv, B*Hv), threadgroup=(32, 4, 1).
// Templates InT=float32, StT=float32, Dk=128, Dv=128, Hk=2, Hv=2; concrete instantiation custom_kernel_gated_delta_step_mask__float_float_128_128_2_2_float_float_float_float_float_float_int32_ts_bool_float_float.

template <typename InT, typename StT, int Dk, int Dv, int Hk, int Hv>
[[kernel]] void custom_kernel_gated_delta_step_mask__float_float_128_128_2_2_float_float_float_float_float_float_int32_ts_bool_float_float(
  const device float* q [[buffer(0)]],
  const device float* k [[buffer(1)]],
  const device float* v [[buffer(2)]],
  const device float* g [[buffer(3)]],
  const device float* beta [[buffer(4)]],
  const device float* state_in [[buffer(5)]],
  const constant int32_t& T [[buffer(6)]],
  const device bool* mask [[buffer(7)]],
  device float* y [[buffer(8)]],
  device float* state_out [[buffer(9)]],
  uint thread_index_in_simdgroup [[thread_index_in_simdgroup]],
  uint3 thread_position_in_grid [[thread_position_in_grid]],
  uint3 thread_position_in_threadgroup [[thread_position_in_threadgroup]]
) {

auto n = thread_position_in_grid.z;
auto b_idx = n / Hv;
auto hv_idx = n % Hv;
auto hk_idx = hv_idx / (Hv / Hk);
constexpr int n_per_t = Dk / 32;

// q, k: [B, T, Hk, Dk]
auto q_ = q + b_idx * T * Hk * Dk + hk_idx * Dk;
auto k_ = k + b_idx * T * Hk * Dk + hk_idx * Dk;

// v, y: [B, T, Hv, Dv]
auto v_ = v + b_idx * T * Hv * Dv + hv_idx * Dv;
y += b_idx * T * Hv * Dv + hv_idx * Dv;

auto dk_idx = thread_position_in_threadgroup.x;
auto dv_idx = thread_position_in_grid.y;

// state_in, state_out: [B, Hv, Dv, Dk]
auto i_state = state_in + (n * Dv + dv_idx) * Dk;
auto o_state = state_out + (n * Dv + dv_idx) * Dk;

float state[n_per_t];
for (int i = 0; i < n_per_t; ++i) {
  auto s_idx = n_per_t * dk_idx + i;
  state[i] = static_cast<float>(i_state[s_idx]);
}

// g: [B, T, Hv]
auto g_ = g + b_idx * T * Hv;
auto beta_ = beta + b_idx * T * Hv;

for (int t = 0; t < T; ++t) {
  if (mask[b_idx * T + t]) {
    float kv_mem = 0.0f;
    for (int i = 0; i < n_per_t; ++i) {
      auto s_idx = n_per_t * dk_idx + i;
      state[i] = state[i] * g_[hv_idx];
      kv_mem += state[i] * k_[s_idx];
    }
    kv_mem = simd_sum(kv_mem);

    auto delta = (v_[dv_idx] - kv_mem) * beta_[hv_idx];

    float out = 0.0f;
    for (int i = 0; i < n_per_t; ++i) {
      auto s_idx = n_per_t * dk_idx + i;
      state[i] = state[i] + k_[s_idx] * delta;
      out += state[i] * q_[s_idx];
    }
    out = simd_sum(out);
    if (thread_index_in_simdgroup == 0) {
      y[dv_idx] = static_cast<InT>(out);
    }
  } else {
    y[dv_idx] = static_cast<InT>(0);
  }
  // Increment data pointers to next time step
  q_ += Hk * Dk;
  k_ += Hk * Dk;
  v_ += Hv * Dv;
  y += Hv * Dv;
  g_ += Hv;
  beta_ += Hv;
}
for (int i = 0; i < n_per_t; ++i) {
  auto s_idx = n_per_t * dk_idx + i;
  o_state[s_idx] = static_cast<StT>(state[i]);
}
}

template [[host_name("custom_kernel_gated_delta_step_mask__float_float_128_128_2_2_float_float_float_float_float_float_int32_ts_bool_float_float")]] [[kernel]] decltype(custom_kernel_gated_delta_step_mask__float_float_128_128_2_2_float_float_float_float_float_float_int32_ts_bool_float_float<float, float, 128, 128, 2, 2>) custom_kernel_gated_delta_step_mask__float_float_128_128_2_2_float_float_float_float_float_float_int32_ts_bool_float_float<float, float, 128, 128, 2, 2>;
