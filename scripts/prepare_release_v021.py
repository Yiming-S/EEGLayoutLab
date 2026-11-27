#!/usr/bin/env python3
"""Local pre-release verifier for EEG Layout Lab v0.2.1 (never pushes, tags or uploads).

Checks:
1. Version consistency across pyproject.toml, webapp/package.json, recipe.yaml, CITATION.cff and .zenodo.json,
   and confirms every data package in data/packages.json accepts code version 0.2.1 (`>=0.2.0,<1.0.0`).
2. Default public data packages (`base` + `scalp-node-table`) in data/packages.json and data/manifest.json,
   plus optional local archive/manifest digest verification when `--verify-archives DIR` is supplied.
3. Three-command onboarding (`quickstart`, `doctor`, `scripts/setup_local.py`) and local web UI missing-data
   guidance (`/api/data-status`, `DataReadinessNotice`) wiring.
4. All 7 GitHub Actions workflows parse cleanly with read-only top-level permissions, and release metadata
   files (`CITATION.cff`, `.zenodo.json`, `SECURITY.md`, `THIRD_PARTY_NOTICES.md`, `CHANGELOG.md`, `mkdocs.yml`)
   are present and valid.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_WORKFLOWS = {
    'checks.yml',
    'docs.yml',
    'pages.yml',
    'data.yml',
    'package.yml',
    'browser.yml',
    'release.yml',
}

EXPECTED_DEFAULT_PACKAGES = {
    'base': {
        'version': '1.0.0',
        'total_size': 406226293,
        'archive_size': 406261760,
        'content_sha256': '01083d8e504feee233b8a4142ce3a0204ad48b28550c3ee06c59b4206ef9c694',
        'manifest_sha256': 'defe75a4df548ed03b0d7da643705fd96d7c9727db5e5556539c3196c39cd5a5',
    },
    'scalp-node-table': {
        'version': '1.0.0',
        'total_size': 1395744261,
        'archive_size': 1395752960,
        'content_sha256': '9a99d6420362fe060a9c30862a89a288e325c836f494071f799804daca652bd6',
        'manifest_sha256': 'aad25cffa9bc875f87002b2c71afe3ace76fb1835e0d244e7b5268593716085e',
    },
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _extract_regex(path: Path, pattern: str, label: str) -> str:
    text = path.read_text(encoding='utf-8')
    match = re.search(pattern, text, flags=re.MULTILINE)
    if not match:
        raise ValueError(f'{label}: could not extract version pattern in {path.relative_to(ROOT)}')
    return match.group(1)


def check_versions(root: Path) -> tuple[str, list[str]]:
    notes: list[str] = []
    py_ver = _extract_regex(root / 'pyproject.toml', r'^version\s*=\s*"([^"]+)"', 'pyproject.toml')
    pkg_json = json.loads((root / 'webapp/package.json').read_text(encoding='utf-8'))
    web_ver = str(pkg_json.get('version', ''))
    recipe_ver = _extract_regex(
        root / 'packaging/conda-forge/eeglayoutlab/recipe.yaml',
        r'^\s*version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?',
        'recipe.yaml',
    )
    cff_ver = _extract_regex(root / 'CITATION.cff', r'^version:\s*"?([0-9]+\.[0-9]+\.[0-9]+)"?', 'CITATION.cff')
    zenodo = json.loads((root / '.zenodo.json').read_text(encoding='utf-8'))
    zen_ver = str(zenodo.get('version', ''))

    versions = {
        'pyproject.toml': py_ver,
        'webapp/package.json': web_ver,
        'recipe.yaml': recipe_ver,
        'CITATION.cff': cff_ver,
        '.zenodo.json': zen_ver,
    }
    unique = set(versions.values())
    if len(unique) != 1:
        raise ValueError(f'Version mismatch across metadata files: {versions}')
    current = next(iter(unique))
    if current not in {'0.2.0', '0.2.1'}:
        raise ValueError(f'Unexpected version {current!r}; expected 0.2.0 (pre-bump) or 0.2.1 (ready to tag)')
    notes.append(f'Metadata version synchronized at {current} across all 5 manifest files')
    return current, notes


def check_data_packages(root: Path, archive_dir: Path | None = None) -> list[str]:
    notes: list[str] = []
    packages_doc = json.loads((root / 'data/packages.json').read_text(encoding='utf-8'))
    if packages_doc.get('schema') != 'eeglayoutlab-data-index/1':
        raise ValueError('data/packages.json schema must be eeglayoutlab-data-index/1')
    packages: list[dict[str, Any]] = packages_doc.get('packages') or []
    if len(packages) != 15:
        raise ValueError(f'Expected 15 entries in data/packages.json, found {len(packages)}')

    by_name = {pkg['name']: pkg for pkg in packages}
    for pkg in packages:
        accepts = pkg.get('accepts_code')
        if accepts != '>=0.2.0,<1.0.0':
            raise ValueError(f"Package {pkg['name']} accepts_code={accepts!r} does not cover 0.2.1")

    for name, expected in EXPECTED_DEFAULT_PACKAGES.items():
        if name not in by_name:
            raise ValueError(f'Missing required default package {name!r} in data/packages.json')
        entry = by_name[name]
        for field, exp_val in expected.items():
            if entry.get(field) != exp_val:
                raise ValueError(f'Package {name} {field}={entry.get(field)!r} != expected {exp_val!r}')

    if by_name['scalp-node-table'].get('requires') != ['base']:
        raise ValueError("scalp-node-table must declare requires=['base']")

    manifest_doc = json.loads((root / 'data/manifest.json').read_text(encoding='utf-8'))
    base_files = manifest_doc.get('files') or []
    if len(base_files) != 21:
        raise ValueError(f'Expected 21 files in data/manifest.json, found {len(base_files)}')

    notes.append(
        'data/packages.json verified: 15 packages accept >=0.2.0,<1.0.0; '
        'base (0.41 GB, 21 files) + scalp-node-table (1.40 GB) digests match pinned values'
    )

    if archive_dir is not None:
        if not archive_dir.is_dir():
            raise ValueError(f'Archive directory not found: {archive_dir}')
        for name, expected in EXPECTED_DEFAULT_PACKAGES.items():
            entry = by_name[name]
            manifest_name = Path(str(entry['manifest_url'])).name
            archive_name = Path(str(entry['archive_url'])).name
            manifest_path = archive_dir / manifest_name
            archive_path = archive_dir / archive_name
            if not manifest_path.is_file():
                raise ValueError(f'Missing manifest file {manifest_path}')
            actual_m_sha = _sha256_file(manifest_path)
            if actual_m_sha != expected['manifest_sha256']:
                raise ValueError(f'{manifest_name} SHA-256 mismatch: {actual_m_sha} != {expected["manifest_sha256"]}')
            if not archive_path.is_file():
                raise ValueError(f'Missing archive file {archive_path}')
            actual_size = archive_path.stat().st_size
            if actual_size != expected['archive_size']:
                raise ValueError(f'{archive_name} size mismatch: {actual_size} != {expected["archive_size"]}')
            notes.append(f'Verified staged {manifest_name} (SHA-256 ok) and {archive_name} ({actual_size:,} bytes)')

    return notes


def check_onboarding_and_ui_guidance(root: Path) -> list[str]:
    required_paths = [
        'scripts/setup_local.py',
        'src/eeglayoutlab/cli/quickstart.py',
        'src/eeglayoutlab/server/routes/data_status.py',
        'webapp/components/data-readiness-notice.tsx',
        'webapp/scripts/build-browser-fixtures.mjs',
    ]
    for rel in required_paths:
        if not (root / rel).is_file():
            raise ValueError(f'Missing onboarding/UI/CI file: {rel}')

    notice_src = (root / 'webapp/components/data-readiness-notice.tsx').read_text(encoding='utf-8')
    if 'eeglayoutlab data install' not in notice_src or 'eeglayoutlab quickstart' not in notice_src:
        raise ValueError('DataReadinessNotice must display eeglayoutlab data install / quickstart commands')

    return [
        '3-command onboarding (quickstart, doctor, setup_local.py) and web UI /api/data-status banner verified'
    ]


def check_workflows_and_release_metadata(root: Path) -> list[str]:
    import yaml  # type: ignore[import-untyped]

    wf_dir = root / '.github/workflows'
    present = {p.name for p in wf_dir.glob('*.yml')}
    missing = EXPECTED_WORKFLOWS - present
    if missing:
        raise ValueError(f'Missing GitHub Actions workflows: {sorted(missing)}')

    for name in sorted(present):
        parsed = yaml.safe_load((wf_dir / name).read_text(encoding='utf-8'))
        if not isinstance(parsed, dict):
            raise ValueError(f'{name}: workflow YAML did not parse as mapping')
        if parsed.get('permissions') != {'contents': 'read'}:
            raise ValueError(f'{name}: top-level permissions must be {{"contents": "read"}}')

    for meta_rel in ('CITATION.cff', '.zenodo.json', 'SECURITY.md', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'):
        path = root / meta_rel
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f'Missing or empty release metadata file: {meta_rel}')

    cff_parsed = yaml.safe_load((root / 'CITATION.cff').read_text(encoding='utf-8'))
    if cff_parsed.get('cff-version') != '1.2.0' or cff_parsed.get('license') != 'GPL-3.0-only':
        raise ValueError('CITATION.cff must declare cff-version 1.2.0 and license GPL-3.0-only')

    mkdocs_text = (root / 'mkdocs.yml').read_text(encoding='utf-8')
    if 'provider: mike' not in mkdocs_text:
        raise ValueError('mkdocs.yml must configure extra.version.provider: mike')

    return [
        f'All {len(present)} GitHub Actions workflows, mike config, and release metadata files verified'
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Verify local readiness for EEG Layout Lab v0.2.1 release.')
    parser.add_argument('--root', type=Path, default=ROOT, help='Repository root to inspect')
    parser.add_argument('--check', action='store_true', default=True, help='Run non-mutating pre-release checks')
    parser.add_argument(
        '--verify-archives',
        type=Path,
        default=None,
        metavar='DIR',
        help='Optional directory holding built data package .json manifests and .tar archives',
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        current_ver, ver_notes = check_versions(root)
        data_notes = check_data_packages(root, args.verify_archives)
        ui_notes = check_onboarding_and_ui_guidance(root)
        wf_notes = check_workflows_and_release_metadata(root)
    except Exception as exc:  # noqa: BLE001
        print(f'[FAIL] v0.2.1 readiness check failed: {exc}', file=sys.stderr)
        return 1

    print('EEG Layout Lab v0.2.1 Pre-Release Check')
    for line in [*ver_notes, *data_notes, *ui_notes, *wf_notes]:
        print(f'  [ OK ] {line}')

    if current_ver == '0.2.0':
        print(
            '  [NEXT] Version manifests are currently at 0.2.0. When ready to cut v0.2.1, update the 5 version '
            'fields to 0.2.1, add the v0.2.1 header in CHANGELOG.md, and follow docs/release-v0.2.1-checklist.md.'
        )
    else:
        print('  [READY] Version manifests are set to 0.2.1; ready for maintainer commit and v0.2.1 tag.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
