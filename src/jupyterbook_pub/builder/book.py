import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

from ..utils import random_port
from .base import Renderer

# We don't have to roundtrip here, because nobody reads that YAML
yaml = YAML(typ="safe")


class JupyterBook2Builder(Renderer):
    def munge_jb_myst_yml(self, myst_yml_path: Path):
        # If there's only one entry in toc, use article not book theme
        with open(myst_yml_path, "r") as f:
            data = yaml.load(f)

        if len(data["project"]["toc"]) == 1:
            data["site"]["template"] = "article-theme"

        with open(myst_yml_path, "w") as f:
            yaml.dump(data, f)

    async def ensure_jb_root(self, repo_path: Path) -> Optional[Path]:
        for dirname, _, filenames in repo_path.walk():
            if "myst.yml" in filenames:
                return dirname

        # No `myst.yml` found. Let's make one
        command = ["jupyter", "book", "init", "--write-toc"]
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_path,
        )

        stdout, stderr = [s.decode() for s in await proc.communicate()]
        retcode = await proc.wait()

        if retcode != 0:
            print(stdout, file=sys.stderr)
            print(stderr, file=sys.stderr)
        else:
            self.munge_jb_myst_yml(repo_path / "myst.yml")

        return repo_path

    async def render(self, repo_path: Path, built_path: Path, base_url: str):
        env = os.environ.copy()
        env["BASE_URL"] = base_url

        jb_root = await self.ensure_jb_root(repo_path)

        if not jb_root:
            # FIXME: Better errors plz
            raise ValueError("No myst.yml found in repo")

        built_html_path = jb_root / "_build/html"

        # If we have been given built HTML files, just use those.
        # This allows for repos that execute notebooks and render them as HTML,
        # and we just serve them. We check for index.json as a simple way to not
        # turn into a random arbitrary HTML server. We also eventually want to be
        # able to offer `--execute` but *only* when cached execution is present
        if not (built_html_path.exists() and (built_html_path / "index.json").exists()):
            # Explicitly pass in a random port, as otherwise jupyter-book will always
            # try to listen on port 5000 and hang forever if it can't.
            command = [
                "jupyter",
                "book",
                "build",
                "--html",
                "--port",
                str(random_port()),
            ]
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=jb_root,
                env=env,
            )

            stdout, stderr = [s.decode() for s in await proc.communicate()]
            _ = await proc.wait()

            print(stdout)
            print(stderr)

        shutil.copytree(jb_root / "_build/html", built_path)
