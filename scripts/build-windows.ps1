# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
param([int]$Jobs = 10)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot)
function Run-CMake([string[]]$Arguments) {
    & cmake @Arguments
    if ($LASTEXITCODE) { throw "CMake failed ($LASTEXITCODE)" }
}
& "$PSScriptRoot/build-bridge.ps1"
if ($LASTEXITCODE) { throw 'Private Wayland bridge build failed' }
& "$PSScriptRoot/build-proxy.ps1"
if ($LASTEXITCODE) { throw 'Private ARM32 proxy build failed' }
Run-CMake @('-S','deps/SDL_ttf','-B','build/ttf','-G','Ninja',"-DCMAKE_TOOLCHAIN_FILE=$PWD/toolchain/windows-clang-aarch64.cmake",'-DCMAKE_BUILD_TYPE=Release','-DSDLTTF_SAMPLES=OFF','-DSDLTTF_HARFBUZZ=OFF','-DSDLTTF_PLUTOSVG=OFF','-DSDLTTF_INSTALL_MAN=OFF')
Run-CMake @('--build','build/ttf','-j',"$Jobs")
Run-CMake @('--install','build/ttf')
$bridge='/media/developer/apps/usr/palm/applications/org.webosbrew.bridge-64to32'
$app='/media/developer/apps/usr/palm/applications/org.ppsspp.webos'
$linkFlags="-Wl,--dynamic-linker,$bridge/lib/ld-linux-aarch64.so.1 -Wl,--disable-new-dtags,-rpath,${app}/lib:${bridge}/lib:${bridge}/lib/pulseaudio"
Run-CMake @('-S','source','-B','build/arm64','-G','Ninja',"-DCMAKE_TOOLCHAIN_FILE=$PWD/toolchain/windows-clang-aarch64.cmake",'-DCMAKE_BUILD_TYPE=Release','-DWEBOS=ON','-DUSING_EGL=OFF','-DUSING_GLES2=ON','-DARM_NO_VULKAN=ON','-DUSE_WAYLAND_WSI=OFF','-DHEADLESS=ON','-DUNITTEST=OFF','-DUSE_DISCORD=OFF','-DUSE_MINIUPNPC=OFF','-DUSE_SYSTEM_LIBPNG=OFF','-DUSE_CCACHE=OFF','-DCMAKE_DISABLE_FIND_PACKAGE_Fontconfig=ON',"-DCMAKE_EXE_LINKER_FLAGS=$linkFlags")
Run-CMake @('--build','build/arm64','--target','PPSSPPSDL','PPSSPPHeadless','-j',"$Jobs")
& "$PSScriptRoot/build-usb.ps1"
if ($LASTEXITCODE) { throw 'USB helper build failed' }
& "$PSScriptRoot/build-screensaver.ps1"
if ($LASTEXITCODE) { throw 'Screensaver helper build failed' }
& python scripts/package.py --sdk-sysroot toolchain/aarch64-webos-linux-gnu_sdk-buildroot/aarch64-webos-linux-gnu/sysroot
if ($LASTEXITCODE) { throw 'Packaging failed' }
