#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ARCHIVE="${SDK_ARCHIVE:-$ROOT/toolchain/sdk.tar.gz}"
SDK="${SDK_DIR:-$ROOT/toolchain/aarch64-webos-linux-gnu_sdk-buildroot}"
SYSROOT="$SDK/aarch64-webos-linux-gnu/sysroot"
TOOL_PREFIX="$SDK/bin/aarch64-webos-linux-gnu-"
TOOLCHAIN_FILE="$ROOT/toolchain/linux-aarch64.cmake"
SDL_TTF_SOURCE="$ROOT/deps/SDL_ttf"
BRIDGE_SOURCE="$ROOT/reference/bridge-v008"
BRIDGE_COMMIT="f44d3cdca74e72f7ebe473707e816bff585495df"
SDL_TTF_BUILD="${SDL_TTF_BUILD_DIR:-$ROOT/build/linux-ttf}"
PPSSPP_BUILD="${PPSSPP_BUILD_DIR:-$ROOT/build/arm64}"
STAGE="$ROOT/stage"
JOBS="${JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4)}"

fail() { echo "build-linux.sh: error: $*" >&2; exit 1; }

[[ -f "$SDK_ARCHIVE" ]] || fail "SDK release archive not found: $SDK_ARCHIVE"
if [[ ! -x "$TOOL_PREFIX"gcc || ! -x "$TOOL_PREFIX"g++ || ! -d "$SYSROOT" ]]; then
    mkdir -p "$(dirname "$SDK")"
    tar -xzf "$SDK_ARCHIVE" -C "$(dirname "$SDK")"
fi
[[ -f "$SDK/relocate-sdk.sh" ]] || fail "SDK relocate script missing under $SDK"
[[ -x "$TOOL_PREFIX"gcc && -x "$TOOL_PREFIX"g++ ]] || fail "AArch64 webOS GCC/G++ missing under $SDK/bin"
[[ -d "$SYSROOT" ]] || fail "SDK sysroot missing: $SYSROOT"

# The SDK release archive stores build-host paths; relocate it for this Linux path.
bash "$SDK/relocate-sdk.sh" "$SDK"

[[ "$(python "$ROOT/scripts/source_revision.py" source)" == "61865a5c899179d8b71616f774d3133c391281d1" ]] || fail "source checkout must be PPSSPP 61865a5c899179d8b71616f774d3133c391281d1"
[[ "$(python "$ROOT/scripts/source_revision.py" deps/SDL_ttf)" == "a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b" ]] || fail "deps/SDL_ttf must be SDL_ttf release-3.2.2 at a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b"
[[ -f "$SDL_TTF_SOURCE/CMakeLists.txt" ]] || fail "SDL_ttf source not found: $SDL_TTF_SOURCE"
[[ -f "$ROOT/source/CMakeLists.txt" ]] || fail "PPSSPP source not found under $ROOT/source"
[[ "$(python "$ROOT/scripts/source_revision.py" reference/bridge-v008)" == "$BRIDGE_COMMIT" ]] || fail "Bridge source must be v0.0.8 commit $BRIDGE_COMMIT; run python scripts/bootstrap.py --bridge"
[[ -f "$ROOT/platform/bridge/wl_stub.c" ]] || fail "app-private bridge stub source missing"
[[ -f "$ROOT/sysroot/libwayland-client-real.so.0" ]] || fail "project-local real Wayland library missing; run python scripts/bootstrap.py --bridge"

mkdir -p "$STAGE/lib"
CORE_BUILD="$ROOT/build/bridge-aarch64-linux"
mkdir -p "$CORE_BUILD"
CORE_CFLAGS=(
    --sysroot="$SYSROOT" -march=armv8-a -Os -fPIC -std=c11 -D_GNU_SOURCE
    -I"$BRIDGE_SOURCE/deps" -I"$BRIDGE_SOURCE/include"
    -I"$BRIDGE_SOURCE/bridge" -I"$BRIDGE_SOURCE/stub"
    -I"$SYSROOT/usr/include"
)
CORE_OBJECTS=()
while IFS='|' read -r name source; do
    object="$CORE_BUILD/$name.o"
    "${TOOL_PREFIX}gcc" "${CORE_CFLAGS[@]}" -c "$source" -o "$object"
    CORE_OBJECTS+=("$object")
