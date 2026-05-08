from __future__ import annotations

import asyncio
import logging
import secrets
import os
from pathlib import Path
from typing import override
import urllib.parse

import tornado
from cachetools import TTLCache
from jinja2 import Environment, FileSystemLoader
from jupyterhub.services.auth import HubOAuthenticated, HubOAuthCallbackHandler
from jupyterhub.utils import url_path_join
from repoproviders import resolve
from repoproviders.fetchers.fetcher import fetch
from repoproviders.resolvers import to_json
from repoproviders.resolvers.base import Exists, MaybeExists
from tornado.web import (
    HTTPError,
    RequestHandler,
    StaticFileHandler as StaticHandler,
    url,
    authenticated,
)
from traitlets import (
    default,
    validate,
    observe,
    Bool,
    Dict,
    Instance,
    Int,
    Integer,
    Type,
    Unicode,
    TraitError,
)
from traitlets.config import Application

from .cache import make_checkout_cache_key, make_rendered_cache_key
from .executor import BuildExecutor, LocalProcessExecutor
from .storage import StorageManager

# Constants for name of unique storage paths
BUILT_SITES_NAME = "built_sites"
REPOS_NAME = "repos"

USE_AUTHENTICATION = (
    "JUPYTERHUB_SERVICE_PREFIX" in os.environ
    # Check for opt-out
    and os.environ.get("JUPYTERBOOK_PUB_NO_AUTH", "0").lower()
    not in ("1", "true", "yes")
)

maybe_authenticated = authenticated if USE_AUTHENTICATION else lambda x: x


class NoAuth: ...


MaybeAuthenticatedMixin = HubOAuthenticated if USE_AUTHENTICATION else NoAuth


class AppMixin:
    def initialize(self, *, app, **kwargs):
        self.app = app
        super().initialize(**kwargs)

    @property
    def log(self):
        return self.app.log


class NoXSRFMixin:
    def check_xsrf_cookie(self):
        # don't need XSRF protections on static assets
        return


class StaticFileHandler(NoXSRFMixin, MaybeAuthenticatedMixin, StaticHandler):
    @maybe_authenticated
    async def get(self, path: str, include_body: bool = True) -> None:

        return await super().get(path, include_body=include_body)


class BuiltRepoHandler(AppMixin, NoXSRFMixin, MaybeAuthenticatedMixin, StaticHandler):
    def get_raw_arg(self, prefix):
        """
        Re-extract spec from request.path.
        Get the original, raw spec, without tornado's unquoting.
        This is needed because tornado converts 'foo%2Fbar/ref' to 'foo/bar/ref'.
        """
        idx = self.request.path.index(prefix)
        spec = self.request.path[idx + len(prefix) :]
        return spec

    @maybe_authenticated
    async def get(self, arg: str):
        root_build_path = Path(self.app.storage_root) / BUILT_SITES_NAME
        root_build_path.mkdir(exist_ok=True)

        # Recieve the raw value of arg
        prefix = url_path_join(self.app.base_url, "/repo/")
        raw_arg = self.get_raw_arg(prefix)

        # Extract the spec, and tail
        raw_repo_spec, tail = raw_arg.split("/", 1)
        repo_spec = urllib.parse.unquote(raw_repo_spec)

        last_answer = await self.app.resolve(repo_spec)
        if last_answer is None:
            raise tornado.web.HTTPError(404, f"{repo_spec} could not be resolved")
        match last_answer:
            case Exists(repo) | MaybeExists(repo):
                build_cache_key = make_rendered_cache_key(repo, self.app.base_url)
                build_path = root_build_path / build_cache_key

                # Can we serve pre-built content?
                if build_path.exists():
                    # Rewrite URL against build cache key
                    # Do not include path to the handler
                    content_url = url_path_join(build_cache_key, tail)
                    return await super().get(content_url)
                else:
                    # Redirect to build handler
                    build_url_result = urllib.parse.urlparse(
                        url_path_join(self.app.base_url, "build")
                    )
                    build_url = urllib.parse.urlunparse(
                        build_url_result._replace(
                            query=urllib.parse.urlencode(
                                {
                                    "spec": repo_spec,
                                    "next": self.request.path,
                                }
                            )
                        )
                    )
                    return self.redirect(build_url)


