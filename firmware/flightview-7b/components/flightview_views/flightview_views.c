#include "flightview_views.h"

#include <inttypes.h>
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "esp_timer.h"
#include "esp_lv_adapter.h"
#include "flightview_protocol.h"
#include "flightview_radar.h"
#include "flightview_fonts.h"
#include "lvgl.h"

#if !LV_USE_FONT_COMPRESSED
#error "FlightView detail fonts require CONFIG_LV_USE_FONT_COMPRESSED=y"
#endif

#define C_MD_BG 0x0F172A
#define C_MD_BG_DARK 0x0B1120
#define C_MD_SURFACE 0x1E293B
#define C_MD_BORDER 0x334155
#define C_MD_TEXT 0xF1F5F9
#define C_MD_DIM 0x94A3B8
#define C_MD_MUTED 0x64748B
#define C_MD_BLUE 0x3B82F6
#define C_MD_BLUE_BRIGHT 0x60A5FA
#define C_LHR_YELLOW 0xFECB00
#define C_LHR_BLACK 0x1A1A1A
#define C_STATUS_OK 0x34D399
#define C_STATUS_WARN 0xF0C850
#define C_STATUS_ERR 0xFB7185

typedef struct {
    QueueHandle_t queue;
    flightview_model_t model;
    lv_obj_t *root;
    lv_obj_t *multi;
    lv_obj_t *detail;
    lv_obj_t *startup;
    lv_obj_t *active_screen;
    lv_obj_t *status_bar;
    lv_obj_t *status_dot;
    lv_obj_t *status_text;
    uint32_t status_color;
    lv_obj_t *multi_count;
    lv_obj_t *radar;
    lv_obj_t *near_ring;
    lv_obj_t *blips[FV_MAX_AIRCRAFT];
    lv_obj_t *headings[FV_MAX_AIRCRAFT];
    lv_point_t heading_points[FV_MAX_AIRCRAFT][2];
    lv_obj_t *blip_labels[FV_MAX_AIRCRAFT];
    lv_obj_t *list_rows[FV_MAX_LIST_ROWS];
    lv_obj_t *list_text[FV_MAX_LIST_ROWS][4];
    lv_obj_t *empty_label;
    lv_obj_t *detail_badge;
    lv_obj_t *detail_near;
    lv_obj_t *detail_airline;
    lv_obj_t *detail_flight;
    lv_obj_t *detail_typecode;
    lv_obj_t *detail_type;
    lv_obj_t *detail_reg;
    lv_obj_t *detail_route;
    lv_obj_t *detail_origin;
    lv_obj_t *detail_origin_city;
    lv_obj_t *detail_dest;
    lv_obj_t *detail_dest_city;
    lv_obj_t *detail_stats[4];
    lv_obj_t *detail_stat_boxes[4];
    lv_obj_t *detail_footer;
    lv_obj_t *detail_heading;
    bool detail_layout_set;
    bool detail_has_route;
    const lv_font_t *detail_carrier_font;
} flightview_views_t;

static flightview_views_t g_views;
static const char *TAG = "fv_views";

static void set_text(lv_obj_t *label, const char *text)
{
    const char *value = (text != NULL && text[0] != '\0') ? text : "-";
    if (strcmp(lv_label_get_text(label), value) != 0) {
        lv_label_set_text(label, value);
    }
}

static const char *aircraft_name(const flightview_aircraft_t *a)
{
    if (a->flight_display[0] != '\0') return a->flight_display;
    if (a->callsign[0] != '\0') return a->callsign;
    if (a->icao24[0] != '\0') return a->icao24;
    return "-";
}

static void format_opt(char *dst, size_t dst_len, flightview_optional_float_t v, const char *unit)
{
    if (!v.valid) {
        snprintf(dst, dst_len, "-");
        return;
    }
    char digits[32], grouped[48];
    snprintf(digits, sizeof(digits), "%.0f", (double)v.value);
    size_t length = strlen(digits), used = 0;
    size_t first_digit = digits[0] == '-' ? 1 : 0;
    for (size_t i = 0; i < length; i++) {
        if (i > first_digit && (length - i) % 3 == 0) grouped[used++] = ',';
        grouped[used++] = digits[i];
    }
    grouped[used] = '\0';
    snprintf(dst, dst_len, "%s%s%s", grouped, unit && unit[0] ? " " : "", unit ? unit : "");
}

static void format_signed(char *dst, size_t dst_len, flightview_optional_float_t v)
{
    if (!v.valid) {
        snprintf(dst, dst_len, "-");
        return;
    }
    snprintf(dst, dst_len, "%+.0f", (double)v.value);
}

static bool same_ascii_text(const char *left, const char *right)
{
    while (*left && *right) {
        if (tolower((unsigned char)*left++) != tolower((unsigned char)*right++)) return false;
    }
    return *left == *right;
}

