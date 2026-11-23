"""``eeglayoutlab serve [WORKSPACE] [--root R] [--port N] [--static DIR] [--no-browser]``, and ``eeglayoutlab data``
(data packages, ``eeglayoutlab.data.cli``).

Starts the local service for one workspace (design 0001, decision 6):

- **Workspace** (decision U3): the given directory, created when missing; without one, the current directory
  when it is a workspace, when it is empty, or when the person confirms on a terminal. Without a terminal a new
  workspace needs an explicit path.
- **Root**: ``--root``, else ``EEG_REPOSITORY_ROOT``, else this checkout, spelled as Node spells it
  (``jobs.runtime.repository_root``). The static interface defaults to ``R/webapp/dist/client``.
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

The service stops on SIGINT or SIGTERM: the runtime file is removed at once, so that a second ``serve`` during the
graceful shutdown waits for the lock instead of opening an instance that no longer answers.
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
from ..jobs.runtime import repository_root
from ..server.workspace import Workspace, WorkspaceError, WorkspaceInUse, is_workspace, open_url, write_open_page

__all__ = ['main', 'choose_workspace']

PROGRAM = 'eeglayoutlab'
# How long the browser thread waits for the service to accept connections.
STARTUP_SECONDS = 30.0


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
    serve.add_argument('--root', metavar='R', help='scientific root (default: EEG_REPOSITORY_ROOT, else this checkout)')
    serve.add_argument('--port', type=_port, default=0, metavar='N', help='loopback port (default: a free port)')
    serve.add_argument('--static', metavar='DIR', help='static interface (default: R/webapp/dist/client)')
    serve.add_argument('--no-browser', action='store_true', help='print the address instead of opening a browser')
    data_cli.add_commands(commands)
    return parser


def choose_workspace(argument: Optional[str], cwd: str, interactive: bool,
                     ask: Callable[[str], str]) -> Optional[str]:
    """The workspace directory (decision U3), or ``None`` when the person declines; ``WorkspaceError`` when a
    path is needed but none was given."""
    if argument:
        return os.path.abspath(argument)
    if is_workspace(cwd):
        return cwd
    if not interactive:
        raise WorkspaceError(f'{cwd} is not an EEG Layout Lab workspace. Give the workspace directory: '
                             f'{PROGRAM} serve <directory>')
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


def _run(workspace: Workspace, root: str, static: str, port: int, browser: bool) -> int:
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
    try:
        bound = sock.getsockname()[1]
        try:
            workspace.write_runtime(bound, tokens.launch, root)
        except WorkspaceError as error:
            return _fail(str(error))
        except OSError as error:
            return _fail(f'cannot write {workspace.runtime_path}: {error.strerror}')
        config = ServiceConfig(root=root, port=bound, tokens=tokens, user=workspace.user_context(root),
                               static_dir=static)
        server = Server(uvicorn.Config(
            create_app(config), host='127.0.0.1', port=bound, timeout_keep_alive=5, timeout_graceful_shutdown=5,
            access_log=False, log_level='warning', proxy_headers=False, server_header=False, ws='none',
            lifespan='on'))
        url = open_url({'port': bound, 'token': tokens.launch})
        print(f'EEG Layout Lab: {url}', flush=True)
        print(f'Workspace: {workspace.path} (PID {os.getpid()}); press Ctrl+C to stop.', flush=True)
        if export_root(static) is None:
            print(f'The interface is not built ({static}); run npm run build in webapp/.', flush=True)

        def stop(number: int, frame: Any) -> None:
            # The runtime file goes first: until the lock is released, a second serve then waits for it instead of
            # opening this instance, which stops accepting connections within 0.1 s.
            try:
                workspace.remove_runtime()
            except OSError:
                pass
            server.handle_exit(number, frame)

        with _signals(stop):
            if browser:
                threading.Thread(target=_open_when_started, args=(server, url, workspace.write_open_page),
                                 name='open-browser', daemon=True).start()
            server.run(sockets=[sock])
    finally:
        sock.close()
    return 0


def serve(args: argparse.Namespace) -> int:
    missing = [name for name in ('fastapi', 'uvicorn') if importlib.util.find_spec(name) is None]
    if missing:
        return _fail(f'the service needs {", ".join(missing)}; install the service extra: '
                     "pip install -e '.[service]'", 2)
    try:
        root = repository_root(nodepath.resolve(args.root) if args.root else None)
    except ValueError as error:
        return _fail(str(error), 2)
    static = os.path.abspath(args.static) if args.static else nodepath.join(root, 'webapp/dist/client')
    interactive = sys.stdin is not None and sys.stdin.isatty()
    try:
        path = choose_workspace(args.workspace, os.getcwd(), interactive, input)
    except WorkspaceError as error:
        return _fail(str(error), 2)
    except (EOFError, KeyboardInterrupt):
        path = None
    if path is None:
        return _fail('no workspace chosen.')
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
        return _run(workspace, root, static, args.port, not args.no_browser)
    finally:
        workspace.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    if args.command == 'serve':
        return serve(args)
    if args.command == 'data':
        return data_cli.run(args)
    return _fail(f'unknown command {args.command}', 2)


if __name__ == '__main__':
    sys.exit(main())
