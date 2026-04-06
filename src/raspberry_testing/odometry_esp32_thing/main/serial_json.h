#pragma once

#include <stdint.h>
#include "robot_types.h"

typedef struct {
    int32_t left_ticks_delta;
    int32_t right_ticks_delta;
    float gyro_z_dps;
    float true_v_mps;
    float true_wz_radps;
} serial_debug_t;

void serial_json_init(void);
void serial_json_send_odom(
    const char *device_id,
    const char *stream,
    uint32_t sample_period_ms,
    uint32_t qos,
    uint32_t retain,
    uint64_t ts_source_ms,
    uint32_t seq,
    const odom_state_t *odom,
    const serial_debug_t *dbg);
