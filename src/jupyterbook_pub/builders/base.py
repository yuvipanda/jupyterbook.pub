from traitlets import Unicode
from traitlets.config import Application

import asyncio
from typing import override


class BuilderApplication(Application):
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
        "repo": "BuilderApplication.repo_path",
        "dest": "BuilderApplication.built_path",
        "base-url": "BuilderApplication.base_url",
        "config": "BuilderApplication.config_file",
    }

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
