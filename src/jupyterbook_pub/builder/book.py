"""An AST to HTML renderer for Jupyter Book (myst) projects."""

import asyncio
import os
import dataclasses
import shutil
from pathlib import Path
import aiohttp
import aiohttp.web
import contextlib
import json
import pathlib
import re
import sys
import urllib.parse
import shlex
import tempfile
from typing import Optional

from traitlets import Bool, Unicode


from ruamel.yaml import YAML

from ..utils import random_port
from .base import Renderer

# We don't have to roundtrip here, because nobody reads that YAML
yaml = YAML(typ="safe")

# Implementation detail:
# Special string that is set by the theme when building HTML from AST (static)
# We find and replace this.
ASSETS_FOLDER = "myst_assets_folder"


@dataclasses.dataclass
class Route:
    url: str
    path: str


class ProcessFailedError(Exception): ...


class JupyterBook2Builder(Renderer):
    """
    Build Jupyter Book from pre-built AST.
    If the AST does not exist, attempt a source build.
    """

    @classmethod
    def config_file_name(cls):
        return "jupyter_book_2_builder"

    allow_source_builds = Bool(
        True,
        help="Allow builds of Jupyter Book projects from source. This may involve execution of foreign JS",
        config=True,
    )
    default_theme = Unicode(
        "site/myst/book-theme",
        help="The default theme id (of the form `site/group/name`) to use for rendering into HTML. Defaults to `site/myst/book-theme`",
        config=True,
    )

    async def run_silent_process(self, *args, **kwargs):
        """
        Helper to run a process that is expected to succeed.

        If a non-zero return code is encountered, throw a ProcessFailedError and log the output.
        """
        proc = await asyncio.create_subprocess_exec(
            *args,
            **kwargs,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        retcode = await proc.wait()

        if retcode != 0:
            for line in stdout.decode().splitlines():
                self.log.error(line)
            raise ProcessFailedError("An error occurred whilst invoking process")

    def munge_jb_myst_yml(self, myst_yml_path: Path):
        # If there's only one entry in toc, use article not book theme
        with open(myst_yml_path, "r") as f:
            data = yaml.load(f)

        if len(data["project"]["toc"]) == 1:
            data["site"]["template"] = "article-theme"

        with open(myst_yml_path, "w") as f:
            yaml.dump(data, f)

    def find_project_root(self, repo_path: Path) -> Optional[Path]:
        """
        Locate the root of a Jupyter Book project by finding the myst.yml.

        Return None if it cannot be located.

        :param repo_path: path to repo contents.
        """
        for dirname, _, filenames in repo_path.walk():
            if "myst.yml" in filenames:
                return dirname

    async def ensure_project_root(self, repo_path: Path) -> Path:
        """
        Locate the root of a Jupyter Book project by finding the myst.yml.

        If it cannot be located, treat the repo as a Jupyter Book, and initialise a
        myst.yml.

        :param repo_path: path to repo contents.
        """
        project_root = self.find_project_root(repo_path)
        if project_root is not None:
            return project_root

        # No `myst.yml` found. Let's make one
        try:
            await self.run_silent_process(
                "jupyter",
                "book",
                "init",
                "--write-toc",
                cwd=repo_path,
            )
        except ProcessFailedError:
            raise RuntimeError(
                "An error occurred whilst initialising Jupyter Book project"
            ) from None

        self.munge_jb_myst_yml(repo_path / "myst.yml")

        return repo_path

    def slug_to_url(self, slug: str) -> str:
        """
        Interpret a Jupyter Book slug of the form foo.bar as a URL path of the form
        foo/bar.

        :param slug: Jupyter Book slug.
        """
        return re.sub(r"\.index$", "", slug).replace(".", "/")

    def build_page_route(self, host: str, page: dict) -> Route:
        """
        Build the route for a single page (HTML).

        :param host: host against which the url is resolved.
        :param page: page to build.
        """
        sub_path = self.slug_to_url(page["slug"])
        return Route(
            url=f"{host}/{sub_path}",
            path=f"{sub_path}/index.html",
        )

    def build_routes(self, project: dict, host: str, base_url: str) -> list[Route]:
        """
        Build a table of routes that should be fetched for a given Jupyter Book project.

        :param project: Jupyter Book project config.
        :param host: host to resolve routes against.
        :param base_url: ultimate base URL against which HTML is built.
        """
        # TODO: I am not 100% on why the base_url is needed for this test. I suspect it
        # might be possible to remove althogether
        site_index = f"/{project['index']}" if base_url else ""
        pages = [p for p in project["pages"] if p.get("slug")]
        return [
            Route(url=f"{host}{site_index}", path="index.html"),
            *[self.build_page_route(host, p) for p in pages],
            # Download all of the configured JSON
            Route(
                url=f"{host}/{project['index']}.json",
                path=f"{project['index']}.json",
            ),
            *[
                Route(
                    url=f"{host}/{p['slug']}.json",
                    path=f"{p['slug']}.json",
                )
                for p in pages
            ],
            # Download other assets
            *[
                Route(url=f"{host}/{asset}", path=asset)
                for asset in [
                    "robots.txt",
                    "favicon.ico",
                    "myst-theme.css",
                    "sitemap.xml",
                    "sitemap_style.xsl",
                ]
            ],
        ]

    def rewrite_assets(self, assets_path: pathlib.Path, base_url: str):
        """
        Rewrite static assets to refer to proper base URL.

        :param assets_path: directory to assets.
        :param base_url: base URL to use.
        """
        for root, _, names in assets_path.walk():
            for name in names:
                path = root / name
                if path.suffix == ".map":
                    path.unlink()
                    continue
                if path.suffix not in (".html", ".js", ".json"):
                    continue
                content = path.read_text()
                modified = re.sub(rf"/{ASSETS_FOLDER}", f"{base_url}/build/", content)
                path.write_text(modified)

    @contextlib.asynccontextmanager
    async def serve_theme(
        self,
        theme_path: pathlib.Path,
        content_port: int,
        theme_port: int,
        base_url: str,
    ):
        """
        Serve a Jupyter Book theme against a particular content server.

        :param theme_path: path to theme directory.
        :param cdn_port: port of running CDN.
        :param theme_port: port at which to serve theme.
        :param base_url: base URL to pass to theme.
        """
        template_config = yaml.load((theme_path / "template.yml").read_text())
        build_config = template_config["build"]

        env = {
            **os.environ,
            "HOST": "localhost",
            "CONTENT_CDN_PORT": str(content_port),
            "PORT": str(theme_port),
            "MODE": "static",
            "BASE_URL": base_url,
        }

        start_cmd = build_config["start"]
        proc = await asyncio.create_subprocess_exec(
            *shlex.split(start_cmd),
            cwd=theme_path,
            env=env,
            stdout=asyncio.subprocess.PIPE,
        )
        while "Server started" not in (await proc.stdout.readline()).decode():
            ...
        yield
        proc.terminate()

    @contextlib.asynccontextmanager
    async def serve_content(self, content_path: pathlib.Path, content_port: int):
        """
        Start a Jupyter Book content server.

        :param content_path: path to Jupyter Book site build.
        :param content_port: port at which to serve content.
        """

        app = aiohttp.web.Application()

        config = yaml.load((content_path / "config.json").read_text())

        def handle_index(request):
            return aiohttp.web.json_response(
                {
                    "version": config["myst"],
                    "links": {
                        "site": f"http://localhost:{content_port}/config.json",
                    },
                }
            )

        def make_handler(path):
            async def handler(request):
                return aiohttp.web.FileResponse(path)

            return handler

        app.add_routes(
            [
                aiohttp.web.get("/", handle_index),
                aiohttp.web.static("/", content_path / "public"),
                aiohttp.web.static("/content", content_path / "content"),
            ]
            + [
                aiohttp.web.get(f"/{name}", make_handler(content_path / name))
                for name in (
                    "config.json",
                    "objects.inv",
                    "myst.xref.json",
                    "myst.search.json",
                )
            ]
        )
        runner = aiohttp.web.AppRunner(app, logger=self.log, access_log=None)
        await runner.setup()
        site = aiohttp.web.TCPSite(runner, "localhost", content_port)
        await site.start()
        yield
        # wait for finish signal
        await runner.cleanup()

    async def fetch_route(
        self, session: aiohttp.ClientSession, route: Route, output_dir: pathlib.Path
    ):
        """
        Fetch a particular route and write the response to the output folder.

        :param session: HTTP session.
        :param route: route to fetch.
        :param output_dir: directory in which to write response.
        """
        path = output_dir / pathlib.Path(route.path)
        path.parent.mkdir(exist_ok=True, parents=True)
        async with session.get(route.url) as response:
            with open(path, "wb") as f:
                f.write(await response.read())

    async def fetch_routes(
        self,
        session: aiohttp.ClientSession,
        routes: list[Route],
        output_dir: pathlib.Path,
    ):
        """
        Fetch a set of routes concurrently and write the response to the output folder.

        :param session: HTTP session.
        :param routes: route to fetch.
        :param output_dir: directory in which to write response.
        """
        async with asyncio.TaskGroup() as tg:
            for route in routes:
                tg.create_task(self.fetch_route(session, route, output_dir))

    async def fetch_static_files(
        self,
        session: aiohttp.ClientSession,
        content_host: str,
        output_path: pathlib.Path,
    ):
        """
        Fetch the built-in static files required by a Jupyter Book site.

        :param session: HTTP session.
        :param content_host: URL of the content server.
        :param output_dir: directory in which to write response.
        """
        for resource in (
            "config.json",
            "objects.inv",
            "myst.search.json",
            "myst.xref.json",
        ):
            url = urllib.parse.urljoin(content_host, resource)
            path = output_path / resource
            async with session.get(url) as response:
                with open(path, "wb") as f:
                    f.write(await response.read())

        with open(output_path / "myst.xref.json", "r") as f:
            data = json.load(f)

        data["references"] = [
            {"data": ref["data"].replace("/content/", ""), **ref}
            for ref in data["references"]
        ]
        with open(output_path / "myst.xref.json", "w") as f:
            json.dump(data, f)

    def copy_template_public_files(
        self, template_path: pathlib.Path, output_dir: pathlib.Path
    ):
        """
        Copy public files from the template to the output directory.

        :param template_path: path to template.
        :param output_dir: directory in which to write public files.
        """
        public_path = template_path / "public"
        shutil.copytree(public_path, output_dir, dirs_exist_ok=True)

    def copy_content_public_files(
        self, content_path: pathlib.Path, output_dir: pathlib.Path
    ):
        """
        Copy public files from the content server to the output directory.

        :param template_path: path to template.
        :param output_dir: directory in which to write public files.
        """
        public_path = content_path / "public"
        shutil.copytree(public_path, output_dir / "build", dirs_exist_ok=True)

    async def ensure_default_template_installed(self) -> pathlib.Path:
        """
        Ensure that the default Jupyter Book template (theme) is available and installed
        """

        # Assume book theme for now
        template_path = pathlib.Path(tempfile.mkdtemp()) / "template"

        self.log.info(f"Downloading Jupyter Book template: {self.default_theme!r}")
        try:
            await self.run_silent_process(
                "jupyter",
                "book",
                "templates",
                "download",
                self.default_theme,
                template_path,
            )
        except ProcessFailedError:
            raise RuntimeError(
                "An error occurred whilst downloading Jupyter Book template"
            ) from None

        await self.install_downloaded_template(template_path)
        return template_path

    async def install_downloaded_template(self, template_path: Path):
        """
        Ensure that a downloaded MyST template has been installed.

        :param template_path: path to downloaded template containing template.yml
        """
        template_config = yaml.load((template_path / "template.yml").read_text())

        # Install the template
        template_name = template_config.get("title", "<unnamed template>")
        install_cmd = template_config.get("build", {}).get("install")
        if install_cmd is not None:
            self.log.info(f"Installing Jupyter Book template: {template_name!r}")
            try:
                await self.run_silent_process(
                    *shlex.split(install_cmd),
                    cwd=template_path,
                )
            except ProcessFailedError:
                raise RuntimeError(
                    "An error occurred whilst installing Jupyter Book template"
                ) from None

    async def render_site_to_html(
        self,
        content_path: pathlib.Path,
        template_path: pathlib.Path,
        output_path: pathlib.Path,
        base_url: str,
    ):
        """
        Render AST of the form produced by `jupyter book build --site` into HTML.

        :param content_path: path to site build.
        :param output_dir: directory in which to write public files.
        :param base_url: base URL to use.
        """

        with open(content_path / "config.json") as f:
            config = yaml.load(f.read())

        try:
            project = config["projects"][0]
        except (KeyError, IndexError):
            raise RuntimeError

        content_port = random_port()
        theme_port = random_port()

        # Implementation derived from upstream in
        # https://github.com/jupyter-book/mystmd/blob/a137e13d8ae607c7008a1912146d0e30ee8545db/packages/myst-cli/src/build/html/index.ts
        async with (
            self.serve_content(content_path, content_port) as content_url,
            self.serve_theme(
                template_path, content_port, theme_port, base_url
            ) as theme_url,
            aiohttp.ClientSession() as session,
        ):
            content_url = f"http://localhost:{content_port}"
            theme_url = f"http://localhost:{theme_port}"

            routes = self.build_routes(project, theme_url, base_url)
            await self.fetch_routes(session, routes, output_path)
            await self.fetch_static_files(session, content_url, output_path)
            self.copy_template_public_files(template_path, output_path)
            self.copy_content_public_files(content_path, output_path)
            self.rewrite_assets(output_path, base_url)

    async def build_site_from_book(self, project_path: Path) -> tuple[Path, Path]:
        """
        Build Jupyter Book into a site.

        :param project_path: path to project root.
        """

        try:
            await self.run_silent_process(
                "jupyter",
                "book",
                "build",
                "--site",
                cwd=project_path,
            )
        except ProcessFailedError:
            raise RuntimeError(
                "An error occurred whilst building Jupyter Book AST"
            ) from None

        ast_path = project_path / "_build" / "site"
        if not ast_path.exists():
            raise RuntimeError("Jupyter Book build failed to produce AST")

        # We will find one, it will have been downloaded by myst build
        template_yml_path = next(
            (project_path / "_build" / "templates").glob("**/template.yml")
        )
        template_path = template_yml_path.parent

        # The template from myst build --site is not installed (as only the
        # template.yml is needed). Let's now install it, so that we never pass around
        # an uninstalled template
        await self.install_downloaded_template(template_path)

        return ast_path, template_path

    async def render(self):
        """
        Render a Jupyter Book into HTML. There are several pathways:

        1. AST (from `jupyter book build --site`) into HTML
        2. HTML (from `jupyter book build --html`) directly
        3. Source into AST (via `jupyter book build --site`) into HTML

        Jupyter Book does not record information about the template that was used
        to build AST, so we use a hard-coded template (by default, the book-theme).

        :param source_or_ast_path: path to the source object.
        :param built_path: path to the built HTML outputs.
        :base_url: base URL of the ultimate render path.
        """
        source_or_ast_path = Path(self.repo_path)
        built_path = Path(self.built_path)
        base_url = self.base_url

        self.log.info("Building book")

        # Source is AST, build HTML from it
        if (source_or_ast_path / "config.json").exists():
            template_path = await self.ensure_default_template_installed()
            await self.render_site_to_html(
                source_or_ast_path, template_path, built_path, base_url
            )
            return

        # Source is a Jupyter Book
        book_root = await self.ensure_project_root(source_or_ast_path)

        # Return pre-built HTML if it exists
        pre_built_html_path = book_root / "_build" / "html"
        if pre_built_html_path.exists() and (pre_built_html_path / "config.json"):
            shutil.copytree(pre_built_html_path, built_path)
            return

        # Otherwise try build from source
        if self.allow_source_builds:
            ast_path, template_path = await self.build_site_from_book(
                source_or_ast_path
            )
            await self.render_site_to_html(
                ast_path, template_path, built_path, base_url
            )
            return
        else:
            raise RuntimeError("Not permitted to build AST from project sources")


if __name__ == "__main__":
    app = JupyterBook2Builder()
    asyncio.run(app.start())
