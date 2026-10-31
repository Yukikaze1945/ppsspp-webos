#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Create a populated corresponding-source archive from pinned checkouts.

Run after bootstrap. No SDK binaries, Git metadata or private test logs are read.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    'source': '61865a5c899179d8b71616f774d3133c391281d1',
    'reference/bridge-v008': 'f44d3cdca74e72f7ebe473707e816bff585495df',
    'deps/SDL_ttf': 'a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b',
}


def tracked(path):
    data = subprocess.check_output(['git', '-C', str(path), 'ls-files', '--stage', '--recurse-submodules', '-z'])
    for row in data.split(b'\0'):
        if not row:
            continue
        meta, name = row.split(b'\t', 1)
        mode = int(meta.split()[0], 8)
        if mode == 0o160000:
            continue  # an uninitialized, unused submodule is not a regular file
        yield name.decode(), mode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/ppsspp-webos-0.1.10-corresponding-source.tar.gz')
    parser.add_argument('--patched-tree', type=Path, help='Optional validated PPSSPP tree used for publication-only change notices')
    args = parser.parse_args()
    entries = {}
    for name, mode in tracked(ROOT):
        entries[name] = (ROOT/name, mode)
    for component, commit in COMPONENTS.items():
        directory = ROOT/component
        actual = subprocess.check_output(['git', '-C', str(directory), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != commit:
            raise SystemExit(f'Unexpected {component} revision: {actual}')
        for name, mode in tracked(directory):
            if component == 'source' and name.startswith(('pspautotests/', 'frametests/')):
                continue  # unused test corpora; neither is compiled into this TV build
            file = directory/name
            if component == 'source' and args.patched_tree:
                alternate = args.patched_tree.resolve()/name
                if alternate.is_file():
                    file = alternate
            entries[component+'/'+name] = (file, mode)
    font = 'source/assets/fonts/NotoSansCJKsc-Regular.otf'
    entries[font] = (ROOT/font, 0o100644)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {'version': '0.1.10', 'components': {k: {'commit': v} for k, v in COMPONENTS.items()}, 'files': {}, 'omitted_unused_binaries': []}
    prefix = 'ppsspp-webos-0.1.10/'
    with args.output.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, compresslevel=6) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, (file, mode) in sorted(entries.items()):
                info = tarfile.TarInfo(prefix+name)
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = 'root'
                info.mode = 0o755 if mode & 0o111 else 0o644
                if mode == 0o120000:
                    info.type = tarfile.SYMTYPE
                    info.linkname = os.readlink(file) if file.is_symlink() else file.read_text().strip()
                    archive.addfile(info)
                    manifest['files'][name] = {'symlink': info.linkname}
                else:
                    data = file.read_bytes()
                    if (data[:4] in (b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe')
                        or data.startswith((b'MZ', b'!<arch>\n'))
                        or file.suffix.lower() in ('.jar', '.aar', '.pbp', '.iso', '.cso')):
                        manifest['omitted_unused_binaries'].append(name)
                        continue
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))
                    manifest['files'][name] = hashlib.sha256(data).hexdigest()
            data = (json.dumps(manifest, indent=2)+'\n').encode()
            info = tarfile.TarInfo(prefix+'SOURCE_SNAPSHOT.json')
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    print(f'Created {args.output.name}: {len(entries)} files, {args.output.stat().st_size} bytes')


if __name__ == '__main__':
    main()
