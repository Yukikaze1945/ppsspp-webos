#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
set -eu
APP=org.ppsspp.webos
DATA=/media/developer/ppsspp-webos-data
mkdir -p "$DATA/PSP/SYSTEM"
if [ ! -f "$DATA/PSP/SYSTEM/ppsspp.ini" ]; then
    cat > "$DATA/PSP/SYSTEM/ppsspp.ini" <<'EOF'
[CPU]
CPUCore = 1
[Graphics]
GraphicsBackend = 0
InternalResolution = 1
FullScreen = True
ShowSpeed = 3
EOF
fi
timeout 35 luna-send -i luna://com.webos.appInstallService/dev/install '{"id":"org.ppsspp.webos","ipkUrl":"/tmp/org.ppsspp.webos_0.1.10_arm.ipk","subscribe":true}' > "$DATA/install.log" 2>&1 || true
cat "$DATA/install.log"
grep -q 'installed' "$DATA/install.log"
B=/media/developer/apps/usr/palm/applications/org.webosbrew.bridge-64to32
A=/media/developer/apps/usr/palm/applications/$APP
"$B/lib/ld-linux-aarch64.so.1" --list "$A/PPSSPPSDL" > "$DATA/loader.log" 2>&1
cat "$DATA/loader.log"
if [ "${INSTALL_ONLY:-0}" != 1 ]; then
    luna-send -n 1 luna://com.webos.applicationManager/launch '{"id":"org.ppsspp.webos"}'
    sh /media/developer/ppsspp-webos-test/fix-data-owner-tv.sh
fi
