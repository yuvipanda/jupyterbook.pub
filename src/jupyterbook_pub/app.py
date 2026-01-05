from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import mimetypes
import os
import shutil
from pathlib import Path
from typing import override

import tornado
from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader
from repoproviders import fetch, resolve
from repoproviders.resolvers.base import DoesNotExist, Exists, MaybeExists, Repo
from tornado.web import RequestHandler, StaticFileHandler, url
from traitlets import Bool, Instance, Integer, Unicode
from traitlets.config import Application


def hash_repo(repo: Repo) -> str:
    return hashlib.sha256(
        f"{repo.__class__.__name__}:{dataclasses.asdict(repo)}".encode()
    ).hexdigest()


async def render_if_needed(app: JupyterBookPubApp, repo: Repo, base_url: str):
    repo_hash = hash_repo(repo)
    repo_path = Path(app.repo_checkout_root) / repo_hash
    built_path = Path(app.built_sites_root) / repo_hash
    env = os.environ.copy()
    env["BASE_URL"] = base_url
    if not built_path.exists():
        if not repo_path.exists():
            yield f"Fetching {repo}...\n"
            await fetch(repo, repo_path)
            yield f"Fetched {repo}"

        command = ["jupyter", "book", "build", "--html"]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_path,
            env=env,
        )

        stdout, stderr = [s.decode() for s in await proc.communicate()]
        retcode = await proc.wait()

        yield stdout
        yield stderr

        shutil.copytree(repo_path / "_build/html", built_path)


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
        if repo_spec in self.app.resolver_cache:
            last_answer = self.app.resolver_cache[repo_spec]
            self.log.debug(f"Found {repo_spec} in cache")
        else:
            answers = await resolve(repo_spec, True)
            if not answers:
                raise tornado.web.HTTPError(404, f"{repo_spec} could not be resolved")
            last_answer = answers[-1]
            self.app.resolver_cache[repo_spec] = last_answer
            self.log.info(f"Resolved {repo_spec} to {last_answer}")
        match last_answer:
            case Exists(repo):
                repo_hash = hash_repo(repo)
                built_path = Path(self.app.built_sites_root) / repo_hash
                if not built_path.exists():
                    base_url = f"/repo/{raw_repo_spec}"
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
            case MaybeExists(repo):
                pass
            case DoesNotExist(repo):
                raise tornado.web.HTTPError(404, f"{repo} could not be resolved")


class JupyterBookPubApp(Application):
    debug = Bool(True, help="Turn on debug mode", config=True)

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
        self.web_app.listen(9200)
        await asyncio.Event().wait()


if __name__ == "__main__":
    app = JupyterBookPubApp()
    asyncio.run(app.start())
