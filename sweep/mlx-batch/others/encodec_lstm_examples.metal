// Origin: mlx-examples@796f5b5, encodec/encodec.py:14.
// Representative call: x/h_in/cell float32 (B=2, time_steps=4, H*4=32, hidden=8); 3 int32 scalars; no template.
// Grid=(B, H*4, 1), threadgroup=(256, 1, 1).


template <typename T>
T sigmoid(T x) {
    auto y = 1 / (1 + metal::exp(-metal::abs(x)));
    return (x < 0) ? 1 - y : y;
}

[[kernel]] void custom_kernel_lstm_float_float_float_int32_ts_int32_ts_int32_ts_float_float(
  const device float* x [[buffer(0)]],
  const device float* h_in [[buffer(1)]],
  const device float* cell [[buffer(2)]],
  const constant int32_t& hidden_size [[buffer(3)]],
  const constant int32_t& time_step [[buffer(4)]],
  const constant int32_t& num_time_steps [[buffer(5)]],
  device float* hidden_state [[buffer(6)]],
  device float* cell_state [[buffer(7)]],
  uint3 thread_position_in_grid [[thread_position_in_grid]]
) {

uint b = thread_position_in_grid.x;
uint d = hidden_size * 4;

uint elem = b * d + thread_position_in_grid.y;
uint index = elem;
uint x_index = b * num_time_steps * d + time_step * d + index;

auto i = sigmoid(h_in[index] + x[x_index]);
index += hidden_size;
x_index += hidden_size;
auto f = sigmoid(h_in[index] + x[x_index]);
index += hidden_size;
x_index += hidden_size;
auto g = metal::precise::tanh(h_in[index] + x[x_index]);
index += hidden_size;
x_index += hidden_size;
auto o = sigmoid(h_in[index] + x[x_index]);

cell_state[elem] = f * cell[elem] + i * g;
hidden_state[elem] = o * metal::precise::tanh(cell_state[elem]);
}
