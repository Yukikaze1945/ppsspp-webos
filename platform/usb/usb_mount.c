/* SPDX-License-Identifier: GPL-3.0-only
 * webOS community adaptation, modified 2026-10-31.
 * Bridge-derived files retain their upstream provenance; see THIRD_PARTY_NOTICES.md.
 */
#define _GNU_SOURCE
#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <mntent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>

#define JAIL "/var/palm/jail/org.ppsspp.webos"

/* No arguments and no caller-supplied paths. Only kernel-listed USB disk
 * mounts can be exposed, read-only, in this application's existing jail. */
static int usb_mount(const struct mntent *m) {
    if (strncmp(m->mnt_fsname, "/dev/sd", 7) ||
        strncmp(m->mnt_dir, "/tmp/usb/sd", 11)) return 0;
    for (const char *p=m->mnt_dir+9; *p; ++p)
        if (!isalnum((unsigned char)*p) && *p!='/') return 0;
    char resolved[PATH_MAX];
    return realpath(m->mnt_dir,resolved) && !strcmp(resolved,m->mnt_dir);
}

static int safe_directory(char *path) {
    /* Reject symlinks throughout the fixed destination before mount/unmount. */
    for (char *p=path+1;; ++p) {
        if (*p && *p!='/') continue;
        const char saved=*p; *p=0;
        struct stat st;
        if (mkdir(path,0755)<0 && errno!=EEXIST) { *p=saved; return -1; }
        if (lstat(path,&st)<0 || !S_ISDIR(st.st_mode)) { *p=saved; return -1; }
        *p=saved;
        if (!saved) return 0;
    }
}

int main(int argc,char **argv) {
    (void)argv;
    if (argc!=1 || geteuid()!=0) {
        fprintf(stderr,"USB helper requires root and takes no arguments\n"); return 2;
    }
    struct stat st;
    if (lstat(JAIL,&st)<0 || !S_ISDIR(st.st_mode)) {
        fprintf(stderr,"PPSSPP jail is not ready\n"); return 1;
    }
    FILE *mounts=setmntent("/proc/mounts","r");
    if (!mounts) return 1;
    int count=0,errors=0;
    struct mntent *m;
    while ((m=getmntent(mounts))) {
        if (!usb_mount(m)) continue;
        char target[PATH_MAX];
        if (snprintf(target,sizeof(target),"%s%s",JAIL,m->mnt_dir)>=(int)sizeof(target) ||
            safe_directory(target)<0) { ++errors; continue; }
        /* Refresh this app's old bind after a drive has been reinserted. */
        if (umount2(target,MNT_DETACH)<0 && errno!=EINVAL && errno!=ENOENT) {
            fprintf(stderr,"USB unmount %s: %s\n",target,strerror(errno)); ++errors; continue;
        }
        if (mount(m->mnt_dir,target,NULL,MS_BIND,NULL)<0) {
            fprintf(stderr,"USB bind %s: %s\n",target,strerror(errno)); ++errors; continue;
        }
        if (mount(NULL,target,NULL,MS_BIND|MS_REMOUNT|MS_RDONLY|MS_NOSUID|MS_NODEV|MS_NOEXEC,NULL)<0) {
            fprintf(stderr,"USB read-only remount %s: %s\n",target,strerror(errno));
            umount2(target,MNT_DETACH); ++errors; continue;
        }
        printf("USB mounted read-only: %s\n",m->mnt_dir); ++count;
    }
    endmntent(mounts);
    printf("USB partitions=%d errors=%d\n",count,errors);
    return errors?1:0;
}
