#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
# Only remove the four fixed Bridge segments proven to belong to a departed test PID.
set -eu
creator=${1:?Pass the recorded PPSSPP test PID}
case "$creator" in *[!0-9]*|'') exit 2;; esac
[ ! -d "/proc/$creator" ] || { echo 'Creator PID still exists; refusing cleanup'; exit 1; }
awk -v creator="$creator" 'NR>1 && $5==creator && $7==0 && $1>=18177 && $1<=18180 {print $2}' /proc/sysvipc/shm |
while read -r id; do
    echo "Removing unattached PPSSPP test segment $id (creator $creator)"
    ipcrm -m "$id"
done
