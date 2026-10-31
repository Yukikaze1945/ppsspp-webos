#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
"""Build a webOS IPK for PPSSPP from already-built, verified inputs."""

from __future__ import annotations

import argparse
import io
import gzip
import os
import stat
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "org.ppsspp.webos"
VERSION = "0.1.10"
APP_ROOT = f"usr/palm/applications/{APP_ID}"
OUTPUT = ROOT / "build" / f"{APP_ID}_{VERSION}_arm.ipk"


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"package.py: error: {message}")


def check_aarch64_elf(path: Path) -> None:
    try:
        with path.open("rb") as stream:
            header = stream.read(20)
    except OSError as exc:
        fail(f"cannot read ELF input {path}: {exc}")
    if len(header) < 20 or header[:4] != b"\x7fELF":
        fail(f"not an ELF file: {path}")
    elf_class, byte_order = header[4], header[5]
    if byte_order not in (1, 2):
        fail(f"invalid ELF byte order in {path}")
    machine = int.from_bytes(header[18:20], "little" if byte_order == 1 else "big")
    if (elf_class, machine) != (2, 183):
        fail(f"{path} must be ELFCLASS64/e_machine 183 (AArch64), got class={elf_class}, machine={machine}")


def add_tar_file(archive: tarfile.TarFile, source: Path, archive_name: str) -> None:
    info = tarfile.TarInfo(archive_name)
    info.size = source.stat().st_size
    info.mode = stat.S_IMODE(source.stat().st_mode) & 0o755 or 0o644
    if source.name in ("PPSSPPSDL", "gles_proxy", "usb-mount-helper", "screensaver-guard") or "/lib/" in archive_name:
        info.mode = 0o755
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    with source.open("rb") as stream:
        archive.addfile(info, stream)


def make_tar(files: list[tuple[Path, str]]) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, compresslevel=9) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for source, archive_name in files:
                add_tar_file(archive, source, archive_name)
    return buffer.getvalue()


def make_control_tar(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    info = tarfile.TarInfo("control")
    info.size = len(payload)
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0, compresslevel=9) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def ar_member(name: str, payload: bytes) -> bytes:
    encoded_name = f"{name}/".encode("ascii")
    if len(encoded_name) > 16:
        fail(f"ar member name too long: {name}")
    header = (
        encoded_name.ljust(16, b" ")
        + b"0           "
        + b"0     "
        + b"0     "
        + b"100644  "
        + str(len(payload)).encode("ascii").ljust(10, b" ")
        + b"`\n"
    )
    if len(header) != 60:
        fail("internal error constructing ar header")
    return header + payload + (b"\n" if len(payload) & 1 else b"")


