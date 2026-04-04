from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import secrets
import os
from pathlib import Path
from typing import override

import tornado
from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader
from jupyterhub.services.auth import HubOAuthenticated, HubOAuthCallbackHandler
from jupyterhub.utils import url_path_join
from repoproviders import resolve
from repoproviders.fetchers.fetcher import fetch
from repoproviders.resolvers import to_json
from repoproviders.resolvers.base import DoesNotExist, Exists, MaybeExists
from tornado.web import (
    HTTPError,
    RequestHandler,
    StaticFileHandler as StaticHandler,
    url,
    authenticated,
)
from traitlets import default, validate, Bool, Instance, Int, Integer, Type, Unicode
from traitlets.config import Application

from .builder.base import Renderer
from .builder.book import JupyterBook2Builder
from .cache import make_checkout_cache_key, make_rendered_cache_key


maybe_authenticated = (
    authenticated if "JUPYTERHUB_SERVICE_PREFIX" in os.environ else lambda x: x
)


class BaseHandler(HubOAuthenticated, RequestHandler):
    def initialize(self, app: JupyterBookPubApp):
        self.app = app
        self.log = app.log


class NoXSRFMixin:
    def check_xsrf_cookie(self):
        # don't need XSRF protections on static assets
        return


class StaticFileHandler(NoXSRFMixin, HubOAuthenticated, StaticHandler):
    @maybe_authenticated
    async def get(self, path: str, include_body: bool = True) -> None:

        return await super().get(path, include_body=include_body)


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

    @maybe_authenticated
    async def get(self, repo_spec: str, path: str):
        # FIXME: baseurl
        spec = self.get_spec_from_request("/repo/")

        raw_repo_spec, _ = spec.split("/", 1)
        last_answer = await self.app.resolve(repo_spec)
        if last_answer is None:
            raise tornado.web.HTTPError(404, f"{repo_spec} could not be resolved")
        match last_answer:
            case Exists(repo) | MaybeExists(repo):
                # In the future, we can explicitly specify full URL here so we
                # can support other kinds of domains too
                base_url = url_path_join(self.app.base_url, f"repo/{raw_repo_spec}")
                built_path = Path(self.app.built_sites_root) / make_rendered_cache_key(
                    repo, base_url
                )

                repo_path = Path(app.repo_checkout_root) / make_checkout_cache_key(repo)

                if not repo_path.exists():
                    self.log.info(f"Fetching {repo}...\n")
                    await fetch(repo, repo_path)
                    self.log.info(f"Fetched {repo}")

                if not built_path.exists():
                    await self.app.renderer.render(repo_path, built_path, base_url)
                # This is a *sure* path traversal attack
                full_path = built_path / path
                if full_path.is_dir():
                    full_path = full_path / "index.html"
                mimetype, encoding = mimetypes.guess_type(full_path)
                if encoding == "gzip":
                    mimetype = "application/gzip"
                if mimetype:
                    self.set_header("Content-Type", mimetype)
                try:
                    with open(full_path, "rb") as f:
                        # hard code the chunk size for now
                        # 64 * 1024 is what tornado uses https://github.com/tornadoweb/tornado/blob/e14929c305019fd494c74934445f0b72af4f98ab/tornado/web.py#L3020
                        while True:
                            chunk = f.read(64 * 1024)
                            if not chunk:
                                break
                            self.write(chunk)
                except FileNotFoundError:
                    # The site is built, just that this particular file doesn't exist
                    raise HTTPError(404)
            case DoesNotExist(repo):
                raise tornado.web.HTTPError(404, f"{repo} could not be resolved")


class ResolveHandler(BaseHandler):
    @maybe_authenticated
    async def get(self):
        question = self.get_query_argument("q")
        if not question:
            raise HTTPError(400, "No question provided")
        answer = await self.app.resolve(question)
        if answer is None:
            raise HTTPError(404, "Could not resolve {question}")

        self.set_header("Content-Type", "application/json")
        self.write(to_json(answer))


class IndexHandler(NoXSRFMixin, BaseHandler):
    @maybe_authenticated
    async def get(self):
        config = {
            "title": self.app.site_title,
            "heading": self.app.site_heading,
            "subheading": self.app.site_subheading,
            "baseUrl": self.app.base_url,
        }
        self.write(
            self.app.templates_loader.get_template("home.html").render(config=config)
        )


