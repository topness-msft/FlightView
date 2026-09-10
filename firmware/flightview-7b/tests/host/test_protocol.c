#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "flightview_protocol.h"
#include "flightview_radar.h"

static const char *payload =
    "{"
    "\"schema_version\":1,"
    "\"display\":{\"icao24\":\"abc123\",\"callsign\":\"DAL123\",\"flight_display\":\"DL 123\","
    "\"airline\":\"Delta\",\"typecode\":\"B739\",\"aircraft_type\":\"Boeing 737 MAX 9\","
    "\"registration\":\"N12345\",\"route_origin\":\"SEA\",\"route_destination\":\"ATL\","
    "\"origin_city\":\"Seattle\",\"destination_city\":\"Atlanta\",\"altitude_ft\":1200,"
    "\"velocity_kts\":210,\"distance_ft\":700,\"vertical_rate_fpm\":-200,"
    "\"bearing\":90,\"heading\":180,\"compass\":\"E\",\"direction\":\"approaching\"},"
    "\"aircraft\":[{\"icao24\":\"abc123\",\"callsign\":\"DAL123\",\"flight_display\":\"DL 123\","
    "\"airline\":\"Delta\",\"typecode\":\"B739\",\"aircraft_type\":\"Boeing 737 MAX 9\","
    "\"registration\":\"N12345\",\"route_origin\":\"SEA\",\"route_destination\":\"ATL\","
    "\"origin_city\":\"Seattle\",\"destination_city\":\"Atlanta\",\"altitude_ft\":1200,"
    "\"velocity_kts\":210,\"distance_ft\":700,\"vertical_rate_fpm\":-200,"
    "\"bearing\":90,\"heading\":180,\"compass\":\"E\",\"direction\":\"approaching\"}],"
    "\"counts\":{\"total_aircraft\":1,\"nearby_aircraft\":1,\"returned_aircraft\":1,\"truncated\":false},"
    "\"zones\":{\"near_radius_ft\":3000,\"radar_radius_ft\":5000},"
    "\"freshness\":{\"source_state_observed_at\":1700000000,\"state_age_ms\":1200,"
    "\"stale_after_ms\":45000,\"is_initial\":false,\"is_stale\":false},"
    "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"},"
    "\"server_version\":\"test\""
    "}";

static void test_parse_rich_payload(void)
{
    flightview_model_t model;
    assert(flightview_parse_display_payload(payload, strlen(payload), 10000, 150, &model) == FV_PARSE_OK);
    assert(model.valid);
    assert(model.has_display);
    assert(model.aircraft_count == 1);
    assert(strcmp(model.display.aircraft_type, "Boeing 737 MAX 9") == 0);
    assert(model.display.distance_ft.valid && model.display.distance_ft.value == 700.0f);
    assert(model.freshness.state_age_ms == 1350);
    assert(flightview_model_age_ms(&model, 11000) == 2350);

    const char *unknown_source =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[],"
        "\"counts\":{\"total_aircraft\":0,\"nearby_aircraft\":0,\"returned_aircraft\":0,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":3000,\"radar_radius_ft\":5000},"
        "\"freshness\":{\"source_state_observed_at\":1700000000,\"state_age_ms\":5000000000,"
        "\"stale_after_ms\":45000,\"is_initial\":false,\"is_stale\":true},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"unknown\",\"message\":\"safe\"}}";
    assert(flightview_parse_display_payload(unknown_source, strlen(unknown_source), 6000000000ULL, 10, &model) == FV_PARSE_OK);
    assert(strcmp(model.health.data_source, "unknown") == 0);
    assert(model.freshness.state_age_ms == 5000000010ULL);
    assert(flightview_model_age_ms(&model, 6000001000ULL) == 5000001010ULL);
}