done <<EOF
bridge_config|$ROOT/platform/bridge/bridge_config.c
bridge_core|$ROOT/platform/bridge/bridge_core.c
bridge_shm|$ROOT/platform/bridge/bridge_shm.c
shared_util|$ROOT/platform/bridge/shared_util.c
cJSON|$BRIDGE_SOURCE/deps/cJSON.c
EOF
"${TOOL_PREFIX}gcc" --sysroot="$SYSROOT" -shared "${CORE_OBJECTS[@]}" \
    -Wl,-soname,libgles_bridge_core.so -lrt -lpthread -ldl \
    -o "$STAGE/lib/libgles_bridge_core.so"

"${TOOL_PREFIX}gcc" -g -O1 -shared -fPIC \
    -Wl,-soname,libwayland-client.so.0 \
    -I"$BRIDGE_SOURCE/stub" \
    -I"$BRIDGE_SOURCE/include" \
    -I"$BRIDGE_SOURCE/bridge" \
    -I"$SYSROOT/usr/include" \
    -L"$STAGE/lib" -L"$ROOT/sysroot" \
    -L"$SYSROOT/usr/lib" \
    -Wl,--no-as-needed \
    -l:libgles_bridge_core.so \
    "$ROOT/sysroot/libwayland-client-real.so.0" \
    -lwayland-cursor -lwayland-egl -lxkbcommon -lwayland-webos-client -ldl -pthread \
    -Wl,--as-needed \
    "$ROOT/platform/bridge/wl_stub.c" \
    -o "$STAGE/lib/libwayland-client.so.0"

if [[ -f "$PPSSPP_BUILD/CMakeCache.txt" ]] && ! grep -Fq "$ROOT" "$PPSSPP_BUILD/CMakeCache.txt"; then
    fail "existing CMake cache at $PPSSPP_BUILD belongs to a different checkout; set PPSSPP_BUILD_DIR to a clean directory"
fi

cmake -S "$SDL_TTF_SOURCE" -B "$SDL_TTF_BUILD" \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$STAGE" \
    -DSDL3_DIR="$SYSROOT/usr/lib/cmake/SDL3" \
    -DSDLTTF_INSTALL=ON \
    -DSDLTTF_INSTALL_CPACK=ON \
    -DSDLTTF_INSTALL_MAN=OFF \
    -DSDLTTF_SAMPLES=OFF \
    -DSDLTTF_HARFBUZZ=OFF \
    -DSDLTTF_PLUTOSVG=OFF \
    -DSDLTTF_VENDORED=OFF
cmake --build "$SDL_TTF_BUILD" --parallel "$JOBS"
cmake --install "$SDL_TTF_BUILD"

cmake -S "$ROOT/source" -B "$PPSSPP_BUILD" \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN_FILE" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$STAGE" \
    -DWEBOS=ON \
    -DUSING_EGL=OFF \
    -DUSING_GLES2=ON \
    -DARM_NO_VULKAN=ON \
    -DUSE_WAYLAND_WSI=OFF \
    -DHEADLESS=ON \
    -DUNITTEST=OFF \
    -DUSE_DISCORD=OFF \
    -DUSE_MINIUPNPC=OFF \
    -DUSE_SYSTEM_LIBPNG=OFF \
    -DUSE_CCACHE=OFF \
    -DCMAKE_DISABLE_FIND_PACKAGE_Fontconfig=ON \
    -DSDL3_DIR="$SYSROOT/usr/lib/cmake/SDL3" \
    -DSDL3_ttf_DIR="$STAGE/lib/cmake/SDL3_ttf"
cmake --build "$PPSSPP_BUILD" --target PPSSPPSDL PPSSPPHeadless --parallel "$JOBS"
bash "$ROOT/scripts/build-proxy-linux.sh"
python "$ROOT/scripts/package.py" --sdk-sysroot "$SYSROOT"
