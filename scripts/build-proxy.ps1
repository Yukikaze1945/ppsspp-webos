# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
[CmdletBinding()]
param(
    [string]$SdkRoot = (Join-Path $PSScriptRoot '..\toolchain\arm-webos-linux-gnueabi_sdk-buildroot'),
    [string]$Archive = (Join-Path $PSScriptRoot '..\toolchain\sdk-arm32.tar.gz'),
    [string]$Output = (Join-Path $PSScriptRoot '..\stage\service\gles_proxy'),
    [string]$Clang = 'C:\Program Files\LLVM\bin\clang.exe'
)

$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$SdkRoot = [System.IO.Path]::GetFullPath($SdkRoot)
$Sysroot = Join-Path $SdkRoot 'arm-webos-linux-gnueabi\sysroot'
$SdkBin = Join-Path $SdkRoot 'bin'
$Ref = Join-Path $Root 'reference\bridge-v008'
$Proxy = Join-Path $Ref 'proxy'
$Bridge = Join-Path $Ref 'bridge'
$SdkInclude = Join-Path $Sysroot 'usr\include'
$SdkLib = Join-Path $Sysroot 'usr\lib'
$Build = Join-Path $Root 'build\proxy-arm32'
$Gen = Join-Path $Build 'generated'
$GenTools = Join-Path $Gen 'tools'
$GenProxy = Join-Path $Gen 'proxy'

