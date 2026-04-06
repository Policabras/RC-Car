#include "sim_robot.h"

#include <math.h>
#include <stddef.h>
#include <string.h>
#include "esp_random.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static float uniform_noise_symmetric(float amplitude)
{
    const uint32_t raw = esp_random();
    const float unit = (float)(raw & 0xFFFFu) / 65535.0f; // [0,1]
    return (2.0f * unit - 1.0f) * amplitude;
}

static void motion_profile(float t_s, float *v_mps, float *wz_radps)
{
    const float phase = fmodf(t_s, 25.0f);

    if (phase < 5.0f) {
        *v_mps = 0.25f;
        *wz_radps = 0.0f;
    } else if (phase < 10.0f) {
        *v_mps = 0.22f;
        *wz_radps = 0.45f;
    } else if (phase < 15.0f) {
        *v_mps = 0.25f;
        *wz_radps = 0.0f;
    } else if (phase < 20.0f) {
        *v_mps = 0.0f;
        *wz_radps = 0.70f;
    } else {
        *v_mps = 0.18f;
        *wz_radps = -0.35f;
    }
}

void sim_robot_init(sim_robot_state_t *state)
{
    memset(state, 0, sizeof(*state));
}

void sim_robot_step(
    sim_robot_state_t *state,
    const sim_robot_config_t *cfg,
    float dt_s,
    sim_measurement_t *out)
{
    float v = 0.0f;
    float wz = 0.0f;
    motion_profile(state->elapsed_s, &v, &wz);

    const float v_l = v - 0.5f * cfg->wheel_base_m * wz;
    const float v_r = v + 0.5f * cfg->wheel_base_m * wz;

    const float dl = v_l * dt_s;
    const float dr = v_r * dt_s;
    const float counts_per_meter = cfg->encoder_cpr_x4 / (2.0f * (float)M_PI * cfg->wheel_radius_m);

    state->left_tick_residual += dl * counts_per_meter;
    state->right_tick_residual += dr * counts_per_meter;

    const int32_t left_ticks_delta = (int32_t)lrintf(state->left_tick_residual);
    const int32_t right_ticks_delta = (int32_t)lrintf(state->right_tick_residual);

    state->left_tick_residual -= (float)left_ticks_delta;
    state->right_tick_residual -= (float)right_ticks_delta;

    const float theta_mid = state->truth.theta_rad + 0.5f * wz * dt_s;
    state->truth.x_m += v * dt_s * cosf(theta_mid);
    state->truth.y_m += v * dt_s * sinf(theta_mid);
    state->truth.theta_rad += wz * dt_s;
    state->truth.v_mps = v;
    state->truth.wz_radps = wz;
    state->elapsed_s += dt_s;

    out->left_ticks_delta = left_ticks_delta;
    out->right_ticks_delta = right_ticks_delta;
    out->gyro_z_dps = (wz * 180.0f / (float)M_PI)
                    + cfg->imu_gyro_bias_dps
                    + uniform_noise_symmetric(cfg->imu_gyro_noise_dps);
    out->true_v_mps = v;
    out->true_wz_radps = wz;
}
