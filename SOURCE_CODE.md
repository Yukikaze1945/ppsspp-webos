# Corresponding source

For every published IPK, the matching release at
https://github.com/Yukikaze1945/ppsspp-webos/releases
provides a separately named `ppsspp-webos-0.1.10-corresponding-source.tar.gz` beside the binary and checksums.

That archive includes the patched PPSSPP source and source dependencies used by this build, the complete project build/installation scripts, app-private Bridge adaptations and pinned upstream Bridge source, SDL_ttf source, licenses, pinned font and the SDK's protocol XML definitions. Unused pspautotests/frametests corpora and prebuilt foreign-platform binaries are omitted. Compiler/system-library dependencies are documented in `docs/BUILD.md` and the bootstrap script. This is source delivery alongside the binary, not a promise to provide unavailable source later.

The ordinary repository contains the smaller patch-and-bootstrap form. `python scripts/bootstrap.py --sdk --sdk32 --bridge` fetches the documented source revisions and build SDKs. SDK downloads and external runtime dependencies are not included in the IPK. Use your own TV access and content.
