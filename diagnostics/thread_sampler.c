#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#define MAX_TARGETS 8
#define STAT_BUFFER_SIZE 4096

typedef struct {
  pid_t pid;
} Target;

static char output_buffer[65536];

static uint64_t monotonic_ns(void) {
  struct timespec ts;
  if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0)
    return 0;
  return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}

static int is_digits(const char *s) {
  if (!s || !*s)
    return 0;
  for (; *s; ++s) {
    if (*s < '0' || *s > '9')
      return 0;
  }
  return 1;
}

static int matches_suffix(const char *path) {
  static const char *suffixes[] = {
      "/org.ppsspp.webos/PPSSPPSDL",
      "/org.ppsspp.webos/service/gles_proxy",
  };
  for (size_t i = 0; i < sizeof(suffixes) / sizeof(suffixes[0]); ++i) {
    size_t path_len = strlen(path);
    size_t suffix_len = strlen(suffixes[i]);
    if (path_len >= suffix_len &&
        strcmp(path + path_len - suffix_len, suffixes[i]) == 0)
      return 1;
  }
  return 0;
}

static size_t discover_targets(Target *targets, size_t capacity) {
  DIR *proc = opendir("/proc");
  if (!proc)
    return 0;
  size_t count = 0;
  struct dirent *entry;
  while (count < capacity && (entry = readdir(proc)) != NULL) {
    if (!is_digits(entry->d_name))
      continue;
    char *end = NULL;
    long value = strtol(entry->d_name, &end, 10);
    if (!end || *end || value <= 0 || value > INT_MAX)
      continue;
    char link_path[64];
    snprintf(link_path, sizeof(link_path), "/proc/%ld/exe", value);
    char exe[PATH_MAX];
    ssize_t length = readlink(link_path, exe, sizeof(exe) - 1);
    if (length <= 0)
      continue;
    exe[length] = '\0';
    if (matches_suffix(exe))
      targets[count++].pid = (pid_t)value;
  }
  closedir(proc);
  return count;
}

static int read_file(const char *path, char *buffer, size_t capacity) {
  FILE *file = fopen(path, "r");
  if (!file)
    return 0;
  size_t length = fread(buffer, 1, capacity - 1, file);
  int ok = !ferror(file);
  fclose(file);
  if (!ok)
    return 0;
  buffer[length] = '\0';
  return 1;
}

static void json_string(const char *text) {
  putchar('"');
  for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
    switch (*p) {
    case '"': fputs("\\\"", stdout); break;
    case '\\': fputs("\\\\", stdout); break;
    case '\b': fputs("\\b", stdout); break;
    case '\f': fputs("\\f", stdout); break;
    case '\n': fputs("\\n", stdout); break;
    case '\r': fputs("\\r", stdout); break;
    case '\t': fputs("\\t", stdout); break;
    default:
      if (*p < 0x20)
        printf("\\u%04x", (unsigned)*p);
      else
        putchar(*p);
    }
  }
  putchar('"');
}

static void sample_target(pid_t pid) {
  char task_path[128];
  snprintf(task_path, sizeof(task_path), "/proc/%ld/task", (long)pid);
  DIR *tasks = opendir(task_path);
  if (!tasks)
    return;

  struct dirent *entry;
  while ((entry = readdir(tasks)) != NULL) {
    if (!is_digits(entry->d_name))
      continue;
    char *end = NULL;
    long tid_value = strtol(entry->d_name, &end, 10);
    if (!end || *end || tid_value <= 0 || tid_value > INT_MAX)
      continue;

    char path[192], stat_buffer[STAT_BUFFER_SIZE], sched_buffer[256];
    snprintf(path, sizeof(path), "/proc/%ld/task/%ld/stat", (long)pid,
             tid_value);
    if (!read_file(path, stat_buffer, sizeof(stat_buffer)))
      continue;
    char *left = strchr(stat_buffer, '(');
    char *right = strrchr(stat_buffer, ')');
    if (!left || !right || right <= left || right[1] != ' ')
      continue;
    char *state_ptr = right + 2;
    if (!*state_ptr)
      continue;
    char state = *state_ptr;
    size_t name_length = (size_t)(right - left - 1);
    char name[256];
    if (name_length >= sizeof(name))
      name_length = sizeof(name) - 1;
    memcpy(name, left + 1, name_length);
    name[name_length] = '\0';

    snprintf(path, sizeof(path), "/proc/%ld/task/%ld/schedstat", (long)pid,
             tid_value);
    if (!read_file(path, sched_buffer, sizeof(sched_buffer)))
      continue;
    unsigned long long run_ns, wait_ns, slices;
    if (sscanf(sched_buffer, "%llu %llu %llu", &run_ns, &wait_ns, &slices) != 3)
      continue;

    printf("{\"mono_ns\":%" PRIu64 ",\"pid\":%ld,\"tid\":%ld,\"name\":",
           monotonic_ns(), (long)pid, tid_value);
    json_string(name);
    printf(",\"state\":\"%c\",\"run_ns\":%llu,\"wait_ns\":%llu,"
           "\"slices\":%llu",
           state, run_ns, wait_ns, slices);
    // Read-only blocked syscall context: args distinguish sleep from futex/IPC.
    char syscall_buffer[512];
    snprintf(path, sizeof(path), "/proc/%ld/task/%ld/syscall", (long)pid, tid_value);
    if (read_file(path, syscall_buffer, sizeof(syscall_buffer))) {
      printf(",\"syscall\":");
      json_string(syscall_buffer);
    }
    printf("}\n");
  }
  closedir(tasks);
}

