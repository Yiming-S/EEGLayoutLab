"""``eeglayoutlab data list|verify|install|compose|remove|build``.

- ``list``: the installed packages, their size and the packages they still need.
- ``verify [NAME ...]``: checks the size and SHA-256 of every installed file and reports unlisted files; exit 1 when
  anything differs.
- ``install MANIFEST [--from-root R]``: installs the package of a manifest (a path, or an https:// or file://
  address) from the archive beside it, or by copying its files from a scientific root.
- ``compose [NAME ...] [--root R]``: places the files of installed packages in a scientific root (the checkout by
  default), as hard links or checked copies.
- ``remove NAME``: removes an installed package.
- ``build --root R --out DIR [--archive NAME ...]``: the author side; writes a manifest for every complete package
  of ``R``, the archives asked for, ``catalog.json`` and ``report.md`` (sizes against the Zenodo record limits).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any, Optional

from . import catalog
from . import compose as composing
from .archive import archive_size, write_archive
from .manifest import Manifest, PackageError
from .store import Store, code_version, data_dir, read_source

# Zenodo's default limits per record (https://help.zenodo.org/docs/deposit/create-new-upload/,
# https://about.zenodo.org/policies/): 50 GB and 100 files; larger quotas are granted case by case.
ZENODO_RECORD_BYTES = 50 * 10**9
ZENODO_RECORD_FILES = 100


def add_commands(commands: Any) -> None:
    data = commands.add_parser('data', help='install, list, verify and remove data packages',
                               description='Data packages in the user data directory (EEGLAYOUTLAB_DATA_DIR).')
    data.add_argument('--data-dir', metavar='D', help='data directory (default: the platform user data directory)')
    actions = data.add_subparsers(dest='data_command', required=True, metavar='ACTION')
    actions.add_parser('list', help='list installed packages')
    verify = actions.add_parser('verify', help='check installed files against their manifests')
    verify.add_argument('names', nargs='*', metavar='NAME')
    install = actions.add_parser('install', help='install a package from its manifest')
    install.add_argument('manifest', metavar='MANIFEST', help='manifest path, or https:// or file:// address')
    install.add_argument('--from-root', metavar='R', help='copy the files from this scientific root instead')
    install.add_argument('--any-code-version', action='store_true',
                         help='install even when the manifest does not accept this code version')
    compose = actions.add_parser('compose', help='place installed packages in a scientific root',
                                 description='Places the files of installed packages at their paths in a scientific '
                                 'root: hard links when possible, else checked copies. Nothing is written while a '
                                 'path conflicts.')
    compose.add_argument('names', nargs='*', metavar='NAME',
                         help='packages (default: every installed package); the packages they need are added')
    compose.add_argument('--root', metavar='R', help='scientific root (default: EEG_REPOSITORY_ROOT, else this checkout)')
    compose.add_argument('--copy', action='store_true', help='copy the files instead of hard-linking them')
    compose.add_argument('--dry-run', action='store_true', help='report what would be done and write nothing')
    remove = actions.add_parser('remove', help='remove an installed package')
    remove.add_argument('name', metavar='NAME')
    build = actions.add_parser('build', help='write manifests and archives for the packages of a scientific root')
    build.add_argument('--root', required=True, metavar='R', help='scientific root holding data/ and results/v2/')
    build.add_argument('--out', required=True, metavar='DIR', help='output directory')
    build.add_argument('--version', default='1.0.0', metavar='V', help='version of every package (default 1.0.0)')
    build.add_argument('--only', action='append', metavar='NAME', help='only this package (repeatable)')
    build.add_argument('--archive', action='append', default=[], metavar='NAME',
                       help='also write the archive of this package (repeatable)')


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _size(count: int) -> str:
    for unit, scale in (('GB', 10**9), ('MB', 10**6), ('kB', 10**3)):
        if count >= scale:
            return f'{count / scale:.2f} {unit}'
    return f'{count} B'


def run(args: argparse.Namespace) -> int:
    store = Store(pathlib.Path(args.data_dir).expanduser() if args.data_dir else data_dir())
    try:
        if args.data_command == 'list':
            return _list(store)
        if args.data_command == 'verify':
            return _verify(store, args.names)
        if args.data_command == 'install':
            return _install(store, args)
        if args.data_command == 'compose':
            return _compose(store, args)
        if args.data_command == 'remove':
            current = store.find(args.name)
            shared = composing.shared_files(current) if current else 0
            removed = store.remove(args.name)
            print(f'Removed {removed.manifest.stem}.')
            if shared:
                print(f'{shared} of its files are still hard-linked elsewhere, for example in a composed root; '
                      'their space is freed when those links are deleted.')
            return 0
        if args.data_command == 'build':
            return _build(args)
    except PackageError as error:
        _say(f'eeglayoutlab data: {error}')
        return 1
    except OSError as error:
        _say(f'eeglayoutlab data: {error.filename or ""}: {error.strerror or error}')
        return 1
    _say(f'eeglayoutlab data: unknown action {args.data_command}')
    return 2


def _list(store: Store) -> int:
    installed = store.installed()
    print(f'Data directory: {store.root}')
    if not installed:
        print('No packages are installed.')
        return 0
    names = {item.manifest.name for item in installed}
    for item in installed:
        manifest = item.manifest
        missing = [name for name in manifest.requires if name not in names]
        need = f'  needs {", ".join(missing)}' if missing else ''
        print(f'{manifest.name}  {manifest.version}  {manifest.kind}  {_size(manifest.total_size)}  '
              f'{len(manifest.files)} files{need}')
    return 0


def _verify(store: Store, names: list[str]) -> int:
    results = store.verify(names or None, on_file=None)
    if not results:
        print(f'No packages are installed in {store.root}.')
        return 0
    failed = 0
    for label, problems in results.items():
        if problems:
            failed += 1
            print(f'{label}: {len(problems)} problem(s)')
            for problem in problems:
                print(f'  {problem}')
        else:
            print(f'{label}: intact')
    return 1 if failed else 0


class _Meter:
    def __init__(self, total: int):
        self.total, self.done, self.shown = total, 0, -1

    def __call__(self, count: int) -> None:
        self.done += count
        percent = self.done * 100 // max(self.total, 1)
        if percent // 10 != self.shown // 10:
            self.shown = percent
            _say(f'  {percent}%')


def _install(store: Store, args: argparse.Namespace) -> int:
    source = read_source(args.manifest)
    manifest = source.manifest
    from_root = pathlib.Path(args.from_root).resolve() if args.from_root else None
    current = store.find(manifest.name)
    if current is None:
        if from_root is None and manifest.archive is None:
            raise PackageError(f'{manifest.stem} is published without an archive; install it with --from-root')
        print(f'Installing {manifest.stem} ({_size(manifest.total_size)}, {len(manifest.files)} files) '
              f'into {store.root}', flush=True)
    installed, written = store.install(source, from_root, check_code=not args.any_code_version,
                                       progress=_Meter(manifest.total_size))
    if not written:
        print(f'{manifest.stem} is already installed; run eeglayoutlab data verify {manifest.name} to check it.')
        return 0
    present = {item.manifest.name for item in store.installed()}
    missing = [name for name in manifest.requires if name not in present]
    print(f'Installed {manifest.stem} in {installed.path}.')
    if missing:
        print(f'It is used together with {", ".join(missing)}, which is not installed.')
    return 0


def _compose(store: Store, args: argparse.Namespace) -> int:
    from ..jobs import nodepath
    from ..jobs.runtime import repository_root
    try:
        root = pathlib.Path(repository_root(nodepath.resolve(args.root) if args.root else None))
    except ValueError as error:
        _say(f'eeglayoutlab data: {error}')
        return 2
    if not (root / 'configs').is_dir():
        raise PackageError(f'{root} has no configs/ directory; compose into a checkout of EEGLayoutLab')
    work = composing.plan(store, root, args.names or None, on_hash=lambda path: _say(f'compare {path}'))
    if not work.packages:
        print(f'No packages are installed in {store.root}.')
        return 0
    print(f'Root: {root}')
    print('Packages: ' + ', '.join(item.manifest.stem for item in work.packages))
    for name, requirement in work.missing:
        print(f'{name} is used together with {requirement}, which is not installed.')
    print(f'{len(work.place)} file(s) to place ({_size(work.place_bytes)}), {len(work.present)} already in place.')
    if work.conflicts:
        print(f'Nothing was written: {len(work.conflicts)} path(s) conflict.')
        for conflict in work.conflicts:
            print(f'  {conflict}')
        return 1
    if args.dry_run:
        print('Dry run: nothing was written.')
        return 0
    outcome = composing.apply(work, copy=args.copy, progress=_Meter(work.place_bytes) if work.place else None)
    copied = f', {outcome.copied} cop{"y" if outcome.copied == 1 else "ies"} ({_size(outcome.copied_bytes)})' \
        if outcome.copied else ''
    print(f'Placed {outcome.linked + outcome.copied} file(s): {outcome.linked} hard link(s){copied}. '
          'They are read-only; eeglayoutlab data verify checks the installed files.')
    return 0


def _build(args: argparse.Namespace) -> int:
    root = pathlib.Path(args.root).resolve()
    out = pathlib.Path(args.out).resolve()
    if not (root / 'results/v2').is_dir():
        raise PackageError(f'{root} has no results/v2 directory')
    out.mkdir(parents=True, exist_ok=True)
    only = set(args.only) if args.only else None
    wanted_archives = set(args.archive)
    if only is not None and not wanted_archives <= only:
        raise PackageError('--archive names a package that --only leaves out')
    candidates = catalog.discover(root, args.version, only, progress=lambda path: _say(f'hash {path}'))
    complete = {c.name for c in candidates if c.manifest is not None}
    if wanted_archives - complete:
        raise PackageError(f'cannot archive {", ".join(sorted(wanted_archives - complete))}: not a complete package')
    manifests: list[Manifest] = []
    for candidate in candidates:
        manifest = candidate.manifest
        if manifest is None:
            continue
        if manifest.name in wanted_archives:
            _say(f'archive {manifest.stem}.tar')
            size, digest = write_archive(root, manifest, out / f'{manifest.stem}.tar', _Meter(manifest.total_size))
            manifest = manifest.with_archive(f'{manifest.stem}.tar', size, digest)
        (out / f'{manifest.stem}.json').write_text(manifest.dumps(), 'utf-8')
        manifests.append(manifest)
    summary = summarize(candidates, manifests, code_version())
    (out / 'catalog.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', 'utf-8')
    (out / 'report.md').write_text(report(summary), 'utf-8')
    print(f'{len(manifests)} manifest(s), {len(wanted_archives)} archive(s) and the report are in {out}')
    for candidate in candidates:
        if candidate.problems:
            print(f'not packaged: {candidate.name}: {"; ".join(candidate.problems)}')
    return 0


def summarize(candidates: list[catalog.Candidate], manifests: list[Manifest], version: str) -> dict[str, Any]:
    by_name = {c.name: c for c in candidates}
    packages = []
    for manifest in manifests:
        archived = manifest.archive is not None
        packages.append({
            'name': manifest.name, 'version': manifest.version, 'kind': manifest.kind,
            'files': len(manifest.files), 'total_size': manifest.total_size,
            'content_sha256': manifest.content_sha256, 'requires': list(manifest.requires),
            'licenses': sorted({str(item.get('license')) for item in manifest.licenses}),
            'archive_size': manifest.archive['size'] if archived else archive_size(manifest),
            'archive_written': archived, 'home_paths': by_name[manifest.name].home_paths,
        })
    archives = sum(item['archive_size'] for item in packages)
    largest = max(packages, key=lambda item: item['archive_size'], default=None)
    return {
        'schema': 'eeglayoutlab-data-catalog/1', 'code_version': version,
        'packages': packages,
        'not_packaged': [{'name': c.name, 'problems': c.problems} for c in candidates if c.problems],
        'zenodo': {
            'record_limit_bytes': ZENODO_RECORD_BYTES, 'record_file_limit': ZENODO_RECORD_FILES,
            'all_archives_bytes': archives, 'all_files_in_one_record': 2 * len(packages),
            'fits_one_record': archives <= ZENODO_RECORD_BYTES and 2 * len(packages) <= ZENODO_RECORD_FILES,
            'largest_package': largest and {'name': largest['name'], 'archive_size': largest['archive_size']},
        },
    }


def report(summary: dict[str, Any]) -> str:
    zenodo = summary['zenodo']
    lines = [
        '# Data package sizes', '',
        f'Code version {summary["code_version"]}. Archive sizes are exact: written archives are measured, the '
        'others are computed from the manifest (uncompressed pax tar).', '',
        '| Package | Kind | Files | Data | Archive | Written | Licences | Home paths in JSON |',
        '| --- | --- | ---: | ---: | ---: | --- | --- | --- |',
    ]
    for item in summary['packages']:
        lines.append(f'| {item["name"]} | {item["kind"]} | {item["files"]} | {_size(item["total_size"])} | '
                     f'{_size(item["archive_size"])} | {"yes" if item["archive_written"] else "no"} | '
                     f'{", ".join(item["licenses"])} | {len(item["home_paths"]) or ""} |')
    lines += [
        '', f'All archives: {_size(zenodo["all_archives_bytes"])} in {len(summary["packages"])} archives '
        f'({zenodo["all_files_in_one_record"]} files with their manifests).', '',
        f'Zenodo accepts {_size(zenodo["record_limit_bytes"])} and {zenodo["record_file_limit"]} files per record. '
        + ('All packages together fit in one record. ' if zenodo['fits_one_record'] else
           'All packages together do not fit in one record. ')
        + (f'The largest package, {zenodo["largest_package"]["name"]}, is '
           f'{_size(zenodo["largest_package"]["archive_size"])}.' if zenodo['largest_package'] else ''),
    ]
    if summary['not_packaged']:
        lines += ['', 'Not packaged:', '']
        lines += [f'- {item["name"]}: {"; ".join(item["problems"])}' for item in summary['not_packaged']]
    return '\n'.join(lines) + '\n'


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog='eeglayoutlab')
    add_commands(parser.add_subparsers(dest='command', required=True))
    return run(parser.parse_args(argv))


if __name__ == '__main__':
    sys.exit(main())