static void short_airline(char *dst, size_t capacity, const char *airline)
{
    snprintf(dst, capacity, "%s", airline[0] ? airline : "Unknown");
    size_t length = strlen(dst);
    while (length && dst[length - 1] == ' ') dst[--length] = '\0';
    const char *suffixes[] = {" Airlines", " Airline", " Air Lines", " Air Line"};
    for (size_t i = 0; i < sizeof(suffixes) / sizeof(suffixes[0]); i++) {
        size_t suffix_length = strlen(suffixes[i]);
        if (length > suffix_length && same_ascii_text(dst + length - suffix_length, suffixes[i])) {
            dst[length - suffix_length] = '\0';
            break;
        }
    }
}

static lv_obj_t *plane_mark(lv_obj_t *parent, uint32_t color)
{
    static const lv_point_t points[] = {
        {16, 3}, {18, 13}, {27, 19}, {27, 22}, {18, 18},
        {18, 25}, {22, 28}, {16, 26}, {10, 28}, {14, 25},
        {14, 18}, {5, 22}, {5, 19}, {14, 13}, {16, 3},
    };
    lv_obj_t *plane = lv_line_create(parent);
    lv_line_set_points(plane, points, sizeof(points) / sizeof(points[0]));
    lv_obj_set_style_line_color(plane, lv_color_hex(color), 0);
    lv_obj_set_style_line_width(plane, 2, 0);
    return plane;
}

static uint64_t now_ms(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000);
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, uint32_t color)
{
    lv_obj_t *obj = lv_label_create(parent);
    lv_obj_set_style_text_font(obj, font, 0);
    lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
    lv_label_set_long_mode(obj, LV_LABEL_LONG_DOT);
    return obj;
}

static void style_panel(lv_obj_t *obj, uint32_t bg, uint32_t border, int radius)
{
    lv_obj_set_style_bg_color(obj, lv_color_hex(bg), 0);
    lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(obj, lv_color_hex(border), 0);
    lv_obj_set_style_border_width(obj, 1, 0);
    lv_obj_set_style_radius(obj, radius, 0);
}

