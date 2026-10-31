/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
/* Temporary app-private profiling, no protocol-layout changes. */
#pragma once
#include <stdatomic.h>
#include <inttypes.h>
#include <time.h>
#include <pthread.h>
#include <unistd.h>

static _Atomic uint64_t pp_sleep_count[4], pp_sleep_ns[4];
static _Thread_local int pp_phase;
static int pp_enabled;
static uint64_t pp_now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (uint64_t)t.tv_sec * 1000000000ull + t.tv_nsec;
}
static int pp_sleep(const struct timespec *req, struct timespec *rem) {
    if (!pp_enabled) return nanosleep(req, rem);
    const uint64_t start = pp_now();
    int ret = nanosleep(req, rem);
    int phase = pp_phase >= 0 && pp_phase < 4 ? pp_phase : 0;
    atomic_fetch_add_explicit(&pp_sleep_count[phase], 1, memory_order_relaxed);
    atomic_fetch_add_explicit(&pp_sleep_ns[phase], pp_now()-start, memory_order_relaxed);
    return ret;
}
