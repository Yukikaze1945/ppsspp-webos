# Community modifications — 2026-10-31

This document describes the modified build and distinguishes it from upstream releases. Upstream copyright and licensing notices remain in their respective files. Source file change notices refer here.

- `patches/0001-webos-runtime.patch`: PPSSPP's standalone SDL/webOS startup, native shell attachment, app-private loader paths, ARM64 JIT diagnostics, CJK fallback, memory mapping and instance lifecycle integration; optional frame/CPU/GLES diagnostics. It uses existing upstream emulation/JIT implementations.
- `platform/bridge`: private copies/adaptations of Bridge 0.0.8. Changes include FIFO handoff of the synchronous Wayland channel, per-run IPC namespace, kernel last-detach cleanup, avoiding redundant eager memory writes, keyboard fallback/remote Back, pointer event forwarding and subscriptions across actual input seats. Diagnostic timing is opt-in. The installed system Bridge is not replaced.
- `platform/usb`: fixed root helper to bind verified USB mounts read-only into this app's native jail.
- `platform/screensaver`: an ordinary-UID helper with fresh-game-heartbeat and compositor-foreground checks, resetting the existing LG idle timer only while appropriate. No permanent global timer setting is changed.
- `scripts`, `toolchain`, `packaging`: pinned source/bootstrap, Windows Clang and Linux cross-build scripts, reproducible IPK assembly and installation helpers.
- Publication: added component licenses, source access instructions, modification notices and privacy-clean documentation. Removed redundant C++ runtime copies from the public IPK; it resolves the identical copies from the required Bridge installation. No new emulator behavior is introduced by this packaging step.

Rejected buffer-upload experiments and a pointer focus-handoff experiment are not enabled in this release. Limitations are recorded in `docs/VALIDATION.md`.
