#include "serial_json.h"

#include <stdio.h>

void serial_json_init(void)
{
    setvbuf(stdout, NULL, _IOLBF, 0);
}

void serial_json_send_odom(
    const char *device_id,
    const char *stream,
    uint32_t sample_period_ms,
    uint32_t qos,
    uint32_t retain,
    uint64_t ts_source_ms,
    uint32_t seq,
    const odom_state_t *odom,
    const serial_debug_t *dbg)
{
    printf(
        "{"
        "\"device_id\":\"%s\"," 
        "\"stream\":\"%s\"," 
        "\"sample_period_ms\":%u," 
        "\"qos\":%u," 
        "\"retain\":%s," 
        "\"ts_source_ms\":%llu," 
        "\"seq\":%u," 
        "\"payload\":{"
            "\"x\":%.6f," 
            "\"y\":%.6f," 
            "\"theta\":%.6f," 
            "\"vx\":%.6f," 
            "\"wz\":%.6f," 
            "\"left_ticks_delta\":%ld," 
            "\"right_ticks_delta\":%ld," 
            "\"gyro_z_dps\":%.6f," 
            "\"true_v\":%.6f," 
            "\"true_wz\":%.6f"
        "}"
        "}\n",
        device_id,
        stream,
        sample_period_ms,
        qos,
        retain ? "true" : "false",
        (unsigned long long)ts_source_ms,
        seq,
        odom->pose.x_m,
        odom->pose.y_m,
        odom->pose.theta_rad,
        odom->pose.v_mps,
        odom->pose.wz_radps,
        (long)dbg->left_ticks_delta,
        (long)dbg->right_ticks_delta,
        dbg->gyro_z_dps,
        dbg->true_v_mps,
        dbg->true_wz_radps
    );
    fflush(stdout);
}