class JupyterBookPubApp(Application):
    debug = Bool(True, help="Turn on debug mode", config=True)

    base_url = Unicode("/", help="The base URL of the entire application", config=True)

    @validate("base_url")
    def _valid_base_url(self, proposal):
        if not proposal.value.startswith("/"):
            proposal.value = "/" + proposal.value
        if not proposal.value.endswith("/"):
            proposal.value = proposal.value + "/"
        return proposal.value

    hub_api_token = Unicode(
        help="""API token for talking to the JupyterHub API""",
        config=True,
    )

    @default("hub_api_token")
    def _default_hub_token(self):
        return os.environ.get("JUPYTERHUB_API_TOKEN", "")

    port = Int(
        int(os.environ.get("PORT", "9200")), help="Port to listen on", config=True
    )
    persistent_path = Unicode(
        help="Base path for persistent files like repo checkouts, and template downloads. Created if it doesn't exist",
        config=True,
    )

    @default("persistent_path")
    def _default_persistent_path(self):
        return str(Path.cwd())

    repo_checkout_root = Unicode(
        help="Path to check out repos to. Created if it doesn't exist",
        config=True,
    )

    @default("repo_checkout_root")
    def _default_repo_checkout_root(self):
        return str(Path(self.persistent_path) / "repos")

    built_sites_root = Unicode(
        help="Path to copy built files to. Created if it doesn't exist",
        config=True,
    )

    @default("built_sites_root")
    def _default_built_sites_root(self):
        return str(Path(self.persistent_path) / "built_sites")

    templates_root = Unicode(
        help="Path to download MyST templates to. Created if it doesn't exist",
        config=True,
    )

    @default("templates_root")
    def _default_templates_root(self):
        return str(Path(self.persistent_path) / "templates")

    resolver_cache_ttl_seconds = Integer(
        10 * 60,
        help="How long to cache successful resolver results (in seconds)",
        config=True,
    )

    resolver_cache_max_size = Integer(
        128, help="Max number of successful resolver results to cache", config=True
    )

    resolver_cache = Instance(klass=TTLCache)

    renderer_class = Type(
        JupyterBook2Builder,
        klass=Renderer,
        config=True,
        help="Renderer to use for this installation",
    )
    renderer = Instance(klass=Renderer)

    site_title = Unicode("JupyterBook.pub", help="Title of the website", config=True)

    site_heading = Unicode(
        "JupyterBook.pub", help="Heading of the website", config=True
    )

    site_subheading = Unicode(
        "Instantly build and share your JupyterBook repository wherever it is",
        help="Subheading of the website",
        config=True,
    )

    config_file = Unicode(
        "jupyterbook_pub_config.py", help="The config file to load", config=True
    )
    aliases = {"f": "JupyterBookPubApp.config_file"}

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
        self.load_config_file(self.config_file)
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

        self.renderer = self.renderer_class(parent=self)

    async def start(self) -> None:
        self.initialize()

        base_url = os.environ["JUPYTERHUB_SERVICE_PREFIX"]
        self.web_app = tornado.web.Application(
            [
                url(
                    url_path_join(base_url, "/oauth_callback"),
                    HubOAuthCallbackHandler,
                ),
                url(
                    url_path_join(base_url, r"/api/v1/resolve"),
                    ResolveHandler,
                    {"app": self},
                    name="resolve-api",
                ),
                url(
                    url_path_join(base_url, r"/repo/(.*?)/(.*)"),
                    RepoHandler,
                    {"app": self},
                    name="repo",
                ),
                url(
                    url_path_join(base_url, "/"),
                    IndexHandler,
                    {"app": self},
                    name="app",
                ),
                url(
                    url_path_join(base_url, "/(.*)"),
                    StaticFileHandler,
                    {
                        "path": str(Path(__file__).parent / "generated_static"),
                        "default_filename": "index.html",
                    },
                ),
            ],
            debug=self.debug,
            cookie_secret=secrets.token_bytes(32),
        )
        self.web_app.listen(self.port)
        await asyncio.Event().wait()


if __name__ == "__main__":
    app = JupyterBookPubApp()
    asyncio.run(app.start())
