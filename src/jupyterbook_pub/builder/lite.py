import pathlib
from jupyterbook_pub.builder.base import Renderer, ReservedCommands


class JupyterLiteBuilder(Renderer):
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
        entrypoint = [
            "jupyter",
            "lite",
            "build",
            "--lite-dir",
            repo_path,
            "--output-dir",
            build_path,
            "--contents",
            repo_path,
        ]
        if config_path is not None:
            entrypoint.extend(["--config", config_path])
        return tuple(entrypoint)
