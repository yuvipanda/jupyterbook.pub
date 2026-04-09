from traitlets import Unicode
from traitlets.config import LoggingConfigurable
import asyncio
import sys
from pathlib import Path


class BuildExecutor(LoggingConfigurable):
    async def execute(
        self, module: str, repo_path: Path, built_path: Path, base_url: str
    ):
        raise NotImplementedError

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
        self, module: str, repo_path: Path, built_path: Path, base_url: str
    ):
        built_path.mkdir(parents=True, exist_ok=True)

        repo_mount_path = "/srv/source"
        dest_mount_path = "/srv/build"
        cmd = [
            self.engine,
            "run",
            "--rm",
            "--mount",
            f"type=bind,src={repo_path},dst={repo_mount_path}",
            "--mount",
            f"type=bind,src={built_path},dst={dest_mount_path}",
            # For now, disable IPV6
            "--sysctl",
            "net.ipv6.conf.all.disable_ipv6=1",
            self.image,
            "python",
            "-m",
            module,
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
