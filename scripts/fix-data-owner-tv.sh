#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
set -eu
APP=/media/developer/apps/usr/palm/applications/org.ppsspp.webos
DATA=/media/developer/ppsspp-webos-data
[ "$(readlink -f "$DATA")" = "$DATA" ] || exit 1
count=0
while [ "$count" -lt 15 ]; do
    for pid in $(pidof PPSSPPSDL 2>/dev/null || true); do
        exe=$(readlink /proc/$pid/exe)
        case "$exe" in
            "$APP/PPSSPPSDL"|"/var/palm/jail/org.ppsspp.webos$APP/PPSSPPSDL") ;;
            *) continue;;
        esac
        owner=$(awk '/^Uid:/{print $2}' /proc/$pid/status)
        group=$(awk '/^Gid:/{print $2}' /proc/$pid/status)
        case "$owner:$group" in *[!0-9:]*|:*) exit 2;; esac
        [ "$owner" != 0 ] || continue
        chown -R "$owner:$group" "$DATA"
        echo "PPSSPP data owner set to $owner:$group"
        exit 0
    done
    count=$((count + 1))
    sleep 1
done
echo 'No desktop PPSSPP process found; data owner not changed' >&2
exit 1
