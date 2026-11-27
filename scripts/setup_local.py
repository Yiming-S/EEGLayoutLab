#!/usr/bin/env python3
"""One-command first-time setup for a source checkout of EEGLayoutLab (macOS arm64 & Linux x86_64).

Runs with any system Python 3.9+ using only the standard library:
  1. Downloads (if needed) and SHA-256-verifies the base model bundle against data/manifest.json
     (no GitHub sign-in, no `gh` CLI, and no platform-specific shasum/sha256sum step needed).
  2. Installs or verifies the locked scientific runtime under .runtime/ via scripts/bootstrap_runtime.py
     (auto-detecting conda/mamba/micromamba in common install locations even before `conda init`).
  3. Creates an isolated .venv from the pinned Python 3.11 interpreter in .runtime/ and installs
     `pip install -e '.[service]'` (no separate Homebrew/system Python 3.11 installation needed).
  4. Builds the web interface in webapp/ (`npm ci && npm run build`) and runs `eeglayoutlab doctor`
     (plus optional `--smoke` calculation check and `--serve` immediate launch).

All four steps are idempotent: re-running skips completed stages. Use `--plan` for a read-only preview.
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_FILENAME = 'eeglayoutlab-data-v1.tar.gz'
DEFAULT_BUNDLE_URL = '/'.join((
    'https:', '', 'github.com', 'Yiming-S', 'EEGLayoutLab',
    'releases', 'download', 'v0.2.0', BUNDLE_FILENAME,
))
MIN_NODE = (22, 18, 0)
CHUNK = 1024 * 1024


class SetupError(RuntimeError):
    """A prerequisite or setup stage failed."""


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https':
            raise urllib.error.URLError(f'refusing non-HTTPS redirect to {parsed.scheme or "unknown"} URL')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _runtime_prefix_name() -> str:
    sys_name, machine = platform.system(), platform.machine()
    if (sys_name, machine) == ('Darwin', 'arm64'):
        return 'simnibs-4.6.0'
    if (sys_name, machine) == ('Linux', 'x86_64'):
        return 'compute-linux-64'
    if sys_name == 'Darwin':
        raise SetupError('Native Apple Silicon (arm64) Python/Terminal is required; disable Rosetta in Terminal.')
    raise SetupError(f'Unsupported platform {sys_name} {machine}; supported source locks: macOS arm64, Linux x86_64.')


def _find_conda(explicit: Optional[str]) -> Optional[str]:
    if explicit:
        cand = Path(explicit).expanduser()
        return str(cand.resolve()) if cand.is_file() and os.access(cand, os.X_OK) else None
    for name in ('conda', 'mamba', 'micromamba'):
        found = shutil.which(name)
        if found and os.access(found, os.X_OK):
            return str(Path(found).resolve())
    home = Path.home()
    common = [
        home / 'miniforge3/bin/conda',
        home / 'mambaforge/bin/conda',
        home / 'miniconda3/bin/conda',
        home / 'anaconda3/bin/conda',
        home / '.local/bin/micromamba',
        Path('/opt/homebrew/Caskroom/miniforge/base/bin/conda'),
        Path('/opt/homebrew/bin/micromamba'),
        Path('/opt/homebrew/bin/conda'),
        Path('/usr/local/bin/micromamba'),
    ]
    for cand in common:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand.resolve())
    return None


def _parse_node_version(text: str) -> Optional[tuple[int, int, int]]:
    match = re.match(r'^v?(\d+)\.(\d+)\.(\d+)', text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _find_node_bin_dir() -> Optional[tuple[Path, tuple[int, int, int]]]:
    candidates: list[Path] = []
    which_node = shutil.which('node')
    if which_node:
        candidates.append(Path(which_node).parent)
    home = Path.home()
    candidates.extend([
        Path('/opt/homebrew/bin'),
        Path('/usr/local/bin'),
        home / '.volta/bin',
    ])
    for pattern in (
        str(home / '.nvm/versions/node/*/bin'),
        str(home / '.fnm/node-versions/*/installation/bin'),
    ):
        for entry in sorted(glob.glob(pattern), reverse=True):
            candidates.append(Path(entry))

    seen: set[str] = set()
    best_old: Optional[tuple[Path, tuple[int, int, int]]] = None
    for directory in candidates:
        key = str(directory)
        if key in seen:
            continue
        seen.add(key)
        node_bin = directory / 'node'
        npm_bin = directory / 'npm'
        if not (node_bin.is_file() and os.access(node_bin, os.X_OK) and npm_bin.is_file()):
            continue
        try:
            out = subprocess.run([str(node_bin), '--version'], capture_output=True, text=True, timeout=10)
        except OSError:
            continue
        ver = _parse_node_version(out.stdout) if out.returncode == 0 else None
        if ver is None:
            continue
        if ver >= MIN_NODE:
            return directory, ver
        if best_old is None or ver > best_old[1]:
            best_old = (directory, ver)
    return best_old


def _base_data_verified(root: Path) -> bool:
    res = subprocess.run(
        [sys.executable, str(root / 'scripts/data_bundle.py'), 'verify', '--root', str(root)],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def _runtime_verified(root: Path, prefix: Path) -> bool:
    py = prefix / 'bin/python'
    if not py.is_file():
        return False
    res = subprocess.run(
        [str(py), str(root / 'scripts/check_environment.py'), '--prefix', str(prefix)],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def _venv_verified(venv_dir: Path) -> bool:
    py = venv_dir / 'bin/python'
    cli = venv_dir / 'bin/eeglayoutlab'
    if not (py.is_file() and cli.is_file()):
        return False
    res = subprocess.run(
        [str(py), '-c', 'import eeglayoutlab, fastapi, uvicorn, pydantic'],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def _download_https(url: str, destination: Path) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https':
        raise SetupError(f'Bundle URL must use https: {url}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    part = destination.with_name(destination.name + '.part')
    opener = urllib.request.build_opener(_HttpsOnlyRedirect())
    req = urllib.request.Request(url, headers={'User-Agent': 'EEGLayoutLab-Setup/1.0'})
    print(f'  Downloading {BUNDLE_FILENAME} (approx. 282.5 MiB)...', flush=True)
    try:
        with opener.open(req, timeout=60) as resp, part.open('wb') as out:
            total = int(resp.headers.get('Content-Length') or 0)
            done = 0
            shown = -1
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total > 0:
                    pct = done * 100 // total
                    if pct // 10 != shown // 10:
                        shown = pct
                        print(f'    {pct}% ({done / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MiB)', flush=True)
        part.replace(destination)
    except BaseException:
        part.unlink(missing_ok=True)
        raise


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', '--dry-run', dest='plan', action='store_true',
                        help='inspect prerequisites and print the 4-step plan without modifying anything')
    parser.add_argument('--conda', metavar='PATH', help='explicit conda, mamba or micromamba executable')
    parser.add_argument('--bundle', type=Path, metavar='FILE',
                        help=f'local {BUNDLE_FILENAME} archive (skips HTTPS download)')
    parser.add_argument('--bundle-url', default=DEFAULT_BUNDLE_URL, metavar='URL',
                        help='HTTPS URL for the base data archive when not already downloaded')
    parser.add_argument('--install-table', action='store_true',
                        help='also install and compose scalp-node-table (1.40 GB) via eeglayoutlab data install')
    parser.add_argument('--from', dest='mirror', metavar='URL|DIR',
                        help='mirror directory or URL for optional data package installation')
    parser.add_argument('--skip-data', action='store_true', help='skip step 1 (base data bundle)')
    parser.add_argument('--skip-webapp', action='store_true', help='skip step 4 web interface build')
    parser.add_argument('--rebuild-webapp', action='store_true',
                        help='run npm ci && npm run build even when webapp/dist/client already exists')
    parser.add_argument('--smoke', action='store_true',
                        help='run end-to-end smoke calculation (Examples 1 & 2) after setup completes')
    parser.add_argument('--serve', nargs='?', const='', default=None, metavar='WORKSPACE',
                        help='launch the web application immediately after setup (default: ~/eeglayoutlab-workspace)')
    parser.add_argument('--no-browser', action='store_true', help='with --serve, print the URL without opening a browser')
    args = parser.parse_args(argv)

    prefix_name = _runtime_prefix_name()
    runtime_prefix = ROOT / '.runtime' / prefix_name
    venv_dir = ROOT / '.venv'
    webapp_index = ROOT / 'webapp/dist/client/index.html'

    data_ok = _base_data_verified(ROOT)
    runtime_ok = _runtime_verified(ROOT, runtime_prefix)
    venv_ok = _venv_verified(venv_dir)
    webapp_ok = webapp_index.is_file() and not args.rebuild_webapp

    conda_exe = _find_conda(args.conda)
    node_found = None if args.skip_webapp else _find_node_bin_dir()

    print(f'EEGLayoutLab local source setup ({platform.system()} {platform.machine()})', flush=True)
    print(f'  [1/4] Base model data (data/manifest.json): {"already verified" if data_ok else ("skipped" if args.skip_data else "will install (282.5 MiB download)")}',
          flush=True)
    conda_note = conda_exe or '<missing conda/micromamba>'
    print(f'  [2/4] Scientific runtime (.runtime/{prefix_name}): {"already verified" if runtime_ok else f"will install via {conda_note}"}',
          flush=True)
    print(f'  [3/4] Service CLI (.venv/bin/eeglayoutlab): {"already ready" if venv_ok else "will create from .runtime Python 3.11"}',
          flush=True)
    if args.skip_webapp:
        web_msg = 'skipped (--skip-webapp)'
    elif webapp_ok:
        web_msg = 'already built (pass --rebuild-webapp to rebuild)'
    elif node_found and node_found[1] >= MIN_NODE:
        v = '.'.join(map(str, node_found[1]))
        web_msg = f'will build with Node.js v{v} ({node_found[0]})'
    elif node_found:
        v = '.'.join(map(str, node_found[1]))
        web_msg = f'Node.js v{v} is older than required >= 22.18.0'
    else:
        web_msg = 'Node.js >= 22.18.0 not found'
    print(f'  [4/4] Web interface (webapp/dist/client): {web_msg}', flush=True)

    if args.plan:
        print('Plan complete (--plan: no files were modified).', flush=True)
        return 0

    # Validate prerequisites for any step that actually needs to run.
    if not runtime_ok and conda_exe is None:
        raise SetupError(
            'Conda or micromamba was not found. Install Miniforge (arm64 on Mac, x86_64 on Linux) '
            'or pass --conda /path/to/conda.'
        )
    if not args.skip_webapp and not webapp_ok:
        if node_found is None:
            raise SetupError('Node.js >= 22.18.0 and npm are required to build webapp/; install Node 22.18+ or pass --skip-webapp.')
        if node_found[1] < MIN_NODE:
            found_str = '.'.join(map(str, node_found[1]))
            raise SetupError(f'Found Node.js v{found_str} at {node_found[0]}, but >= 22.18.0 is required.')

    # Step 1: Base data bundle
    if not data_ok and not args.skip_data:
        print('\n==> [1/4] Installing and verifying base model data...', flush=True)
        archive = args.bundle.expanduser().resolve() if args.bundle else (ROOT / 'releases' / BUNDLE_FILENAME)
        if not archive.is_file():
            if args.bundle:
                raise SetupError(f'Bundle file not found: {archive}')
            _download_https(args.bundle_url, archive)
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts/data_bundle.py'), 'install', '--root', str(ROOT), str(archive)],
            check=True,
        )
        subprocess.run(
            [sys.executable, str(ROOT / 'scripts/data_bundle.py'), 'verify', '--root', str(ROOT)],
            check=True,
        )

    # Step 2: Managed computation runtime
    if not runtime_ok:
        print(f'\n==> [2/4] Preparing scientific runtime (.runtime/{prefix_name})...', flush=True)
        assert conda_exe is not None
        cmd = [sys.executable, str(ROOT / 'scripts/bootstrap_runtime.py'), '--execute', '--conda', conda_exe]
        marker = ROOT / '.runtime' / f'{prefix_name}.bootstrap.json'
        if runtime_prefix.exists() and marker.is_file():
            cmd.append('--resume')
        subprocess.run(cmd, cwd=ROOT, check=True)

    # Step 3: Isolated .venv built from the verified Python 3.11 in .runtime/<prefix>
    if not venv_ok:
        print('\n==> [3/4] Creating .venv and installing eeglayoutlab CLI & service...', flush=True)
        runtime_py = runtime_prefix / 'bin/python'
        if not runtime_py.is_file():
            raise SetupError(f'Expected Python 3.11 interpreter at {runtime_py}')
        clean_env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        clean_env['PYTHONNOUSERSITE'] = '1'
        if not (venv_dir / 'bin/python').is_file():
            subprocess.run([str(runtime_py), '-m', 'venv', str(venv_dir)], cwd=ROOT, env=clean_env, check=True)
        subprocess.run(
            [str(venv_dir / 'bin/python'), '-m', 'pip', 'install', '-e', '.[service]'],
            cwd=ROOT,
            env=clean_env,
            check=True,
        )

    # Step 4: Build static web interface
    if not args.skip_webapp and not webapp_ok:
        print('\n==> [4/4] Building static web interface (webapp/dist/client)...', flush=True)
        assert node_found is not None
        node_dir = str(node_found[0])
        web_env = os.environ.copy()
        web_env['PATH'] = node_dir + os.pathsep + web_env.get('PATH', '')
        subprocess.run(
            [str(node_found[0] / 'npm'), 'ci', '--no-audit', '--no-fund', '--prefer-offline'],
            cwd=ROOT / 'webapp',
            env=web_env,
            check=True,
        )
        subprocess.run(
            [str(node_found[0] / 'npm'), 'run', 'build'],
            cwd=ROOT / 'webapp',
            env=web_env,
            check=True,
        )

    eeg_bin = venv_dir / 'bin/eeglayoutlab'
    if args.install_table:
        print('\n==> Installing and composing nominal scalp-node-table...', flush=True)
        table_cmd = [str(eeg_bin), 'data', 'install', 'scalp-node-table', '--compose', '--root', str(ROOT)]
        if args.mirror:
            table_cmd.extend(['--from', args.mirror])
        subprocess.run(table_cmd, cwd=ROOT, check=True)

    print('\n==> Running installation health check...', flush=True)
    doctor_cmd = [str(eeg_bin), 'doctor', '--root', str(ROOT)]
    if args.smoke:
        doctor_cmd.append('--smoke')
    subprocess.run(doctor_cmd, cwd=ROOT, check=True)

    if args.serve is not None:
        serve_cmd = [str(eeg_bin), 'quickstart', '--root', str(ROOT)]
        if args.serve:
            serve_cmd.append(args.serve)
        else:
            serve_cmd.append('--base-only')
        if args.no_browser:
            serve_cmd.append('--no-browser')
        return subprocess.run(serve_cmd, cwd=ROOT).returncode

    print('\nSetup complete! Start EEGLayoutLab anytime with:', flush=True)
    print('  .venv/bin/eeglayoutlab serve ~/eeglayoutlab-workspace', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (SetupError, subprocess.CalledProcessError, urllib.error.URLError, OSError) as err:
        print(f'setup_local: {err}', file=sys.stderr, flush=True)
        sys.exit(1)
