#include "unity.h"

#include <stdio.h>
#include <string.h>

#include "flightview_protocol.h"
#include "flightview_radar.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

TEST_CASE("display payload parses selected aircraft without local choice", "[flightview]")
{
    const char *json =
        "{\"schema_version\":1,\"display\":{\"icao24\":\"sel001\",\"flight_display\":\"SEL\"},"
        "\"aircraft\":[{\"icao24\":\"nearer\",\"flight_display\":\"NEAR\",\"distance_ft\":10},"
        "{\"icao24\":\"sel001\",\"flight_display\":\"SEL\",\"distance_ft\":100}],"
        "\"counts\":{\"total_aircraft\":2,\"nearby_aircraft\":2,\"returned_aircraft\":2,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":3000,\"radar_radius_ft\":5000},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":45000,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    static flightview_model_t model;
    TEST_ASSERT_EQUAL(FV_PARSE_OK, flightview_parse_display_payload(json, strlen(json), 1, 0, &model));
    TEST_ASSERT_TRUE(model.has_display);
    TEST_ASSERT_EQUAL_STRING("sel001", model.display.icao24);
}

TEST_CASE("radar cardinal projection matches screen compass", "[flightview]")
{
    TEST_ASSERT_LESS_THAN(250, flightview_radar_project(0, 100, 100, 0, 0, 380, 500).y);
    TEST_ASSERT_GREATER_THAN(190, flightview_radar_project(90, 100, 100, 0, 0, 380, 500).x);
    TEST_ASSERT_GREATER_THAN(250, flightview_radar_project(180, 100, 100, 0, 0, 380, 500).y);
    TEST_ASSERT_LESS_THAN(190, flightview_radar_project(270, 100, 100, 0, 0, 380, 500).x);
}

void app_main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    vTaskDelay(pdMS_TO_TICKS(3000));
    UNITY_BEGIN();
    unity_run_all_tests();
    const int failures = UNITY_END();
    while (true) {
        printf("FLIGHTVIEW_UNITY_RESULT tests=%u failures=%d ignored=%u\n",
               (unsigned)Unity.NumberOfTests, failures, (unsigned)Unity.TestIgnores);
        vTaskDelay(pdMS_TO_TICKS(2000));
    }
}
