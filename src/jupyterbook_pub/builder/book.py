"""An AST to HTML renderer for Jupyter Book (myst) projects."""

import asyncio
import dataclasses
import shutil
from pathlib import Path
import tempfile
from typing import Optional

from traitlets import default, Bool, Instance, Unicode


from ruamel.yaml import YAML
from jupyter_book_site_renderer import JupyterBookSiteRenderer

from .base import PythonRenderer

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


class JupyterBook2Builder(PythonRenderer):
    """
    Build Jupyter Book from pre-built AST.
    If the AST does not exist, attempt a source build.
    """

    name = Unicode("jupyterbook2builder")

    @classmethod
    def config_file_name(cls) -> str:
        return "jupyter_book_2_builder"

    allow_source_builds = Bool(
        True,
        help="Allow builds of Jupyter Book projects from source. This may involve execution of foreign JS",
        config=True,
    )

    ast_renderer = Instance(JupyterBookSiteRenderer)

    @default("ast_renderer")
    def _default_ast_renderer(self):
        return JupyterBookSiteRenderer(parent=self)

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
        await self.ast_renderer.install_downloaded_template(template_path)

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
            await self.ast_renderer.render_html(
                source_or_ast_path, built_path, base_url=base_url
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
            with tempfile.TemporaryDirectory() as _tmpdir:
                # Copy the source to somewhere writeable
                source_path = Path(_tmpdir)
                shutil.copytree(source_or_ast_path, source_path, dirs_exist_ok=True)

                ast_path, template_path = await self.build_site_from_book(source_path)
                await self.ast_renderer.render_html(
                    ast_path, built_path, template_path, base_url
                )
                return
        else:
            raise RuntimeError("Not permitted to build AST from project sources")


if __name__ == "__main__":
    app = JupyterBook2Builder()
    app.initialize()
    app.start()
