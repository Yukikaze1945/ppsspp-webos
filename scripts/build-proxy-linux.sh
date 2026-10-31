#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ARCHIVE="${SDK32_ARCHIVE:-$ROOT/toolchain/sdk-arm32.tar.gz}"
SDK_ARCHIVE_SHA256="61ada10c6b2b94510968b99137762cbd7a7956b4bdc4e456792ae8bbe000410e"
SDK="${SDK32_DIR:-$ROOT/toolchain/arm-webos-linux-gnueabi_sdk-buildroot}"
SYSROOT="$SDK/arm-webos-linux-gnueabi/sysroot"
CC="${CC_32:-$SDK/bin/arm-webos-linux-gnueabi-gcc}"
REF="$ROOT/reference/bridge-v008"
PROXY="$REF/proxy"
BRIDGE="$REF/bridge"
SDK_INCLUDE="$SYSROOT/usr/include"
SDK_LIB="$SYSROOT/usr/lib"
BUILD="${PROXY32_BUILD_DIR:-$ROOT/build/proxy-arm32-linux}"
GEN="$BUILD/generated"
GEN_TOOLS="$GEN/tools"
GEN_PROXY="$GEN/proxy"
OUTPUT="${PROXY32_OUTPUT:-$ROOT/stage/service/gles_proxy}"

fail() { echo "build-proxy-linux.sh: error: $*" >&2; exit 1; }

[[ -f "$SDK_ARCHIVE" ]] || fail "ARM32 SDK archive missing: $SDK_ARCHIVE (run python scripts/bootstrap.py --sdk32)"
echo "$SDK_ARCHIVE_SHA256  $SDK_ARCHIVE" | sha256sum --check --status || fail "ARM32 SDK archive SHA-256 mismatch: $SDK_ARCHIVE"
if [[ ! -f "$SDK_INCLUDE/wayland-webos-shell-client-protocol.h" || ! -x "$CC" ]]; then
    tar -xzf "$SDK_ARCHIVE" -C "$(dirname "$SDK")"
fi
[[ -f "$SDK/relocate-sdk.sh" ]] || fail "ARM32 SDK relocate script missing: $SDK/relocate-sdk.sh"
[[ -x "$CC" ]] || fail "ARM32 GCC missing or not executable: $CC"
[[ -f "$SDK_INCLUDE/wayland-webos-shell-client-protocol.h" ]] || fail "ARM32 webOS Wayland headers missing under $SDK_INCLUDE"
[[ -d "$SDK_LIB" ]] || fail "ARM32 SDK library directory missing: $SDK_LIB"
[[ -f "$ROOT/platform/bridge/proxy_wl.c" && -f "$ROOT/platform/bridge/pointer_wire.h" ]] || fail "private proxy pointer sources are missing"
[[ -f "$REF/proxy/protocol/wl.h" ]] || fail "Bridge v0.0.8 source is missing: $REF"
[[ "$(python "$ROOT/scripts/source_revision.py" reference/bridge-v008)" == "f44d3cdca74e72f7ebe473707e816bff585495df" ]] || fail "Bridge source must be v0.0.8 commit f44d3cdca74e72f7ebe473707e816bff585495df"

# Relocation updates toolchain-wrapper/sysroot references for this Linux path.
bash "$SDK/relocate-sdk.sh" "$SDK"

mkdir -p "$GEN_TOOLS" "$GEN_PROXY" "$(dirname "$OUTPUT")"
cp "$REF/tools/gen_gles2_sigs.py" "$GEN_TOOLS/"
cp "$REF/tools/gen_egl_sigs.py" "$GEN_TOOLS/"
cp "$SDK_INCLUDE/GLES2/gl2ext.h" "$GEN_TOOLS/gl2ext.h"
cp "$SDK_INCLUDE/EGL/eglext.h" "$GEN_TOOLS/eglext.h"
(
    cd "$GEN_TOOLS"
    python3 gen_gles2_sigs.py
    python3 gen_egl_sigs.py
)
# Use the SDK's generated protocol descriptors without invoking wayland-scanner.
printf '%s\n' '#include <wayland-webos-shell-client-protocol.h>' > "$GEN_PROXY/webos-shell-32.h"
printf '%s\n' '#include <wayland-webos-input-manager-client-protocol.h>' > "$GEN_PROXY/webos-input-manager-32.h"

