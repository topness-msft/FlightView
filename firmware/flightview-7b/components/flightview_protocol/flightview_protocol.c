#include "flightview_protocol.h"

#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    const char *s;
    size_t len;
    size_t pos;
    unsigned depth;
} json_cursor_t;

static void model_set_transport(flightview_model_t *model, flightview_transport_status_t status, const char *message);

void flightview_model_init(flightview_model_t *model)
{
    if (model == NULL) {
        return;
    }
    memset(model, 0, sizeof(*model));
    model->schema_version = FV_SCHEMA_VERSION;
    model->transport_status = FV_TRANSPORT_STARTING;
    strcpy(model->transport_message, "Starting");
}

const char *flightview_parse_result_name(flightview_parse_result_t result)
{
    switch (result) {
    case FV_PARSE_OK: return "ok";
    case FV_PARSE_ERR_BODY_TOO_LARGE: return "body-too-large";
    case FV_PARSE_ERR_MALFORMED_JSON: return "malformed-json";
    case FV_PARSE_ERR_UNSUPPORTED_SCHEMA: return "unsupported-schema";
    case FV_PARSE_ERR_REQUIRED_FIELD: return "required-field";
    case FV_PARSE_ERR_BOUNDS: return "bounds";
    case FV_PARSE_ERR_STRING_OVERFLOW: return "string-overflow";
    case FV_PARSE_ERR_INVALID_VALUE: return "invalid-value";
    default: return "unknown";
    }
}

const char *flightview_transport_status_text(flightview_transport_status_t status)
{
    switch (status) {
    case FV_TRANSPORT_STARTING: return "starting";
    case FV_TRANSPORT_OK: return "online";
    case FV_TRANSPORT_WIFI_DISCONNECTED: return "wifi offline";
    case FV_TRANSPORT_HTTP_ERROR: return "host offline";
    case FV_TRANSPORT_PARSE_ERROR: return "bad payload";
    default: return "unknown";
    }
}

static void skip_ws(json_cursor_t *c)
{
    while (c->pos < c->len && strchr(" \t\r\n", c->s[c->pos]) != NULL && c->s[c->pos] != '\0') {
        c->pos++;
    }
}

static bool consume(json_cursor_t *c, char ch)
{
    skip_ws(c);
    if (c->pos < c->len && c->s[c->pos] == ch) {
        c->pos++;
        return true;
    }
    return false;
}

static bool match_literal(json_cursor_t *c, const char *literal)
{
    skip_ws(c);
    const size_t n = strlen(literal);
    if (c->pos + n > c->len || memcmp(c->s + c->pos, literal, n) != 0) {
        return false;
    }
    c->pos += n;
    return true;
}

static bool append_utf8(char *dst, size_t cap, size_t *out_len, unsigned codepoint)
{
    if (codepoint == 0 || (codepoint >= 0xd800 && codepoint <= 0xdfff)) {
        return false;
    }
    char tmp[4];
    size_t n = 0;
    if (codepoint <= 0x7f) {
        tmp[n++] = (char)codepoint;
    } else if (codepoint <= 0x7ff) {
        tmp[n++] = (char)(0xc0 | (codepoint >> 6));
        tmp[n++] = (char)(0x80 | (codepoint & 0x3f));
    } else if (codepoint <= 0xffff) {
        tmp[n++] = (char)(0xe0 | (codepoint >> 12));
        tmp[n++] = (char)(0x80 | ((codepoint >> 6) & 0x3f));
        tmp[n++] = (char)(0x80 | (codepoint & 0x3f));
    } else if (codepoint <= 0x10ffff) {
        tmp[n++] = (char)(0xf0 | (codepoint >> 18));
        tmp[n++] = (char)(0x80 | ((codepoint >> 12) & 0x3f));
        tmp[n++] = (char)(0x80 | ((codepoint >> 6) & 0x3f));
        tmp[n++] = (char)(0x80 | (codepoint & 0x3f));
    } else {
        return false;
    }
    if (dst != NULL && *out_len + n > cap) {
        return false;
    }
    if (dst != NULL) memcpy(dst + *out_len, tmp, n);
    *out_len += n;
    return true;
}

