#pragma once

#include <stdbool.h>

typedef struct {
    int x;
    int y;
    bool clamped;
} flightview_radar_point_t;

flightview_radar_point_t flightview_radar_project(
    float bearing_deg,
    float distance_ft,
    float radar_radius_ft,
    int left,
    int top,
    int width,
    int height);
int flightview_radar_near_ring_radius_px(
    float near_radius_ft,
    float radar_radius_ft,
    int width,
    int height);