static void test_initial_empty_payload(void)
{
    const char *empty =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[],"
        "\"counts\":{\"total_aircraft\":0,\"nearby_aircraft\":0,\"returned_aircraft\":0,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":3000,\"radar_radius_ft\":5000},"
        "\"freshness\":{\"source_state_observed_at\":null,\"state_age_ms\":null,"
        "\"stale_after_ms\":45000,\"is_initial\":true,\"is_stale\":true},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"awaiting\"}}";
    flightview_model_t model;
    assert(flightview_parse_display_payload(empty, strlen(empty), 500, 0, &model) == FV_PARSE_OK);
    assert(model.valid);
    assert(!model.has_display);
    assert(model.aircraft_count == 0);
    assert(model.freshness.is_initial);
}

static void test_unknown_numbers_and_hidden_route(void)
{
    const char *unknown =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[{\"icao24\":\"abc123\","
        "\"callsign\":\"\",\"flight_display\":\"\",\"airline\":\"\",\"typecode\":\"\","
        "\"aircraft_type\":\"\",\"registration\":\"\",\"route_origin\":\"\",\"route_destination\":\"\","
        "\"origin_city\":\"\",\"destination_city\":\"\",\"altitude_ft\":null,\"velocity_kts\":null,"
        "\"distance_ft\":null,\"vertical_rate_fpm\":null,\"bearing\":null,\"heading\":null,"
        "\"compass\":\"\",\"direction\":\"\"}],"
        "\"counts\":{\"total_aircraft\":1,\"nearby_aircraft\":0,\"returned_aircraft\":1,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":3000,\"radar_radius_ft\":5000},"
        "\"freshness\":{\"source_state_observed_at\":1700000000,\"state_age_ms\":1,"
        "\"stale_after_ms\":45000,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    flightview_model_t model;
    assert(flightview_parse_display_payload(unknown, strlen(unknown), 1, 0, &model) == FV_PARSE_OK);
    assert(!model.aircraft[0].altitude_ft.valid);
    assert(model.aircraft[0].route_origin[0] == '\0');
    assert(model.aircraft[0].route_destination[0] == '\0');
}

static void test_bounds_schema_and_strings(void)
{
    char too_large[FV_HTTP_BODY_MAX_BYTES + 2];
    memset(too_large, ' ', sizeof(too_large));
    flightview_model_t model;
    assert(flightview_parse_display_payload(too_large, sizeof(too_large), 0, 0, &model) == FV_PARSE_ERR_BODY_TOO_LARGE);

    const char *bad_schema =
        "{\"schema_version\":2,\"display\":null,\"aircraft\":[],"
        "\"counts\":{\"total_aircraft\":0,\"nearby_aircraft\":0,\"returned_aircraft\":0,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":1,\"radar_radius_ft\":1},"
        "\"freshness\":{\"source_state_observed_at\":null,\"state_age_ms\":null,"
        "\"stale_after_ms\":1,\"is_initial\":true,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    assert(flightview_parse_display_payload(bad_schema, strlen(bad_schema), 0, 0, &model) == FV_PARSE_ERR_UNSUPPORTED_SCHEMA);

    const char *long_icao =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[{\"icao24\":\"abcdefg\"}],"
        "\"counts\":{\"total_aircraft\":1,\"nearby_aircraft\":0,\"returned_aircraft\":1,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":1,\"radar_radius_ft\":1},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":1,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    assert(flightview_parse_display_payload(long_icao, strlen(long_icao), 0, 0, &model) == FV_PARSE_ERR_STRING_OVERFLOW);

    const char *bad_counts =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[],"
        "\"counts\":{\"total_aircraft\":0,\"nearby_aircraft\":0,\"returned_aircraft\":1,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":1,\"radar_radius_ft\":1},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":1,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    assert(flightview_parse_display_payload(bad_counts, strlen(bad_counts), 0, 0, &model) == FV_PARSE_ERR_BOUNDS);

    const char *bad_freshness =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[],"
        "\"counts\":{\"total_aircraft\":0,\"nearby_aircraft\":0,\"returned_aircraft\":0,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":1,\"radar_radius_ft\":1},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":0,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    assert(flightview_parse_display_payload(bad_freshness, strlen(bad_freshness), 0, 0, &model) == FV_PARSE_ERR_INVALID_VALUE);

    const char *larger_near_zone =
        "{\"schema_version\":1,\"display\":null,\"aircraft\":[],"
        "\"counts\":{\"total_aircraft\":0,\"nearby_aircraft\":0,\"returned_aircraft\":0,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":5000,\"radar_radius_ft\":3000},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":1,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    assert(flightview_parse_display_payload(larger_near_zone, strlen(larger_near_zone), 0, 0, &model) == FV_PARSE_OK);

    char oversized[8192];
    strcpy(oversized, "{\"schema_version\":1,\"display\":null,\"aircraft\":[");
    for (int i = 0; i < 33; i++) {
        char item[96];
        snprintf(item, sizeof(item), "%s{\"icao24\":\"%06d\"}", i == 0 ? "" : ",", i);
        strcat(oversized, item);
    }
    strcat(oversized,
        "],\"counts\":{\"total_aircraft\":33,\"nearby_aircraft\":0,\"returned_aircraft\":33,\"truncated\":true},"
        "\"zones\":{\"near_radius_ft\":1,\"radar_radius_ft\":1},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":1,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}");
    assert(flightview_parse_display_payload(oversized, strlen(oversized), 0, 0, &model) == FV_PARSE_ERR_BOUNDS);
}

static void test_unicode_and_extra_fields(void)
{
    const char *unicode =
        "{\"schema_version\":1,\"display\":null,\"extra\":{\"ignored\":\"value\"},\"aircraft\":[{"
        "\"icao24\":\"abc123\",\"callsign\":\"TAM1\",\"flight_display\":\"TAM 1\","
        "\"airline\":\"LATAM\",\"aircraft_type\":\"Airbus A350\",\"origin_city\":\"S\\u00e3o Paulo\","
        "\"destination_city\":\"M\\u00fcnchen\",\"altitude_ft\":1,\"distance_ft\":2}],"
        "\"counts\":{\"total_aircraft\":1,\"nearby_aircraft\":0,\"returned_aircraft\":1,\"truncated\":false},"
        "\"zones\":{\"near_radius_ft\":1,\"radar_radius_ft\":1},"
        "\"freshness\":{\"source_state_observed_at\":1,\"state_age_ms\":1,"
        "\"stale_after_ms\":1,\"is_initial\":false,\"is_stale\":false},"
        "\"health\":{\"status\":\"ok\",\"data_source\":\"mock\",\"message\":\"ok\"}}";
    flightview_model_t model;
    assert(flightview_parse_display_payload(unicode, strlen(unicode), 0, 0, &model) == FV_PARSE_OK);
    assert(strcmp(model.aircraft[0].origin_city, "São Paulo") == 0);
    assert(strcmp(model.aircraft[0].destination_city, "München") == 0);
}

static void test_age_preserved_across_old_success_and_failure(void)
{
    flightview_model_t current;
    assert(flightview_parse_display_payload(payload, strlen(payload), 10000, 0, &current) == FV_PARSE_OK);
    flightview_model_t parsed;
    assert(flightview_parse_display_payload(payload, strlen(payload), 20000, 0, &parsed) == FV_PARSE_OK);
    flightview_model_apply_success(&current, &parsed);
    assert(flightview_model_age_ms(&current, 20000) >= 11200);
    flightview_model_apply_transport(&current, FV_TRANSPORT_HTTP_ERROR, "offline", 25000);
    assert(current.valid);
    assert(current.transport_status == FV_TRANSPORT_HTTP_ERROR);
    assert(flightview_model_age_ms(&current, 25000) >= 16200);
}

static void test_radar_math_cardinals(void)
{
    flightview_radar_point_t n = flightview_radar_project(0, 5000, 5000, 0, 0, 380, 500);
    flightview_radar_point_t e = flightview_radar_project(90, 5000, 5000, 0, 0, 380, 500);
    flightview_radar_point_t s = flightview_radar_project(180, 5000, 5000, 0, 0, 380, 500);
    flightview_radar_point_t w = flightview_radar_project(270, 5000, 5000, 0, 0, 380, 500);
    assert(n.y < 250);
    assert(e.x > 190);
    assert(s.y > 250);
    assert(w.x < 190);
    assert(flightview_radar_project(0, 9000, 5000, 0, 0, 380, 500).clamped);
    assert(flightview_radar_near_ring_radius_px(2500, 5000, 380, 500) > 70);
}

static void replace_payload(char *dst, const char *from, const char *to)
{
    const char *at = strstr(payload, from);
    assert(at != NULL);
    size_t prefix = (size_t)(at - payload);
    memcpy(dst, payload, prefix);
    strcpy(dst + prefix, to);
    strcat(dst, at + strlen(from));
}

static void test_strict_json_and_metadata(void)
{
    char changed[8192];
    flightview_model_t model;
    const char *bad_numbers[] = {"+1", "01", ".1", "0x1", "1.", "1e", "1e999", "NaN"};
    for (size_t i = 0; i < sizeof(bad_numbers) / sizeof(bad_numbers[0]); i++) {
        char replacement[64];
        snprintf(replacement, sizeof(replacement), "\"schema_version\":%s", bad_numbers[i]);
        replace_payload(changed, "\"schema_version\":1", replacement);
        assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    }
    replace_payload(changed, "\"airline\":\"Delta\"", "\"airline\":\"\\udc00\"");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"airline\":\"Delta\"", "\"airline\":\"\xc0\xaf\"");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"airline\":\"Delta\"", "\"airline\":\"\\u0000hidden\"");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"airline\":\"Delta\"", "\"airline\":\"\\ud83d\\ude80\"");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) == FV_PARSE_OK);
    assert(strcmp(model.display.airline, "\xf0\x9f\x9a\x80") == 0);
    assert(flightview_parse_display_payload(payload, strlen(payload) - 1, 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"server_version\":\"test\"", "\"server_version\":\"test\",");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"is_initial\":false", "\"is_initial\":true");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"state_age_ms\":1200", "\"state_age_ms\":18446744073709551616");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"truncated\":false", "\"truncated\":true");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"velocity_kts\":210", "\"velocity_kts\":1e100");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    replace_payload(changed, "\"server_version\":\"test\"", "\"server_version\":\"0123456789012345678901234567890123456789\"");
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) == FV_PARSE_OK);

    /* The public parser accepts a length, not necessarily a terminated string. */
    size_t len = strlen(payload);
    char *unterminated = malloc(len);
    assert(unterminated != NULL);
    memcpy(unterminated, payload, len);
    assert(flightview_parse_display_payload(unterminated, len, 0, 0, &model) == FV_PARSE_OK);
    free(unterminated);
}