class BuildHandler(AppMixin, MaybeAuthenticatedMixin, RequestHandler):
    @maybe_authenticated
    async def get(self):
        storage_path = Path(self.app.storage_root)

        root_build_path = storage_path / BUILT_SITES_NAME
        root_build_path.mkdir(exist_ok=True)

        repos_root_path = storage_path / REPOS_NAME

        spec = self.get_argument("spec")
        next_url = self.get_argument("next")
        raw_spec = urllib.parse.quote(spec, safe="")

        last_answer = await self.app.resolve(spec)
        if last_answer is None:
            raise tornado.web.HTTPError(404, f"{spec} could not be resolved")
        match last_answer:
            case Exists(repo) | MaybeExists(repo):
                build_cache_key = make_rendered_cache_key(repo, self.app.base_url)
                build_path = root_build_path / build_cache_key

                # If directly invoked, build path may exist
                if build_path.exists():
                    self.redirect(next_url)

                # Find the source content
                repo_path = repos_root_path / make_checkout_cache_key(repo)
                if not repo_path.exists():
                    # First, fetch the repo
                    self.log.info(f"Fetching {repo}...\n")
                    await fetch(repo, repo_path)
                    self.log.info(f"Fetched {repo}")

                # Define BASE_URL for the resolved path
                base_url = url_path_join(self.app.base_url, "repo", raw_spec)
                async with (
                    # Limit build duration
                    asyncio.timeout(self.app.build_timeout_seconds),
                    # Limit concurrent builds
                    self.app._build_semaphore,
                ):
                    await self.app.executor.execute(repo_path, build_path, base_url)

                # Sweep the storage
                self.app.built_sites_storage_manager.notify_of_build()
                self.app.repos_storage_manager.notify_of_build()

                # Redirect to `?next`
                return self.redirect(next_url)


class ResolveHandler(AppMixin, MaybeAuthenticatedMixin, RequestHandler):
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


