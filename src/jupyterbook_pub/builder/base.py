from pathlib import Path

from traitlets.config import LoggingConfigurable


class Renderer(LoggingConfigurable):
    async def render(self, repo_path: Path, built_path: Path, base_url: str):
        """
        Render a checked out repo at repo_path, outputting static assets to built_path
        """
        raise NotImplementedError(
            "Inherit from Renderer and implement the render method"
        )