def gather_assets(asset_root: Path) -> list[tuple[Path, str]]:
    collected: list[tuple[Path, str]] = []
    for path in sorted(asset_root.rglob("*")):
        if ".git" in path.relative_to(asset_root).parts:
            continue
        if path.is_symlink():
            fail(f"symlink in assets is unsupported: {path}")
        if path.is_file():
            relative = path.relative_to(asset_root).as_posix()
            collected.append((path, f"{APP_ROOT}/assets/{relative}"))
    return collected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sdk-sysroot",
        default=os.environ.get("WEBOS_SDK_SYSROOT"),
        help="SDK sysroot containing usr/lib/libstdc++.so.6 and libgcc_s.so.1 (or set WEBOS_SDK_SYSROOT)",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT, help="output IPK path")
    args = parser.parse_args()
    if not args.sdk_sysroot:
        fail("provide --sdk-sysroot or set WEBOS_SDK_SYSROOT")

    sysroot = Path(args.sdk_sysroot).expanduser().resolve()
    executable = ROOT / "build" / "arm64" / "PPSSPPSDL"
    assets = ROOT / "source" / "assets"
    icon = ROOT / "source" / "icons" / "icon-114.png"
    sdl_ttf = ROOT / "stage" / "lib" / "libSDL3_ttf.so.0.2.2"
    stdcpp = sysroot / "usr" / "lib" / "libstdc++.so.6"
    libgcc = sysroot / "usr" / "lib" / "libgcc_s.so.1"
    if not libgcc.exists():
        libgcc = sysroot / "lib" / "libgcc_s.so.1"
    webos_client = sysroot / "usr" / "lib" / "libwayland-webos-client.so.1"
    wayland_stub = ROOT / "stage" / "lib" / "libwayland-client.so.0"
    bridge_core = ROOT / "stage" / "lib" / "libgles_bridge_core.so"
    proxy = ROOT / "stage" / "service" / "gles_proxy"
    usb_helper = ROOT / "stage" / "service" / "usb-mount-helper"
    screensaver_guard = ROOT / "stage" / "service" / "screensaver-guard"
    required = [executable, assets, icon, sdl_ttf, stdcpp, libgcc, webos_client, wayland_stub, bridge_core, proxy, usb_helper, screensaver_guard]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        fail("required input(s) missing:\n  " + "\n  ".join(missing))
    if not executable.is_file() or not icon.is_file() or not sdl_ttf.is_file() or not stdcpp.is_file() or not libgcc.is_file():
        fail("executable, icon, and shared-library inputs must be regular files (SDK symlink targets are followed)")
    if not assets.is_dir():
        fail(f"assets input is not a directory: {assets}")

    for library in (sdl_ttf, stdcpp, libgcc):
        check_aarch64_elf(library.resolve())
    check_aarch64_elf(executable.resolve())

    appinfo = ROOT / "packaging" / "appinfo.json"
    if not appinfo.is_file():
        fail(f"app metadata missing: {appinfo}")

    data_files: list[tuple[Path, str]] = [
        (executable, f"{APP_ROOT}/PPSSPPSDL"),
        (appinfo, f"{APP_ROOT}/appinfo.json"),
        (icon, f"{APP_ROOT}/icon-114.png"),
        (sdl_ttf.resolve(), f"{APP_ROOT}/lib/libSDL3_ttf.so.0"),
    ]
    data_files.extend(gather_assets(assets))
    for notice in sorted((ROOT / "LICENSES").rglob("*")):
        if notice.is_file():
            relative = notice.relative_to(ROOT / "LICENSES").as_posix()
            data_files.append((notice, f"{APP_ROOT}/licenses/{relative}"))
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "SOURCE_CODE.md", "MODIFICATIONS.md"):
        data_files.append((ROOT / name, f"{APP_ROOT}/licenses/{name}"))
    data_files.append((ROOT / "source" / "LICENSE.TXT", f"{APP_ROOT}/licenses/PPSSPP.txt"))
    data_files.append((ROOT / "reference" / "bridge-v008" / "LICENSE", f"{APP_ROOT}/licenses/Bridge.txt"))
    check_aarch64_elf(webos_client.resolve())
    data_files.append((webos_client.resolve(), f"{APP_ROOT}/lib/libwayland-webos-client.so.1"))
    check_aarch64_elf(wayland_stub.resolve())
    data_files.append((wayland_stub.resolve(), f"{APP_ROOT}/lib/libwayland-client.so.0"))
    check_aarch64_elf(bridge_core.resolve())
    data_files.append((bridge_core.resolve(), f"{APP_ROOT}/lib/libgles_bridge_core.so"))
    proxy_header = proxy.read_bytes()[:20]
    if proxy_header[:5] != b"\x7fELF\x01" or int.from_bytes(proxy_header[18:20], "little") != 40:
        fail("private proxy must be ELF32 ARM (softfp)")
    data_files.append((proxy, f"{APP_ROOT}/service/gles_proxy"))
    helper_header = usb_helper.read_bytes()[:20]
    if helper_header[:5] != b"\x7fELF\x01" or int.from_bytes(helper_header[18:20], "little") != 40:
        fail("USB helper must be ELF32 ARM")
    data_files.append((usb_helper, f"{APP_ROOT}/service/usb-mount-helper"))
    guard_header = screensaver_guard.read_bytes()[:20]
    if guard_header[:5] != b"\x7fELF\x01" or int.from_bytes(guard_header[18:20], "little") != 40:
        fail("Screensaver guard must be ELF32 ARM")
    data_files.append((screensaver_guard, f"{APP_ROOT}/service/screensaver-guard"))

    installed_size_kb = (sum(path.stat().st_size for path, _ in data_files) + 1023) // 1024
    control = (
        f"Package: {APP_ID}\n"
        f"Version: {VERSION}\n"
        "Section: multimedia\n"
        "Priority: optional\n"
        "Architecture: arm\n"
        f"Installed-Size: {installed_size_kb}\n"
        "Maintainer: PPSSPP\n"
        "Description: PPSSPP PlayStation Portable emulator\n"
    ).encode("utf-8")
    control_tar = make_control_tar(control)
    data_tar = make_tar(data_files)
    ipk_bytes = (
        b"!<arch>\n"
        + ar_member("debian-binary", b"2.0\n")
        + ar_member("control.tar.gz", control_tar)
        + ar_member("data.tar.gz", data_tar)
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(ipk_bytes)
    print(f"Created {output} ({len(ipk_bytes)} bytes)")


if __name__ == "__main__":
    main()