CFLAGS=(
    --sysroot="$SYSROOT" -march=armv7-a -mfpu=neon -mfloat-abi=softfp -marm
    -std=c11 -O2 -fPIC -pthread -D_GNU_SOURCE -DDEBUG_TO_LOGFILE
    -DHAVE_OWN_WAYLAND_CLIENT -DHAVE_OWN_WAYLAND_EGL
    -I"$GEN_PROXY" -I"$GEN_TOOLS" -I"$PROXY" -I"$BRIDGE" -I"$REF/include"
    -I"$SDK_INCLUDE" -I"$ROOT/platform/bridge"
)

SOURCES=(
    "bridge_config|$ROOT/platform/bridge/bridge_config.c"
    "proxy|$ROOT/platform/bridge/proxy.c"
    "egl|$PROXY/protocol/egl.c"
    "gles2|$PROXY/protocol/gles2.c"
    "shaders|$PROXY/tests/shaders.c"
    "bridge_shm|$ROOT/platform/bridge/bridge_shm.c"
    "shared_util|$ROOT/platform/bridge/shared_util.c"
    "gles2_invoke_dynamic|$GEN_TOOLS/gles2_invoke_dynamic.c"
    "gles3_2|$PROXY/protocol/gles3_2.c"
    "egl_invoke_dynamic|$GEN_TOOLS/egl_invoke_dynamic.c"
    "proxy_wl|$ROOT/platform/bridge/proxy_wl.c"
    "wl_egl|$PROXY/protocol/wl_egl.c"
)
OBJECTS=()
for item in "${SOURCES[@]}"; do
    name="${item%%|*}"
    source="${item#*|}"
    object="$BUILD/$name.o"
    mkdir -p "$BUILD"
    "$CC" "${CFLAGS[@]}" -c "$source" -o "$object"
    OBJECTS+=("$object")
done

"$CC" --sysroot="$SYSROOT" -march=armv7-a -mfpu=neon -mfloat-abi=softfp -marm \
    -pthread -L"$SDK_LIB" -Wl,-rpath-link,"$SDK_LIB" \
    -Wl,--dynamic-linker=/lib/ld-linux.so.3 "${OBJECTS[@]}" \
    -Wl,--no-as-needed -lGLESv2 -lEGL -lwayland-client -lwayland-egl \
    -lwayland-webos-client -lrt -lpthread -ldl -lm -latomic -Wl,--as-needed \
    -o "$OUTPUT"

if command -v readelf >/dev/null 2>&1; then
    headers="$(readelf -h "$OUTPUT")"
    program_headers="$(readelf -l "$OUTPUT")"
    grep -Eq 'Class:[[:space:]]+ELF32' <<<"$headers" || fail 'output is not ELF32'
    grep -Eq 'Machine:[[:space:]]+ARM' <<<"$headers" || fail 'output is not EM_ARM'
    grep -q '/lib/ld-linux.so.3' <<<"$program_headers" || fail 'unexpected ELF interpreter'
    grep -Eq 'soft-float ABI' <<<"$headers" || fail 'output is not ARM softfp'
    ! grep -Eq 'hard-float ABI' <<<"$headers" || fail 'output advertises hard-float ABI'
else
    echo 'build-proxy-linux.sh: warning: readelf unavailable; ELF ABI checks skipped' >&2
fi
echo "Built ARMv7 ELF32 proxy: $OUTPUT"

"$CC" --sysroot="$SYSROOT" -march=armv7-a -mfpu=neon -mfloat-abi=softfp -marm \
    -std=c11 -O2 -Wall -Wextra -Werror -Wl,--dynamic-linker=/lib/ld-linux.so.3 \
    "$ROOT/platform/usb/usb_mount.c" -o "$ROOT/stage/service/usb-mount-helper"

"$CC" --sysroot="$SYSROOT" -march=armv7-a -mfpu=neon -mfloat-abi=softfp -marm \
    -std=c11 -O2 -Wall -Wextra -Werror -I"$REF/deps" \
    -Wl,--dynamic-linker=/lib/ld-linux.so.3 \
    "$ROOT/platform/screensaver/guard.c" "$REF/deps/cJSON.c" -lm -lrt \
    -o "$ROOT/stage/service/screensaver-guard"
