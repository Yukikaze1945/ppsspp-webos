/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
/* App-private v0.0.8 core, profiling is opt-in via PPSSPP_BRIDGE_PROFILE=1. */
#define _GNU_SOURCE
#include <stdio.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include "profile_core.h"
#define bridge_begin pp_inner_begin
#define bridge_send_call pp_inner_call
#define bridge_send_void pp_inner_void
#define wl_bridge_begin pp_inner_wl_begin
#define wl_bridge_end pp_inner_wl_end
#define bridge_send_call_wl pp_inner_wl_call
#define bridge_send_void_wl pp_inner_wl_void
#define nanosleep pp_sleep
#define bridge_data_write ppsspp_inner_data_write
#include "../../reference/bridge-v008/stub/bridge_core.c"
#undef bridge_data_write
#undef bridge_begin
#undef bridge_send_call
#undef bridge_send_void
#undef wl_bridge_begin
#undef wl_bridge_end
#undef bridge_send_call_wl
#undef bridge_send_void_wl
#undef nanosleep

typedef struct { _Atomic uint64_t count, ns, maximum; } PPMetric;
static PPMetric pp_calls[OP_MAX], pp_voids, pp_begin, pp_data, pp_wl;
static _Atomic uint64_t pp_depth_max;
static pthread_once_t pp_once = PTHREAD_ONCE_INIT;
// FIFO hand-off prevents the polling thread from repeatedly reacquiring the WL
// channel while SDL's render thread waits to flush/present. This gate only wraps
// the app-private channel; it does not change the wire protocol or system driver.
static pthread_mutex_t pp_wl_gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t pp_wl_turn = PTHREAD_COND_INITIALIZER;
static uint64_t pp_wl_next, pp_wl_serving;
static int pp_fair_wl;