static bool parse_hex4(json_cursor_t *c, unsigned *out)
{
    if (c->pos + 4 > c->len) {
        return false;
    }
    unsigned value = 0;
    for (int i = 0; i < 4; i++) {
        const char ch = c->s[c->pos++];
        value <<= 4;
        if (ch >= '0' && ch <= '9') {
            value |= (unsigned)(ch - '0');
        } else if (ch >= 'a' && ch <= 'f') {
            value |= (unsigned)(10 + ch - 'a');
        } else if (ch >= 'A' && ch <= 'F') {
            value |= (unsigned)(10 + ch - 'A');
        } else {
            return false;
        }
    }
    *out = value;
    return true;
}

static flightview_parse_result_t parse_string(json_cursor_t *c, char *dst, size_t cap)
{
    skip_ws(c);
    if (c->pos >= c->len || c->s[c->pos++] != '"') {
        return FV_PARSE_ERR_MALFORMED_JSON;
    }

    size_t out_len = 0;
    while (c->pos < c->len) {
        unsigned char ch = (unsigned char)c->s[c->pos++];
        if (ch == '"') {
            if (dst != NULL) dst[out_len] = '\0';
            return FV_PARSE_OK;
        }
        if (ch == '\\') {
            if (c->pos >= c->len) {
                return FV_PARSE_ERR_MALFORMED_JSON;
            }
            ch = (unsigned char)c->s[c->pos++];
            switch (ch) {
            case '"':
            case '\\':
            case '/':
                if (!append_utf8(dst, cap, &out_len, ch)) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            case 'b':
                if (!append_utf8(dst, cap, &out_len, '\b')) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            case 'f':
                if (!append_utf8(dst, cap, &out_len, '\f')) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            case 'n':
                if (!append_utf8(dst, cap, &out_len, '\n')) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            case 'r':
                if (!append_utf8(dst, cap, &out_len, '\r')) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            case 't':
                if (!append_utf8(dst, cap, &out_len, '\t')) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            case 'u': {
                unsigned cp = 0;
                if (!parse_hex4(c, &cp)) return FV_PARSE_ERR_MALFORMED_JSON;
                if (cp >= 0xd800 && cp <= 0xdbff) {
                    if (c->pos + 6 > c->len || c->s[c->pos++] != '\\' || c->s[c->pos++] != 'u') {
                        return FV_PARSE_ERR_MALFORMED_JSON;
                    }
                    unsigned lo = 0;
                    if (!parse_hex4(c, &lo) || lo < 0xdc00 || lo > 0xdfff) {
                        return FV_PARSE_ERR_MALFORMED_JSON;
                    }
                    cp = 0x10000 + (((cp - 0xd800) << 10) | (lo - 0xdc00));
                }
                if (!append_utf8(dst, cap, &out_len, cp)) return FV_PARSE_ERR_STRING_OVERFLOW;
                break;
            }
            default:
                return FV_PARSE_ERR_MALFORMED_JSON;
            }
        } else {
            if (ch < 0x20) {
                return FV_PARSE_ERR_MALFORMED_JSON;
            }
            unsigned cp = ch;
            if (ch >= 0x80) {
                unsigned continuation, minimum;
                if (ch >= 0xc2 && ch <= 0xdf) {
                    continuation = 1; minimum = 0x80; cp = ch & 0x1f;
                } else if (ch >= 0xe0 && ch <= 0xef) {
                    continuation = 2; minimum = 0x800; cp = ch & 0x0f;
                } else if (ch >= 0xf0 && ch <= 0xf4) {
                    continuation = 3; minimum = 0x10000; cp = ch & 0x07;
                } else {
                    return FV_PARSE_ERR_MALFORMED_JSON;
                }
                for (unsigned i = 0; i < continuation; i++) {
                    if (c->pos >= c->len) return FV_PARSE_ERR_MALFORMED_JSON;
                    unsigned char next = (unsigned char)c->s[c->pos++];
                    if ((next & 0xc0) != 0x80) return FV_PARSE_ERR_MALFORMED_JSON;
                    cp = (cp << 6) | (next & 0x3f);
                }
                if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff)) {
                    return FV_PARSE_ERR_MALFORMED_JSON;
                }
            }
            if (!append_utf8(dst, cap, &out_len, cp)) return FV_PARSE_ERR_STRING_OVERFLOW;
        }
    }
    return FV_PARSE_ERR_MALFORMED_JSON;
}

