# Device validation and limitations

Date: 2026-10-31. Tested device: LG OLED55G5PCA, webOS 25 / 10.3.0, Linux 5.4, 2 GB RAM, Mali-G510. AArch64 emulator with ARM64 JIT; ARM32 softfp graphics proxy; OpenGL ES 3.2 through Bridge 0.0.8; 1920×1080 output.

## Observed results

- Independent desktop installation, Chinese menu, keyboard navigation and mouse clicks: observed; physical mouse clicking Settings confirmed after multi-seat subscription fix.
- BG3 homebrew: actually loaded/rendered, input and emulator save/load exercised on earlier feature builds. Not a claim of compatibility with every PSP game.
- Cave Story: audible music physically confirmed. BG3 audio and complete controller mapping were not separately re-accepted after every revision.
- ARM64 JIT: logs recorded execution of 264 native compiled blocks. A separate executable-memory probe is supplemental, not the only evidence.
- USB content browsing: read-only mounts within this app's jail verified; host USB remains writable. Remote Back observed as Linux key 412 and mapped to Escape.
- Foreground-game screensaver: BG3 title screen remained visible for five minutes without injected input. Entering the emulator pause menu restored natural screensaver activation after about three minutes. Full IPK desktop menu/close/relaunch checked. The five-minute game window used the same native jail directly, not a repeated manual desktop selection test.
- Process shutdown/relaunch and per-run Bridge shared-memory cleanup checked on device. Full audio-menu-exit regression remains separate.

## Performance evidence

An intermittent stall was traced to unfair Wayland-channel lock acquisition. FIFO handoff prevents the polling thread repeatedly overtaking a render request. These are observed emulated-frame flips, **not physical display scanout or GPU execution timings**.

| Same-boot BG3 replay | Duration | Mean FPS | P95 frame ms | P99 frame ms | Max ms | >100 ms flips |
|---|---:|---:|---:|---:|---:|---:|
| FIFO off | 60 s | 55.75 | 25.74 | 59.07 | 557.53 | 7 |
| FIFO on | 90 s | 59.25 | 22.37 | 31.53 | 82.87 | 0 |

Normal no-span-timing 90-second replays measured 58.88 FPS at 1× and 59.50 at 2×, both with zero >100 ms flips. Earlier outliers remain unexplained; these short windows do not establish universal stable 60 FPS. Other TV activity, scheduling and paging are confounders. No CPU governor, system driver or thermal policy was changed.

Avoiding redundant eager zeroing reduced app-plus-proxy PSS by about 65.1 MiB in a menu comparison. Do not add shared RSS twice or treat this as a separately proven stutter fix.

Raw private logs and physical photos are intentionally not published. This summary reports the recorded measurements without device access details, user paths or game data. Generic collectors/analysis scripts are included under `diagnostics/`.

## Outstanding

- Broader game/firmware compatibility, long soaks, full controller mappings, audio/video synchronization, Bluetooth reconnect stress and USB hotplug refresh.
- PSP XMB/official firmware path has not been accepted.
- ARM32 standalone PPSSPP was not built for a matched comparison. A separate ARM64 RetroArch installation displayed BG3, but no controlled performance comparison against it is claimed.
- Original screen-saver subscription and per-app manual policy returned success but failed visibly; the final timer-reset implementation replaced them.
- An extra logical-pointer focus-handoff experiment black-screened on restart and was removed. The smaller per-real-seat subscription fix is the release implementation.
- Linux build scripts remain unexecuted on the release host.

Treat this as an experimental, device-specific community release.
