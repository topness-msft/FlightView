#include "flightview_radar.h"

#include <math.h>

static float clampf(float value, float min_value, float max_value)
{
    if (value < min_value) {
        return min_value;
    }
    if (value > max_value) {
        return max_value;
    }
    return value;
}

flightview_radar_point_t flightview_radar_project(
    float bearing_deg,
    float distance_ft,
    float radar_radius_ft,
    int left,
    int top,
    int width,
    int height)
{
    const float cx = (float)left + ((float)width / 2.0f);
    const float cy = (float)top + ((float)height / 2.0f);
    const float scope_radius = ((float)((width < height) ? width : height) / 2.0f) - 22.0f;
    const float safe_radar_radius = radar_radius_ft > 1.0f ? radar_radius_ft : 1.0f;
    const float ratio = clampf(distance_ft / safe_radar_radius, 0.0f, 1.0f);
    const float radians = bearing_deg * 3.14159265358979323846f / 180.0f;
    const float r = ratio * scope_radius;
    flightview_radar_point_t point = {
        .x = (int)lroundf(cx + (r * sinf(radians))),
        .y = (int)lroundf(cy - (r * cosf(radians))),
        .clamped = distance_ft > safe_radar_radius,
    };
    return point;
}

int flightview_radar_near_ring_radius_px(
    float near_radius_ft,
    float radar_radius_ft,
    int width,
    int height)
{
    const float scope_radius = ((float)((width < height) ? width : height) / 2.0f) - 22.0f;
    const float safe_radar_radius = radar_radius_ft > 1.0f ? radar_radius_ft : 1.0f;
    return (int)lroundf(scope_radius * clampf(near_radius_ft / safe_radar_radius, 0.0f, 1.0f));
}

