// Origin: mlx-lm@2184db2, mlx_lm/tuner/losses.py:329.
// Representative call: logits_q/p float32 [..., V=8192], cotan float32; T=float, V=8192.
// Grid=(1024, cotan.size, 1), threadgroup=(1024, 1, 1).
// Templates T=float32, V=8192; concrete instantiation custom_kernel_kl_backward__float_8192_float_float_float_float.

template <typename T, int V>
[[kernel]] void custom_kernel_kl_backward__float_8192_float_float_float_float(
  const device float* logits_q [[buffer(0)]],
  const device float* logits_p [[buffer(1)]],
  const device float* cotan [[buffer(2)]],
  device float* out [[buffer(3)]],
  uint simdgroup_index_in_threadgroup [[simdgroup_index_in_threadgroup]],
  uint thread_index_in_simdgroup [[thread_index_in_simdgroup]],
  uint thread_index_in_threadgroup [[thread_index_in_threadgroup]],
  uint3 threadgroup_position_in_grid [[threadgroup_position_in_grid]]
) {

constexpr int M = 4;
constexpr int block = 1024 * M;
constexpr int full_blocks = V / block;
constexpr int extra = V - full_blocks * block;

threadgroup float shared[32 * 2];

uint out_idx = threadgroup_position_in_grid.y;
uint simd_lane_id = thread_index_in_simdgroup;
uint simd_group_id = simdgroup_index_in_threadgroup;

logits_q += out_idx * V;
logits_p += out_idx * V;
out += out_idx * V;
cotan += out_idx;

float lse_q;
float lse_p;

{
    float max_q = -1e30;
    float max_p = -1e30;
    float sum_exp_q = 0;
    float sum_exp_p = 0;

    int offset = thread_index_in_threadgroup * M;
    for (int i = 0; i < full_blocks; i++) {
        // Read and update q and p
        float vals_q[M];
        float vals_p[M];
        for (int j=0; j<M; j++) {
            vals_q[j] = logits_q[offset + j];
            vals_p[j] = logits_p[offset + j];
        }
        float prev_max_q = max_q;
        float prev_max_p = max_p;
        for (int j=0; j<M; j++) {
            max_q = max(max_q, vals_q[j]);
            max_p = max(max_p, vals_p[j]);
        }
        sum_exp_q *= metal::fast::exp(prev_max_q - max_q);
        sum_exp_p *= metal::fast::exp(prev_max_p - max_p);
        for (int j=0; j<M; j++) {
            sum_exp_q += metal::fast::exp(vals_q[j] - max_q);
            sum_exp_p += metal::fast::exp(vals_p[j] - max_p);
        }

        // Move to the next block
        offset += block;
    }
    if (extra > 0) {
        // Read and update q and p
        float vals_q[M];
        float vals_p[M];
        for (int j=0; j < M; j++) {
            vals_q[j] = (offset + j < V) ? logits_q[offset + j] : -1e30;
            vals_p[j] = (offset + j < V) ? logits_p[offset + j] : -1e30;
        }
        float prev_max_q = max_q;
        float prev_max_p = max_p;
        for (int j=0; j<M; j++) {
            max_q = max(max_q, vals_q[j]);
            max_p = max(max_p, vals_p[j]);
        }
        sum_exp_q *= metal::fast::exp(prev_max_q - max_q);
        sum_exp_p *= metal::fast::exp(prev_max_p - max_p);
        for (int j=0; j<M; j++) {
            sum_exp_q += metal::fast::exp(vals_q[j] - max_q);
            sum_exp_p += metal::fast::exp(vals_p[j] - max_p);
        }
    }

    // Share the maxs across the threadgroup
    float prev_max_q = max_q;
    float prev_max_p = max_p;
    max_q = simd_max(max_q);
    max_p = simd_max(max_p);
    if (simd_lane_id == 0) {
        shared[simd_group_id * 2 + 0] = max_q;
        shared[simd_group_id * 2 + 1] = max_p;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    max_q = shared[simd_lane_id * 2 + 0];
    max_p = shared[simd_lane_id * 2 + 1];
    max_q = simd_max(max_q);
    max_p = simd_max(max_p);

    // Share the sum_exp across the threadgroup
    sum_exp_q *= metal::fast::exp(prev_max_q - max_q);
    sum_exp_p *= metal::fast::exp(prev_max_p - max_p);
    sum_exp_q = simd_sum(sum_exp_q);
    sum_exp_p = simd_sum(sum_exp_p);
    if (simd_lane_id == 0) {
        shared[simd_group_id * 2 + 0] = sum_exp_q;
        shared[simd_group_id * 2 + 1] = sum_exp_p;
    }
    threadgroup_barrier(mem_flags::mem_threadgroup);
    sum_exp_q = shared[simd_lane_id * 2 + 0];
    sum_exp_p = shared[simd_lane_id * 2 + 1];
    sum_exp_q = simd_sum(sum_exp_q);
    sum_exp_p = simd_sum(sum_exp_p);

    lse_p = max_p + metal::fast::log(sum_exp_p);
    lse_q = max_q + metal::fast::log(sum_exp_q);
}

threadgroup_barrier(mem_flags::mem_none);

{
    float kl = 0;
    float c = cotan[0];

    int offset = thread_index_in_threadgroup * M;
    for (int i = 0; i < full_blocks; i++) {
        // Read and add to the kl
        float vals_q[M];
        float vals_p[M];
        for (int j=0; j<M; j++) {
            vals_q[j] = logits_q[offset + j];
            vals_p[j] = logits_p[offset + j];
        }

        for (int j=0; j<M; j++) {
            out[offset + j] = static_cast<T>(
                c * (metal::fast::exp(vals_q[j] - lse_q) - metal::fast::exp(vals_p[j] - lse_p)));
        }

        // Move to the next block
        offset += block;
    }
    if (extra > 0) {
        float vals_q[M];
        float vals_p[M];
        for (int j=0; j<M; j++) {
            vals_q[j] = (offset + j < V) ? logits_q[offset + j] : -1e30;
            vals_p[j] = (offset + j < V) ? logits_p[offset + j] : -1e30;
        }

        for (int j=0; j<M; j++) {
            if (offset + j < V) {
                out[offset + j] = static_cast<T>(
                    c * (metal::fast::exp(vals_q[j] - lse_q) - metal::fast::exp(vals_p[j] - lse_p)));
            }
        }
    }
}
}

template [[host_name("custom_kernel_kl_backward__float_8192_float_float_float_float")]] [[kernel]] decltype(custom_kernel_kl_backward__float_8192_float_float_float_float<float, 8192>) custom_kernel_kl_backward__float_8192_float_float_float_float<float, 8192>;
