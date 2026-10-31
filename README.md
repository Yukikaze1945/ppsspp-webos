# PPSSPP for LG webOS — community port

An **unofficial standalone AArch64 PPSSPP app** for rooted LG webOS TVs. It opens PPSSPP's own interface, not RetroArch. Tested on an LG G5 (webOS 25 / 10.3.0), with a 1920×1080 window, ARM64 JIT, OpenGL ES and PulseAudio.

[中文说明](README.zh-CN.md) · [Build](docs/BUILD.md) · [Validation and limits](docs/VALIDATION.md) · [Licensing](THIRD_PARTY_NOTICES.md)

This is an experimental device-tested release, not an official PPSSPP or LG product. The emulator, JIT and most platform infrastructure are upstream work; this repository contains community integration and fixes. Other TV models and firmware versions are unverified. The build is tuned for Cortex-A78.

## Requirements

- Rooted webOS TV with an AArch64 kernel and ARM32 graphics drivers.
- [webOSBrew 64-to-32 Bridge v0.0.8](https://github.com/webosbrew/webos-bridge-64to32/releases/tag/v0.0.8), installed separately. Test its cube first.
- Homebrew Channel's root execution service, used by fixed app-owned helpers for USB visibility and foreground-game screensaver activity.
- A keyboard or compatible controller. Controller mappings may need adjustment.

## Install

Download the IPK from [Releases](https://github.com/Yukikaze1945/ppsspp-webos/releases). It uses application ID `org.ppsspp.webos`; it will replace earlier community builds with that ID. Back up your own data before replacing another build.

Use webOS Dev Manager or your existing SSH installation workflow. The IPK's installer architecture is `arm` for webOS compatibility; the **PPSSPPSDL executable is AArch64**. Only the graphics proxy and small helpers are ARM32 softfp.

When using the included TV-side installer, upload the IPK to `/tmp/`, and upload `install-tv.sh` and `fix-data-owner-tv.sh` to `/media/developer/ppsspp-webos-test/`. Run the installer on the TV. It verifies installation, checks the loader and launches the app. No personal SSH key or TV address is included.

## Games, settings and saves

No games, commercial firmware, user configuration or saves are included. Supply your own legally obtained content.

Persistent data is under `/media/developer/ppsspp-webos-data`:

- `PSP/GAME`: homebrew; ISO/CSO/PBP can also be selected through the browser.
- `PSP/SAVEDATA`: in-game saves; `PSP/PPSSPP_STATE`: emulator save states.
- `PSP/SYSTEM`: settings and controller mappings.

USB drives are exposed read-only **inside this app's jail** at startup, without changing the host drive's original mount. Browse `/tmp/usb` to find your partition. Reopen PPSSPP after plugging in a drive. Saves stay on TV storage.

LG remote Back is mapped to Escape. Foreground game activity resets the existing LG screensaver countdown; it stops in the emulator pause menu, when backgrounded or on exit. It does not permanently disable the TV's screensaver settings.

Delete the app through the TV's application editor to uninstall it. Its external data directory is retained. Bridge remains a separately installed dependency.

## Source and build

The small Git repository contains pinned bootstrap scripts, the complete local Bridge adaptations, and a PPSSPP patch. Releases also provide a **full corresponding-source archive**, including the patched upstream tree and dependencies used by this build, SDL_ttf and Bridge sources. Unused test corpora and foreign-platform prebuilt binaries are omitted. Do not confuse GitHub's automatic repository zip with that full archive.

The verified build host is Windows with Clang 22.1.4, CMake, Ninja, Python and Git; Linux scripts are included but have not been executed for this release. See [docs/BUILD.md](docs/BUILD.md) for exact revisions and commands.

## License and credits

The combined port is distributed under **GPLv3**, preserving each component's original terms. PPSSPP permits GPLv2-or-later; the included Bridge-derived code is GPLv3. SDL_ttf, cJSON, protocol definitions and the CJK font retain their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), [LICENSE](LICENSE) and [SOURCE_CODE.md](SOURCE_CODE.md).

Thanks to [PPSSPP](https://github.com/hrydgard/ppsspp), [webOSBrew Bridge](https://github.com/webosbrew/webos-bridge-64to32), [Buildroot SDK maintainers](https://github.com/cscd98/buildroot-nc4), SDL, FFmpeg, Noto and all upstream contributors. The native webOS CMake/FFmpeg support predates this repository.
