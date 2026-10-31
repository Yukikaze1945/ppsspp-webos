/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
/*
 * App-private, low-overhead timing for the ARM32 GLES proxy dispatch loop.
 * Counters are process-local and do not change the Bridge shared ABI.
 */
#pragma once

#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/types.h>

#include "gles_bridge_protocol.h"

typedef struct ProxyOpcodeProfile {
  uint64_t count;
  uint64_t sync_count;
  uint64_t dispatch_ns;
  uint64_t max_ns;
  uint64_t bind_ns;
} ProxyOpcodeProfile;

/* dispatch_ns is CLOCK_MONOTONIC elapsed time inside the CPU-side handler;
 * it may include time blocked in a graphics driver and is not GPU time. */

typedef struct ProxyProfile {
  int enabled;
  FILE *file;
  FILE *slow_file;
  uint64_t last_emit_ns;
  uint64_t depth_max;
  char output_buffer[8192];
  char slow_output_buffer[8192];
  ProxyOpcodeProfile op[OP_MAX];
} ProxyProfile;

static ProxyProfile g_proxy_profile;

static inline uint64_t proxy_profile_clock_ns(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
    return 0;
  return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

static inline int proxy_profile_enabled(void) {
  return g_proxy_profile.enabled;
}

static inline void proxy_profile_init(void) {
  const char *setting = getenv("PPSSPP_BRIDGE_PROFILE");
  if (!setting || strcmp(setting, "1") != 0)
    return;

  char path[256];
  snprintf(path, sizeof(path), "/media/developer/ppsspp-webos-data/perf-proxy-%ld.jsonl",
           (long)getpid());
  int fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
  if (fd < 0)
    return;

  g_proxy_profile.file = fdopen(fd, "a");
  if (!g_proxy_profile.file) {
    close(fd);
    return;
  }
  if (setvbuf(g_proxy_profile.file, g_proxy_profile.output_buffer, _IOFBF,
              sizeof(g_proxy_profile.output_buffer)) != 0) {
    fclose(g_proxy_profile.file);
    g_proxy_profile.file = NULL;
    return;
  }

  snprintf(path, sizeof(path),
           "/media/developer/ppsspp-webos-data/perf-proxy-%ld.slow.jsonl",
           (long)getpid());
  fd = open(path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644);
  if (fd >= 0) {
    g_proxy_profile.slow_file = fdopen(fd, "a");
    if (!g_proxy_profile.slow_file) {
      close(fd);
    } else if (setvbuf(g_proxy_profile.slow_file,
                       g_proxy_profile.slow_output_buffer, _IOFBF,
                       sizeof(g_proxy_profile.slow_output_buffer)) != 0) {
      fclose(g_proxy_profile.slow_file);
      g_proxy_profile.slow_file = NULL;
    }
  }

  g_proxy_profile.last_emit_ns = proxy_profile_clock_ns();
  g_proxy_profile.enabled = 1;
}

static inline void proxy_profile_observe_depth(uint64_t depth) {
  if (depth > g_proxy_profile.depth_max)
    g_proxy_profile.depth_max = depth;
}

static inline void proxy_profile_emit(uint64_t now_ns) {
  FILE *file = g_proxy_profile.file;
  if (!file)
    return;

  fprintf(file, "{\"mono_ns\":%" PRIu64 ",\"pid\":%ld,\"depth_max\":%" PRIu64 ",\"ops\":[",
          now_ns, (long)getpid(), g_proxy_profile.depth_max);
  int first = 1;
  for (uint32_t opcode = 1; opcode < OP_MAX; ++opcode) {
    const ProxyOpcodeProfile *p = &g_proxy_profile.op[opcode];
    if (p->count == 0)
      continue;
    const char *name = opcode_to_string(opcode);
    if (!name)
      name = "unknown";
    fprintf(file, "%s[\"%s\",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]",
            first ? "" : ",", name, p->count, p->sync_count,
            p->dispatch_ns, p->max_ns, p->bind_ns);
    first = 0;
  }
  fputs("]}\n", file);
  fflush(file);
  if (g_proxy_profile.slow_file)
    fflush(g_proxy_profile.slow_file);
  g_proxy_profile.last_emit_ns = now_ns;
}

static inline void proxy_profile_record(uint32_t opcode, int needs_response,
                                        uint64_t dispatch_ns, uint64_t bind_ns,
                                        uint64_t now_ns) {
  if (opcode == 0 || opcode >= OP_MAX)
    return;
  ProxyOpcodeProfile *p = &g_proxy_profile.op[opcode];
  p->count++;
  if (needs_response)
    p->sync_count++;
  p->dispatch_ns += dispatch_ns;
  p->bind_ns += bind_ns;
  if (dispatch_ns > p->max_ns)
    p->max_ns = dispatch_ns;

  if (dispatch_ns >= UINT64_C(5000000) && g_proxy_profile.slow_file) {
    const char *name = opcode_to_string(opcode);
    if (!name)
      name = "unknown";
    fprintf(g_proxy_profile.slow_file,
            "{\"mono_ns\":%" PRIu64 ",\"op\":\"%s\",\"ns\":%" PRIu64
            ",\"bind_ns\":%" PRIu64 "}\n",
            now_ns, name, dispatch_ns, bind_ns);
  }

  if (now_ns >= g_proxy_profile.last_emit_ns &&
      now_ns - g_proxy_profile.last_emit_ns >= UINT64_C(1000000000))
    proxy_profile_emit(now_ns);
}

static inline void proxy_profile_close(void) {
  if (g_proxy_profile.file) {
    fflush(g_proxy_profile.file);
    fclose(g_proxy_profile.file);
    g_proxy_profile.file = NULL;
  }
  if (g_proxy_profile.slow_file) {
    fflush(g_proxy_profile.slow_file);
    fclose(g_proxy_profile.slow_file);
    g_proxy_profile.slow_file = NULL;
  }
  g_proxy_profile.enabled = 0;
}
