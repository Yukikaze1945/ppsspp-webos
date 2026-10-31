# Build and source provenance

## Pinned inputs

- PPSSPP: `61865a5c899179d8b71616f774d3133c391281d1` plus `patches/0001-webos-runtime.patch`.
- Bridge: `f44d3cdca74e72f7ebe473707e816bff585495df` (0.0.8); only private adaptations are packaged.
- SDL_ttf: `a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b` (3.2.2).
- ARM64/ARM32 SDK: cscd98/buildroot-nc4 `webos-c14c7bd`; exact download URLs and SHA-256 hashes are constants in `scripts/bootstrap.py`.
- Noto CJK SC: fixed source and checksums in `LICENSES/Noto-SOURCE.txt`.
- PPSSPP recursive submodule revisions: `source-submodules.txt`.

## Verified host: Windows

Install Git, Python 3, CMake, Ninja and LLVM/Clang 22.1.4. Scripts currently expect LLVM at `C:/Program Files/LLVM/bin`. Use a short local checkout path.

```
python scripts/bootstrap.py --sdk --sdk32 --bridge
```

Extract `toolchain/sdk.tar.gz` and `toolchain/sdk-arm32.tar.gz` into `toolchain/`. The SDK tools themselves are Linux-hosted; the verified Windows build uses their headers/libraries through Clang. Windows tar may report unrelated terminfo case collisions; verify that the target sysroot headers and libraries exist. Prefer a Linux filesystem when fully extracting a Linux SDK.

```
powershell -ExecutionPolicy Bypass -File scripts/build-windows.ps1
```

Output: `build/org.ppsspp.webos_0.1.10_arm.ipk`. The main program is AArch64; `service/gles_proxy` and helpers are ARM32 softfp with `/lib/ld-linux.so.3`. The ARM64 interpreter points to the separately installed Bridge. CMake uses `WEBOS=ON`, GLES through SDL, and no Vulkan. `-mcpu=cortex-a78` means this build is specifically tuned for the tested G5.

The public package adds all license/source-access documents and resolves libstdc++/libgcc from Bridge instead of duplicating them. Keep the matched private core, Wayland stub and proxy together.

## Linux

After bootstrap, run `bash scripts/build-linux.sh`. It relocates the SDK and builds both ABI components. **This route is provided but was not executed for the release**; no Linux build result is claimed.

## Full source archive

The release's corresponding-source archive contains populated source/dependency trees in the same relative layout. Its `SOURCE_SNAPSHOT.json` records provenance. It omits Git metadata, host caches, compiled binaries, games, keys and user data. To use bootstrap's Git revision checks, obtain the pinned checkouts through bootstrap; the archive also independently supplies the source itself.

The SDK's bundled `libwayland-webos-client` contains generated protocol descriptors. The exact SDK protocol XML files are preserved in `third_party/wayland-webos`; they can be regenerated with a host `wayland-scanner` and the SDK compiler. These Apache-licensed definitions retain their original LG copyright notices.
