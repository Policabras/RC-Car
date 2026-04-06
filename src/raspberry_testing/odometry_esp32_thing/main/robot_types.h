#pragma once

#include <stdint.h>

typedef struct {
    float x_m;
    float y_m;
    float theta_rad;
    float v_mps;
    float wz_radps;
} robot_pose_t;

typedef struct {
    int32_t left_ticks_delta;
    int32_t right_ticks_delta;
    float gyro_z_dps;
    float true_v_mps;
    float true_wz_radps;
} sim_measurement_t;

typedef struct {
    robot_pose_t pose;
    uint32_t seq;
} odom_state_t;
