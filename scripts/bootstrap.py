#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Community build/packaging adaptation, 2026-10-31.
"""Prepare pinned PPSSPP sources, submodules, webOS patch, and fonts."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

PPSSPP_COMMIT = "61865a5c899179d8b71616f774d3133c391281d1"
SDL_TTF_COMMIT = "a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b"
SDK_SHA256 = "2462c0389ed82efc5b05d75badba55adba0227bcf21d2cb1573500a8bc8ff263"
SDK_URL = (
    "https://github.com/cscd98/buildroot-nc4/releases/download/webos-c14c7bd/"
    "aarch64-webos-linux-gnu_sdk-buildroot-x86_64.tar.gz"
)
SDK32_SHA256 = "61ada10c6b2b94510968b99137762cbd7a7956b4bdc4e456792ae8bbe000410e"
SDK32_URL = (
    "https://github.com/cscd98/buildroot-nc4/releases/download/webos-c14c7bd/"
    "arm-webos-linux-gnueabi_sdk-buildroot-x86_64.tar.gz"
)
BRIDGE_COMMIT = "f44d3cdca74e72f7ebe473707e816bff585495df"
BRIDGE_REPO = "https://github.com/webosbrew/webos-bridge-64to32.git"
BRIDGE_IPK_URL = (
    "https://github.com/webosbrew/webos-bridge-64to32/releases/download/v0.0.8/"
    "org.webosbrew.bridge-64to32_aarch64_v0.0.8.ipk"
)
BRIDGE_IPK_SHA256 = "01c9c94a85b434a3b21fee5ed1dbf79d448ed788c1ae019234f4eb16c141aaf7"


def fail(message: str) -> "NoReturn":
    raise SystemExit(f"bootstrap.py: error: {message}")


def run_git(arguments: list[str], cwd: Path, *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError:
        fail("git is required but was not found on PATH")


def git_output(arguments: list[str], cwd: Path) -> str:
    result = run_git(arguments, cwd, capture=True)
    if result.returncode:
        fail(f"git {' '.join(arguments)} failed in {cwd}: {result.stderr.strip()}")
    return result.stdout.rstrip()


def ensure_clone(destination: Path, url: str, expected_commit: str, label: str) -> None:
    if destination.exists() and not (destination / ".git").exists():
        root = Path(__file__).resolve().parents[1]
        marker = root / "SOURCE_SNAPSHOT.json"
        if marker.is_file():
            recorded = json.loads(marker.read_text())["components"].get(destination.relative_to(root).as_posix(), {})
            if recorded.get("commit") == expected_commit:
                print(f"{label}: using populated corresponding-source archive ({expected_commit})")
                return
    if destination.exists():
        if not (destination / ".git").exists():
            fail(f"{label} path exists but is not a git checkout: {destination}")
        current = git_output(["rev-parse", "HEAD"], destination)
        if current != expected_commit:
            fail(f"{label} checkout at {destination} is {current}, expected {expected_commit}; leaving it untouched")
        print(f"{label}: pinned checkout already present ({current})")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(["clone", "--no-checkout", url, str(destination)], destination.parent)
    if result.returncode:
        fail(f"could not clone {label} from {url}")
    result = run_git(["checkout", "--detach", expected_commit], destination)
    if result.returncode:
        fail(f"new {label} checkout could not select pinned commit {expected_commit}")
    current = git_output(["rev-parse", "HEAD"], destination)
    if current != expected_commit:
        fail(f"new {label} checkout resolved to unexpected commit {current}")
    print(f"{label}: cloned pinned commit {current}")


def check_submodules(source: Path) -> None:
    status = git_output(["submodule", "status", "--recursive"], source)
    for line in status.splitlines():
        if not line:
            continue
        marker = line[0]
        remainder = line[1:].strip()
        parts = remainder.split(maxsplit=1)
        if len(parts) < 2:
            fail(f"cannot parse git submodule status line: {line}")
        sub_path = parts[1].split(" (", maxsplit=1)[0]
        if marker in "+U":
            fail(f"submodule {sub_path} is at a non-pinned or conflicted commit; refusing to checkout over it")
        if marker == "-":
            continue
        submodule = source / sub_path
        if submodule.exists() and git_output(["status", "--porcelain"], submodule):
            fail(f"submodule {sub_path} has local changes; refusing to update it")


def prepare_submodules(source: Path) -> None:
    if not (source / ".git").exists():
        print("submodules: populated in corresponding-source archive")
        return
    check_submodules(source)
    result = run_git(["submodule", "update", "--init", "--recursive"], source)
    if result.returncode:
        fail("git submodule update --init --recursive failed")
    print("submodules: initialized missing pinned checkouts")


def prepare_patch(source: Path, patch: Path) -> None:
    if not (source / ".git").exists():
        print("webOS patch: included in populated corresponding-source archive")
        return
    reverse = run_git(["apply", "--reverse", "--check", str(patch)], source, capture=True)
    if reverse.returncode == 0:
        print("webOS patch: already applied; skipped")
        return
    forward = run_git(["apply", "--check", str(patch)], source, capture=True)
    if forward.returncode:
        detail = forward.stderr.strip() or reverse.stderr.strip()
        fail(f"webOS patch neither applies cleanly nor matches the applied state: {detail}")
    result = run_git(["apply", str(patch)], source)
    if result.returncode:
        fail("git apply failed after the patch check")
    print("webOS patch: applied")


def read_source_fields(source_file: Path) -> dict[str, str]:
    if not source_file.is_file():
        fail(f"font source record not found: {source_file}")
    values: dict[str, str] = {}
    for line in source_file.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip()] = value.strip()
    for key in ("Immutable source commit", "Font raw URL", "Font SHA-256", "License URL", "License SHA-256", "Local license copy"):
        if not values.get(key):
            fail(f"font source record is missing {key!r}")
    commit = values["Immutable source commit"]
    if not re.fullmatch(r"[0-9a-f]{40}", commit) or commit not in values["Font raw URL"] or commit not in values["License URL"]:
        fail("font URLs must point to the immutable commit recorded in SOURCE.txt")
    for key in ("Font SHA-256", "License SHA-256"):
        if not re.fullmatch(r"[0-9a-fA-F]{64}", values[key]):
            fail(f"invalid SHA-256 in font source record: {key}")
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    if destination.exists():
        actual = sha256_file(destination)
        if actual.lower() != expected_sha256.lower():
            fail(f"existing file has wrong SHA-256; leaving it untouched: {destination} (got {actual})")
        print(f"verified existing file: {destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=destination.parent)
    os.close(fd)
    temporary = Path(temp_name)
    digest = hashlib.sha256()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "PPSSPP-webOS-bootstrap/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                digest.update(chunk)
        actual = digest.hexdigest()
        if actual.lower() != expected_sha256.lower():
            fail(f"download hash mismatch for {url}: expected {expected_sha256}, got {actual}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"downloaded and verified: {destination}")


def prepare_fonts(root: Path) -> None:
    font_dir = root / "source" / "assets" / "fonts"
    source = read_source_fields(font_dir / "SOURCE.txt")
    font_url = source["Font raw URL"]
    font_name = font_url.rsplit("/", 1)[-1]
    download_verified(font_url, font_dir / font_name, source["Font SHA-256"])
    # Git on Windows may check text licenses out as CRLF. Canonicalize only
    # when the LF form exactly matches the pinned upstream SHA-256.
    license_file = font_dir / source["Local license copy"]
    if license_file.is_file():
        current = license_file.read_bytes()
        canonical = current.replace(b"\r\n", b"\n")
        if current != canonical and hashlib.sha256(canonical).hexdigest() == source["License SHA-256"]:
            license_file.write_bytes(canonical)
    download_verified(
        source["License URL"],
        font_dir / source["Local license copy"],
        source["License SHA-256"],
    )


def prepare_sdk(root: Path) -> None:
    archive = root / "toolchain" / "sdk.tar.gz"
    download_verified(SDK_URL, archive, SDK_SHA256)
    print("SDK archive verified. Extraction is intentionally manual to avoid cross-platform tar case-collision corruption.")
    print(f"On Linux/WSL, from the repository root, extract with: tar -xzf {archive.relative_to(root).as_posix()} -C toolchain")
    print("Then run: cd toolchain/aarch64-webos-linux-gnu_sdk-buildroot && ./relocate-sdk.sh")


def prepare_sdk32(root: Path) -> None:
    archive = root / "toolchain" / "sdk-arm32.tar.gz"
    download_verified(SDK32_URL, archive, SDK32_SHA256)
    print("ARM32 SDK archive verified. Extraction is intentionally manual.")
    print(f"On Linux, from the repository root, extract with: tar -xzf {archive.relative_to(root).as_posix()} -C toolchain")
    print("Then run: cd toolchain/arm-webos-linux-gnueabi_sdk-buildroot && ./relocate-sdk.sh")


def read_ar_member(data: bytes, wanted: str) -> bytes | None:
    if not data.startswith(b"!<arch>\n"):
        return None
    offset = 8
    string_table = b""
    while offset + 60 <= len(data):
        header = data[offset : offset + 60]
        if header[58:60] != b"`\n":
            fail("invalid ar member header in Bridge IPK")
        raw_name = header[:16].decode("ascii", errors="replace").strip()
        try:
            member_size = int(header[48:58].decode("ascii").strip())
        except ValueError:
            fail("invalid ar member size in Bridge IPK")
        start = offset + 60
        end = start + member_size
        if end > len(data):
            fail("truncated ar member in Bridge IPK")
        payload = data[start:end]
        name = raw_name.rstrip("/")
        if raw_name == "//":
            string_table = payload
        elif raw_name.startswith("#1/"):
            try:
                name_size = int(raw_name[3:])
            except ValueError:
                fail("invalid BSD ar member name in Bridge IPK")
            name = payload[:name_size].decode("utf-8", errors="replace")
            payload = payload[name_size:]
        elif raw_name.startswith("/") and raw_name[1:].isdigit():
            name_offset = int(raw_name[1:])
            if name_offset >= len(string_table):
                fail("invalid GNU ar member name in Bridge IPK")
            name = string_table[name_offset:].split(b"/\n", 1)[0].decode("utf-8", errors="replace")
        if name == wanted:
            return payload
        offset = end + (member_size & 1)
    return None


def read_ipk_data_archive(ipk: bytes) -> bytes:
    ar_data = read_ar_member(ipk, "data.tar.gz")
    if ar_data is not None:
        return ar_data
    try:
        with tarfile.open(fileobj=io.BytesIO(ipk), mode="r:*") as outer:
            for member in outer.getmembers():
                if PurePosixPath(member.name).name == "data.tar.gz" and member.isfile():
                    stream = outer.extractfile(member)
                    if stream is not None:
                        return stream.read()
            # Some IPK variants are just a tar archive containing app files.
            return ipk
    except tarfile.TarError as exc:
        fail(f"unsupported Bridge IPK container: {exc}")


def extract_bridge_libraries(ipk: bytes) -> dict[str, bytes]:
    data_archive = read_ipk_data_archive(ipk)
    wanted = {
        "libgles_bridge_core.so",
        "libwayland-client-real.so.0",
    }
    entries: dict[str, tuple[str, bytes | str]] = {}
    tail = ("usr", "palm", "applications", "org.webosbrew.bridge-64to32", "lib")
    try:
        with tarfile.open(fileobj=io.BytesIO(data_archive), mode="r:*") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                parts = tuple(part for part in path.parts if part not in (".", ""))
                if ".." in parts or len(parts) < len(tail) + 1 or parts[-len(tail) - 1 : -1] != tail:
                    continue
                name = parts[-1]
                if name not in wanted and name != "libwayland-client-real.so.0.22.0":
                    continue
                if name in entries:
                    fail(f"duplicate {name} in Bridge IPK")
                if member.isfile():
                    stream = archive.extractfile(member)
                    if stream is None:
                        continue
                    entries[name] = ("file", stream.read())
                elif member.issym():
                    entries[name] = ("link", member.linkname)
                else:
                    entries[name] = ("other", "")
    except tarfile.TarError as exc:
        fail(f"cannot read Bridge IPK data archive: {exc}")
    def read_entry(name: str, seen: set[str]) -> bytes:
        if name in seen:
            fail(f"symlink cycle in Bridge IPK library chain: {name}")
        entry = entries.get(name)
        if entry is None:
            fail(f"Bridge IPK library symlink target is missing: {name}")
        kind, value = entry
        if kind == "file":
            if isinstance(value, bytes):
                return value
            fail(f"invalid Bridge IPK regular-file entry: {name}")
        if kind == "link":
            if not isinstance(value, str):
                fail(f"invalid Bridge IPK symlink entry: {name}")
            target = PurePosixPath(value)
            if target.is_absolute() or len(target.parts) != 1 or target.name in ("", ".", ".."):
                fail(f"unsafe Bridge IPK library symlink: {name} -> {value}")
            return read_entry(target.name, seen | {name})
        fail(f"Bridge IPK library is not a regular file or symlink: {name}")

    missing = sorted(name for name in wanted if name not in entries)
    if missing:
        fail("Bridge IPK is missing required library/libraries: " + ", ".join(missing))
    extracted = {name: read_entry(name, set()) for name in wanted}
    return extracted


def install_project_library(destination: Path, data: bytes) -> None:
    if destination.is_symlink():
        fail(f"refusing to replace symlink in project sysroot: {destination}")
    if destination.is_file() and destination.read_bytes() == data:
        print(f"Bridge library already matches release: {destination.name}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=destination.name + ".", suffix=".part", dir=destination.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"installed verified Bridge release library to project sysroot: {destination.name}")


def prepare_bridge(root: Path) -> None:
    bridge_source = root / "reference" / "bridge-v008"
    ensure_clone(bridge_source, BRIDGE_REPO, BRIDGE_COMMIT, "Bridge v0.0.8")
    ipk_path = root / "toolchain" / "bridge-v0.0.8.ipk"
    download_verified(BRIDGE_IPK_URL, ipk_path, BRIDGE_IPK_SHA256)
    ipk_data = ipk_path.read_bytes()
    libraries = extract_bridge_libraries(ipk_data)
    project_sysroot = root / "sysroot"
    for name in sorted(libraries):
        install_project_library(project_sysroot / name, libraries[name])
    print("Bridge v0.0.8 source and link-only libraries are ready; no system Bridge files were changed.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", action="store_true", help="download and verify the pinned SDK archive; do not extract it")
    parser.add_argument("--sdk32", action="store_true", help="download and verify the pinned ARM32 SDK archive; do not extract it")
    parser.add_argument("--bridge", action="store_true", help="prepare the pinned Bridge v0.0.8 source and link-only libraries")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    if args.sdk32 and not args.sdk:
        prepare_sdk32(root)
        if args.bridge:
            prepare_bridge(root)
        print("Requested toolchain bootstrap complete.")
        return
    if args.bridge and not args.sdk:
        prepare_bridge(root)
        print("Bridge bootstrap complete.")
        return
    source = root / "source"
    sdl_ttf = root / "deps" / "SDL_ttf"
    ensure_clone(source, "https://github.com/hrydgard/ppsspp.git", PPSSPP_COMMIT, "PPSSPP")
    ensure_clone(sdl_ttf, "https://github.com/libsdl-org/SDL_ttf.git", SDL_TTF_COMMIT, "SDL_ttf")
    prepare_submodules(source)
    prepare_patch(source, root / "patches" / "0001-webos-runtime.patch")
    prepare_fonts(root)
    if args.sdk:
        prepare_sdk(root)
    if args.sdk32:
        prepare_sdk32(root)
    if args.bridge:
        prepare_bridge(root)
    print("Bootstrap complete. No existing checkout was reset or force-checked-out.")


if __name__ == "__main__":
    main()
