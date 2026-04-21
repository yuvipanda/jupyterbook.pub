from traitlets import Unicode
from traitlets.config import Application
from enum import StrEnum
import pathlib
import logging


class ReservedCommands(StrEnum):
    python = "python"


class Renderer:
    @classmethod
    def config_file_name(cls):
        raise NotImplementedError

    @classmethod
    def entrypoint(
        cls, repo_path: pathlib.Path, build_path: pathlib.Path, base_url: str
    ) -> tuple[ReservedCommands | str, ...]:
        raise NotImplementedError


class PythonRenderer(Renderer, Application):
    repo_path = Unicode(config=True)
    built_path = Unicode(config=True)
    base_url = Unicode(config=True)

    aliases = {
        **Application.aliases,
        "repo": "Renderer.repo_path",
        "dest": "Renderer.built_path",
        "base-url": "Renderer.base_url",
    }

    @classmethod
    def entrypoint(
        cls, repo_path: pathlib.Path, build_path: pathlib.Path, base_url: str
    ) -> tuple[ReservedCommands | str, ...]:
        return (
            ReservedCommands.python,
            "-m",
            cls.__module__,
            "--repo",
            repo_path,
            "--dest",
            build_path,
            "--base-url",
            base_url,
            "--log-level",
            str(logging.INFO),
        )

    async def start(self):
        self.initialize()
        self.load_config_file(self.config_file_name())
        self.load_config_environ()

        await self.render()

    async def render(self):
        """
        Render a checked out repo at repo_path, outputting static assets to built_path
        """
        raise NotImplementedError(
            "Inherit from Renderer and implement the render method"
        )
