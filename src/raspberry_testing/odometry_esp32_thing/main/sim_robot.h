#pragma once

#include <stdint.h>
#include "robot_types.h"

typedef struct {
    float wheel_radius_m;
    float wheel_base_m;
    float encoder_cpr_x4;
    float imu_gyro_bias_dps;
    float imu_gyro_noise_dps;
} sim_robot_config_t;

typedef struct {
    robot_pose_t truth;
    float left_tick_residual;
    float right_tick_residual;
    float elapsed_s;
} sim_robot_state_t;

void sim_robot_init(sim_robot_state_t *state);
void sim_robot_step(
    sim_robot_state_t *state,
    const sim_robot_config_t *cfg,
    float dt_s,
    sim_measurement_t *out);
