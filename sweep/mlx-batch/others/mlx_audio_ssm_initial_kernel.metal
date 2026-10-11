// Origin: mlx-audio@17001a6, mlx_audio/lm/models/ssm.py:127.
// Representative call: n=1,l=2,h=2,d=8,groups=1,state_dim=32; T=float,U=float,Dh=8,Ds=32,H=2,Ng=1,HpG=2; sequence_length uint32 (1,) constant.
// Grid=(32, d, h*n), threadgroup=(32, 8, 1).
// Templates T=float32, U=float32, Dh=8, Ds=32, H=2, Ng=1, HpG=2; concrete instantiation custom_kernel_ssm_initial_kernel__float_float_8_32_2_1_2_float_float_float_float_float_float_uint32_tc_float_float.

template <typename T, typename U, int Dh, int Ds, int H, int Ng, int HpG>
[[kernel]] void custom_kernel_ssm_initial_kernel__float_float_8_32_2_1_2_float_float_float_float_float_float_uint32_tc_float_float(
  const device float* X [[buffer(0)]],
  const device float* decay [[buffer(1)]],
  const device float* B [[buffer(2)]],
  const device float* C [[buffer(3)]],
  const device float* D [[buffer(4)]],
  const device float* dt [[buffer(5)]],
  const device uint32_t* sequence_length [[buffer(6)]],
  device float* out [[buffer(7)]],
  device float* state_out [[buffer(8)]],
  uint thread_index_in_simdgroup [[thread_index_in_simdgroup]],
  uint3 thread_position_in_grid [[thread_position_in_grid]],
  uint3 thread_position_in_threadgroup [[thread_position_in_threadgroup]]
) {

auto length = static_cast<int>(sequence_length[0]);
auto n = thread_position_in_grid.z;
auto batch = n / H;
auto head = n % H;
auto group = head / HpG;
auto d = thread_position_in_grid.y;
auto lane = thread_position_in_threadgroup.x;
constexpr int n_per_t = Ds / 32;

auto output_state = state_out + n * Dh * Ds;
float local_state[n_per_t];
for (int i = 0; i < n_per_t; ++i) {
    local_state[i] = 0.0f;
}

for (int t = 0; t < length; ++t) {
    auto token_head = (batch * length + t) * H + head;
    auto token_group = (batch * length + t) * Ng + group;
    auto x_ = static_cast<float>(X[token_head * Dh + d]);
    auto dt_ = static_cast<float>(dt[token_head]);
    auto dA = static_cast<float>(decay[token_head]);
    auto input_scale = x_ * dt_;
    auto B_ = B + token_group * Ds;
    auto C_ = C + token_group * Ds;
    float acc = 0.0f;

    for (int i = 0; i < n_per_t; ++i) {
        auto s = n_per_t * lane + i;
        auto next = dA * local_state[i]
            + input_scale * static_cast<float>(B_[s]);
        local_state[i] = next;
        acc += next * C_[s];
    }
    acc = simd_sum(acc);
    if (thread_index_in_simdgroup == 0) {
        out[token_head * Dh + d] = static_cast<T>(
            acc + x_ * D[head]);
    }
}

for (int i = 0; i < n_per_t; ++i) {
    auto s = n_per_t * lane + i;
    output_state[d * Ds + s] = static_cast<U>(local_state[i]);
}
}

template [[host_name("custom_kernel_ssm_initial_kernel__float_float_8_32_2_1_2_float_float_float_float_float_float_uint32_tc_float_float")]] [[kernel]] decltype(custom_kernel_ssm_initial_kernel__float_float_8_32_2_1_2_float_float_float_float_float_float_uint32_tc_float_float<float, float, 8, 32, 2, 1, 2>) custom_kernel_ssm_initial_kernel__float_float_8_32_2_1_2_float_float_float_float_float_float_uint32_tc_float_float<float, float, 8, 32, 2, 1, 2>;
