"""The head-package listing (``eeglayoutlab.jobs.design_heads.heads``) equals Node's ``DesignEvaluationService.heads``
(phase 2 slice 3), and ports check-design-decision.mjs:516.

- The port builds that test's packages: complete ones, one without a package file or a table file, one whose
  manifest changed, a link to a package outside the project, a package with a file linked outside it, and a plain
  file.
- Parity: ``HEADS_DRIVER`` runs Node's own ``DesignEvaluationService`` (over the same ``{root, python}`` queue as the
  Node test, so nothing is written) on roots holding many more variants: names at and past each rule, links inside
  and outside the project, package and table files that are not JSON, not objects or carry other types, manifest
  paths that are absolute, leave the project or name a directory, unreadable files and directories, a root reached
  through a link and, on a case-insensitive file system, a root spelled in another letter case (every package is
  then outside the project, as in Node). Lists must be equal text; failures compare by Node's code.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import pytest

from eeglayoutlab.jobs.design_heads import heads
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV, needs_node

ROOT = Path(__file__).resolve().parents[2]
WEBAPP = ROOT / 'webapp'
TABLE = 'h' * 64


def sha(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def write(path: Path, body: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(body, bytes):
        path.write_bytes(body)
    else:
        path.write_text(body if isinstance(body, str) else jsjson.stringify(body), encoding='utf-8')


def head_package(base: Path, head_id: str, *, manifest: str = 'manifest', skip: tuple = (),
                 package: Any = None, table: Any = None) -> None:
    """``headPackage(base, head_id, {manifest, skip})`` of check-design-decision.mjs; ``package`` and ``table``
    replace the bodies of ``package.json`` and ``table.json``."""
    directory = f'results/v2/heads/{head_id}/table/{TABLE}'
    files = {
        'package.json': {'head_id': head_id, 'dataset': {'name': 'IXI', 'subject': head_id}} if package is None
        else package,
        'scalp.npz': 'scalp', 'admissibility.npz': 'mask', 'sources.npz': 'sources', 'mapping.npz': 'mapping',
        'table.json': {'manifest_path': directory + '/manifest.json', 'manifest_sha256': sha('manifest')}
        if table is None else table,
    }
    for name, body in files.items():
        if name not in skip:
            write(base / name, body)
    for name, body in (('manifest.json', manifest), ('index.npz', 'index'), ('rows.npy', 'rows')):
        if name not in skip:
            write(base / 'table' / TABLE / name, body)


def test_head_listing_offers_only_complete_plain_package_directories_contained_in_the_project(tmp_path):
    """check-design-decision.mjs:516."""
    root, outside = tmp_path / 'eeg-design-heads', tmp_path / 'eeg-design-heads-outside'
    root.mkdir()
    outside.mkdir()
    packages = root / 'results/v2/heads'
    assert heads(str(root)) == []
    head_package(packages / 'ixi002', 'ixi002')
    head_package(packages / 'ixi012', 'ixi012', skip=('mapping.npz',))
    head_package(packages / 'ixi013', 'ixi013', skip=('rows.npy',))
    head_package(packages / 'ixi014', 'ixi014', manifest='changed manifest')
    head_package(outside / 'ext1', 'ext1')
    (packages / 'ext1').symlink_to(outside / 'ext1')
    head_package(packages / 'ext2', 'ext2')
    (packages / 'ext2/scalp.npz').unlink()
    write(outside / 'scalp.npz', 'scalp')
    (packages / 'ext2/scalp.npz').symlink_to(outside / 'scalp.npz')
    write(packages / 'notes', 'not a package')
    assert heads(str(root)) == [{'head_id': 'ixi002', 'dataset': 'IXI', 'subject': 'ixi002'}]


# --- Parity with Node -------------------------------------------------------------------------------------------

def variants_root(root: Path, outside: Path) -> None:
    """Packages that pass or fail each rule of ``heads()``."""
    packages = root / 'results/v2/heads'
    for name in ('ixi002', 'a', '0a', 'a-1', 'a_1', 'b1', 'a1-b2_c3', 'x' * 40, 'z' * 41, 'A1', 'a--b', '-a', 'a-',
                 'a.b', 'ä1', 'a b', 'ａ1'):
        head_package(packages / name, name)
    # Package manifests: the head id, and what dataset and subject become.
    head_package(packages / 'other-id', 'other-id', package={'head_id': 'ixi002'})
    head_package(packages / 'no-dataset', 'no-dataset', package={'head_id': 'no-dataset'})
    head_package(packages / 'null-dataset', 'null-dataset', package={'head_id': 'null-dataset', 'dataset': None})
    head_package(packages / 'text-dataset', 'text-dataset', package={'head_id': 'text-dataset', 'dataset': 'IXI'})
    head_package(packages / 'list-dataset', 'list-dataset', package={'head_id': 'list-dataset', 'dataset': ['IXI']})
    head_package(packages / 'typed-dataset', 'typed-dataset', package={
        'head_id': 'typed-dataset', 'dataset': {'name': None, 'subject': 5, '__proto__': {'name': 'x'}}})
    head_package(packages / 'object-dataset', 'object-dataset', package={
        'head_id': 'object-dataset', 'dataset': {'name': {'a': [1, 2.5]}, 'subject': ''}})
    head_package(packages / 'duplicate-id', 'duplicate-id',
                 package='{"head_id":"nobody","head_id":"duplicate-id","dataset":{"name":"Ⅸ","subject":"s"}}')
    head_package(packages / 'bom', 'bom', package=b'\xef\xbb\xbf{"head_id":"bom"}')
    head_package(packages / 'latin1', 'latin1', package=b'{"head_id":"latin1","dataset":{"name":"\xe9"}}')
    head_package(packages / 'not-json', 'not-json', package='{head_id: "not-json"}')
    head_package(packages / 'null-package', 'null-package', package='null')
    head_package(packages / 'list-package', 'list-package', package='["list-package"]')
    head_package(packages / 'id-number', 'id-number', package={'head_id': 5})
    # Tables: manifest paths and digests.
    head_package(packages / 'null-table', 'null-table', table='null')
    head_package(packages / 'list-table', 'list-table', table='[]')
    head_package(packages / 'number-path', 'number-path',
                 table={'manifest_path': 5, 'manifest_sha256': sha('manifest')})
    head_package(packages / 'no-digest', 'no-digest',
                 table={'manifest_path': f'results/v2/heads/no-digest/table/{TABLE}/manifest.json'})
    head_package(packages / 'digest-number', 'digest-number',
                 table={'manifest_path': f'results/v2/heads/digest-number/table/{TABLE}/manifest.json',
                        'manifest_sha256': 5})
    head_package(packages / 'upper-digest', 'upper-digest',
                 table={'manifest_path': f'results/v2/heads/upper-digest/table/{TABLE}/manifest.json',
                        'manifest_sha256': sha('manifest').upper()})
    head_package(packages / 'absolute', 'absolute',
                 table={'manifest_path': str(packages / f'absolute/table/{TABLE}/manifest.json'),
                        'manifest_sha256': sha('manifest')})
    head_package(packages / 'dotted', 'dotted',
                 table={'manifest_path': f'results/../results/v2/heads/dotted/table/{TABLE}/./manifest.json',
                        'manifest_sha256': sha('manifest')})
    head_package(packages / 'shared-table', 'shared-table',
                 table={'manifest_path': f'results/v2/heads/ixi002/table/{TABLE}/manifest.json',
                        'manifest_sha256': sha('manifest')})
    head_package(outside / 'far', 'far')
    head_package(packages / 'outside-table', 'outside-table',
                 table={'manifest_path': str(outside / f'far/table/{TABLE}/manifest.json'),
                        'manifest_sha256': sha('manifest')})
    head_package(packages / 'directory-manifest', 'directory-manifest', skip=('manifest.json',),
                 table={'manifest_path': f'results/v2/heads/directory-manifest/table/{TABLE}/manifest.json',
                        'manifest_sha256': sha('manifest')})
    (packages / f'directory-manifest/table/{TABLE}/manifest.json').mkdir()
    head_package(packages / 'nul-path', 'nul-path', table={'manifest_path': 'results/v2/heads/nul-path/table\u0000/m',
                                                           'manifest_sha256': sha('manifest')})
    head_package(packages / 'directory-rows', 'directory-rows', skip=('rows.npy',))
    (packages / f'directory-rows/table/{TABLE}/rows.npy').mkdir()
    # Links: files inside the project are followed; a package directory that is a link is not a package.
    head_package(packages / 'linked-files', 'linked-files')
    for name, target in (('scalp.npz', packages / 'ixi002/scalp.npz'),
                         ('table.json', packages / 'ixi002/table.json')):
        (packages / 'linked-files' / name).unlink()
        (packages / 'linked-files' / name).symlink_to(target)
    (packages / 'ixi002-link').symlink_to(packages / 'ixi002')
    head_package(outside / 'ext1', 'ext1')
    (packages / 'ext1').symlink_to(outside / 'ext1')
    head_package(packages / 'dangling', 'dangling')
    (packages / 'dangling/sources.npz').unlink()
    (packages / 'dangling/sources.npz').symlink_to(root / 'missing')
    write(packages / 'notes', 'not a package')
    if os.geteuid() != 0:
        head_package(packages / 'unreadable-package', 'unreadable-package')
        (packages / 'unreadable-package/package.json').chmod(0)
        head_package(packages / 'unreadable-manifest', 'unreadable-manifest')
        (packages / f'unreadable-manifest/table/{TABLE}/manifest.json').chmod(0)
        head_package(packages / 'closed', 'closed')
        (packages / 'closed').chmod(0o600)


def case_insensitive(directory: Path) -> bool:
    probe = directory / 'Case-Probe'
    probe.mkdir()
    try:
        return (directory / 'case-probe').exists()
    finally:
        probe.rmdir()


HEADS_DRIVER = r"""
// Node reference of tests/service/test_heads.py: DesignEvaluationService.heads() on each root, over the
// {root, python} queue check-design-decision.mjs uses (nothing is written).
import { readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const [specPath, outPath] = process.argv.slice(2);
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const server = pathToFileURL(`${spec.webapp}/server/design-evaluation-server.mjs`).href;
const { DesignEvaluationService } = await import(server);
const out = {};
for (const item of spec.roots) {
  try {
    const service = new DesignEvaluationService({ root: item.root, python: 'python3' });
    out[item.id] = { ok: true, value: JSON.stringify(await service.heads()) };
    service.dispose();
  } catch (error) {
    out[item.id] = { ok: false, code: error?.code ?? null, message: String(error?.message ?? error) };
  }
}
writeFileSync(outPath, JSON.stringify(out));
process.exit(0);
"""


def run_heads_node(roots: dict[str, str], scratch: Path) -> dict:
    driver, spec_path, out_path = scratch / 'heads.mjs', scratch / 'heads-spec.json', scratch / 'heads.json'
    driver.write_text(HEADS_DRIVER, encoding='utf-8')
    spec_path.write_text(jsjson.stringify({'webapp': str(WEBAPP), 'roots': [
        {'id': id, 'root': root} for id, root in roots.items()]}), encoding='utf-8')
    subprocess.run(['node', str(driver), str(spec_path), str(out_path)], check=True, cwd=ROOT, env=NODE_ENV)
    return json.loads(out_path.read_text(encoding='utf-8'))


def python_heads(root: str) -> dict:
    from eeglayoutlab.jobs.records import error_code

    try:
        return {'ok': True, 'value': jsjson.stringify(heads(root))}
    except Exception as error:  # noqa: BLE001 - compared with Node
        code = error_code(error)
        return {'ok': False, 'code': code} if code else {'ok': False, 'message': str(error)}


def node_result(result: dict) -> dict:
    if result['ok']:
        return result
    return {'ok': False, 'code': result['code']} if result['code'] else {'ok': False, 'message': result['message']}


@pytest.fixture(scope='module')
def parity(tmp_path_factory):
    base = tmp_path_factory.mktemp('heads-parity')
    variants_root(base / 'variants', base / 'outside')
    roots = {'variants': str(base / 'variants'), 'empty': str(base / 'empty')}
    (base / 'empty/results/v2').mkdir(parents=True)
    (base / 'linked').symlink_to(base / 'variants')
    roots['linked'] = str(base / 'linked')
    roots['through-link'] = str(base / 'linked/results/..')
    file_root = base / 'file-heads'
    write(file_root / 'results/v2/heads', 'not a directory')
    roots['file-heads'] = str(file_root)
    if case_insensitive(base):
        roots['other-case'] = str(base / 'VARIANTS')
    if os.geteuid() != 0:
        closed = base / 'closed-heads'
        head_package(closed / 'results/v2/heads/ixi002', 'ixi002')
        (closed / 'results/v2/heads').chmod(0)
        roots['closed-heads'] = str(closed)
    try:
        node = run_heads_node(roots, tmp_path_factory.mktemp('heads-node'))
        python = {id: python_heads(root) for id, root in roots.items()}
    finally:
        if 'closed-heads' in roots:
            (base / 'closed-heads/results/v2/heads').chmod(0o700)
        if os.geteuid() != 0:
            (base / 'variants/results/v2/heads/closed').chmod(0o700)
    return node, python


@needs_node
@pytest.mark.parametrize('root', ['variants', 'empty', 'linked', 'through-link', 'file-heads', 'other-case',
                                  'closed-heads'])
def test_heads_parity(root, parity):
    node, python = parity
    if root not in node:
        pytest.skip('not applicable on this system')
    assert python[root] == node_result(node[root])


@needs_node
def test_heads_parity_covers_each_rule(parity):
    node, _ = parity
    listed = {head['head_id']: head for head in json.loads(node['variants']['value'])}
    assert {'ixi002', 'a', '0a', 'a-1', 'a_1', 'b1', 'a1-b2_c3', 'x' * 40, 'linked-files', 'absolute', 'dotted',
            'shared-table', 'duplicate-id', 'latin1', 'no-dataset', 'typed-dataset', 'object-dataset'} <= set(listed)
    assert not {'z' * 41, 'A1', 'a--b', '-a', 'a-', 'a.b', 'ä1', 'a b', 'ａ1', 'other-id', 'bom', 'not-json',
                'null-package', 'list-package', 'id-number', 'null-table', 'list-table', 'number-path', 'no-digest',
                'digest-number', 'upper-digest', 'outside-table', 'directory-manifest', 'nul-path', 'directory-rows',
                'ixi002-link', 'ext1', 'dangling', 'notes', 'unreadable-package', 'unreadable-manifest',
                'closed'} & set(listed)
    assert listed['typed-dataset'] == {'head_id': 'typed-dataset', 'dataset': '', 'subject': 5}
    assert list(listed) == sorted(listed)
    assert node['file-heads']['code'] == 'ENOTDIR'
    if 'other-case' in node:
        assert node['other-case']['value'] == '[]'
    if 'closed-heads' in node:
        assert node['closed-heads']['code'] == 'EACCES'
