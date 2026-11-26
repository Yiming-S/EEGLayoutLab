"""The head packages a design evaluation can use: ``DesignEvaluationService.heads`` of Node's
``webapp/server/design-evaluation-server.mjs`` (lines 474-499), statement by statement. Read only; never starts
Python.

A directory ``results/v2/heads/<head_id>`` is offered when it is a plain directory (not a link) named like a head
(at most 40 characters of ``[a-z0-9]`` groups joined by ``_`` or ``-``) whose real path is inside the project; its
six package files and the table's ``index.npz`` and ``rows.npy`` resolve (``realpath(3)``, ``nodefs.realpath``) to
regular files inside the project; ``package.json`` names the same head; and the table manifest still has the
digest ``table.json`` records (``InputIntegrity.digest``, the digest design identities use). Any failure for one
package leaves it out silently. The project is ``InputIntegrity``'s root (``fs.realpathSync`` of the root), and the
two JSON files are read at ``nodepath.join(root, ...)`` with links followed, as in Node.
"""
from __future__ import annotations

import re
import stat as stat_module
from typing import Any, Optional

from ..schemas import jsjson
from . import nodefs, nodepath
from .identity import UNDEFINED, _member, _path, _same
from .integrity import InputIntegrity
from .records import error_code, read_file, realpath, scandir, stat
from .runtime import installed_environment

__all__ = ['HEADS_DIRECTORY', 'HEAD_PACKAGE_FILES', 'heads']

HEADS_DIRECTORY = 'results/v2/heads'
HEAD_PACKAGE_FILES = ('package.json', 'scalp.npz', 'admissibility.npz', 'sources.npz', 'mapping.npz', 'table.json')
_HEAD_ID = re.compile('[a-z0-9]+(?:[_-][a-z0-9]+)*')
_HEAD_ID_LIMIT = 40


def _units(text: str) -> bytes:
    """A sort key in UTF-16 code-unit order (JavaScript's ``<`` on strings)."""
    return text.encode('utf-16-be', errors='surrogatepass')


def _contained_file(root: str, path: str) -> None:
    """``file(path)``: the real path of ``path`` (relative to the real root) must be a regular file inside it."""
    real = realpath(nodepath.resolve(root, path))
    if not real.startswith(root + '/') or not stat_module.S_ISREG(stat(real).st_mode):
        raise ValueError('outside')


def _read_json(path: str) -> Any:
    """``JSON.parse(await readFile(path, 'utf8'))``."""
    return jsjson.parse(nodefs.decode(read_file(path)))


def _nullish_default(value: Any) -> Any:
    """``value ?? ''``."""
    return '' if value is None or value is UNDEFINED else value


def _option(value: Any, key: str) -> Any:
    """``value?.key``."""
    return UNDEFINED if value is None or value is UNDEFINED else _member(value, key)


def heads(root: str, inputs: Optional[InputIntegrity] = None) -> list[dict]:
    """``await heads()``: ``[{head_id, dataset, subject}]`` in code-unit order of the directory names.

    ``root`` is the service root (``RuntimeConfig.repository_root``, Node's ``queue.root``); ``inputs`` the
    service's ``InputIntegrity`` (its memo is shared with the design identities), built here when ``None``. A
    missing ``results/v2/heads`` lists nothing; any other error reading it propagates (Node rejects).
    """
    if inputs is None:
        inputs = InputIntegrity(root, installed_environment(root))
    try:
        entries = scandir(nodepath.join(root, HEADS_DIRECTORY))
    except OSError as error:
        if error_code(error) != 'ENOENT':
            raise
        entries = []
    real_root = inputs.root
    found = []
    for head_id, is_directory in sorted(entries, key=lambda entry: _units(entry[0])):
        head = f'{HEADS_DIRECTORY}/{head_id}'
        if not is_directory or len(_units(head_id)) // 2 > _HEAD_ID_LIMIT or not _HEAD_ID.fullmatch(head_id):
            continue
        try:
            if not realpath(nodepath.resolve(real_root, head)).startswith(real_root + '/'):
                continue
            for name in HEAD_PACKAGE_FILES:
                _contained_file(real_root, f'{head}/{name}')
            manifest = _read_json(nodepath.join(root, head, 'package.json'))
            table = _read_json(nodepath.join(root, head, 'table.json'))
            manifest_path = _member(table, 'manifest_path')
            directory = nodepath.dirname(_path(manifest_path))
            for path in (nodepath.join(directory, 'index.npz'), nodepath.join(directory, 'rows.npy')):
                _contained_file(real_root, path)
            if (not _same(_member(manifest, 'head_id'), head_id)
                    or not _same(inputs.digest(manifest_path), _member(table, 'manifest_sha256'))):
                continue
            dataset = _member(manifest, 'dataset')
            found.append({'head_id': head_id, 'dataset': _nullish_default(_option(dataset, 'name')),
                          'subject': _nullish_default(_option(dataset, 'subject'))})
        except Exception:  # noqa: BLE001 - incomplete or uncontained packages are not offered
            continue
    return found