class IndexHandler(NoXSRFMixin, AppMixin, MaybeAuthenticatedMixin, RequestHandler):
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
    name = Unicode("jupyterbook-pub-app")
    debug = Bool(help="Turn on debug mode", config=True)

    port = Int(9200, help="Port to listen on", config=True)
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

    storage_root = Unicode(
        "persistent",
        help="Path to use for artifact (sites, repos) storage",
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

    site_title = Unicode("JupyterBook.pub", help="Title of the website", config=True)

    site_heading = Unicode(
        "JupyterBook.pub", help="Heading of the website", config=True
    )

    site_subheading = Unicode(
        "Instantly build and share your JupyterBook repository wherever it is",
        help="Subheading of the website",
        config=True,
    )

    built_sites_max_age_hours = Integer(
        24, config=True, help="Max age of built site in hours before it is removed"
    )
    repos_max_age_hours = Integer(
        12, config=True, help="Max age of downloaded repo in hours before it is removed"
    )
    build_timeout_seconds = Integer(
        5 * 60, config=True, help="Max age of build in seconds before it is cancelled"
    )
    storage_sweep_interval = Integer(
        10,
        config=True,
        help="Number of successive builds before performing a successive sweep",
    )

    executor_class = Type(
        LocalProcessExecutor,
        klass=BuildExecutor,
        config=True,
        help="Executor to use for this installation",
    )
    executor = Instance(klass=BuildExecutor)

    max_concurrent_builds = Integer(
        4, config=True, help="Maximum number of concurrent builds"
    )
    _build_semaphore = Instance(asyncio.Semaphore)

    storage_manager_class = Type(
        StorageManager,
        klass=StorageManager,
        config=True,
        help="Storage manager to use for this installation",
    )
    built_sites_storage_manager = Instance(klass=StorageManager)
    repos_storage_manager = Instance(klass=StorageManager)

    config_file = Unicode(
        "jupyterbook_pub_config.py", help="The config file to load", config=True
    )
    aliases = Dict(
        {
            "port": "JupyterBookPubApp.port",
            "config": "JupyterBookPubApp.config_file",
            "executor": "JupyterBookPubApp.executor_class",
            "storage": "JupyterBookPubApp.storage_root",
            "storage-manager": "JupyterBookPubApp.storage_manager_class",
            "resolver-ttl": "JupyterBookPubApp.resolver_cache_ttl_seconds",
            "resolver-size": "JupyterBookPubApp.resolver_cache_max_size",
            "timeout": "JupyterBookPubApp.build_timeout_seconds",
        }
    )
    flags = Dict(
        {
            **Application.flags,
            "debug": (
                {"JupyterBookPubApp": {"debug": True}},
                "Set log-level to debug, and turn on debug features",
            ),
        }
    )

    @validate(
        "built_sites_max_age_hours",
        "repos_max_age_hours",
        "storage_sweep_interval",
        "build_timeout_seconds",
        "max_concurrent_builds",
    )
    def _validate_ages(self, proposal):
        value = proposal["value"]
        name = proposal["trait"].name
        if value < 0:
            raise TraitError(f"{name} value must be positive integer, not {value}")
        return value

    @observe("debug")
    def _observe_debug(self, change):
        debug = change["new"]

        if debug:
            self.log_level = logging.DEBUG

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

    def ensure_storage(self):
        # Ensure storage
        storage_path = Path(self.storage_root)
        storage_path.mkdir(exist_ok=True)

        built_sites_path = storage_path / BUILT_SITES_NAME
        built_sites_path.mkdir(exist_ok=True)

        repos_path = storage_path / REPOS_NAME
        repos_path.mkdir(exist_ok=True)

        self.built_sites_storage_manager = self.storage_manager_class(
            parent=self,
            max_age_hours=self.built_sites_max_age_hours,
            storage_root=str(built_sites_path),
            build_interval=self.storage_sweep_interval,
        )
        self.repos_storage_manager = self.storage_manager_class(
            parent=self,
            max_age_hours=self.repos_max_age_hours,
            storage_root=str(repos_path),
            build_interval=self.storage_sweep_interval,
        )

    @override
    def initialize(self, argv=None) -> None:
        super().initialize(argv)

        self.load_config_file(self.config_file)
        self.load_config_environ()

        if self.debug:
            self.log_level = logging.DEBUG
        tornado.options.options.logging = logging.getLevelName(self.log_level)
        tornado.log.enable_pretty_logging()
        self.log = tornado.log.app_log

        self.templates_loader = Environment(
            loader=FileSystemLoader(Path(__file__).parent / "templates")
        )

        self.ensure_storage()

        self.resolver_cache = TTLCache(
            maxsize=self.resolver_cache_max_size, ttl=10 * 60
        )

        self.executor = self.executor_class(
            parent=self,
            storage_root=self.storage_root,
        )

        self._build_semaphore = asyncio.Semaphore(self.max_concurrent_builds)

    async def launch(self) -> None:
        self.web_app = tornado.web.Application(
            [
                url(
                    url_path_join(self.base_url, "oauth_callback"),
                    HubOAuthCallbackHandler,
                ),
                url(
                    url_path_join(self.base_url, r"api/v1/resolve"),
                    ResolveHandler,
                    {"app": self},
                    name="resolve-api",
                ),
                url(
                    url_path_join(self.base_url, r"repo/(.*?)"),
                    BuiltRepoHandler,
                    {
                        "app": self,
                        "path": str(Path(self.storage_root) / BUILT_SITES_NAME),
                        "default_filename": "index.html",
                    },
                    name="render-repo",
                ),
                url(
                    url_path_join(self.base_url, r"build"),
                    BuildHandler,
                    {"app": self},
                    name="build-repo",
                ),
                url(
                    self.base_url,
                    IndexHandler,
                    {"app": self},
                    name="app",
                ),
                url(
                    url_path_join(self.base_url, "(.*)"),
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

    def start(self):
        asyncio.run(self.launch())


if __name__ == "__main__":
    app = JupyterBookPubApp()
    app.initialize()
    app.start()
