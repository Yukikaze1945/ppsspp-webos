# Licensing and upstream attribution

The combined community port is conveyed under **GNU GPL version 3**. This does not replace the original license of any separately identifiable component. No exclusive ownership of upstream PPSSPP, Bridge, SDL or other libraries is claimed.

| Component | Source/version | Original terms |
|---|---|---|
| PPSSPP and community changes to it | hrydgard/ppsspp `61865a5c899179d8b71616f774d3133c391281d1` | GPL-2.0-or-later; original PSPSDK notices retained in `LICENSES/PPSSPP.txt` |
| Bridge core, Wayland stub/proxy and adaptations | webosbrew/webos-bridge-64to32 `f44d3cdca74e72f7ebe473707e816bff585495df` (0.0.8) | GPLv3, see root LICENSE and upstream source |
| App-owned build/installation scripts and helpers | This repository, modifications dated 2026-10-31 | GPL-3.0-only unless a file retains other upstream terms |
| SDL_ttf | libsdl-org/SDL_ttf `a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b` | zlib, see `LICENSES/SDL_ttf.txt` |
| cJSON in Bridge | Dave Gamble and cJSON contributors | MIT, see `LICENSES/cJSON.txt` |
| webOS Wayland protocol definitions/client DSO | SDK webos-c14c7bd, LG Electronics protocol definitions under `third_party/wayland-webos` | Apache-2.0 and the per-file copyright notices; see `LICENSES/Apache-2.0.txt` |
| Noto Sans CJK SC font | notofonts/noto-cjk Sans2.004 | SIL OFL 1.1; exact source/checksum in `LICENSES/Noto-SOURCE.txt` |
| FFmpeg and other statically built PPSSPP dependencies | Pinned PPSSPP tree/submodules | Their original licenses remain in the corresponding-source archive; FFmpeg LGPL 2.1 text is also copied here |

Additional upstream license files are copied under `LICENSES/upstream/` and included in the app package. The full source archive retains the original license and copyright files throughout each tree. See `source-submodules.txt` for the recorded submodule revisions.

SDL3, FreeType, glibc, GCC runtime libraries and the installed graphics stack are supplied by the separately installed Bridge/TV environment. The public IPK does **not** redistribute the redundant libstdc++/libgcc copies present in earlier private test packages: their hashes were verified identical to Bridge 0.0.8's copies. The executable search path already includes Bridge's library directory.

The public package includes the same functional emulator, proxy and helper binaries tested as 0.1.10, plus license/source-access documents. Publication source annotations mark changed files; they do not change the executable logic. PPSSPP's original notices and in-app attribution remain intact. This is an unofficial modified build, not an upstream release.

No PSP game, commercial firmware, private SDK credential, TV key, personal configuration or user save is part of this distribution.