static void test_depth_and_saturating_age(void)
{
    char changed[8192], extra[1024] = "\"extra\":";
    for (int i = 0; i < 32; i++) strcat(extra, "[");
    strcat(extra, "0");
    for (int i = 0; i < 32; i++) strcat(extra, "]");
    strcat(extra, ",\"server_version\":\"test\"");
    replace_payload(changed, "\"server_version\":\"test\"", extra);
    flightview_model_t model;
    assert(flightview_parse_display_payload(changed, strlen(changed), 0, 0, &model) != FV_PARSE_OK);
    assert(flightview_parse_display_payload(payload, strlen(payload), 10000, UINT64_MAX, &model) == FV_PARSE_OK);
    assert(model.freshness.state_age_ms == UINT64_MAX);
    assert(flightview_model_age_ms(&model, 11000) == UINT64_MAX);
    assert(flightview_parse_display_payload(payload, strlen(payload), 10000, 0, &model) == FV_PARSE_OK);
    assert(flightview_model_age_ms(&model, 9999) == 1200);
}

int main(void)
{
    test_strict_json_and_metadata();
    test_depth_and_saturating_age();
    test_parse_rich_payload();
    test_initial_empty_payload();
    test_unknown_numbers_and_hidden_route();
    test_bounds_schema_and_strings();
    test_unicode_and_extra_fields();
    test_age_preserved_across_old_success_and_failure();
    test_radar_math_cardinals();
    puts("flightview host protocol tests passed");
    return 0;
}
