# LG webOS 独立 PPSSPP 社区移植版

这是非官方的独立 **ARM64 / AArch64** 应用，打开即进入 PPSSPP 自己的界面。模拟器、ARM64 JIT、基础 webOS 支持和 Bridge 都复用上游；本仓库公开电视集成与修复代码。

已实测 LG G5、webOS 25 / 10.3.0。它仍是实验性版本，其他机型、完整手柄映射和所有游戏兼容性没有保证。当前编译针对 Cortex-A78 优化。

## 安装与使用

1. 电视需 Root，并安装 Homebrew Channel 和 [64-to-32 Bridge 0.0.8](https://github.com/webosbrew/webos-bridge-64to32/releases/tag/v0.0.8)。先确认 Bridge 测试能显示。
2. 从 [Releases](https://github.com/Yukikaze1945/ppsspp-webos/releases) 下载 IPK，用现有 webOS Dev Manager / SSH 方法安装。
3. 应用 ID 为 `org.ppsspp.webos`，会覆盖相同 ID 的旧社区版。先自行备份已有数据。
4. 包名里的 `arm` 是安装器元数据；模拟器主体实际是 **64 位 ELF**。图形代理和小助手才是 32 位。

不附带游戏、商业固件、私人设置和存档。用户数据保留在 `/media/developer/ppsspp-webos-data`，游戏内存档在 `PSP/SAVEDATA`，即时存档在 `PSP/PPSSPP_STATE`。

U盘从 `/tmp/usb` 浏览，启动时只读接入本应用沙箱，不修改宿主挂载；存档继续写电视。插入新U盘后重启应用刷新。遥控器返回键对应 Escape，进入游戏暂停菜单。游戏前台活动时阻止自然屏保，模拟器暂停菜单恢复原有空闲计时。

卸载可在电视应用编辑界面删除。外置用户数据保留；不要为卸载本应用而删除其他应用也会使用的 Bridge。

## 开发和许可证

本次实际构建环境为 Windows Clang 22.1.4；Linux 脚本尚未在本机验证。构建步骤见 [BUILD.md](docs/BUILD.md)，测试边界见 [VALIDATION.md](docs/VALIDATION.md)。发布附件同时提供完整对应源码，而不只是零散补丁。

PPSSPP 原代码允许 GPLv2 或更高版本；本组合包含 GPLv3 的 Bridge 代码，因此整体按 GPLv3 发布，保留所有原版权和第三方许可证。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。这是社区移植，不代表 PPSSPP、LG 或 webOSBrew 官方发行。