static uint64_t timeval_ns(const struct timeval *value) {
  return (uint64_t)value->tv_sec * UINT64_C(1000000000) +
         (uint64_t)value->tv_usec * UINT64_C(1000);
}

static int parse_positive(const char *text, long minimum, long maximum,
                          long *value) {
  if (!is_digits(text))
    return 0;
  errno = 0;
  char *end = NULL;
  long parsed = strtol(text, &end, 10);
  if (errno || !end || *end || parsed < minimum || parsed > maximum)
    return 0;
  *value = parsed;
  return 1;
}

int main(int argc, char **argv) {
  long seconds = 45;
  long interval_ms = 100;
  for (int i = 1; i < argc; ++i) {
    if ((strcmp(argv[i], "--seconds") == 0 ||
         strcmp(argv[i], "--interval-ms") == 0) && i + 1 < argc) {
      long parsed;
      if (strcmp(argv[i], "--seconds") == 0) {
        if (!parse_positive(argv[++i], 1, 86400, &parsed)) {
          fprintf(stderr, "invalid --seconds value\n");
          return 2;
        }
        seconds = parsed;
      } else {
        if (!parse_positive(argv[++i], 10, 60000, &parsed)) {
          fprintf(stderr, "invalid --interval-ms value\n");
          return 2;
        }
        interval_ms = parsed;
      }
    } else {
      fprintf(stderr, "usage: %s [--seconds N] [--interval-ms N]\n", argv[0]);
      return 2;
    }
  }

  setvbuf(stdout, output_buffer, _IOFBF, sizeof(output_buffer));
  struct rusage usage_before, usage_after;
  getrusage(RUSAGE_SELF, &usage_before);

  const uint64_t interval_ns = (uint64_t)interval_ms * UINT64_C(1000000);
  const uint64_t start_ns = monotonic_ns();
  const uint64_t stop_ns = start_ns + (uint64_t)seconds * UINT64_C(1000000000);
  uint64_t next_scan_ns = 0;
  uint64_t next_sample_ns = start_ns;
  uint64_t next_flush_ns = start_ns + UINT64_C(1000000000);
  Target targets[MAX_TARGETS];
  size_t target_count = 0;

  while (monotonic_ns() < stop_ns) {
    uint64_t now_ns = monotonic_ns();
    if (now_ns >= next_scan_ns) {
      target_count = discover_targets(targets, MAX_TARGETS);
      next_scan_ns = now_ns + UINT64_C(1000000000);
    }
    for (size_t i = 0; i < target_count; ++i)
      sample_target(targets[i].pid);

    now_ns = monotonic_ns();
    if (now_ns >= next_flush_ns) {
      fflush(stdout);
      next_flush_ns = now_ns + UINT64_C(1000000000);
    }
    next_sample_ns += interval_ns;
    now_ns = monotonic_ns();
    while (next_sample_ns <= now_ns)
      next_sample_ns += interval_ns;
    struct timespec deadline = {
        .tv_sec = (time_t)(next_sample_ns / UINT64_C(1000000000)),
        .tv_nsec = (long)(next_sample_ns % UINT64_C(1000000000)),
    };
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL) == EINTR) {
    }
  }

  fflush(stdout);
  getrusage(RUSAGE_SELF, &usage_after);
  uint64_t elapsed_ns = monotonic_ns() - start_ns;
  uint64_t cpu_ns = timeval_ns(&usage_after.ru_utime) +
                    timeval_ns(&usage_after.ru_stime) -
                    timeval_ns(&usage_before.ru_utime) -
                    timeval_ns(&usage_before.ru_stime);
  fprintf(stderr,
          "thread_sampler: elapsed=%.3fs self_cpu=%.3fs self_cpu_percent_one_core=%.2f%%\n",
          elapsed_ns / 1e9, cpu_ns / 1e9,
          elapsed_ns ? 100.0 * (double)cpu_ns / (double)elapsed_ns : 0.0);
  return 0;
}
