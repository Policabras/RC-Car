#pragma once

#include "robot_types.h"

typedef struct {
    float wheel_radius_m;
    float wheel_base_m;
    float encoder_cpr_x4;
    float imu_blend_alpha;
    float imu_bias_dps;
} odom_config_t;

void odom_init(odom_state_t *state);
void odom_update(
    odom_state_t *state,
    const odom_config_t *cfg,
    float dt_s,
    int32_t left_ticks_delta,
    int32_t right_ticks_delta,
    float gyro_z_dps);
