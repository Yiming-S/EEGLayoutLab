"""``eeglayoutlab serve [WORKSPACE] [--root R] [--port N] [--static DIR] [--docs DIR] [--no-browser] [--cache-only]
[--clear-interrupted]``, ``eeglayoutlab workspace import-legacy [WORKSPACE] [--root R] [--queue-directory Q]
[--dry-run]`` (``server.legacy_import``) and ``eeglayoutlab data`` (data packages, ``eeglayoutlab.data.cli``).

Starts the local service for one workspace (design 0001, decision 6):

- **Workspace** (decision U3): the given directory, created when missing; without one, the current directory
  when it is a workspace, when it is empty, or when the person confirms on a terminal. Without a terminal a new
  workspace needs an explicit path. The Node host's queue directory ``R/results/web-service``, or a directory inside
  it, is refused (exit 2): the Python service never writes there.
- **Root**: ``--root``, else ``EEG_REPOSITORY_ROOT``, else the checkout that holds this package, spelled as Node
  spells it, else the installed root ``P/share/eeglayoutlab/root`` of the environment (``jobs.runtime.repository_root``,
  design 0002). The static interface defaults to ``R/webapp/dist/client`` and the documentation site, served under
  ``/docs/``, to ``R/site`` (what ``mkdocs build`` writes).
- **Read-only root** (0002, decision 3): before a workspace is chosen or opened, R, and the deepest of
  ``R/results/v2`` and ``R/results`` that exists, must be writable, also with ``--cache-only``; otherwise ``serve``
  exits 2, in the installed form with the instruction to create a user environment.
- **Port and token** (decision U6): a new loopback port (``--port``, default a free one) and new tokens at every
  start. The socket is bound before ``runtime.json`` is written, so the file never names a port in use by
  someone else.
- **Instance reuse**: when the workspace is already served, the command opens (or prints) the running instance's
  address and exits 0.
- **Browser**: opened once the service accepts connections, from a thread, so a browser that the launcher waits for
  (a text browser, or a ``BROWSER`` command) never holds up the service, and not once it is stopping. The launch URL
  goes to the browser in ``W/.eeglayoutlab/open.html`` (``workspace.write_open_page``), not on its command line,
  which every local user can read; only macOS's default launcher, which passes the URL on standard input, gets the
  URL itself.
- **Job queue** (``W/.eeglayoutlab/queue.json``): started with the service, after its restart rules. A queue file
  that cannot be used stops ``serve`` with a message and stays as it was. ``--cache-only`` serves stored results
  and refuses new computations (Node's maintenance mode); ``--clear-interrupted`` lets the queue dispatch again after
  a crash left a spawn whose outcome is unknown (a receipt with ``starting`` and no worker) or the pid of a worker
  that blocks dispatch while a process with that pid lives, once the person has checked that no worker of the
  earlier run is still computing.

The service stops on SIGINT or SIGTERM: the runtime file is removed at once, so that a second ``serve`` during the
graceful shutdown waits for the lock instead of opening an instance that no longer answers. The handlers are
installed before the runtime file is written, so a stop that comes while the service starts is never the default
action (the process killed by the signal): ``serve`` then removes the file and exits 0 without serving, or stops the
server it has started. The first signal also stops the compute services at once, as Node's ``dispose`` does: no new
dispatch or admission, the running worker sent SIGTERM (``ComputeHost.stop_soon``); one that comes before they are
built is applied as soon as they are, so nothing is dispatched. Every signal reaches uvicorn as SIGTERM, since uvicorn
takes a repeated SIGINT (Ctrl+C twice) as a forced exit that skips the lifespan's shutdown; that shutdown waits for
the worker and writes its records (``ComputeHost.close``). ``serve`` exits 1 when that last write of the queue fails,
as Node's host does.

``workspace import-legacy`` copies the Node host's research projects, robustness studies and completed signal records
from its queue directory (``--queue-directory``, default ``R/results/web-service``), which it never writes, into the
workspace, chosen as ``serve`` chooses it. It holds the workspace lock, so a served workspace is refused (stop the
service first). It prints what it imported and refused, and exits 0 when nothing was refused, 1 otherwise, 2 for a
usage error.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import logging
import os
import pathlib
import signal
import socket
import sys
import threading
import time
from typing import Any, Callable, Iterator, Optional, Sequence
import webbrowser

from ..data import cli as data_cli
from ..jobs import nodepath
from ..jobs.runtime import checkout_root, installed_form, repository_root, unwritable_root
from ..server.workspace import (
    NODE_QUEUE_DIRECTORY, Workspace, WorkspaceError, WorkspaceInUse, inside, is_workspace, open_url, write_open_page,
)

__all__ = ['main', 'choose_workspace']

PROGRAM = 'eeglayoutlab'
# How long the browser thread waits for the service to accept connections.
STARTUP_SECONDS = 30.0
ROOT_HELP = data_cli.ROOT_HELP


def _port(text: str) -> int:
    try:
        port = int(text, 10)
    except ValueError:
        port = -1
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError(f'invalid port {text!r}; use 0-65535 (0 picks a free port)')
    return port


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROGRAM, description='EEG Layout Lab, the local application.')
    commands = parser.add_subparsers(dest='command', required=True, metavar='COMMAND')
    serve = commands.add_parser('serve', help='serve the interface for a workspace on 127.0.0.1',
                                description='Serve the interface for a workspace on 127.0.0.1 and open it.')
    serve.add_argument('workspace', nargs='?', metavar='WORKSPACE',
                       help='workspace directory (default: the current directory)')
    serve.add_argument('--root', metavar='R', help=ROOT_HELP)
    serve.add_argument('--port', type=_port, default=0, metavar='N', help='loopback port (default: a free port)')
    serve.add_argument('--static', metavar='DIR', help='static interface (default: R/webapp/dist/client)')
    serve.add_argument('--docs', metavar='DIR', help='built documentation site served under /docs/ (default: R/site)')
    serve.add_argument('--no-browser', action='store_true', help='print the address instead of opening a browser')
    serve.add_argument('--cache-only', action='store_true',
                       help='serve stored results only; new computations are refused')
    serve.add_argument('--clear-interrupted', action='store_true',
                       help='dispatch again after an interrupted run whose worker may not have started or may still '
                            'run; use only once no worker of that run is still computing')
    workspace = commands.add_parser('workspace', help='manage a workspace', description='Manage a workspace.')
    actions = workspace.add_subparsers(dest='action', required=True, metavar='ACTION')
    legacy = actions.add_parser(
        'import-legacy', help="copy the Node host's projects, studies and signal records into a workspace",
        description="Copy the Node host's research projects, robustness studies and completed signal records from its "
                    'queue directory into a workspace. The queue directory is only read.')
    legacy.add_argument('workspace', nargs='?', metavar='WORKSPACE',
                        help='workspace directory (default: the current directory)')
    legacy.add_argument('--root', metavar='R', help=ROOT_HELP)
    legacy.add_argument('--queue-directory', metavar='Q',
                        help="the Node host's queue directory (default: R/results/web-service)")
    legacy.add_argument('--dry-run', action='store_true', help='report what would be imported; write nothing')
    data_cli.add_commands(commands)
    return parser


def choose_workspace(argument: Optional[str], cwd: str, interactive: bool,
                     ask: Callable[[str], str], command: str = 'serve') -> Optional[str]:
    """The workspace directory (decision U3), or ``None`` when the person declines; ``WorkspaceError`` when a
    path is needed but none was given (the message names ``command``)."""
    if argument:
        return os.path.abspath(argument)
    if is_workspace(cwd):
        return cwd
    if not interactive:
        raise WorkspaceError(f'{cwd} is not an EEG Layout Lab workspace. Give the workspace directory: '
                             f'{PROGRAM} {command} <directory>')
    with os.scandir(cwd) as entries:
        empty = next(entries, None) is None
    if empty:
        return cwd
    answer = ask(f'{cwd} is not empty and not an EEG Layout Lab workspace. Make it a workspace? [y/N] ')
    return cwd if answer.strip().lower() in ('y', 'yes') else None


def _fail(message: str, code: int = 1) -> int:
    print(f'{PROGRAM}: {message}', file=sys.stderr, flush=True)
    return code


def _passes_url_on_stdin(browser: object) -> bool:
    """Whether ``browser`` is macOS's launcher, which hands the URL to ``osascript`` on standard input; every other
    launcher puts it on a command line (``xdg-open URL``, ``$BROWSER URL``)."""
    launchers = tuple(getattr(webbrowser, name) for name in ('MacOSXOSAScript', 'MacOSX') if hasattr(webbrowser, name))
    return bool(launchers) and isinstance(browser, launchers)


def _open_browser(url: str, open_page: Callable[[str], Optional[str]],
                  stopping: Callable[[], bool] = lambda: False) -> None:
    """Opens ``url`` in a browser; on a command line only as the path of the page ``open_page`` writes. Nothing is
    opened once the service is stopping: ``stopping()`` is true, or ``open_page`` writes no page.

    ``webbrowser.get()`` runs first on every platform. Its first call looks for the browsers (on Linux it runs
    ``xdg-settings`` and reads ``$BROWSER``), which ``webbrowser.open`` would otherwise do after the page is written
    and after the last ``stopping()`` check, so a stop during that lookup would still start a browser. After it,
    ``webbrowser.open`` only starts the launcher. Without a browser no page is written."""
    try:
        try:
            browser: Optional[object] = webbrowser.get()
        except webbrowser.Error:
            browser = None
        if browser is None:
            opened = False
        else:
            if _passes_url_on_stdin(browser):
                target: Optional[str] = url
            else:
                page = open_page(url)
                target = None if page is None else pathlib.Path(page).as_uri()
            if target is None or stopping():
                return
            opened = webbrowser.open(target)
    except Exception:  # noqa: BLE001 - a missing browser must not stop the service
        opened = False
    if not opened:
        print('Open the address above in a browser.', flush=True)


def _open_when_started(server: Any, url: str, open_page: Callable[[str], Optional[str]]) -> None:
    """``_open_browser`` once the uvicorn ``server`` accepts connections; nothing when it stops first."""
    deadline = time.monotonic() + STARTUP_SECONDS
    while not server.started and not server.should_exit and time.monotonic() < deadline:
        time.sleep(0.05)
    if server.started and not server.should_exit:
        _open_browser(url, open_page, lambda: server.should_exit)


@contextlib.contextmanager
def _signals(handler: Callable[[int, object], None]) -> Iterator[None]:
    previous = {number: signal.signal(number, handler) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for number, old in previous.items():
            signal.signal(number, old)


def _bind(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(('127.0.0.1', port))
        sock.listen(2048)
    except BaseException:
        sock.close()
        raise
    return sock


def _run(workspace: Workspace, root: str, static: str, port: int, browser: bool, cache_only: bool = False,
         clear_interrupted: bool = False, docs: Optional[str] = None) -> int:
    import uvicorn

    from ..server.access import Tokens
    from ..server.app import ServiceConfig, create_app
    from ..server.static import export_root

    class Server(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self) -> Iterator[None]:
            # uvicorn re-raises a caught SIGTERM after shutting down, which would end the process before the
            # workspace is closed; _signals installs the handlers instead.
            yield

    tokens = Tokens.generate()
    try:
        sock = _bind(port)
    except OSError as error:
        return _fail(f'cannot listen on 127.0.0.1:{port}: {error.strerror}')
    # A stop can come at any time from here on: before the server exists it is only noted, and serve then exits
    # without serving.
    stopping = threading.Event()
    servers: list[Any] = []
    apps: list[Any] = []

    def stop(number: int, frame: Any) -> None:
        # The runtime file goes first: until the lock is released, a second serve then waits for it instead of
        # opening this instance, which stops accepting connections within 0.1 s.
        stopping.set()
        try:
            workspace.remove_runtime()
        except OSError:
            pass
        if apps:
            # Node's dispose on the first signal: the running worker is stopped now, not after the graceful wait (and
            # services not built yet are stopped once they are).
            apps[0].compute.stop_soon()
        if servers:
            # Always as SIGTERM: uvicorn would take a second SIGINT as a forced exit, which skips the lifespan's
            # shutdown (ComputeHost.close) and leaves the worker and its records unattended.
            servers[0].handle_exit(signal.SIGTERM, frame)

    try:
        with _signals(stop):
            bound = sock.getsockname()[1]
            try:
                workspace.write_runtime(bound, tokens.launch, root)
            except WorkspaceError as error:
                return _fail(str(error))
            except OSError as error:
                return _fail(f'cannot write {workspace.runtime_path}: {error.strerror}')
            config = ServiceConfig(root=root, port=bound, tokens=tokens, user=workspace.user_context(root),
                                   static_dir=static, docs_dir=docs, cache_only=cache_only,
                                   clear_interrupted=clear_interrupted)
            app = create_app(config)
            apps.append(app)
            server = Server(uvicorn.Config(
                app, host='127.0.0.1', port=bound, timeout_keep_alive=5, timeout_graceful_shutdown=5,
                access_log=False, log_level='warning', proxy_headers=False, server_header=False, ws='none',
                lifespan='on'))
            servers.append(server)
            if stopping.is_set():
                # Stopped while starting: the file may have been written after the handler removed it.
                workspace.remove_runtime()
                return 0
            url = open_url({'port': bound, 'token': tokens.launch})
            print(f'EEG Layout Lab: {url}', flush=True)
            print(f'Workspace: {workspace.path} (PID {os.getpid()}); press Ctrl+C to stop.', flush=True)
            if cache_only:
                print('Cache only: stored results are served; new computations are refused.', flush=True)
            if export_root(static) is None:
                print(f'The interface is not built ({static}); {_interface_hint(root, static)}', flush=True)
            if browser:
                threading.Thread(target=_open_when_started, args=(server, url, workspace.write_open_page),
                                 name='open-browser', daemon=True).start()
            try:
                server.run(sockets=[sock])
            except SystemExit:
                # uvicorn exits this way when the lifespan's startup fails (a queue file that cannot be used).
                failure = app.compute.failure
                return _fail(failure or 'the service did not start')
            if app.compute.failure:
                return _fail(app.compute.failure)
    finally:
        sock.close()
    return 0


def _service_hint() -> str:
    """How to get the service's packages: the service extra in a checkout, the environment's own packages else."""
    if checkout_root() is not None:
        return "install the service extra: pip install -e '.[service]'"
    return 'they are dependencies of the eeglayoutlab package; install it again into this environment'


def _interface_hint(root: str, static: str) -> str:
    """How to get the built interface: build it in a checkout; the installed package ships it in R."""
    if checkout_root() is not None:
        return 'run npm run build in webapp/.'
    if installed_form(root) and static == nodepath.join(root, 'webapp/dist/client'):
        return 'it is part of the eeglayoutlab package, so install the package again.'
    return 'build it in a checkout (npm run build in webapp/) and give it with --static DIR.'


def serve(args: argparse.Namespace) -> int:
    missing = [name for name in ('fastapi', 'uvicorn') if importlib.util.find_spec(name) is None]
    if missing:
        return _fail(f'the service needs {", ".join(missing)}; {_service_hint()}', 2)
    try:
        root = repository_root(nodepath.resolve(args.root) if args.root else None)
    except ValueError as error:
        return _fail(str(error), 2)
    problem = unwritable_root(root)
    if problem is not None:
        return _fail(problem, 2)
    static = os.path.abspath(args.static) if args.static else nodepath.join(root, 'webapp/dist/client')
    docs = os.path.abspath(args.docs) if args.docs else nodepath.join(root, 'site')
    interactive = sys.stdin is not None and sys.stdin.isatty()
    try:
        path = choose_workspace(args.workspace, os.getcwd(), interactive, input)
    except WorkspaceError as error:
        return _fail(str(error), 2)
    except (EOFError, KeyboardInterrupt):
        path = None
    if path is None:
        return _fail('no workspace chosen.')
    queue = nodepath.join(root, NODE_QUEUE_DIRECTORY)
    if inside(path, queue):
        return _fail(f"the workspace {path} is the Node host's queue directory {queue} or inside it, which the "
                     'service never writes. Choose a workspace elsewhere; eeglayoutlab workspace import-legacy copies '
                     'what the Node host saved there into a workspace.', 2)
    try:
        workspace = Workspace.open(path)
    except WorkspaceInUse as running:
        if running.runtime is None:
            return _fail(f'another process holds the lock of {path}, but its runtime file is missing or not valid. '
                         'Stop that process, then run the command again.')
        url = open_url(running.runtime)
        print(f'EEG Layout Lab is already running for {path}: {url}', flush=True)
        if not args.no_browser:
            _open_browser(url, lambda target: write_open_page(path, target))
        return 0
    except WorkspaceError as error:
        return _fail(str(error))
    try:
        return _run(workspace, root, static, args.port, not args.no_browser, args.cache_only, args.clear_interrupted,
                    docs)
    finally:
        workspace.close()


def import_legacy(args: argparse.Namespace) -> int:
    if importlib.util.find_spec('pydantic') is None:
        return _fail(f'the import needs pydantic; {_service_hint()}', 2)
    from ..server import legacy_import

    try:
        root: Optional[str] = repository_root(nodepath.resolve(args.root) if args.root else None)
    except ValueError as error:
        if args.root or not args.queue_directory:
            return _fail(str(error), 2)
        root = None  # the queue directory is given; the root only says which records have a stored result
    if args.queue_directory:
        queue = nodepath.resolve(args.queue_directory)
    else:
        assert root is not None
        queue = legacy_import.default_queue_directory(root)
    interactive = sys.stdin is not None and sys.stdin.isatty()
    try:
        path = choose_workspace(args.workspace, os.getcwd(), interactive, input, 'workspace import-legacy')
    except WorkspaceError as error:
        return _fail(str(error), 2)
    except (EOFError, KeyboardInterrupt):
        path = None
    if path is None:
        return _fail('no workspace chosen.')
    try:
        report = legacy_import.import_legacy(path, queue, root=root, dry_run=args.dry_run)
    except legacy_import.LegacyImportError as error:
        return _fail(str(error), 2)
    except WorkspaceInUse:
        return _fail(f'{path} is in use by a running service (or another import). Stop it, then run the command '
                     'again.')
    except WorkspaceError as error:
        return _fail(str(error))
    print(legacy_import.describe(report), flush=True)
    return 0 if legacy_import.succeeded(report) else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if args.command == 'serve':
        return serve(args)
    if args.command == 'workspace':
        return import_legacy(args)
    if args.command == 'data':
        return data_cli.run(args)
    return _fail(f'unknown command {args.command}', 2)


if __name__ == '__main__':
    sys.exit(main())
