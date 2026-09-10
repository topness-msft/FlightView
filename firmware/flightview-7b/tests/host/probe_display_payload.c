#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#include "flightview_protocol.h"

static char *read_file(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) {
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size < 0 || size > (long)FV_HTTP_BODY_MAX_BYTES) {
        fclose(f);
        return NULL;
    }
    char *buf = calloc((size_t)size + 1, 1);
    if (buf == NULL) {
        fclose(f);
        return NULL;
    }
    size_t read = fread(buf, 1, (size_t)size, f);
    fclose(f);
    if (read != (size_t)size) {
        free(buf);
        return NULL;
    }
    *len = read;
    return buf;
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: %s display.json\n", argv[0]);
        return 2;
    }
    size_t len = 0;
    char *body = read_file(argv[1], &len);
    if (body == NULL) {
        fprintf(stderr, "failed to read bounded payload\n");
        return 2;
    }

    flightview_model_t model;
    flightview_parse_result_t result = flightview_parse_display_payload(body, len, 100000, 0, &model);
    free(body);
    if (result != FV_PARSE_OK) {
        fprintf(stderr, "parse failed: %s\n", flightview_parse_result_name(result));
        return 1;
    }

    printf("schema=%lu aircraft=%u display=%s health=%s source=%s stale=%s initial=%s\n",
           (unsigned long)model.schema_version,
           (unsigned)model.aircraft_count,
           model.has_display ? "yes" : "no",
           model.health.ok ? "ok" : "error",
           model.health.data_source,
           model.freshness.is_stale ? "yes" : "no",
           model.freshness.is_initial ? "yes" : "no");
    assert(model.aircraft_count <= FV_MAX_AIRCRAFT);
    assert((int)model.aircraft_count == model.counts.returned_aircraft);
    return 0;
}