static flightview_parse_result_t parse_number(json_cursor_t *c, double *out)
{
    skip_ws(c);
    if (c->pos >= c->len) {
        return FV_PARSE_ERR_MALFORMED_JSON;
    }
    size_t start = c->pos;
    if (c->s[c->pos] == '-') c->pos++;
    if (c->pos >= c->len) return FV_PARSE_ERR_MALFORMED_JSON;
    if (c->s[c->pos] == '0') {
        c->pos++;
    } else {
        if (c->s[c->pos] < '1' || c->s[c->pos] > '9') return FV_PARSE_ERR_MALFORMED_JSON;
        do { c->pos++; } while (c->pos < c->len && isdigit((unsigned char)c->s[c->pos]));
    }
    if (c->pos < c->len && c->s[c->pos] == '.') {
        c->pos++;
        size_t fraction = c->pos;
        while (c->pos < c->len && isdigit((unsigned char)c->s[c->pos])) c->pos++;
        if (fraction == c->pos) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    if (c->pos < c->len && (c->s[c->pos] == 'e' || c->s[c->pos] == 'E')) {
        c->pos++;
        if (c->pos < c->len && (c->s[c->pos] == '+' || c->s[c->pos] == '-')) c->pos++;
        size_t exponent = c->pos;
        while (c->pos < c->len && isdigit((unsigned char)c->s[c->pos])) c->pos++;
        if (exponent == c->pos) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    char token[64];
    size_t token_len = c->pos - start;
    if (token_len >= sizeof(token)) return FV_PARSE_ERR_BOUNDS;
    memcpy(token, c->s + start, token_len);
    token[token_len] = '\0';
    char *end = NULL;
    errno = 0;
    double value = strtod(token, &end);
    if (end != token + token_len || errno == ERANGE || !isfinite(value)) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    *out = value;
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_bool(json_cursor_t *c, bool *out)
{
    if (match_literal(c, "true")) {
        *out = true;
        return FV_PARSE_OK;
    }
    if (match_literal(c, "false")) {
        *out = false;
        return FV_PARSE_OK;
    }
    return FV_PARSE_ERR_REQUIRED_FIELD;
}

static flightview_parse_result_t skip_value(json_cursor_t *c);

static flightview_parse_result_t skip_string(json_cursor_t *c)
{
    return parse_string(c, NULL, 0);
}

static flightview_parse_result_t skip_array(json_cursor_t *c)
{
    if (!consume(c, '[')) {
        return FV_PARSE_ERR_MALFORMED_JSON;
    }
    skip_ws(c);
    if (consume(c, ']')) {
        return FV_PARSE_OK;
    }
    while (c->pos < c->len) {
        flightview_parse_result_t r = skip_value(c);
        if (r != FV_PARSE_OK) return r;
        skip_ws(c);
        if (consume(c, ']')) return FV_PARSE_OK;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    return FV_PARSE_ERR_MALFORMED_JSON;
}

static flightview_parse_result_t skip_object(json_cursor_t *c)
{
    if (!consume(c, '{')) {
        return FV_PARSE_ERR_MALFORMED_JSON;
    }
    skip_ws(c);
    if (consume(c, '}')) {
        return FV_PARSE_OK;
    }
    while (c->pos < c->len) {
        flightview_parse_result_t r = skip_string(c);
        if (r != FV_PARSE_OK) return r;
        if (!consume(c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;
        r = skip_value(c);
        if (r != FV_PARSE_OK) return r;
        skip_ws(c);
        if (consume(c, '}')) return FV_PARSE_OK;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    return FV_PARSE_ERR_MALFORMED_JSON;
}

static flightview_parse_result_t skip_value(json_cursor_t *c)
{
    skip_ws(c);
    if (c->pos >= c->len) return FV_PARSE_ERR_MALFORMED_JSON;
    const char ch = c->s[c->pos];
    if (ch == '"') {
        return skip_string(c);
    }
    if (ch == '{' || ch == '[') {
        if (c->depth >= 16) return FV_PARSE_ERR_BOUNDS;
        c->depth++;
        flightview_parse_result_t result = ch == '{' ? skip_object(c) : skip_array(c);
        c->depth--;
        return result;
    }
    if (match_literal(c, "true") || match_literal(c, "false") || match_literal(c, "null")) {
        return FV_PARSE_OK;
    }
    double ignored_number = 0;
    return parse_number(c, &ignored_number);
}

static flightview_parse_result_t parse_optional_float(json_cursor_t *c, flightview_optional_float_t *out)
{
    if (match_literal(c, "null")) {
        out->valid = false;
        out->value = 0.0f;
        return FV_PARSE_OK;
    }
    double value = 0;
    flightview_parse_result_t r = parse_number(c, &value);
    if (r != FV_PARSE_OK) return r;
    if (value < -1e12 || value > 1e12) return FV_PARSE_ERR_BOUNDS;
    out->valid = true;
    out->value = (float)value;
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_required_int(json_cursor_t *c, int *out)
{
    double value = 0;
    flightview_parse_result_t r = parse_number(c, &value);
    if (r != FV_PARSE_OK) return r;
    if (value < -2147483648.0 || value > 2147483647.0 || floor(value) != value) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    *out = (int)value;
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_required_u64(json_cursor_t *c, uint64_t *out)
{
    double value = 0;
    flightview_parse_result_t r = parse_number(c, &value);
    if (r != FV_PARSE_OK) return r;
    if (value < 0.0 || value > 9007199254740991.0 || floor(value) != value) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    *out = (uint64_t)value;
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_optional_epoch(json_cursor_t *c, flightview_freshness_t *fresh)
{
    if (match_literal(c, "null")) {
        fresh->source_state_observed_at_valid = false;
        fresh->source_state_observed_at = 0;
        return FV_PARSE_OK;
    }
    double value = 0;
    flightview_parse_result_t r = parse_number(c, &value);
    if (r != FV_PARSE_OK) return r;
    if (value < 0.0) return FV_PARSE_ERR_INVALID_VALUE;
    fresh->source_state_observed_at_valid = true;
    fresh->source_state_observed_at = value;
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_optional_age_ms(json_cursor_t *c, flightview_freshness_t *fresh)
{
    if (match_literal(c, "null")) {
        fresh->state_age_ms_valid = false;
        fresh->state_age_ms = 0;
        return FV_PARSE_OK;
    }
    uint64_t value = 0;
    flightview_parse_result_t r = parse_required_u64(c, &value);
    if (r != FV_PARSE_OK) return r;
    fresh->state_age_ms_valid = true;
    fresh->state_age_ms = value;
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_aircraft(json_cursor_t *c, flightview_aircraft_t *aircraft)
{
    memset(aircraft, 0, sizeof(*aircraft));
    if (!consume(c, '{')) return FV_PARSE_ERR_MALFORMED_JSON;
    skip_ws(c);
    if (consume(c, '}')) return FV_PARSE_OK;

    while (c->pos < c->len) {
        char key[64];
        flightview_parse_result_t r = parse_string(c, key, sizeof(key) - 1);
        if (r != FV_PARSE_OK) return r;
        if (!consume(c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;

        if (strcmp(key, "icao24") == 0) r = parse_string(c, aircraft->icao24, FV_TEXT_ICAO24);
        else if (strcmp(key, "callsign") == 0) r = parse_string(c, aircraft->callsign, FV_TEXT_CALLSIGN);
        else if (strcmp(key, "flight_display") == 0) r = parse_string(c, aircraft->flight_display, FV_TEXT_FLIGHT_DISPLAY);
        else if (strcmp(key, "airline") == 0) r = parse_string(c, aircraft->airline, FV_TEXT_AIRLINE);
        else if (strcmp(key, "typecode") == 0) r = parse_string(c, aircraft->typecode, FV_TEXT_TYPECODE);
        else if (strcmp(key, "aircraft_type") == 0) r = parse_string(c, aircraft->aircraft_type, FV_TEXT_AIRCRAFT_TYPE);
        else if (strcmp(key, "registration") == 0) r = parse_string(c, aircraft->registration, FV_TEXT_REGISTRATION);
        else if (strcmp(key, "route_origin") == 0) r = parse_string(c, aircraft->route_origin, FV_TEXT_ROUTE);
        else if (strcmp(key, "route_destination") == 0) r = parse_string(c, aircraft->route_destination, FV_TEXT_ROUTE);
        else if (strcmp(key, "origin_city") == 0) r = parse_string(c, aircraft->origin_city, FV_TEXT_CITY);
        else if (strcmp(key, "destination_city") == 0) r = parse_string(c, aircraft->destination_city, FV_TEXT_CITY);
        else if (strcmp(key, "altitude_ft") == 0) r = parse_optional_float(c, &aircraft->altitude_ft);
        else if (strcmp(key, "velocity_kts") == 0) r = parse_optional_float(c, &aircraft->velocity_kts);
        else if (strcmp(key, "distance_ft") == 0) r = parse_optional_float(c, &aircraft->distance_ft);
        else if (strcmp(key, "vertical_rate_fpm") == 0) r = parse_optional_float(c, &aircraft->vertical_rate_fpm);
        else if (strcmp(key, "bearing") == 0) r = parse_optional_float(c, &aircraft->bearing);
        else if (strcmp(key, "heading") == 0) r = parse_optional_float(c, &aircraft->heading);
        else if (strcmp(key, "compass") == 0) r = parse_string(c, aircraft->compass, FV_TEXT_COMPASS);
        else if (strcmp(key, "direction") == 0) r = parse_string(c, aircraft->direction, FV_TEXT_DIRECTION);
        else r = skip_value(c);
        if (r != FV_PARSE_OK) return r;

        skip_ws(c);
        if (consume(c, '}')) return FV_PARSE_OK;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    return FV_PARSE_ERR_MALFORMED_JSON;
}

static flightview_parse_result_t parse_aircraft_array(json_cursor_t *c, flightview_model_t *model)
{
    if (!consume(c, '[')) return FV_PARSE_ERR_MALFORMED_JSON;
    skip_ws(c);
    if (consume(c, ']')) return FV_PARSE_OK;

    while (c->pos < c->len) {
        if (model->aircraft_count >= FV_MAX_AIRCRAFT) {
            return FV_PARSE_ERR_BOUNDS;
        }
        flightview_parse_result_t r = parse_aircraft(c, &model->aircraft[model->aircraft_count]);
        if (r != FV_PARSE_OK) return r;
        model->aircraft_count++;
        skip_ws(c);
        if (consume(c, ']')) return FV_PARSE_OK;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    return FV_PARSE_ERR_MALFORMED_JSON;
}

static flightview_parse_result_t parse_counts(json_cursor_t *c, flightview_counts_t *counts)
{
    bool have_total = false, have_nearby = false, have_returned = false, have_truncated = false;
    if (!consume(c, '{')) return FV_PARSE_ERR_MALFORMED_JSON;
    while (c->pos < c->len) {
        skip_ws(c);
        if (consume(c, '}')) break;
        char key[64];
        flightview_parse_result_t r = parse_string(c, key, sizeof(key) - 1);
        if (r != FV_PARSE_OK) return r;
        if (!consume(c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;
        if (strcmp(key, "total_aircraft") == 0) {
            r = parse_required_int(c, &counts->total_aircraft);
            have_total = true;
        } else if (strcmp(key, "nearby_aircraft") == 0) {
            r = parse_required_int(c, &counts->nearby_aircraft);
            have_nearby = true;
        } else if (strcmp(key, "returned_aircraft") == 0) {
            r = parse_required_int(c, &counts->returned_aircraft);
            have_returned = true;
        } else if (strcmp(key, "truncated") == 0) {
            r = parse_bool(c, &counts->truncated);
            have_truncated = true;
        } else {
            r = skip_value(c);
        }
        if (r != FV_PARSE_OK) return r;
        skip_ws(c);
        if (consume(c, '}')) break;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    if (!have_total || !have_nearby || !have_returned || !have_truncated) return FV_PARSE_ERR_REQUIRED_FIELD;
    if (counts->total_aircraft < 0 ||
        counts->nearby_aircraft < 0 ||
        counts->returned_aircraft < 0 ||
        counts->returned_aircraft > FV_MAX_AIRCRAFT ||
        counts->returned_aircraft > counts->total_aircraft ||
        counts->nearby_aircraft > counts->total_aircraft) {
        return FV_PARSE_ERR_BOUNDS;
    }
    if (counts->truncated != (counts->returned_aircraft < counts->total_aircraft)) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_zones(json_cursor_t *c, flightview_zones_t *zones)
{
    bool have_near = false, have_radar = false;
    if (!consume(c, '{')) return FV_PARSE_ERR_MALFORMED_JSON;
    while (c->pos < c->len) {
        skip_ws(c);
        if (consume(c, '}')) break;
        char key[64];
        flightview_parse_result_t r = parse_string(c, key, sizeof(key) - 1);
        if (r != FV_PARSE_OK) return r;
        if (!consume(c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;
        if (strcmp(key, "near_radius_ft") == 0) {
            r = parse_required_int(c, &zones->near_radius_ft);
            have_near = true;
        } else if (strcmp(key, "radar_radius_ft") == 0) {
            r = parse_required_int(c, &zones->radar_radius_ft);
            have_radar = true;
        } else {
            r = skip_value(c);
        }
        if (r != FV_PARSE_OK) return r;
        skip_ws(c);
        if (consume(c, '}')) break;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    if (!have_near || !have_radar ||
        zones->near_radius_ft <= 0 ||
        zones->radar_radius_ft <= 0) {
        return FV_PARSE_ERR_REQUIRED_FIELD;
    }
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_freshness(json_cursor_t *c, flightview_freshness_t *fresh)
{
    bool have_observed = false, have_age = false, have_stale_after = false, have_initial = false, have_stale = false;
    if (!consume(c, '{')) return FV_PARSE_ERR_MALFORMED_JSON;
    while (c->pos < c->len) {
        skip_ws(c);
        if (consume(c, '}')) break;
        char key[64];
        flightview_parse_result_t r = parse_string(c, key, sizeof(key) - 1);
        if (r != FV_PARSE_OK) return r;
        if (!consume(c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;
        if (strcmp(key, "source_state_observed_at") == 0) {
            r = parse_optional_epoch(c, fresh);
            have_observed = true;
        } else if (strcmp(key, "state_age_ms") == 0) {
            r = parse_optional_age_ms(c, fresh);
            have_age = true;
        } else if (strcmp(key, "stale_after_ms") == 0) {
            r = parse_required_u64(c, &fresh->stale_after_ms);
            have_stale_after = true;
        } else if (strcmp(key, "is_initial") == 0) {
            r = parse_bool(c, &fresh->is_initial);
            have_initial = true;
        } else if (strcmp(key, "is_stale") == 0) {
            r = parse_bool(c, &fresh->is_stale);
            have_stale = true;
        } else {
            r = skip_value(c);
        }
        if (r != FV_PARSE_OK) return r;
        skip_ws(c);
        if (consume(c, '}')) break;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    if (!have_observed || !have_age || !have_stale_after || !have_initial || !have_stale) {
        return FV_PARSE_ERR_REQUIRED_FIELD;
    }
    if (!fresh->is_initial && (!fresh->source_state_observed_at_valid || !fresh->state_age_ms_valid)) {
        return FV_PARSE_ERR_REQUIRED_FIELD;
    }
    if (fresh->is_initial && (fresh->source_state_observed_at_valid || fresh->state_age_ms_valid || !fresh->is_stale)) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    if (fresh->stale_after_ms == 0) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    return FV_PARSE_OK;
}

static flightview_parse_result_t parse_health(json_cursor_t *c, flightview_health_t *health)
{
    bool have_status = false, have_source = false, have_message = false;
    if (!consume(c, '{')) return FV_PARSE_ERR_MALFORMED_JSON;
    while (c->pos < c->len) {
        skip_ws(c);
        if (consume(c, '}')) break;
        char key[64];
        flightview_parse_result_t r = parse_string(c, key, sizeof(key) - 1);
        if (r != FV_PARSE_OK) return r;
        if (!consume(c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;
        if (strcmp(key, "status") == 0) {
            char status[8] = {0};
            r = parse_string(c, status, sizeof(status) - 1);
            health->ok = strcmp(status, "ok") == 0;
            if (!health->ok && strcmp(status, "error") != 0) return FV_PARSE_ERR_INVALID_VALUE;
            have_status = true;
        } else if (strcmp(key, "data_source") == 0) {
            r = parse_string(c, health->data_source, FV_TEXT_DATA_SOURCE);
            if (strcmp(health->data_source, "rtlsdr") != 0 &&
                strcmp(health->data_source, "opensky") != 0 &&
                strcmp(health->data_source, "mock") != 0 &&
                strcmp(health->data_source, "unknown") != 0) {
                return FV_PARSE_ERR_INVALID_VALUE;
            }
            have_source = true;
        } else if (strcmp(key, "message") == 0) {
            r = parse_string(c, health->message, FV_TEXT_HEALTH_MESSAGE);
            have_message = true;
        } else {
            r = skip_value(c);
        }
        if (r != FV_PARSE_OK) return r;
        skip_ws(c);
        if (consume(c, '}')) break;
        if (!consume(c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    return (have_status && have_source && have_message) ? FV_PARSE_OK : FV_PARSE_ERR_REQUIRED_FIELD;
}

flightview_parse_result_t flightview_parse_display_payload(
    const char *body,
    size_t len,
    uint64_t received_monotonic_ms,
    uint64_t request_duration_ms,
    flightview_model_t *out)
{
    if (body == NULL || out == NULL) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    if (len > FV_HTTP_BODY_MAX_BYTES) {
        return FV_PARSE_ERR_BODY_TOO_LARGE;
    }

    flightview_model_init(out);
    json_cursor_t c = {.s = body, .len = len, .pos = 0};
    /* Validate nesting, termination and JSON grammar before projecting fields. */
    flightview_parse_result_t syntax = skip_value(&c);
    if (syntax != FV_PARSE_OK) return syntax;
    skip_ws(&c);
    if (c.pos != c.len) return FV_PARSE_ERR_MALFORMED_JSON;
    c.pos = 0;
    bool have_schema = false, have_display = false, have_aircraft = false;
    bool have_counts = false, have_zones = false, have_freshness = false, have_health = false;

    if (!consume(&c, '{')) return FV_PARSE_ERR_MALFORMED_JSON;
    while (c.pos < c.len) {
        skip_ws(&c);
        if (consume(&c, '}')) break;
        char key[64];
        flightview_parse_result_t r = parse_string(&c, key, sizeof(key) - 1);
        if (r != FV_PARSE_OK) return r;
        if (!consume(&c, ':')) return FV_PARSE_ERR_MALFORMED_JSON;

        if (strcmp(key, "schema_version") == 0) {
            uint64_t schema = 0;
            r = parse_required_u64(&c, &schema);
            if (r != FV_PARSE_OK) return r;
            if (schema != FV_SCHEMA_VERSION) return FV_PARSE_ERR_UNSUPPORTED_SCHEMA;
            out->schema_version = schema;
            have_schema = true;
        } else if (strcmp(key, "display") == 0) {
            if (match_literal(&c, "null")) {
                out->has_display = false;
                r = FV_PARSE_OK;
            } else {
                out->has_display = true;
                r = parse_aircraft(&c, &out->display);
            }
            have_display = true;
        } else if (strcmp(key, "aircraft") == 0) {
            r = parse_aircraft_array(&c, out);
            have_aircraft = true;
        } else if (strcmp(key, "counts") == 0) {
            r = parse_counts(&c, &out->counts);
            have_counts = true;
        } else if (strcmp(key, "zones") == 0) {
            r = parse_zones(&c, &out->zones);
            have_zones = true;
        } else if (strcmp(key, "freshness") == 0) {
            r = parse_freshness(&c, &out->freshness);
            have_freshness = true;
        } else if (strcmp(key, "health") == 0) {
            r = parse_health(&c, &out->health);
            have_health = true;
        } else if (strcmp(key, "server_version") == 0) {
            if (match_literal(&c, "null")) {
                out->server_version[0] = '\0';
                r = FV_PARSE_OK;
            } else {
                r = parse_string(&c, out->server_version, sizeof(out->server_version) - 1);
            }
        } else {
            r = skip_value(&c);
        }
        if (r != FV_PARSE_OK) return r;
        skip_ws(&c);
        if (consume(&c, '}')) break;
        if (!consume(&c, ',')) return FV_PARSE_ERR_MALFORMED_JSON;
    }
    skip_ws(&c);
    if (c.pos != c.len) return FV_PARSE_ERR_MALFORMED_JSON;

    if (!have_schema || !have_display || !have_aircraft || !have_counts ||
        !have_zones || !have_freshness || !have_health) {
        return FV_PARSE_ERR_REQUIRED_FIELD;
    }
    if ((int)out->aircraft_count != out->counts.returned_aircraft) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    if (out->has_display != (out->counts.nearby_aircraft > 0) ||
        (out->freshness.is_initial && out->counts.total_aircraft != 0)) {
        return FV_PARSE_ERR_INVALID_VALUE;
    }
    out->received_monotonic_ms = received_monotonic_ms;
    out->request_duration_ms = request_duration_ms;
    if (out->freshness.state_age_ms_valid) {
        out->freshness.state_age_ms = UINT64_MAX - out->freshness.state_age_ms < request_duration_ms
            ? UINT64_MAX : out->freshness.state_age_ms + request_duration_ms;
    }
    out->valid = true;
    model_set_transport(out, FV_TRANSPORT_OK, "HTTP OK");
    return FV_PARSE_OK;
}

uint64_t flightview_model_age_ms(const flightview_model_t *model, uint64_t now_monotonic_ms)
{
    if (model == NULL || !model->valid || !model->freshness.state_age_ms_valid) {
        return 0;
    }
    uint64_t elapsed = now_monotonic_ms > model->received_monotonic_ms
        ? now_monotonic_ms - model->received_monotonic_ms : 0;
    if (UINT64_MAX - model->freshness.state_age_ms < elapsed) {
        return UINT64_MAX;
    }
    return model->freshness.state_age_ms + elapsed;
}

void flightview_model_apply_success(flightview_model_t *current, const flightview_model_t *parsed)
{
    if (current == NULL || parsed == NULL) {
        return;
    }
    uint64_t previous_age = flightview_model_age_ms(current, parsed->received_monotonic_ms);
    bool same_observation = current->valid && parsed->freshness.source_state_observed_at_valid &&
        current->freshness.source_state_observed_at_valid &&
        fabs(parsed->freshness.source_state_observed_at - current->freshness.source_state_observed_at) < 0.001;
    *current = *parsed;
    if (same_observation && current->freshness.state_age_ms_valid && current->freshness.state_age_ms < previous_age) {
        current->freshness.state_age_ms = previous_age;
        current->received_monotonic_ms = parsed->received_monotonic_ms;
    }
    model_set_transport(current, FV_TRANSPORT_OK, "HTTP OK");
}

void flightview_model_apply_transport(
    flightview_model_t *current,
    flightview_transport_status_t status,
    const char *message,
    uint64_t monotonic_ms)
{
    if (current == NULL) {
        return;
    }
    if (current->valid && current->freshness.state_age_ms_valid) {
        current->freshness.state_age_ms = flightview_model_age_ms(current, monotonic_ms);
        current->received_monotonic_ms = monotonic_ms;
    }
    model_set_transport(current, status, message);
}

static void model_set_transport(flightview_model_t *model, flightview_transport_status_t status, const char *message)
{
    model->transport_status = status;
    if (message == NULL || message[0] == '\0') {
        snprintf(model->transport_message, sizeof(model->transport_message), "%s", flightview_transport_status_text(status));
    } else {
        snprintf(model->transport_message, sizeof(model->transport_message), "%s", message);
    }
}
