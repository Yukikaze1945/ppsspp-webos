# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
param(
    [string]$LlvmBin = 'C:\Program Files\LLVM\bin',
    [string]$SdkRoot = ''
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($SdkRoot)) {
    $SdkRoot = Join-Path $root 'toolchain/aarch64-webos-linux-gnu_sdk-buildroot'
}
$sdk = [System.IO.Path]::GetFullPath($SdkRoot)
$sysroot = Join-Path $sdk 'aarch64-webos-linux-gnu/sysroot'
$bridgeSysroot = Join-Path $root 'sysroot'
$reference = Join-Path $root 'reference/bridge-v008'
$source = Join-Path $root 'platform/bridge/wl_stub.c'
$outputDir = Join-Path $root 'stage/lib'
$coreOutput = Join-Path $outputDir 'libgles_bridge_core.so'
$output = Join-Path $outputDir 'libwayland-client.so.0'
$clang = Join-Path $LlvmBin 'clang.exe'
$git = (Get-Command git.exe -ErrorAction Stop).Source

$referenceHead = (& python "$root/scripts/source_revision.py" reference/bridge-v008).Trim()
if ($LASTEXITCODE -ne 0 -or $referenceHead -ne 'f44d3cdca74e72f7ebe473707e816bff585495df') {
    throw "Expected Bridge v0.0.8 source f44d3cdca74e72f7ebe473707e816bff585495df, got $referenceHead"
}
$required = @(
    $clang,
    (Join-Path $sdk 'bin/aarch64-webos-linux-gnu-gcc'),
    (Join-Path $sysroot 'usr/include/wayland-client.h'),
    (Join-Path $sysroot 'usr/include/xkbcommon/xkbcommon.h'),
    (Join-Path $sysroot 'usr/lib/libwayland-cursor.so'),
    (Join-Path $sysroot 'usr/lib/libwayland-egl.so'),
    (Join-Path $sysroot 'usr/lib/libxkbcommon.so'),
    (Join-Path $sysroot 'usr/lib/libwayland-webos-client.so'),
    (Join-Path $sysroot 'usr/lib/libdl.a'),
    (Join-Path $sysroot 'usr/lib/libpthread.a'),
    (Join-Path $bridgeSysroot 'libwayland-client-real.so.0'),
    (Join-Path $reference 'stub/bridge_core.c'),
    (Join-Path $root 'platform/bridge/bridge_config.c'),
    (Join-Path $reference 'include/bridge_config.h'),
    (Join-Path $reference 'deps/cJSON.c'),
    (Join-Path $reference 'deps/cJSON.h'),
    (Join-Path $reference 'stub/wl_stub.c'),
    (Join-Path $reference 'stub/bridge_core.h'),
    (Join-Path $reference 'include/gles_bridge_protocol.h'),
    (Join-Path $reference 'bridge/shared_util.h'),
    $source
)
$missing = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missing.Count -gt 0) {
    throw "Missing required build input(s):`n  $($missing -join "`n  ")"
}

$includeDirs = @(
    (Join-Path $reference 'deps'),
    (Join-Path $reference 'stub'),
    (Join-Path $reference 'include'),
    (Join-Path $reference 'bridge'),
    (Join-Path $sysroot 'usr/include')
)
$outputDir = Split-Path -Parent $output
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$coreBuild = Join-Path $root 'build/bridge-aarch64'
New-Item -ItemType Directory -Force -Path $coreBuild | Out-Null
$commonArgs = @(
    '--target=aarch64-webos-linux-gnu',
    "--sysroot=$sysroot",
    "--gcc-toolchain=$sdk",
    '-fPIC', '-g', '-O1', '-std=c11', '-D_GNU_SOURCE',
    "-I$(Join-Path $sysroot 'usr/include')"
)
foreach ($includeDir in $includeDirs) { $commonArgs += "-I$includeDir" }
$coreSources = @(
    @{ Name='bridge_config'; Path=(Join-Path $root 'platform/bridge/bridge_config.c') },
    @{ Name='bridge_core'; Path=(Join-Path $root 'platform/bridge/bridge_core.c') },
    @{ Name='bridge_shm'; Path=(Join-Path $root 'platform/bridge/bridge_shm.c') },
    @{ Name='shared_util'; Path=(Join-Path $root 'platform/bridge/shared_util.c') },
    @{ Name='cJSON'; Path=(Join-Path $reference 'deps/cJSON.c') }
)
$coreObjects = @()
foreach ($item in $coreSources) {
    $object = Join-Path $coreBuild ($item.Name + '.o')
    & $clang @commonArgs -c $item.Path -o $object
    if ($LASTEXITCODE -ne 0) { throw "clang failed building private Bridge core object $($item.Name)" }
    $coreObjects += $object
}
& $clang '--target=aarch64-webos-linux-gnu' "--sysroot=$sysroot" "--gcc-toolchain=$sdk" -fuse-ld=lld -shared "-L$outputDir" "-L$(Join-Path $sysroot 'usr/lib')" -L"$sysroot/lib" $coreObjects '-Wl,-soname,libgles_bridge_core.so' -lrt -pthread -ldl -o $coreOutput
if ($LASTEXITCODE -ne 0) { throw 'clang failed linking the app-private Bridge core.' }
$coreBytes = [System.IO.File]::ReadAllBytes($coreOutput)
if ($coreBytes.Length -lt 20 -or $coreBytes[0] -ne 0x7f -or $coreBytes[1] -ne 0x45 -or $coreBytes[2] -ne 0x4c -or $coreBytes[3] -ne 0x46 -or $coreBytes[4] -ne 2 -or $coreBytes[18] -ne 183 -or $coreBytes[19] -ne 0) {
    throw 'Private core output is not an ELFCLASS64 AArch64 shared object'
}

$clangArgs = @(
    '--target=aarch64-webos-linux-gnu',
    "--sysroot=$sysroot",
    "--gcc-toolchain=$sdk",
    '-fuse-ld=lld',
    '-shared', '-fPIC', '-g', '-O1',
    '-Wl,-soname,libwayland-client.so.0',
    "-L$outputDir",
    "-L$bridgeSysroot",
    "-L$(Join-Path $sysroot 'usr/lib')",
    "-L$(Join-Path $sysroot 'lib')"
)
foreach ($includeDir in $includeDirs) { $clangArgs += "-I$includeDir" }
$clangArgs += @(
    $source,
    '-Wl,--no-as-needed',
    '-l:libgles_bridge_core.so',
    '-l:libwayland-client-real.so.0',
    '-lwayland-cursor',
    '-lwayland-egl',
    '-lxkbcommon',
    '-lwayland-webos-client',
    '-ldl',
    '-pthread',
    '-Wl,--as-needed',
    '-o', $output
)
& $clang @clangArgs
if ($LASTEXITCODE -ne 0) { throw "clang failed with exit code $LASTEXITCODE" }

$bytes = [System.IO.File]::ReadAllBytes($output)
if ($bytes.Length -lt 20 -or $bytes[0] -ne 0x7f -or $bytes[1] -ne 0x45 -or $bytes[2] -ne 0x4c -or $bytes[3] -ne 0x46 -or $bytes[4] -ne 2 -or $bytes[18] -ne 183 -or $bytes[19] -ne 0) {
    throw 'Output is not an ELFCLASS64 AArch64 shared object'
}
Write-Output "Built ELFCLASS64 AArch64 app-private Bridge core: $coreOutput"
Write-Output "Built ELFCLASS64 AArch64 app-private Wayland stub: $output"