static lv_obj_t *make_status_bar(lv_obj_t *root)
{
    lv_obj_t *bar = lv_obj_create(root);
    lv_obj_set_style_pad_all(bar, 0, 0);
    lv_obj_set_style_radius(bar, 0, 0);
    lv_obj_set_size(bar, 1024, 30);
    lv_obj_align(bar, LV_ALIGN_TOP_LEFT, 0, 0);
    lv_obj_set_style_bg_color(bar, lv_color_hex(C_MD_BG_DARK), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(bar, 0, 0);
    lv_obj_clear_flag(bar, LV_OBJ_FLAG_SCROLLABLE);

    g_views.status_dot = lv_obj_create(bar);
    lv_obj_set_size(g_views.status_dot, 10, 10);
    lv_obj_align(g_views.status_dot, LV_ALIGN_LEFT_MID, 18, 0);
    lv_obj_set_style_radius(g_views.status_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_border_width(g_views.status_dot, 0, 0);
    lv_obj_set_style_bg_color(g_views.status_dot, lv_color_hex(C_STATUS_WARN), 0);

    g_views.status_text = label(bar, &lv_font_montserrat_14, C_MD_DIM);
    lv_obj_set_width(g_views.status_text, 940);
    lv_obj_align(g_views.status_text, LV_ALIGN_LEFT_MID, 38, 0);
    lv_label_set_text(g_views.status_text, "Starting");
    return bar;
}

static void create_multi(lv_obj_t *root)
{
    g_views.multi = lv_obj_create(root);
    lv_obj_set_style_pad_all(g_views.multi, 0, 0);
    lv_obj_set_style_radius(g_views.multi, 0, 0);
    lv_obj_set_size(g_views.multi, 1024, 570);
    lv_obj_align(g_views.multi, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    lv_obj_set_style_bg_color(g_views.multi, lv_color_hex(C_MD_BG), 0);
    lv_obj_set_style_bg_opa(g_views.multi, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_views.multi, 0, 0);
    lv_obj_clear_flag(g_views.multi, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *title = label(g_views.multi, &lv_font_montserrat_18, C_MD_DIM);
    lv_label_set_text(title, "FlightView radar");
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 28, 14);

    g_views.multi_count = label(g_views.multi, &lv_font_montserrat_16, C_MD_MUTED);
    lv_obj_set_width(g_views.multi_count, 260);
    lv_obj_align(g_views.multi_count, LV_ALIGN_TOP_RIGHT, -28, 16);

    g_views.radar = lv_obj_create(g_views.multi);
    lv_obj_set_size(g_views.radar, 380, 500);
    lv_obj_align(g_views.radar, LV_ALIGN_BOTTOM_LEFT, 28, -20);
    style_panel(g_views.radar, C_MD_BG_DARK, C_MD_BORDER, 10);
    lv_obj_set_style_pad_all(g_views.radar, 0, 0);
    lv_obj_set_style_border_width(g_views.radar, 0, 0);
    lv_obj_clear_flag(g_views.radar, LV_OBJ_FLAG_SCROLLABLE);

    for (int i = 0; i < 3; i++) {
        lv_obj_t *ring = lv_obj_create(g_views.radar);
        int size = (i + 1) * 112;
        lv_obj_set_size(ring, size, size);
        lv_obj_center(ring);
        lv_obj_set_style_radius(ring, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(ring, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_color(ring, lv_color_hex(C_MD_BLUE), 0);
        lv_obj_set_style_border_opa(ring, LV_OPA_20, 0);
        lv_obj_set_style_border_width(ring, 1, 0);
    }

    static const lv_point_t cross_h[] = {{22, 250}, {358, 250}};
    static const lv_point_t cross_v[] = {{190, 82}, {190, 418}};
    lv_obj_t *horizontal = lv_line_create(g_views.radar);
    lv_obj_t *vertical = lv_line_create(g_views.radar);
    lv_line_set_points(horizontal, cross_h, 2);
    lv_line_set_points(vertical, cross_v, 2);
    lv_obj_set_style_line_color(horizontal, lv_color_hex(C_MD_BORDER), 0);
    lv_obj_set_style_line_color(vertical, lv_color_hex(C_MD_BORDER), 0);
    lv_obj_set_style_line_width(horizontal, 1, 0);
    lv_obj_set_style_line_width(vertical, 1, 0);

    g_views.near_ring = lv_obj_create(g_views.radar);
    lv_obj_set_style_radius(g_views.near_ring, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(g_views.near_ring, lv_color_hex(C_MD_BLUE), 0);
    lv_obj_set_style_bg_opa(g_views.near_ring, LV_OPA_10, 0);
    lv_obj_set_style_border_color(g_views.near_ring, lv_color_hex(C_MD_BLUE_BRIGHT), 0);
    lv_obj_set_style_border_opa(g_views.near_ring, LV_OPA_60, 0);
    lv_obj_set_style_border_width(g_views.near_ring, 1, 0);

    const char *dirs[] = {"N", "E", "S", "W"};
    const lv_align_t aligns[] = {LV_ALIGN_TOP_MID, LV_ALIGN_RIGHT_MID, LV_ALIGN_BOTTOM_MID, LV_ALIGN_LEFT_MID};
    const int xo[] = {0, -8, 0, 8};
    const int yo[] = {8, 0, -8, 0};
    for (int i = 0; i < 4; i++) {
        lv_obj_t *d = label(g_views.radar, &lv_font_montserrat_12, C_MD_MUTED);
        lv_label_set_text(d, dirs[i]);
        lv_obj_align(d, aligns[i], xo[i], yo[i]);
    }

    lv_obj_t *home = lv_obj_create(g_views.radar);
    lv_obj_set_size(home, 8, 8);
    lv_obj_center(home);
    lv_obj_set_style_radius(home, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(home, lv_color_hex(C_MD_BLUE), 0);
    lv_obj_set_style_border_width(home, 0, 0);

    for (int i = 0; i < FV_MAX_AIRCRAFT; i++) {
        g_views.blips[i] = lv_obj_create(g_views.radar);
        lv_obj_set_size(g_views.blips[i], 12, 12);
        lv_obj_set_style_radius(g_views.blips[i], LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(g_views.blips[i], lv_color_hex(C_MD_BLUE_BRIGHT), 0);
        lv_obj_set_style_border_width(g_views.blips[i], 0, 0);
        g_views.blip_labels[i] = label(g_views.radar, &lv_font_montserrat_12, C_MD_DIM);
        g_views.headings[i] = lv_line_create(g_views.radar);
        lv_obj_set_style_line_color(g_views.headings[i], lv_color_hex(C_MD_BLUE_BRIGHT), 0);
        lv_obj_set_style_line_width(g_views.headings[i], 3, 0);
        lv_obj_add_flag(g_views.headings[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_set_width(g_views.blip_labels[i], 95);
        lv_obj_add_flag(g_views.blips[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(g_views.blip_labels[i], LV_OBJ_FLAG_HIDDEN);
    }

    lv_obj_t *list = lv_obj_create(g_views.multi);
    lv_obj_set_style_pad_all(list, 0, 0);
    lv_obj_set_size(list, 560, 500);
    lv_obj_align(list, LV_ALIGN_BOTTOM_RIGHT, -28, -20);
    lv_obj_set_style_bg_opa(list, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(list, 0, 0);
    lv_obj_clear_flag(list, LV_OBJ_FLAG_SCROLLABLE);

    g_views.empty_label = label(list, &lv_font_montserrat_20, C_MD_MUTED);
    lv_label_set_text(g_views.empty_label, "No aircraft detected");
    lv_obj_center(g_views.empty_label);

    for (int i = 0; i < FV_MAX_LIST_ROWS; i++) {
        lv_obj_t *row = lv_obj_create(list);
        g_views.list_rows[i] = row;
        lv_obj_set_size(row, 548, 43);
        lv_obj_align(row, LV_ALIGN_TOP_LEFT, 0, i * 49);
        style_panel(row, C_MD_SURFACE, C_MD_BORDER, 6);
        lv_obj_set_style_pad_all(row, 0, 0);
        lv_obj_clear_flag(row, LV_OBJ_FLAG_SCROLLABLE);
        g_views.list_text[i][0] = label(row, &lv_font_montserrat_18, C_MD_BLUE_BRIGHT);
        lv_obj_set_width(g_views.list_text[i][0], 120);
        lv_obj_align(g_views.list_text[i][0], LV_ALIGN_LEFT_MID, 12, -7);
        g_views.list_text[i][1] = label(row, &lv_font_montserrat_14, C_MD_DIM);
        lv_obj_set_width(g_views.list_text[i][1], 180);
        lv_obj_align(g_views.list_text[i][1], LV_ALIGN_LEFT_MID, 12, 11);
        g_views.list_text[i][2] = label(row, &lv_font_montserrat_16, C_MD_TEXT);
        lv_obj_set_width(g_views.list_text[i][2], 175);
        lv_obj_align(g_views.list_text[i][2], LV_ALIGN_CENTER, 15, 0);
        g_views.list_text[i][3] = label(row, &lv_font_montserrat_14, C_MD_DIM);
        lv_obj_set_width(g_views.list_text[i][3], 120);
        lv_obj_set_height(g_views.list_text[i][3], 36);
        lv_label_set_long_mode(g_views.list_text[i][3], LV_LABEL_LONG_CLIP);
        lv_obj_align(g_views.list_text[i][3], LV_ALIGN_RIGHT_MID, -10, 0);
        lv_obj_add_flag(row, LV_OBJ_FLAG_HIDDEN);
    }
}

static void create_detail(lv_obj_t *root)
{
    g_views.detail = lv_obj_create(root);
    lv_obj_set_style_pad_all(g_views.detail, 0, 0);
    lv_obj_set_style_radius(g_views.detail, 0, 0);
    lv_obj_set_size(g_views.detail, 1024, 570);
    lv_obj_align(g_views.detail, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    lv_obj_set_style_bg_color(g_views.detail, lv_color_hex(C_LHR_YELLOW), 0);
    lv_obj_set_style_bg_opa(g_views.detail, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_views.detail, 0, 0);
    lv_obj_clear_flag(g_views.detail, LV_OBJ_FLAG_SCROLLABLE);

    g_views.detail_badge = lv_obj_create(g_views.detail);
    lv_obj_set_size(g_views.detail_badge, 36, 36);
    lv_obj_set_style_bg_color(g_views.detail_badge, lv_color_hex(C_LHR_BLACK), 0);
    lv_obj_set_style_bg_opa(g_views.detail_badge, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_all(g_views.detail_badge, 0, 0);
    lv_obj_set_style_border_width(g_views.detail_badge, 0, 0);
    lv_obj_set_style_radius(g_views.detail_badge, LV_RADIUS_CIRCLE, 0);
    lv_obj_clear_flag(g_views.detail_badge, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_align(g_views.detail_badge, LV_ALIGN_TOP_LEFT, 28, 10);
    lv_obj_set_pos(plane_mark(g_views.detail_badge, C_LHR_YELLOW), 2, 2);

    lv_obj_t *title = label(g_views.detail, &lv_font_montserrat_20, C_LHR_BLACK);
    lv_label_set_text(title, "Overhead Flight");
    lv_obj_align(title, LV_ALIGN_TOP_LEFT, 78, 18);

    static const lv_point_t header_points[] = {{28, 56}, {996, 56}};
    lv_obj_t *divider = lv_line_create(g_views.detail);
    lv_line_set_points(divider, header_points, 2);
    lv_obj_set_style_line_color(divider, lv_color_hex(0xE3B600), 0);
    lv_obj_set_style_line_width(divider, 2, 0);

    g_views.detail_near = label(g_views.detail, &lv_font_montserrat_16, 0x594600);
    lv_obj_set_width(g_views.detail_near, 220);
    lv_obj_set_style_text_align(g_views.detail_near, LV_TEXT_ALIGN_RIGHT, 0);
    lv_obj_align(g_views.detail_near, LV_ALIGN_TOP_RIGHT, -28, 20);

    g_views.detail_carrier_font = &fv_outfit_88;
    g_views.detail_airline = label(g_views.detail, g_views.detail_carrier_font, C_LHR_BLACK);
    lv_obj_set_size(g_views.detail_airline, 650, 108);

    g_views.detail_typecode = label(g_views.detail, &fv_mono_80, C_LHR_BLACK);
    lv_obj_set_size(g_views.detail_typecode, 286, 110);
    lv_obj_set_style_text_align(g_views.detail_typecode, LV_TEXT_ALIGN_RIGHT, 0);

    g_views.detail_type = label(g_views.detail, &fv_outfit_28, 0x6F5B00);
    lv_obj_set_size(g_views.detail_type, 340, 40);
    lv_obj_set_style_text_align(g_views.detail_type, LV_TEXT_ALIGN_RIGHT, 0);

    g_views.detail_flight = label(g_views.detail, &fv_mono_40, C_LHR_BLACK);
    lv_obj_set_size(g_views.detail_flight, 310, 58);
    lv_obj_set_style_bg_color(g_views.detail_flight, lv_color_hex(0xEFC000), 0);
    lv_obj_set_style_bg_opa(g_views.detail_flight, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_hor(g_views.detail_flight, 10, 0);
    lv_obj_set_style_radius(g_views.detail_flight, 4, 0);

    g_views.detail_reg = label(g_views.detail, &lv_font_montserrat_18, 0x6F5B00);
    lv_obj_set_width(g_views.detail_reg, 260);

    g_views.detail_route = lv_obj_create(g_views.detail);
    lv_obj_set_style_pad_all(g_views.detail_route, 0, 0);
    lv_obj_set_size(g_views.detail_route, 968, 182);
    lv_obj_align(g_views.detail_route, LV_ALIGN_TOP_LEFT, 28, 236);
    lv_obj_set_style_bg_opa(g_views.detail_route, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_color(g_views.detail_route, lv_color_hex(0xE0B400), 0);
    lv_obj_set_style_border_width(g_views.detail_route, 2, 0);
    lv_obj_set_style_border_side(g_views.detail_route, LV_BORDER_SIDE_TOP | LV_BORDER_SIDE_BOTTOM, 0);
    lv_obj_set_style_radius(g_views.detail_route, 0, 0);
    lv_obj_clear_flag(g_views.detail_route, LV_OBJ_FLAG_SCROLLABLE);

    g_views.detail_origin = label(g_views.detail_route, &fv_mono_96, C_LHR_BLACK);
    lv_obj_set_size(g_views.detail_origin, 350, 130);
    lv_obj_set_style_text_align(g_views.detail_origin, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(g_views.detail_origin, 0, 0);
    g_views.detail_origin_city = label(g_views.detail_route, &fv_outfit_28, 0x6F5B00);
    lv_obj_set_size(g_views.detail_origin_city, 350, 36);
    lv_obj_set_style_text_align(g_views.detail_origin_city, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(g_views.detail_origin_city, 0, 130);

    lv_obj_set_pos(plane_mark(g_views.detail_route, C_LHR_BLACK), 468, 57);
    static const lv_point_t route_left[] = {{366, 73}, {453, 73}};
    static const lv_point_t route_right[] = {{515, 73}, {602, 73}};
    lv_obj_t *path_left = lv_line_create(g_views.detail_route);
    lv_obj_t *path_right = lv_line_create(g_views.detail_route);
    lv_line_set_points(path_left, route_left, 2);
    lv_line_set_points(path_right, route_right, 2);
    lv_obj_set_style_line_color(path_left, lv_color_hex(0xB08E00), 0);
    lv_obj_set_style_line_color(path_right, lv_color_hex(0xB08E00), 0);
    lv_obj_set_style_line_width(path_left, 2, 0);
    lv_obj_set_style_line_width(path_right, 2, 0);

    g_views.detail_dest = label(g_views.detail_route, &fv_mono_96, C_LHR_BLACK);
    lv_obj_set_size(g_views.detail_dest, 350, 130);
    lv_obj_set_style_text_align(g_views.detail_dest, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(g_views.detail_dest, 618, 0);
    g_views.detail_dest_city = label(g_views.detail_route, &fv_outfit_28, 0x6F5B00);
    lv_obj_set_size(g_views.detail_dest_city, 350, 36);
    lv_obj_set_style_text_align(g_views.detail_dest_city, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_pos(g_views.detail_dest_city, 618, 130);

    const char *stat_labels[] = {"ALTITUDE", "SPEED", "DISTANCE", "VERT SPEED"};
    const char *stat_units[] = {"ft", "kts", "ft", "fpm"};
    for (int i = 0; i < 4; i++) {
        lv_obj_t *box = lv_obj_create(g_views.detail);
        g_views.detail_stat_boxes[i] = box;
        lv_obj_set_style_pad_all(box, 0, 0);
        lv_obj_set_size(box, 242, 100);
        lv_obj_set_style_bg_opa(box, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_color(box, lv_color_hex(0xE0B400), 0);
        lv_obj_set_style_border_width(box, 1, 0);
        lv_obj_set_style_border_side(box, i == 3 ? LV_BORDER_SIDE_NONE : LV_BORDER_SIDE_RIGHT, 0);
        lv_obj_set_style_radius(box, 0, 0);
        lv_obj_clear_flag(box, LV_OBJ_FLAG_SCROLLABLE);
        g_views.detail_stats[i] = label(box, &fv_mono_40, C_LHR_BLACK);
        lv_obj_set_width(g_views.detail_stats[i], 232);
        lv_obj_set_style_text_align(g_views.detail_stats[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(g_views.detail_stats[i], LV_ALIGN_TOP_MID, 0, 0);
        lv_obj_t *unit = label(box, &lv_font_montserrat_14, 0x6F5B00);
        lv_label_set_text(unit, stat_units[i]);
        lv_obj_align(unit, LV_ALIGN_TOP_MID, 0, 56);
        lv_obj_t *lbl = label(box, &lv_font_montserrat_12, 0x6F5B00);
        lv_label_set_text(lbl, stat_labels[i]);
        lv_obj_set_style_text_letter_space(lbl, 1, 0);
        lv_obj_align(lbl, LV_ALIGN_BOTTOM_MID, 0, -8);
    }

    g_views.detail_footer = label(g_views.detail, &lv_font_montserrat_16, C_LHR_YELLOW);
    lv_obj_set_size(g_views.detail_footer, 170, 28);
    lv_obj_set_style_text_align(g_views.detail_footer, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_bg_color(g_views.detail_footer, lv_color_hex(C_LHR_BLACK), 0);
    lv_obj_set_style_bg_opa(g_views.detail_footer, LV_OPA_COVER, 0);
    lv_obj_set_style_pad_ver(g_views.detail_footer, 4, 0);
    lv_obj_set_style_radius(g_views.detail_footer, 20, 0);
    lv_obj_align(g_views.detail_footer, LV_ALIGN_BOTTOM_MID, -110, -10);
    g_views.detail_heading = label(g_views.detail, &lv_font_montserrat_16, 0x6F5B00);
    lv_obj_set_width(g_views.detail_heading, 230);
    lv_obj_align(g_views.detail_heading, LV_ALIGN_BOTTOM_MID, 110, -14);
}

static void create_startup(lv_obj_t *root)
{
    g_views.startup = lv_obj_create(root);
    lv_obj_set_style_pad_all(g_views.startup, 0, 0);
    lv_obj_set_style_radius(g_views.startup, 0, 0);
    lv_obj_set_size(g_views.startup, 1024, 570);
    lv_obj_align(g_views.startup, LV_ALIGN_BOTTOM_LEFT, 0, 0);
    lv_obj_set_style_bg_color(g_views.startup, lv_color_hex(C_MD_BG), 0);
    lv_obj_set_style_bg_opa(g_views.startup, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(g_views.startup, 0, 0);
    lv_obj_clear_flag(g_views.startup, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_t *msg = label(g_views.startup, &lv_font_montserrat_32, C_MD_TEXT);
    lv_label_set_text(msg, "Awaiting FlightView data");
    lv_obj_center(msg);
}

static void set_screen(bool startup, bool detail)
{
    lv_obj_t *next = startup ? g_views.startup : (detail ? g_views.detail : g_views.multi);
    if (g_views.active_screen == next) return;
    lv_obj_add_flag(g_views.startup, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(g_views.multi, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(g_views.detail, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(next, LV_OBJ_FLAG_HIDDEN);
    g_views.active_screen = next;
}

static void update_status(void)
{
    uint32_t color = C_STATUS_OK;
    const char *prefix = "OK";
    uint64_t age_ms = flightview_model_age_ms(&g_views.model, now_ms());
    bool stale = g_views.model.freshness.is_stale || g_views.model.freshness.is_initial ||
        (g_views.model.valid && age_ms >= g_views.model.freshness.stale_after_ms);
    if (g_views.model.transport_status != FV_TRANSPORT_OK) {
        color = C_STATUS_ERR;
        prefix = flightview_transport_status_text(g_views.model.transport_status);
    } else if (!g_views.model.health.ok || stale) {
        color = C_STATUS_WARN;
        prefix = stale ? "stale source" : "source error";
    }
    if (g_views.status_color != color) {
        lv_obj_set_style_bg_color(g_views.status_dot, lv_color_hex(color), 0);
        g_views.status_color = color;
    }

    uint64_t age_s = age_ms / 1000U;
    char text[160];
    if (!g_views.model.valid) {
        snprintf(text, sizeof(text), "%s | %s", prefix, g_views.model.transport_message);
    } else {
        snprintf(text, sizeof(text), "%s | %.80s | age %" PRIu64 "s | %d aircraft%s",
                 prefix,
                 g_views.model.transport_status != FV_TRANSPORT_OK
                     ? g_views.model.transport_message
                     : (g_views.model.health.message[0] ? g_views.model.health.message : "display feed"),
                 age_s,
                 g_views.model.counts.total_aircraft,
                 g_views.model.counts.truncated ? " | truncated" : "");
    }
    set_text(g_views.status_text, text);
}

static void update_multi(void)
{
    char count[64];
    size_t rows = g_views.model.aircraft_count < FV_MAX_LIST_ROWS ? g_views.model.aircraft_count : FV_MAX_LIST_ROWS;
    snprintf(count, sizeof(count), "List %u / radar %u / total %d",
             (unsigned)rows, (unsigned)g_views.model.aircraft_count,
             g_views.model.counts.total_aircraft);
    set_text(g_views.multi_count, count);

    int near_px = flightview_radar_near_ring_radius_px(
        (float)g_views.model.zones.near_radius_ft,
        (float)g_views.model.zones.radar_radius_ft,
        380,
        500);
    if (lv_obj_get_width(g_views.near_ring) != near_px * 2 ||
        lv_obj_get_height(g_views.near_ring) != near_px * 2) {
        lv_obj_set_size(g_views.near_ring, near_px * 2, near_px * 2);
        lv_obj_center(g_views.near_ring);
    }

    for (int i = 0; i < FV_MAX_AIRCRAFT; i++) {
        if ((size_t)i >= g_views.model.aircraft_count) {
            lv_obj_add_flag(g_views.blips[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(g_views.blip_labels[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(g_views.headings[i], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        const flightview_aircraft_t *a = &g_views.model.aircraft[i];
        if (!a->bearing.valid || !a->distance_ft.valid) {
            lv_obj_add_flag(g_views.blips[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(g_views.blip_labels[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(g_views.headings[i], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        float bearing = a->bearing.value;
        float dist = a->distance_ft.value;
        flightview_radar_point_t p = flightview_radar_project(
            bearing,
            dist,
            (float)g_views.model.zones.radar_radius_ft,
            0,
            0,
            380,
            500);
        lv_obj_set_pos(g_views.blips[i], p.x - 6, p.y - 6);
        lv_obj_set_pos(g_views.blip_labels[i], p.x > 275 ? p.x - 105 : p.x + 10, p.y + 8);
        if (a->heading.valid) {
            float angle = a->heading.value * 3.14159265358979323846f / 180.0f;
            lv_point_t end = {
                p.x + (int)lroundf(17 * sinf(angle)), p.y - (int)lroundf(17 * cosf(angle)),
            };
            if (g_views.heading_points[i][0].x != p.x || g_views.heading_points[i][0].y != p.y ||
                g_views.heading_points[i][1].x != end.x || g_views.heading_points[i][1].y != end.y) {
                g_views.heading_points[i][0] = (lv_point_t){p.x, p.y};
                g_views.heading_points[i][1] = end;
                lv_line_set_points(g_views.headings[i], g_views.heading_points[i], 2);
            }
            lv_obj_clear_flag(g_views.headings[i], LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(g_views.headings[i], LV_OBJ_FLAG_HIDDEN);
        }
        set_text(g_views.blip_labels[i], aircraft_name(a));
        lv_obj_clear_flag(g_views.blips[i], LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(g_views.blip_labels[i], LV_OBJ_FLAG_HIDDEN);
    }

    if (rows == 0) {
        lv_obj_clear_flag(g_views.empty_label, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(g_views.empty_label, LV_OBJ_FLAG_HIDDEN);
    }

    for (int i = 0; i < FV_MAX_LIST_ROWS; i++) {
        if ((size_t)i >= rows) {
            lv_obj_add_flag(g_views.list_rows[i], LV_OBJ_FLAG_HIDDEN);
            continue;
        }
        const flightview_aircraft_t *a = &g_views.model.aircraft[i];
        char stats[52];
        char dist[24];
        char alt[24];
        format_opt(alt, sizeof(alt), a->altitude_ft, "ft");
        format_opt(dist, sizeof(dist), a->distance_ft, "ft");
        snprintf(stats, sizeof(stats), "%s\n%s", alt, dist);
        set_text(g_views.list_text[i][0], aircraft_name(a));
        set_text(g_views.list_text[i][1], a->airline);
        set_text(g_views.list_text[i][2], a->aircraft_type[0] ? a->aircraft_type : a->typecode);
        set_text(g_views.list_text[i][3], stats);
        lv_obj_clear_flag(g_views.list_rows[i], LV_OBJ_FLAG_HIDDEN);
    }
}

static void layout_detail(bool has_route)
{
    if (g_views.detail_layout_set && g_views.detail_has_route == has_route) return;
    int top = has_route ? 64 : 164;
    lv_obj_set_pos(g_views.detail_airline, 28, top);
    lv_obj_align(g_views.detail_typecode, LV_ALIGN_TOP_RIGHT, -28, top);
    lv_obj_align(g_views.detail_type, LV_ALIGN_TOP_RIGHT, -28, top + 116);
    lv_obj_set_pos(g_views.detail_flight, 28, top + 112);
    lv_obj_set_pos(g_views.detail_reg, 354, top + 130);
    for (int i = 0; i < 4; i++) {
        lv_obj_set_pos(g_views.detail_stat_boxes[i], 28 + i * 242, has_route ? 428 : 354);
    }
    if (has_route) {
        lv_obj_clear_flag(g_views.detail_route, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(g_views.detail_route, LV_OBJ_FLAG_HIDDEN);
    }
    g_views.detail_has_route = has_route;
    g_views.detail_layout_set = true;
}

static void update_detail(void)
{
    const flightview_aircraft_t *a = &g_views.model.display;
    char near[48];
    snprintf(near, sizeof(near), "%d nearby", g_views.model.counts.nearby_aircraft);
    set_text(g_views.detail_near, near);
    char carrier[FV_TEXT_AIRLINE + 1];
    short_airline(carrier, sizeof(carrier), a->airline);
    lv_point_t carrier_size;
    lv_txt_get_size(&carrier_size, carrier, &fv_outfit_88, 0, 0, LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    const lv_font_t *carrier_font = carrier_size.x <= 650 ? &fv_outfit_88 : &fv_outfit_64;
    if (carrier_font != g_views.detail_carrier_font) {
        lv_obj_set_style_text_font(g_views.detail_airline, carrier_font, 0);
        g_views.detail_carrier_font = carrier_font;
    }
    set_text(g_views.detail_airline, carrier);
    set_text(g_views.detail_flight, aircraft_name(a));
    set_text(g_views.detail_typecode, a->typecode);
    bool duplicate_type = !a->aircraft_type[0] || same_ascii_text(a->aircraft_type, a->typecode);
    if (duplicate_type) {
        lv_obj_add_flag(g_views.detail_type, LV_OBJ_FLAG_HIDDEN);
    } else {
        set_text(g_views.detail_type, a->aircraft_type);
        lv_obj_clear_flag(g_views.detail_type, LV_OBJ_FLAG_HIDDEN);
    }
    if (!a->registration[0] || same_ascii_text(a->registration, aircraft_name(a))) {
        lv_obj_add_flag(g_views.detail_reg, LV_OBJ_FLAG_HIDDEN);
    } else {
        set_text(g_views.detail_reg, a->registration);
        lv_obj_clear_flag(g_views.detail_reg, LV_OBJ_FLAG_HIDDEN);
    }

    const bool has_route = a->route_origin[0] != '\0' && a->route_destination[0] != '\0';
    layout_detail(has_route);
    if (has_route) {
        set_text(g_views.detail_origin, a->route_origin);
        set_text(g_views.detail_origin_city, a->origin_city);
        set_text(g_views.detail_dest, a->route_destination);
        set_text(g_views.detail_dest_city, a->destination_city);
    }

    char buf[64];
    format_opt(buf, sizeof(buf), a->altitude_ft, NULL);
    set_text(g_views.detail_stats[0], buf);
    format_opt(buf, sizeof(buf), a->velocity_kts, NULL);
    set_text(g_views.detail_stats[1], buf);
    format_opt(buf, sizeof(buf), a->distance_ft, NULL);
    set_text(g_views.detail_stats[2], buf);
    format_signed(buf, sizeof(buf), a->vertical_rate_fpm);
    set_text(g_views.detail_stats[3], buf);
    char heading[32];
    format_opt(heading, sizeof(heading), a->heading, "deg");
    snprintf(buf, sizeof(buf), "%s", a->direction[0] ? a->direction : "-");
    for (size_t i = 0; buf[i]; i++) buf[i] = (char)toupper((unsigned char)buf[i]);
    set_text(g_views.detail_footer, buf);
    snprintf(buf, sizeof(buf), "from %s  %s", a->compass[0] ? a->compass : "-", heading);
    set_text(g_views.detail_heading, buf);
}

static void render(void)
{
    update_status();
    if (!g_views.model.valid || g_views.model.freshness.is_initial) {
        set_screen(true, false);
        return;
    }
    if (g_views.model.has_display) {
        update_detail();
        set_screen(false, true);
    } else {
        update_multi();
        set_screen(false, false);
    }
}

static void ui_timer(lv_timer_t *timer)
{
    (void)timer;
    static flightview_ui_message_t msg;
    bool model_received = false;
    while (xQueueReceive(g_views.queue, &msg, 0) == pdTRUE) {
        if (msg.type == FV_UI_MSG_MODEL) {
            flightview_model_apply_success(&g_views.model, &msg.model);
            model_received = true;
        } else if (msg.type == FV_UI_MSG_TRANSPORT) {
            flightview_model_apply_transport(&g_views.model, msg.transport_status, msg.transport_message, msg.monotonic_ms);
        }
    }
    if (model_received) {
        render();
    } else {
        update_status();
    }
}

QueueHandle_t flightview_views_start(void)
{
    memset(&g_views, 0, sizeof(g_views));
    flightview_model_init(&g_views.model);
    g_views.queue = xQueueCreate(1, sizeof(flightview_ui_message_t));
    if (g_views.queue == NULL) {
        ESP_LOGE(TAG, "UI queue allocation failed");
        return NULL;
    }

    if (esp_lv_adapter_lock(-1) != ESP_OK) {
        return NULL;
    }
    g_views.root = lv_scr_act();
    lv_obj_set_style_pad_all(g_views.root, 0, 0);
    lv_obj_set_style_border_width(g_views.root, 0, 0);
    lv_obj_set_style_bg_color(g_views.root, lv_color_hex(C_MD_BG), 0);
    lv_obj_set_style_bg_opa(g_views.root, LV_OPA_COVER, 0);
    g_views.status_bar = make_status_bar(g_views.root);
    create_multi(g_views.root);
    create_detail(g_views.root);
    create_startup(g_views.root);
    set_screen(true, false);
    lv_timer_create(ui_timer, 250, NULL);
    esp_lv_adapter_unlock();
    return g_views.queue;
}
