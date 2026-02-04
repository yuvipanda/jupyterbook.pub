from __future__ import annotations

import socket
import asyncio
import dataclasses
import hashlib
import logging
import mimetypes
import os
import shutil
from pathlib import Path
import sys
from typing import Optional, override

import tornado
from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader
from repoproviders import fetch, resolve
from repoproviders.resolvers import to_json
from repoproviders.resolvers.base import DoesNotExist, Exists, MaybeExists, Repo
from tornado.web import HTTPError, RequestHandler, StaticFileHandler, url
from traitlets import Bool, Instance, Int, Integer, Unicode
from traitlets.config import Application

from .cache import make_rendered_cache_key, make_checkout_cache_key


def random_port():
    """
    Get a single random port likely to be available for listening in.
    """
    sock = socket.socket()
    sock.bind(('', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def ensure_jb_root(repo_path: Path) -> Optional[Path]:
    for dirname, _, filenames in repo_path.walk():
        if "myst.yml" in filenames:
            return dirname

    # No `myst.yml` found. Let's make one
    command = ["jupyter", "book", "init", "--write-toc"]
    proc = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=repo_path
    )

    stdout, stderr = [s.decode() for s in await proc.communicate()]
    retcode = await proc.wait()

    if retcode != 0:
        print(stdout, file=sys.stderr)
        print(stderr, file=sys.stderr)

    return repo_path


async def render_if_needed(app: JupyterBookPubApp, repo: Repo, base_url: str):
    repo_path = Path(app.repo_checkout_root) / make_checkout_cache_key(repo)
    built_path = Path(app.built_sites_root) / make_rendered_cache_key(repo, base_url)
    env = os.environ.copy()
    env["BASE_URL"] = base_url
    if not built_path.exists():
        if not repo_path.exists():
            yield f"Fetching {repo}...\n"
            await fetch(repo, repo_path)
            yield f"Fetched {repo}"

        jb_root = await ensure_jb_root(repo_path)
        if not jb_root:
            # FIXME: Better errors plz
            raise ValueError("No myst.yml found in repo")
        # Explicitly pass in a random port, as otherwise jupyter-book will always
        # try to listen on port 5000 and hang forever if it can't.
        command = ["jupyter", "book", "build", "--html", "--port", str(random_port())]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=jb_root,
            env=env,
        )

        stdout, stderr = [s.decode() for s in await proc.communicate()]
        retcode = await proc.wait()

        yield stdout
        yield stderr

        shutil.copytree(jb_root / "_build/html", built_path)


class BaseHandler(RequestHandler):
    def initialize(self, app: JupyterBookPubApp):
        self.app = app
        self.log = app.log


class RepoHandler(BaseHandler):

    def get_spec_from_request(self, prefix):
        """
        Re-extract spec from request.path.
        Get the original, raw spec, without tornado's unquoting.
        This is needed because tornado converts 'foo%2Fbar/ref' to 'foo/bar/ref'.
        """
        idx = self.request.path.index(prefix)
        spec = self.request.path[idx + len(prefix) :]
        return spec

    async def get(self, repo_spec: str, path: str):
        spec = self.get_spec_from_request("/repo/")

        raw_repo_spec, _ = spec.split("/", 1)
        last_answer = await self.app.resolve(repo_spec)
        if last_answer is None:
            raise tornado.web.HTTPError(404, f"{repo_spec} could not be resolved")
        match last_answer:
            case Exists(repo) | MaybeExists(repo):
                # Construct a *full* URL as base_url, as we can support different *domains*
                # Including different base urls in the future
                base_url = f"{self.request.protocol}://{self.request.host}/repo/{raw_repo_spec}"
                built_path = Path(self.app.built_sites_root) / make_rendered_cache_key(repo, base_url)
                if not built_path.exists():
                    async for line in render_if_needed(self.app, repo, base_url):
                        self.write(line)
                # This is a *sure* path traversal attack
                full_path = built_path / path
                if full_path.is_dir():
                    full_path = full_path / "index.html"
                mimetype, encoding = mimetypes.guess_type(full_path)
                if encoding == "gzip":
                    mimetype = "application/gzip"
                if mimetype:
                    self.set_header("Content-Type", mimetype)
                with open(full_path, "rb") as f:
                    # hard code the chunk size for now
                    # 64 * 1024 is what tornado uses https://github.com/tornadoweb/tornado/blob/e14929c305019fd494c74934445f0b72af4f98ab/tornado/web.py#L3020
                    while True:
                        chunk = f.read(64 * 1024)
                        if not chunk:
                            break
                        self.write(chunk)
            case DoesNotExist(repo):
                raise tornado.web.HTTPError(404, f"{repo} could not be resolved")


class ResolveHandler(BaseHandler):
    async def get(self):
        question = self.get_query_argument("q")
        if not question:
            raise HTTPError(400, "No question provided")
        answer = await self.app.resolve(question)
        if answer is None:
            raise HTTPError(404, "Could not resolve {question}")

        self.set_header("Content-Type", "application/json")
        self.write(to_json(answer))


class JupyterBookPubApp(Application):
    debug = Bool(True, help="Turn on debug mode", config=True)

    port = Int(
        int(os.environ.get("PORT", "9200")), help="Port to listen on", config=True
    )
    repo_checkout_root = Unicode(
        str(Path(__file__).parent.parent.parent / "repos"),
        help="Path to check out repos to. Created if it doesn't exist",
        config=True,
    )

    built_sites_root = Unicode(
        str(Path(__file__).parent.parent.parent / "built_sites"),
        help="Path to copy built files to. Created if it doesn't exist",
        config=True,
    )

    resolver_cache_ttl_seconds = Integer(
        10 * 60,
        help="How long to cache successful resolver results (in seconds)",
        config=True,
    )

    resolver_cache_max_size = Integer(
        128, help="Max number of successful resolver results to cache", config=True
    )

    resolver_cache = Instance(klass=TTLCache)

    async def resolve(self, question: str):
        if question in self.resolver_cache:
            last_answer = self.resolver_cache[question]
            self.log.debug(f"Found {question} in cache")
        else:
            answers = await resolve(question, True)
            if not answers:
                return None
            last_answer = answers[-1]
            self.resolver_cache[question] = last_answer
            self.log.info(f"Resolved {question} to {last_answer}")
        return last_answer

    @override
    def initialize(self, argv=None) -> None:
        super().initialize(argv)
        if self.debug:
            self.log_level = logging.DEBUG
        tornado.options.options.logging = logging.getLevelName(self.log_level)
        tornado.log.enable_pretty_logging()
        self.log = tornado.log.app_log

        self.templates_loader = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "templates")
        )

        os.makedirs(self.built_sites_root, exist_ok=True)
        os.makedirs(self.repo_checkout_root, exist_ok=True)

        self.resolver_cache = TTLCache(
            maxsize=self.resolver_cache_max_size, ttl=10 * 60
        )

    async def start(self) -> None:
        self.initialize()
        self.web_app = tornado.web.Application(
            [
                url(
                    r"/api/v1/resolve",
                    ResolveHandler,
                    {"app": self},
                    name="resolve-api",
                ),
                url(r"/repo/(.*?)/(.*)", RepoHandler, {"app": self}, name="repo"),
                (
                    "/(.*)",
                    StaticFileHandler,
                    {
                        "path": str(Path(__file__).parent / "generated_static"),
                        "default_filename": "index.html",
                    },
                ),
            ],
            debug=self.debug,
        )
        self.web_app.listen(self.port)
        await asyncio.Event().wait()


if __name__ == "__main__":
    app = JupyterBookPubApp()
    asyncio.run(app.start())
