#include <inttypes.h>
#include <stdio.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"

#include "app_config.h"
#include "odom_estimator.h"
#include "serial_json.h"
#include "sim_robot.h"

static const char *TAG = "diff_odom_serial";

static uint64_t now_ms(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000ULL);
}

void app_main(void)
{
    const float dt_s = (float)APP_SAMPLE_PERIOD_MS / 1000.0f;

    const sim_robot_config_t sim_cfg = {
        .wheel_radius_m = APP_WHEEL_RADIUS_M,
        .wheel_base_m = APP_WHEEL_BASE_M,
        .encoder_cpr_x4 = APP_ENCODER_CPR_X4,
        .imu_gyro_bias_dps = APP_IMU_GYRO_BIAS_DPS,
        .imu_gyro_noise_dps = APP_IMU_GYRO_NOISE_DPS,
    };

    const odom_config_t odom_cfg = {
        .wheel_radius_m = APP_WHEEL_RADIUS_M,
        .wheel_base_m = APP_WHEEL_BASE_M,
        .encoder_cpr_x4 = APP_ENCODER_CPR_X4,
        .imu_blend_alpha = APP_IMU_BLEND_ALPHA,
        .imu_bias_dps = APP_IMU_GYRO_BIAS_DPS,
    };

    sim_robot_state_t sim_state;
    sim_measurement_t sim_meas;
    odom_state_t odom_state;

    sim_robot_init(&sim_state);
    odom_init(&odom_state);
    serial_json_init();

    ESP_LOGI(TAG, "Starting simulated differential odometry sender");
    ESP_LOGI(TAG, "device_id=%s sample_period_ms=%d encoder_cpr_x4=%.1f",
             APP_DEVICE_ID, APP_SAMPLE_PERIOD_MS, APP_ENCODER_CPR_X4);

    TickType_t last_wake = xTaskGetTickCount();

    while (1) {
        sim_robot_step(&sim_state, &sim_cfg, dt_s, &sim_meas);

        odom_update(
            &odom_state,
            &odom_cfg,
            dt_s,
            sim_meas.left_ticks_delta,
            sim_meas.right_ticks_delta,
            sim_meas.gyro_z_dps);

        const serial_debug_t dbg = {
            .left_ticks_delta = sim_meas.left_ticks_delta,
            .right_ticks_delta = sim_meas.right_ticks_delta,
            .gyro_z_dps = sim_meas.gyro_z_dps,
            .true_v_mps = sim_meas.true_v_mps,
            .true_wz_radps = sim_meas.true_wz_radps,
        };

        serial_json_send_odom(
            APP_DEVICE_ID,
            APP_STREAM_NAME,
            APP_SAMPLE_PERIOD_MS,
            APP_QOS,
            APP_RETAIN,
            now_ms(),
            odom_state.seq,
            &odom_state,
            &dbg);

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(APP_SAMPLE_PERIOD_MS));
    }
}
