/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <stdint.h>
#include <unistd.h>

#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#include <sys/ipc.h>
#include <sys/shm.h>

#include "bridge_shm.h"
#include "shared_util.h"

#define LEGACY_SHM_FIRST 0x4701UL
#define LEGACY_SHM_LAST 0x4704UL

static int bridge_key(const char *name_or_key, key_t *key)
{
  char *end = NULL;
  errno = 0;
  unsigned long value = strtoul(name_or_key, &end, 0);
  if (errno || end == name_or_key || *end != '\0' || value > INT32_MAX)
  {
    log_error("bridge_key: invalid shared-memory key: %s", name_or_key);
    return 0;
  }

  if (value >= LEGACY_SHM_FIRST && value <= LEGACY_SHM_LAST)
  {
    const char *base_env = getenv("PPSSPP_BRIDGE_SHM_BASE");
    if (base_env && *base_env)
    {
      errno = 0;
      unsigned long base = strtoul(base_env, &end, 0);
      if (errno || end == base_env || *end != '\0' ||
          base > (unsigned long)INT32_MAX - (value - LEGACY_SHM_FIRST + 1))
      {
        log_error("bridge_key: invalid PPSSPP_BRIDGE_SHM_BASE: %s", base_env);
        return 0;
      }
      value = base + (value - LEGACY_SHM_FIRST + 1);
    }
  }

  *key = (key_t)value;
  return 1;
}

/* ───────────────── SYSV ───────────────── */

static BridgeShm sysv_create(key_t key, size_t size)
{
#ifdef DEBUG
  log_console("sysv_create key:%d size:%ld", key, size);
#endif
  BridgeShm s = {.ptr = NULL, .shmid = -1};

  int old = shmget(key, 0, 0600);
  if (old >= 0)
  {
    struct shmid_ds old_info;
    if (shmctl(old, IPC_STAT, &old_info) < 0)
    {
      log_error("sysv_create: cannot inspect existing shmid=%d: %s", old,
                strerror(errno));
      return s;
    }
    if (old_info.shm_nattch != 0 || old_info.shm_perm.uid != geteuid() ||
        old_info.shm_cpid <= 0 ||
        (kill(old_info.shm_cpid, 0) == 0 || errno != ESRCH))
    {
      log_error("sysv_create: refusing to remove existing segment shmid=%d (nattch=%lu owner=%u creator=%d)",
                old, (unsigned long)old_info.shm_nattch,
                (unsigned)old_info.shm_perm.uid, old_info.shm_cpid);
      return s;
    }
#ifdef DEBUG
    log_console("sysv_create: removing stale shmid=%d", old);
#endif
    if (shmctl(old, IPC_RMID, NULL) < 0)
    {
      log_error("sysv_create: shmctl IPC_RMID failed: %s", strerror(errno));
      return s;
    }
  }

  s.shmid = shmget(key, size, IPC_CREAT | IPC_EXCL | 0600);
  if (s.shmid < 0)
  {
    log_error("sysv_create: shmget FAILED key=%d size=%zu errno=%d (%s)", key,
              size, errno, strerror(errno));
    return s;
  }

  s.ptr = shmat(s.shmid, NULL, 0);
  if (s.ptr == (void *)-1)
  {
    log_error("sysv_create: shmat FAILED shmid=%d errno=%d (%s)", s.shmid,
              errno, strerror(errno));
    s.ptr = NULL;
    return s;
  }

  /* IPC_CREAT | IPC_EXCL above guarantees this is a newly created SysV
   * segment, whose pages the kernel initializes to zero. Avoid eagerly
   * touching the full arena; attach paths never clear existing segments.
   * Set PPSSPP_BRIDGE_EAGER_ZERO=1 for an explicit A/B comparison using the
   * previous eager-zero behavior. */
  const char *eager_zero = getenv("PPSSPP_BRIDGE_EAGER_ZERO");
  if (eager_zero && strcmp(eager_zero, "1") == 0)
    memset(s.ptr, 0, size);
  return s;
}

static BridgeShm sysv_attach(key_t key, size_t size)
{
#ifdef DEBUG
  log_console("sysv_attach key:%d size:%ld", key, size);
#endif
  BridgeShm s = {.ptr = NULL, .shmid = -1};

  s.shmid = shmget(key, size, 0600);
  if (s.shmid < 0)
    return s;

  s.ptr = shmat(s.shmid, NULL, 0);
  if (s.ptr == (void *)-1)
  {
    s.ptr = NULL;
  }

  return s;
}

static void sysv_destroy(BridgeShm *s)
{
  if (s->ptr)
  {
    shmdt(s->ptr);
  }

  if (s->shmid >= 0)
  {
    shmctl(s->shmid, IPC_RMID, NULL);
  }
}

/* ───────────────── PUBLIC API ───────────────── */

BridgeShm shm_create(const char *name_or_key, size_t size)
{
  key_t key;
  if (!bridge_key(name_or_key, &key))
    return (BridgeShm){.ptr = NULL, .shmid = -1};
  return sysv_create(key, size);
}

BridgeShm shm_attach(const char *name_or_key, size_t size)
{
  key_t key;
  if (!bridge_key(name_or_key, &key))
    return (BridgeShm){.ptr = NULL, .shmid = -1};
  return sysv_attach(key, size);
}

void shm_detach(BridgeShm *s)
{
  if (!s)
    return;

  if (s->ptr && s->shmid >= 0)
  {
    shmdt(s->ptr);
  }

  s->ptr = NULL;
  s->shmid = -1;
}

void shm_destroy(const char *key, BridgeShm *s)
{
  if (!s)
  {
    log_error("shm_destroy: key: %s - s is NULL", key);
    return;
  }

#ifdef DEBUG
  log_console("shm_destroy: key: %s s->ptr:%p s->shmid:%d", key, s->ptr,
              s->shmid);
#endif

  if (s->ptr != NULL)
    sysv_destroy(s);

  s->ptr = NULL;
  s->shmid = -1;
}
