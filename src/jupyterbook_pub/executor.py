from traitlets import Unicode
from traitlets.config import Application, LoggingConfigurable
import asyncio
import sys
from pathlib import Path

from .builder.base import Renderer


class BuildExecutor(LoggingConfigurable):
    async def execute(
        self, module: str, repo_path: Path, built_path: Path, base_url: str
    ):
        raise NotImplementedError

    @classmethod
    def resolve_config_file(
        cls, app: Application, builder_class: type[Renderer]
    ) -> Path | None:
        for _path in app.loaded_config_files:
            path = Path(_path)

            full_path = path.parent / f"{builder_class.config_file_name()}.json"

            if full_path.exists():
                return full_path

    async def run_process(self, args: list[str]):
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        retcode = await proc.wait()

        for line in stdout.decode().splitlines():
            self.log.info(line)

        for line in stderr.decode().splitlines():
            self.log.error(line)

        if retcode != 0:
            raise ProcessFailedError("An error occurred whilst invoking process")


class DockerExecutor(BuildExecutor):
    engine = Unicode("docker", config=True)
    image = Unicode("jupyterbook-pub:latest", allow_none=False, config=True)

    async def execute(
        self,
        builder_class: type[Renderer],
        repo_path: Path,
        built_path: Path,
        base_url: str,
    ):
        built_path.mkdir(parents=True, exist_ok=True)
        repo_mount_path = "/srv/source"
        dest_mount_path = "/srv/build"
        mounts = [
            "--mount",
            f"type=bind,src={repo_path},dst={repo_mount_path}",
            "--mount",
            f"type=bind,src={built_path},dst={dest_mount_path}",
        ]

        # Find config file for builder, and mount it
        builder_config_path = self.resolve_config_file(self.parent, builder_class)
        if builder_config_path is not None:
            # TODO nicer way to locate this explicitly
            dest_config_path = builder_config_path.name
            mounts.extend(
                (
                    "--mount",
                    f"type=bind,src={builder_config_path},dst={dest_config_path}",
                )
            )

        builder_module = builder_class.__module__

        cmd = [
            self.engine,
            "run",
            "--rm",
            *mounts,
            # For now, disable IPV6
            "--sysctl",
            "net.ipv6.conf.all.disable_ipv6=1",
            self.image,
            "python",
            "-m",
            builder_module,
            "--repo",
            repo_mount_path,
            "--dest",
            dest_mount_path,
            "--base-url",
            base_url,
        ]
        await self.run_process(cmd)


class ProcessFailedError(Exception): ...


class LocalProcessExecutor(BuildExecutor):
    async def execute(
        self, module: str, repo_path: Path, built_path: Path, base_url: str
    ):
        cmd = [
            sys.executable,
            "-m",
            module,
            "--repo",
            repo_path,
            "--dest",
            built_path,
            "--base-url",
            base_url,
        ]

        await self.run_process(cmd)