static void pp_max(_Atomic uint64_t *value, uint64_t sample) {
    uint64_t old = atomic_load_explicit(value, memory_order_relaxed);
    while (old < sample && !atomic_compare_exchange_weak_explicit(value, &old, sample,
            memory_order_relaxed, memory_order_relaxed)) {}
}
static void pp_note(PPMetric *m, uint64_t ns) {
    atomic_fetch_add_explicit(&m->count, 1, memory_order_relaxed);
    atomic_fetch_add_explicit(&m->ns, ns, memory_order_relaxed);
    pp_max(&m->maximum, ns);
}
static void pp_print_metric(FILE *f, const char *name, PPMetric *m) {
    fprintf(f, "\"%s\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],", name,
        atomic_load(&m->count), atomic_load(&m->ns), atomic_load(&m->maximum));
}
static void *pp_trace(void *unused) {
    (void)unused;
    char path[160];
    snprintf(path,sizeof(path),"/media/developer/ppsspp-webos-data/perf-core-%d.jsonl",getpid());
    FILE *f=fopen(path,"w");
    if (!f) return NULL;
    setvbuf(f,NULL,_IOFBF,16384);
    for (;;) {
        fprintf(f,"{\"mono_ns\":%" PRIu64 ",\"pid\":%d,\"depth_max\":%" PRIu64 ",",pp_now(),getpid(),atomic_load(&pp_depth_max));
        pp_print_metric(f,"begin",&pp_begin);
        pp_print_metric(f,"data",&pp_data);
        pp_print_metric(f,"wl_call",&pp_wl);
        pp_print_metric(f,"enqueue",&pp_voids);
        fprintf(f,"\"sleeps\":[");
        for (int i=0;i<4;i++) fprintf(f,"%s[%" PRIu64 ",%" PRIu64 "]",i?",":"",atomic_load(&pp_sleep_count[i]),atomic_load(&pp_sleep_ns[i]));
        fprintf(f,"],\"ops\":[");
        int comma=0;
        for (int i=0;i<OP_MAX;i++) if (atomic_load(&pp_calls[i].count)) {
            fprintf(f,"%s[\"%s\",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",comma++?",":"",opcode_to_string(i),
                atomic_load(&pp_calls[i].count),atomic_load(&pp_calls[i].ns),atomic_load(&pp_calls[i].maximum));
        }
        fprintf(f,"]}\n"); fflush(f);
        struct timespec t={1,0}; nanosleep(&t,NULL);
    }
    return NULL;
}
static void pp_init(void) {
    const char *env=getenv("PPSSPP_BRIDGE_PROFILE");
    pp_enabled=env && strcmp(env,"1")==0;
    const char *fair=getenv("PPSSPP_BRIDGE_FAIR_WL");
    pp_fair_wl=!fair || strcmp(fair,"0")!=0;
    if (pp_enabled) {
        pthread_t thread;
        if (pthread_create(&thread,NULL,pp_trace,NULL)==0) pthread_detach(thread);
    }
}
void bridge_begin(void) {
    pthread_once(&pp_once,pp_init);
    if (!pp_enabled) { pp_inner_begin(); return; }
    uint64_t start=pp_now(); pp_phase=1;
    pp_inner_begin(); pp_phase=0;
    pp_note(&pp_begin,pp_now()-start);
    if (g_ring) pp_max(&pp_depth_max,g_cur_seq-atomic_load_explicit(&g_ring->completed_seq,memory_order_acquire));
}
void bridge_send_void(void) {
    if (!pp_enabled) { pp_inner_void(); return; }
    uint64_t start=pp_now(); pp_inner_void(); pp_note(&pp_voids,pp_now()-start);
}
uint64_t bridge_send_call(void) {
    if (!pp_enabled) return pp_inner_call();
    uint32_t op=g_cur_slot->opcode;
    uint64_t start=pp_now(), result=pp_inner_call();
    if (op<OP_MAX) pp_note(&pp_calls[op],pp_now()-start);
    return result;
}
void wl_bridge_begin(void) {
    pthread_once(&pp_once,pp_init);
    uint64_t start=pp_enabled?pp_now():0;
    if (pp_fair_wl) {
        pthread_mutex_lock(&pp_wl_gate);
        const uint64_t ticket=pp_wl_next++;
        while (ticket!=pp_wl_serving) pthread_cond_wait(&pp_wl_turn,&pp_wl_gate);
        pthread_mutex_unlock(&pp_wl_gate);
    }
    pp_inner_wl_begin();
    if (pp_enabled && pp_now()-start>UINT64_C(50000000))
        fprintf(stderr,"[perf-wl-lock] {\"mono_ns\":%" PRIu64 ",\"ns\":%" PRIu64 ",\"tid\":%ld}\n",
            pp_now(),pp_now()-start,(long)syscall(SYS_gettid));
}
static void pp_wl_release_turn(void) {
    if (pp_fair_wl) {
        pthread_mutex_lock(&pp_wl_gate);
        ++pp_wl_serving;
        pthread_cond_broadcast(&pp_wl_turn);
        pthread_mutex_unlock(&pp_wl_gate);
    }
}
void wl_bridge_end(void) {
    pp_inner_wl_end();
    pp_wl_release_turn();
}
uint64_t bridge_send_call_wl(void) {
    uint64_t start=pp_enabled?pp_now():0,result=pp_inner_wl_call();
    pp_wl_release_turn();
    if (pp_enabled) pp_note(&pp_wl,pp_now()-start);
    return result;
}
void bridge_send_void_wl(void) {
    if (!pp_enabled) { pp_inner_wl_void(); pp_wl_release_turn(); return; }
    uint64_t start=pp_now();
    pp_inner_wl_void();
    pp_wl_release_turn();
    uint64_t end=pp_now();
    uint64_t elapsed=end>=start ? end-start : 0;
    pp_note(&pp_wl,elapsed);
    if (elapsed>UINT64_C(50000000))
        fprintf(stderr,"[perf-wl] {\"mono_ns\":%" PRIu64 ",\"op\":\"bridge_send_void_wl\",\"ns\":%" PRIu64 ",\"tid\":%ld}\n",
            end,elapsed,(long)syscall(SYS_gettid));
}
uint32_t bridge_data_write(const void *src, size_t size) {
    if (size > GLES_BRIDGE_DATA_SIZE) {
        Dl_info info = {0};
        dladdr(__builtin_return_address(0), &info);
        fprintf(stderr, "[perf] oversized payload opcode=%u caller=%s symbol=%s src=%p size=%zu\n",
            g_cur_slot ? g_cur_slot->opcode : 0, info.dli_fname ? info.dli_fname : "?",
            info.dli_sname ? info.dli_sname : "?", src, size);
    }
    if (!pp_enabled) return ppsspp_inner_data_write(src,size);
    uint64_t start=pp_now(); pp_phase=2;
    uint32_t result=ppsspp_inner_data_write(src,size); pp_phase=0;
    pp_note(&pp_data,pp_now()-start); return result;
}
void ppsspp_bridge_shutdown(void) { bridge_cleanup(); }
