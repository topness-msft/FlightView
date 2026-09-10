#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define FV_SCHEMA_VERSION 1
#define FV_MAX_AIRCRAFT 32
#define FV_MAX_LIST_ROWS 10
#define FV_HTTP_BODY_MAX_BYTES 65536

#define FV_TEXT_ICAO24 6
#define FV_TEXT_CALLSIGN 16
#define FV_TEXT_FLIGHT_DISPLAY 24
#define FV_TEXT_AIRLINE 96
#define FV_TEXT_TYPECODE 8
#define FV_TEXT_AIRCRAFT_TYPE 96
#define FV_TEXT_REGISTRATION 24
#define FV_TEXT_ROUTE 8
#define FV_TEXT_CITY 96
#define FV_TEXT_COMPASS 4
#define FV_TEXT_DIRECTION 16
#define FV_TEXT_HEALTH_MESSAGE 128
#define FV_TEXT_DATA_SOURCE 8

typedef enum {
    FV_PARSE_OK = 0,
    FV_PARSE_ERR_BODY_TOO_LARGE,
    FV_PARSE_ERR_MALFORMED_JSON,
    FV_PARSE_ERR_UNSUPPORTED_SCHEMA,
    FV_PARSE_ERR_REQUIRED_FIELD,
    FV_PARSE_ERR_BOUNDS,
    FV_PARSE_ERR_STRING_OVERFLOW,
    FV_PARSE_ERR_INVALID_VALUE,
} flightview_parse_result_t;

typedef enum {
    FV_TRANSPORT_STARTING = 0,
    FV_TRANSPORT_OK,
    FV_TRANSPORT_WIFI_DISCONNECTED,
    FV_TRANSPORT_HTTP_ERROR,
    FV_TRANSPORT_PARSE_ERROR,
} flightview_transport_status_t;

typedef struct {
    bool valid;
    float value;
} flightview_optional_float_t;

typedef struct {
    char icao24[FV_TEXT_ICAO24 + 1];
    char callsign[FV_TEXT_CALLSIGN + 1];
    char flight_display[FV_TEXT_FLIGHT_DISPLAY + 1];
    char airline[FV_TEXT_AIRLINE + 1];
    char typecode[FV_TEXT_TYPECODE + 1];
    char aircraft_type[FV_TEXT_AIRCRAFT_TYPE + 1];
    char registration[FV_TEXT_REGISTRATION + 1];
    char route_origin[FV_TEXT_ROUTE + 1];
    char route_destination[FV_TEXT_ROUTE + 1];
    char origin_city[FV_TEXT_CITY + 1];
    char destination_city[FV_TEXT_CITY + 1];
    flightview_optional_float_t altitude_ft;
    flightview_optional_float_t velocity_kts;
    flightview_optional_float_t distance_ft;
    flightview_optional_float_t vertical_rate_fpm;
    flightview_optional_float_t bearing;
    flightview_optional_float_t heading;
    char compass[FV_TEXT_COMPASS + 1];
    char direction[FV_TEXT_DIRECTION + 1];
} flightview_aircraft_t;

typedef struct {
    int total_aircraft;
    int nearby_aircraft;
    int returned_aircraft;
    bool truncated;
} flightview_counts_t;

typedef struct {
    int near_radius_ft;
    int radar_radius_ft;
} flightview_zones_t;

typedef struct {
    bool source_state_observed_at_valid;
    double source_state_observed_at;
    bool state_age_ms_valid;
    uint64_t state_age_ms;
    uint64_t stale_after_ms;
    bool is_initial;
    bool is_stale;
} flightview_freshness_t;

typedef struct {
    bool ok;
    char data_source[FV_TEXT_DATA_SOURCE + 1];
    char message[FV_TEXT_HEALTH_MESSAGE + 1];
} flightview_health_t;

typedef struct {
    bool valid;
    uint32_t schema_version;
    bool has_display;
    flightview_aircraft_t display;
    flightview_aircraft_t aircraft[FV_MAX_AIRCRAFT];
    size_t aircraft_count;
    flightview_counts_t counts;
    flightview_zones_t zones;
    flightview_freshness_t freshness;
    flightview_health_t health;
    char server_version[41];
    uint64_t received_monotonic_ms;
    uint64_t request_duration_ms;
    flightview_transport_status_t transport_status;
    char transport_message[96];
} flightview_model_t;

typedef enum {
    FV_UI_MSG_MODEL = 1,
    FV_UI_MSG_TRANSPORT = 2,
} flightview_ui_message_type_t;

typedef struct {
    flightview_ui_message_type_t type;
    flightview_model_t model;
    flightview_transport_status_t transport_status;
    char transport_message[96];
    uint64_t monotonic_ms;
} flightview_ui_message_t;

const char *flightview_parse_result_name(flightview_parse_result_t result);
void flightview_model_init(flightview_model_t *model);
flightview_parse_result_t flightview_parse_display_payload(
    const char *body,
    size_t len,
    uint64_t received_monotonic_ms,
    uint64_t request_duration_ms,
    flightview_model_t *out);
uint64_t flightview_model_age_ms(const flightview_model_t *model, uint64_t now_monotonic_ms);
void flightview_model_apply_success(flightview_model_t *current, const flightview_model_t *parsed);
void flightview_model_apply_transport(
    flightview_model_t *current,
    flightview_transport_status_t status,
    const char *message,
    uint64_t monotonic_ms);
const char *flightview_transport_status_text(flightview_transport_status_t status);
