#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
set -eu
luna-send -n 1 luna://com.webos.applicationManager/closeByAppId '{"id":"org.ppsspp.webos"}' || true
for pid in $(pidof PPSSPPSDL 2>/dev/null || true); do
    exe=$(readlink /proc/$pid/exe)
    case "$exe" in
        /media/developer/apps/usr/palm/applications/org.ppsspp.webos/PPSSPPSDL|/var/palm/jail/org.ppsspp.webos/media/developer/apps/usr/palm/applications/org.ppsspp.webos/PPSSPPSDL)
            kill -TERM "$pid" || true;;
    esac
done
