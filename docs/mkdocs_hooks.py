"""MkDocs hooks that build the documentation site from the Markdown as it is read on GitHub.

The repository's Markdown is written for GitHub: README.md links to docs/..., pages in docs/
link back to ../CONTRIBUTING.md and to source files such as ../src/compact_eeg/metrics.py.
These hooks let MkDocs read the same files unchanged (mkdocs.yml loads them):

- Every page keeps its repository path as its source path, so relative links resolve as on
  GitHub. docs/ is left out of the published address: docs/architecture.md is /architecture/.
- Markdown files outside docs/ that the navigation names (README.md as the home page,
  CONTRIBUTING.md, ...) become pages.
- A link to any other repository file or directory points to it on GitHub, at the commit or
  branch in DOCS_SOURCE_REF (default: main). A directory link goes to the directory's
  README.md instead when that README is a page.
- Two GitHub list rules that Python-Markdown lacks: a list may start directly below a
  paragraph line, and items indented by two or three spaces nest under the item above.

A link whose target exists neither in the site nor in the repository is left alone, so strict
mode still reports it.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from markdown import Extension
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File, Files

_state: dict = {}


def on_config(config):
    if not config.repo_url:
        raise PluginError("mkdocs_hooks.py needs repo_url to link repository files on GitHub.")
    _state["root"] = Path(config.config_file_path).resolve().parent
    _state["docs_dir"] = Path(config.docs_dir).resolve()
    _state["source_base"] = config.repo_url.rstrip("/")
    _state["source_ref"] = os.environ.get("DOCS_SOURCE_REF") or "main"
    config.markdown_extensions.append(_RepositoryMarkdown())
    return config


def on_files(files: Files, config) -> Files:
    root, docs_dir = _state["root"], _state["docs_dir"]
    prefix = docs_dir.relative_to(root).as_posix() + "/"
    rooted = []
    for file in files:
        if file.src_dir is None or Path(file.src_dir).resolve() != docs_dir:
            rooted.append(file)  # theme assets
            continue
        page = File(
            prefix + file.src_uri,
            str(root),
            config.site_dir,
            config.use_directory_urls,
            inclusion=file.inclusion,
        )
        page.dest_uri = page.dest_uri.removeprefix(prefix)
        rooted.append(page)
    for src_uri in dict.fromkeys(_nav_paths(config.nav or [])):
        if not src_uri.startswith(prefix) and (root / src_uri).is_file():
            rooted.append(File(src_uri, str(root), config.site_dir, config.use_directory_urls))
    return Files(rooted)


def on_page_markdown(markdown, page, config, files):
    _state["page"], _state["files"] = page.file, files
    return markdown


def _nav_paths(items):
    for item in items:
        if isinstance(item, dict):
            yield from _nav_paths(item.values())
        elif isinstance(item, list):
            yield from _nav_paths(item)
        elif isinstance(item, str) and item.endswith(".md") and "://" not in item:
            yield item


class _RepositoryMarkdown(Extension):
    def extendMarkdown(self, md):
        # After fenced code is stashed (25) and raw HTML (20); before the block parser.
        md.preprocessors.register(_GitHubLists(md), "github_lists", 15)
        # After links are built (inline, 20); before MkDocs resolves them (relpath, 0).
        md.treeprocessors.register(_RepositoryLinks(md), "repository_links", 3)


_ITEM = re.compile(r"^(?P<indent> {0,3})(?:[-*+]|\d{1,9}[.)])(?: |$)")


class _GitHubLists(Preprocessor):
    def run(self, lines):
        out, in_list, after_blank = [], False, True
        for line in lines:
            if not line.strip():
                after_blank = True
                out.append(line)
                continue
            item = _ITEM.match(line)
            top_item = bool(item) and not item.group("indent")
            if after_blank:
                if top_item:
                    in_list = True
                elif not line.startswith(" "):
                    in_list = False
            elif top_item and not in_list:
                out.append("")  # A list directly below a paragraph line starts its own block.
                in_list = True
            if item and item.group("indent") and in_list:
                line = "    " + line.lstrip(" ")  # Python-Markdown nests at four spaces.
            after_blank = False
            out.append(line)
        return out


class _RepositoryLinks(Treeprocessor):
    def run(self, root):
        page, files = _state["page"], _state["files"]
        for element in root.iter():
            key = {"a": "href", "img": "src"}.get(element.tag)
            url = element.get(key) if key else None
            if url:
                element.set(key, self._resolve(url, page, files))

    @staticmethod
    def _resolve(url, page, files):
        scheme, netloc, path, query, fragment = urlsplit(url)
        if scheme or netloc or not path or url.startswith(("/", "\\")):
            return url
        target = posixpath.normpath(posixpath.join(posixpath.dirname(page.src_uri), unquote(path)))
        if target.startswith("../") or files.get_file_from_path(target):
            return url
        on_disk = _state["root"] / target
        if on_disk.is_dir():
            for name in ("README.md", "index.md"):
                if files.get_file_from_path(posixpath.join(target, name)):
                    return posixpath.join(path.rstrip("/"), name) + (f"#{fragment}" if fragment else "")
        elif not on_disk.is_file():
            return url
        kind = "tree" if on_disk.is_dir() else "blob"
        source = f"{_state['source_base']}/{kind}/{_state['source_ref']}/{quote(target)}"
        return source + (f"?{query}" if query else "") + (f"#{fragment}" if fragment else "")
