// Origin: mlx-audio@17001a6, mlx_audio/lm/models/ssm.py:67.
// Representative call: vendored from mlx-lm 0.31.3 ssm_kernel; X/A_log/B/C/D/dt/state_in float32 [n=1,h=2,d=8,hb=1,Ds=32]; T=float,U=float,Dh=8,Ds=32,H=2,G=2; grid=(32,8,2),tg=(32,8,1).
// Grid=(32, d, h*n), threadgroup=(32, 8, 1).
// Templates T=float32, U=float32, Dh=8, Ds=32, H=2, G=2; concrete instantiation custom_kernel_ssm_kernel__float_float_8_32_2_2_float_float_float_float_float_float_float_float_float.

template <typename T, typename U, int Dh, int Ds, int H, int G>
[[kernel]] void custom_kernel_ssm_kernel__float_float_8_32_2_2_float_float_float_float_float_float_float_float_float(
  const device float* X [[buffer(0)]],
  const device float* A_log [[buffer(1)]],
  const device float* B [[buffer(2)]],
  const device float* C [[buffer(3)]],
  const device float* D [[buffer(4)]],
  const device float* dt [[buffer(5)]],
  const device float* state_in [[buffer(6)]],
  device float* out [[buffer(7)]],
  device float* state_out [[buffer(8)]],
  uint thread_index_in_simdgroup [[thread_index_in_simdgroup]],
  uint3 thread_position_in_grid [[thread_position_in_grid]],
  uint3 thread_position_in_threadgroup [[thread_position_in_threadgroup]]
) {

auto n = thread_position_in_grid.z;
auto h_idx = n % H;
auto g_idx = n / G;
constexpr int n_per_t = Ds / 32;

auto x = X + n * Dh;
out += n * Dh;
auto i_state = state_in + n * Dh * Ds;
auto o_state = state_out + n * Dh * Ds;

// C and B have shape [batch, group, state_dim]
// C and B need to be offset by group size
auto C_ = C + g_idx * Ds;
auto B_ = B + g_idx * Ds;

auto ds_idx = thread_position_in_threadgroup.x;
auto d_idx = thread_position_in_grid.y;

auto dt_ = static_cast<float>(dt[n]);
auto A = -fast::exp(static_cast<float>(A_log[h_idx]));
auto dA = fast::exp(A * dt_);

float acc = 0.0;
auto x_ = static_cast<float>(x[d_idx]);

for (int i = 0; i < n_per_t; ++i) {
    auto s_idx = n_per_t * ds_idx + i;
    auto idx = d_idx * Ds + s_idx;
    auto dB_by_x = x_ * dt_ * static_cast<float>(B_[s_idx]);
    auto state = dA * i_state[idx] + dB_by_x;
    o_state[idx] = static_cast<U>(state);
    acc += state * C_[s_idx];
}
acc = simd_sum(acc);
if (thread_index_in_simdgroup == 0) {
    out[d_idx] = static_cast<T>(acc + x_ * D[h_idx]);
}
}

template [[host_name("custom_kernel_ssm_kernel__float_float_8_32_2_2_float_float_float_float_float_float_float_float_float")]] [[kernel]] decltype(custom_kernel_ssm_kernel__float_float_8_32_2_2_float_float_float_float_float_float_float_float_float<float, float, 8, 32, 2, 2>) custom_kernel_ssm_kernel__float_float_8_32_2_2_float_float_float_float_float_float_float_float_float<float, float, 8, 32, 2, 2>;
