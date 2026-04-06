#include "odom_estimator.h"

#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static float deg2rad(float deg)
{
    return deg * ((float)M_PI / 180.0f);
}

void odom_init(odom_state_t *state)
{
    memset(state, 0, sizeof(*state));
}

void odom_update(
    odom_state_t *state,
    const odom_config_t *cfg,
    float dt_s,
    int32_t left_ticks_delta,
    int32_t right_ticks_delta,
    float gyro_z_dps)
{
    const float meters_per_count = (2.0f * (float)M_PI * cfg->wheel_radius_m) / cfg->encoder_cpr_x4;
    const float dl = (float)left_ticks_delta * meters_per_count;
    const float dr = (float)right_ticks_delta * meters_per_count;

    const float ds = 0.5f * (dl + dr);
    const float v_enc = ds / dt_s;
    const float wz_enc = (dr - dl) / (cfg->wheel_base_m * dt_s);
    const float wz_imu = deg2rad(gyro_z_dps - cfg->imu_bias_dps);

    const float alpha = cfg->imu_blend_alpha;
    const float wz_fused = (alpha * wz_imu) + ((1.0f - alpha) * wz_enc);
    const float theta_mid = state->pose.theta_rad + 0.5f * wz_fused * dt_s;

    state->pose.x_m += ds * cosf(theta_mid);
    state->pose.y_m += ds * sinf(theta_mid);
    state->pose.theta_rad += wz_fused * dt_s;
    state->pose.v_mps = v_enc;
    state->pose.wz_radps = wz_fused;
    state->seq += 1;
}