if (-not (Test-Path -LiteralPath (Join-Path $Sysroot 'usr\include\wayland-webos-shell-client-protocol.h'))) {
    if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) { throw "32-bit SDK archive missing: $Archive" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SdkRoot) | Out-Null
    & tar.exe -xzf $Archive -C (Split-Path -Parent $SdkRoot)
    if (-not (Test-Path -LiteralPath (Join-Path $Sysroot 'usr\include\wayland-webos-shell-client-protocol.h'))) {
        throw 'SDK extraction did not produce required ARM32 webOS headers; see tar output for unrelated Windows terminfo collisions.'
    }
}
foreach ($required in @(
    (Join-Path $SdkInclude 'wayland-webos-shell-client-protocol.h'),
    (Join-Path $SdkInclude 'wayland-webos-input-manager-client-protocol.h'),
    (Join-Path $SdkInclude 'GLES3\gl32.h'),
    (Join-Path $SdkInclude 'EGL\eglext.h'),
    (Join-Path $SdkInclude 'GLES2\gl2ext.h'),
    (Join-Path $SdkLib 'libGLESv2.so.2.1.0'),
    (Join-Path $SdkLib 'libEGL.so.1.4.0'),
    (Join-Path $SdkLib 'libwayland-webos-client.so.1.0.0')
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Required ARM32 SDK input missing: $required" }
}
if (-not (Test-Path -LiteralPath $Clang -PathType Leaf)) { throw "Clang not found: $Clang" }

New-Item -ItemType Directory -Force -Path $GenTools,$GenProxy,(Split-Path -Parent $Output) | Out-Null
Copy-Item -LiteralPath (Join-Path $Ref 'tools\gen_gles2_sigs.py') -Destination $GenTools
Copy-Item -LiteralPath (Join-Path $Ref 'tools\gen_egl_sigs.py') -Destination $GenTools
Copy-Item -LiteralPath (Join-Path $SdkInclude 'GLES2\gl2ext.h') -Destination (Join-Path $GenTools 'gl2ext.h')
Copy-Item -LiteralPath (Join-Path $SdkInclude 'EGL\eglext.h') -Destination (Join-Path $GenTools 'eglext.h')
Push-Location $GenTools
try {
    & python.exe gen_gles2_sigs.py
    if ($LASTEXITCODE -ne 0) { throw 'GLES signature generator failed.' }
    & python.exe gen_egl_sigs.py
    if ($LASTEXITCODE -ne 0) { throw 'EGL signature generator failed.' }
} finally { Pop-Location }

# The project protocol headers are generated equivalents already shipped by this SDK.
[System.IO.File]::WriteAllText((Join-Path $GenProxy 'webos-shell-32.h'), "#include <wayland-webos-shell-client-protocol.h>`n", [System.Text.UTF8Encoding]::new($false))
[System.IO.File]::WriteAllText((Join-Path $GenProxy 'webos-input-manager-32.h'), "#include <wayland-webos-input-manager-client-protocol.h>`n", [System.Text.UTF8Encoding]::new($false))

$Common = @(
    '--target=arm-webos-linux-gnueabi',
    "--gcc-toolchain=$SdkRoot",
    "--sysroot=$Sysroot",
    '-march=armv7-a', '-mfpu=neon', '-mfloat-abi=softfp', '-marm',
    '-std=c11', '-O2', '-fPIC', '-pthread', '-D_GNU_SOURCE', '-DDEBUG_TO_LOGFILE',
    '-DHAVE_OWN_WAYLAND_CLIENT', '-DHAVE_OWN_WAYLAND_EGL',
    "-I$GenProxy", "-I$GenTools", "-I$Proxy", "-I$Bridge", "-I$Ref\include", "-I$SdkInclude", "-I$Root\platform\bridge"
)
$Sources = @(
    @{ Name='bridge_config'; Path=(Join-Path $Root 'platform\bridge\bridge_config.c') },
    @{ Name='proxy'; Path=(Join-Path $Root 'platform\bridge\proxy.c') },
    @{ Name='egl'; Path=(Join-Path $Proxy 'protocol\egl.c') },
    @{ Name='gles2'; Path=(Join-Path $Proxy 'protocol\gles2.c') },
    @{ Name='shaders'; Path=(Join-Path $Proxy 'tests\shaders.c') },
    @{ Name='bridge_shm'; Path=(Join-Path $Root 'platform\bridge\bridge_shm.c') },
    @{ Name='shared_util'; Path=(Join-Path $Root 'platform\bridge\shared_util.c') },
    @{ Name='gles2_invoke_dynamic'; Path=(Join-Path $GenTools 'gles2_invoke_dynamic.c') },
    @{ Name='gles3_2'; Path=(Join-Path $Proxy 'protocol\gles3_2.c') },
    @{ Name='egl_invoke_dynamic'; Path=(Join-Path $GenTools 'egl_invoke_dynamic.c') },
    @{ Name='proxy_wl'; Path=(Join-Path $Root 'platform\bridge\proxy_wl.c') },
    @{ Name='wl_egl'; Path=(Join-Path $Proxy 'protocol\wl_egl.c') }
)
$Objects = @()
foreach ($source in $Sources) {
    $obj = Join-Path $Build ($source.Name + '.o')
    & $Clang @Common -c $source.Path -o $obj
    if ($LASTEXITCODE -ne 0) { throw "Compile failed: $($source.Path)" }
    $Objects += $obj
}

$LinkHead = @(
    '--target=arm-webos-linux-gnueabi', "--gcc-toolchain=$SdkRoot", "--sysroot=$Sysroot",
    '-march=armv7-a', '-mfpu=neon', '-mfloat-abi=softfp', '-marm',
    '-pthread', "-L$SdkLib", "-Wl,-rpath-link,$SdkLib", '-Wl,--dynamic-linker=/lib/ld-linux.so.3'
)
$LinkTail = @(
    '-Wl,--no-as-needed', '-lGLESv2', '-lEGL', '-lwayland-client', '-lwayland-egl',
    '-lwayland-webos-client', '-lrt', '-lpthread', '-ldl', '-lm', '-latomic',
    '-Wl,--as-needed'
)
& $Clang @LinkHead $Objects @LinkTail -o $Output
if ($LASTEXITCODE -ne 0) { throw 'Link failed for ARM32 proxy.' }

$ReadObj = Join-Path (Split-Path -Parent $Clang) 'llvm-readobj.exe'
if (-not (Test-Path -LiteralPath $ReadObj -PathType Leaf)) { throw "ELF verifier missing: $ReadObj" }
$elf = & $ReadObj --file-headers --program-headers $Output | Out-String
$binaryAscii = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($Output))
if ($LASTEXITCODE -ne 0 -or $elf -notmatch 'Class:\s+32-bit' -or $elf -notmatch 'Machine:\s+EM_ARM') {
    throw "Output is not an ELF32 ARM binary:`n$elf"
}
if ($elf -notmatch '(?m)^\s+0x200\s*$' -or $elf -match '(?m)^\s+0x400\s*$') {
    throw "ELF EABI flags do not identify ARM softfp without VFP argument ABI:`n$elf"
}
if (-not $binaryAscii.Contains('/lib/ld-linux.so.3')) { throw 'ARM ELF does not contain the required /lib/ld-linux.so.3 interpreter string.' }
Write-Host "Built ARMv7 ELF32 proxy: $Output"
Write-Host 'ELF verification: EM_ARM, ELF32, softfp (no hard-float ABI flag).'
