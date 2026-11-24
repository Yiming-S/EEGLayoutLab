"""Shared setup for the workspace queue tests (``eeglayoutlab.jobs.queue``, tests/service/test_queue.py).

``Stubs`` is the fixture of check-community-queue.mjs:11-38 for Python: one stub adapter per kind, sharing a
scientific revision (``v1``, then ``v2`` after ``change()``), recording every start and keeping its jobs and stored
results in memory. ``finish(kind)`` ends the running job as the fixture's ``finish`` does and then calls the
completion callbacks (``on_finish``), as a real service does once its records are written. Methods can be replaced
on one adapter, as the Node tests reassign ``f.adapters[kind].start``.

``run_scenario`` interprets the scenario steps of ``parity/queue_views.mjs`` (its header documents them) with the
Python queue; ``node_scenarios`` runs the same scenarios with Node's ``CommunityQueue``; ``comparable`` puts both
outputs in the compared form (``owners``, ``networks`` and ``online_visitors`` removed, identifiers numbered in
order of appearance).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Optional
import uuid

from eeglayoutlab.jobs.queue import WorkspaceQueue
from eeglayoutlab.schemas import jsjson

from .key_parity_support import NODE_ENV

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / 'tests/service/parity/queue_views.mjs'
KINDS = ('local-compute', 'source-reception', 'design-evaluation', 'electrode-editor')
PICKED = ('id', 'sequence', 'kind', 'key', 'status', 'created_at', 'progress', 'cached', 'catalog', 'finished_at',
          'message')
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_DROPPED = ('owners', 'networks', 'online_visitors')


class StubAdapter:
    """One kind of the fixture: ``prepare`` refuses anything but ``{n: <integer>}``; ``start`` records
    ``'<kind>:<n>'`` and returns a running job."""

    def __init__(self, stubs: 'Stubs', kind: str):
        self.stubs, self.kind = stubs, kind
        self.workers: dict[str, dict] = {}
        self.caches: dict[str, dict] = {}
        self.callbacks: list[Callable[[str, dict], None]] = []

    def key(self, n: Any) -> str:
        return f'{self.stubs.revision}-{jsjson.number_to_string(n)}'

    async def prepare(self, raw: Any) -> dict:
        if not isinstance(raw, dict) or not jsjson.is_integer(raw.get('n')):
            raise ValueError('invalid')
        return {'request': raw, 'key': self.key(raw['n'])}

    async def lookup(self, prepared: dict) -> dict:
        cache = self.caches.get(prepared['key'])
        return {'hit': True, 'job': cache} if cache is not None else {'hit': False}

    async def start(self, prepared: dict) -> dict:
        request = prepared['request']
        self.stubs.starts.append(f'{self.kind}:{jsjson.number_to_string(request["n"])}')
        job = {'id': str(uuid.uuid4()), 'key': self.key(request['n']), 'request': request, 'status': 'running',
               'result': None}
        self.workers[job['id']] = job
        return {'job': job}

    def get(self, id: Any) -> Optional[dict]:
        return self.workers.get(id)

    def pid(self) -> Optional[int]:
        return None

    def busy(self) -> bool:
        return any(job['status'] in ('running', 'cancelling') for job in self.workers.values())

    def cancel(self, id: Any) -> None:
        self.workers[id]['status'] = 'cancelling'

    def on_finish(self, callback: Callable[[str, dict], None]) -> None:
        self.callbacks.append(callback)

    def running(self) -> dict:
        return next(job for job in self.workers.values() if job['status'] in ('running', 'cancelling'))

    def finish(self, status: Optional[str] = None, **members: Any) -> dict:
        """The fixture's ``finish``: running -> completed (stored as a cache hit), cancelling -> cancelled; or the
        given status and members. Then the completion callbacks."""
        job = self.running()
        if status is None:
            job['status'] = 'cancelled' if job['status'] == 'cancelling' else 'completed'
            job['result'] = {'scientific': True}
            if job['status'] == 'completed':
                self.caches[job['key']] = {**job, 'cached': True}
        else:
            job['status'] = status
            job.update(members)
        for callback in list(self.callbacks):
            callback(job['id'], job)
        return job


class Stubs:
    def __init__(self, kinds: tuple[str, ...] = KINDS):
        self.revision = 'v1'
        self.starts: list[str] = []
        self.adapters = {kind: StubAdapter(self, kind) for kind in kinds}

    def finish(self, kind: str) -> dict:
        return self.adapters[kind].finish()

    def change(self) -> None:
        self.revision = 'v2'


def task_json(directory: Path) -> dict:
    return jsjson.parse((directory / 'queue.json').read_text(encoding='utf-8'))


# --- Parity scenarios ---------------------------------------------------------------------------------------------

def _error(error: BaseException) -> dict:
    status = getattr(error, 'status', None)
    message = getattr(error, 'message', None)
    return {'error': {'status': status, 'message': message if isinstance(message, str) else str(error)}}


async def _run(scenario: dict, directory: Path) -> str:
    clock = [scenario['clock']]
    options = scenario.get('options', {})
    limits = options.get('receiptLimits', {})
    state: dict[str, Any] = {'stubs': Stubs()}
    starts: list[str] = []

    def open_queue(cache_only: bool) -> WorkspaceQueue:
        return WorkspaceQueue(str(directory), state['stubs'].adapters, now=lambda: clock[0],
                              max_queued=options.get('maxQueued', 50), cache_only=bool(cache_only),
                              receipt_limits={'computed': limits.get('computed', 1000),
                                              'cached': limits.get('cached', 300)})
    queue = open_queue(options.get('cacheOnly', False))
    ids: list[str] = []
    records: list = []
    try:
        for step in scenario['steps']:
            op, args = step[0], step[1:]
            stubs: Stubs = state['stubs']
            value: Any = None
            try:
                if op == 'submit':
                    kind, n = args[0], args[1]
                    raw = {'n': n} if jsjson.is_number(n) else n
                    value = await queue.submit(kind, raw, bool(args[2]) if len(args) > 2 else False)
                    job_id = (value.get('job') or {}).get('id')
                    if job_id and job_id not in ids:
                        ids.append(job_id)
                elif op == 'tick':
                    await queue.tick()
                elif op == 'finish':
                    stubs.finish(args[0])
                elif op == 'fail':
                    stubs.adapters[args[0]].finish('failed', message=args[1])
                elif op == 'progress':
                    job = stubs.adapters[args[0]].running()
                    job['progress'], job['stage'], job['message'] = args[1], args[2], args[3]
                elif op == 'cancel':
                    value = await queue.cancel(ids[int(args[0])], args[1] if len(args) > 1 else None)
                elif op == 'view':
                    value = await queue.view(queue.own(ids[int(args[0])]), args[1] if len(args) > 1 else True)
                elif op == 'own':
                    task = queue.own(ids[int(args[0])])
                    value = {name: task[name] for name in PICKED if name in task}
                elif op == 'stats':
                    value = await queue.stats()
                elif op == 'active':
                    value = await queue.active(args[0])
                elif op == 'status':
                    value = queue.maintenance_status()
                elif op == 'cache':
                    kind, n, status, result = args[:4]
                    key = stubs.adapters[kind].key(n)
                    entry = {'key': key, 'status': status, 'result': result, 'cached': True}
                    if len(args) > 4 and args[4]:
                        entry['finished_at'] = args[4]
                    stubs.adapters[kind].caches[key] = entry
                elif op == 'change':
                    stubs.change()
                elif op == 'clock':
                    clock[0] = args[0]
                elif op == 'restart':
                    option = args[0] if args else {}
                    queue.dispose()
                    if not option.get('keep'):
                        starts.extend(stubs.starts)
                        state['stubs'] = Stubs()
                    queue = open_queue(option.get('cacheOnly', False))
                else:
                    raise AssertionError(f'unknown step {op}')
                records.append([op, value])
            except AssertionError:
                raise
            except Exception as error:  # noqa: BLE001 - recorded as Node records its rejections
                records.append([op, _error(error)])
        starts.extend(state['stubs'].starts)
        records.append(['starts', starts])
    finally:
        queue.dispose()
    return jsjson.stringify(records)


def run_scenario(scenario: dict, directory: Path) -> str:
    """The scenario's records as JSON text, from the Python queue in ``directory`` (created)."""
    directory.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_run(scenario, directory))


def node_scenarios(scenarios: list[dict], scratch: Path) -> dict[str, str]:
    """Each scenario's records as Node writes them (``parity/queue_views.mjs``)."""
    spec, out = scratch / 'queue-spec.json', scratch / 'queue-node.json'
    spec.write_text(jsjson.stringify({'scenarios': scenarios}), encoding='utf-8')
    subprocess.run(['node', str(DRIVER), str(spec), str(out)], check=True, cwd=ROOT, env=NODE_ENV)
    output = jsjson.parse(out.read_text(encoding='utf-8'))
    return {item['id']: item['records'] for item in output['scenarios']}


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in _DROPPED}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def comparable(text: str) -> str:
    """The records without the public-service members, identifiers numbered in order of first appearance."""
    text = jsjson.stringify(_strip(jsjson.parse(text)))
    names: dict[str, str] = {}
    return _UUID.sub(lambda match: names.setdefault(match.group(0), f'<id {len(names) + 1}>'), text)
