from traitlets import Unicode
from traitlets.config import Application
from enum import StrEnum

import asyncio
import pathlib
import logging
from typing import override


class ReservedCommands(StrEnum):
    python = "python"


class Renderer:
    @classmethod
    def entrypoint(
        cls,
        repo_path: pathlib.Path,
        build_path: pathlib.Path,
        base_url: str,
        config_path: pathlib.Path = None,
    ) -> tuple[ReservedCommands | str, ...]:
        """
        Tuple of executable entrypoint items required to launch this renderer.

        Consumers should substitute ReservedCommands instances with appropriate values,
        e.g. python → sys.executable.
        """
        raise NotImplementedError


class TraitletsRenderer(Renderer, Application):
    repo_path = Unicode(
        None, allow_none=False, config=True, help="Path to source repository"
    )
    built_path = Unicode(
        None,
        allow_none=False,
        config=True,
        help="Path to directly populate with build outputs",
    )
    base_url = Unicode(
        None,
        allow_none=False,
        config=True,
        help="Optional base URL to use for built site",
    )
    config_file = Unicode("", help="Load this config file", config=True)

    aliases = {
        **Application.aliases,
        "repo": "TraitletsRenderer.repo_path",
        "dest": "TraitletsRenderer.built_path",
        "base-url": "TraitletsRenderer.base_url",
        "config": "TraitletsRenderer.config_file",
    }

    @classmethod
    def entrypoint(
        cls,
        repo_path: pathlib.Path,
        build_path: pathlib.Path,
        base_url: str,
        config_path: pathlib.Path = None,
    ) -> tuple[ReservedCommands | str, ...]:
        entrypoint = [
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
        ]
        if config_path is not None:
            entrypoint.extend(["--config", config_path])
        return tuple(entrypoint)

    @override
    def initialize(self, argv=None) -> None:
        super().initialize(argv)
        self.load_config_file(self.config_file)
        self.load_config_environ()

    async def render(self):
        """
        Render a checked out repo at repo_path, outputting static assets to built_path
        """
        raise NotImplementedError(
            "Inherit from Renderer and implement the render method"
        )

    def start(self):
        asyncio.run(self.render())
