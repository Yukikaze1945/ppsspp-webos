# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
param()
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot
$sdk=Join-Path $root 'toolchain/arm-webos-linux-gnueabi_sdk-buildroot'
$sysroot=Join-Path $sdk 'arm-webos-linux-gnueabi/sysroot'
New-Item -ItemType Directory -Force "$root/stage/service" | Out-Null
& 'C:/Program Files/LLVM/bin/clang.exe' --target=arm-webos-linux-gnueabi "--gcc-toolchain=$sdk" "--sysroot=$sysroot" -march=armv7-a -mfpu=neon -mfloat-abi=softfp -marm -std=c11 -O2 -Wall -Wextra -Werror '-Wl,--dynamic-linker=/lib/ld-linux.so.3' "$root/platform/usb/usb_mount.c" -o "$root/stage/service/usb-mount-helper"
if ($LASTEXITCODE) { throw 'USB helper build failed' }
