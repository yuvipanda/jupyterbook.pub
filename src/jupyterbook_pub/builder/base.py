from traitlets import Unicode
from traitlets.config import Application, Config


class Renderer(Application):
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
    def config_file_name(cls):
        raise NotImplementedError

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
