from traitlets import Bool, Unicode
from traitlets.config import Application, LoggingConfigurable
import asyncio
import sys
from pathlib import Path
from typing import Callable
import logging
import tempfile
import os
import shutil

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
        """
        Resolve the config file name for a particular builder with respect
        to existing config files.

        Return the path to the found file if detected.

        :param app: main Application
        :param builder_class: builder to configure
        """
        for _path in app.loaded_config_files:
            path = Path(_path)

            # For now, only JSON (easier to reason about)
            full_path = path.parent / f"{builder_class.config_file_name()}.json"

            if full_path.exists():
                return full_path


class ProcessFailedError(Exception): ...


class ProcessBasedExecutor(BuildExecutor):
    # Ensure that concurrent processes don't interleave around proc spawning
    # and PID writing. This is aggressive — we should really map this by path
    _spawn_pid_lock = asyncio.Lock()

    async def run_process(
        self,
        args: list[str],
        log_output: bool = True,
        pid_file_path: Path = None,
    ):
        async with self._spawn_pid_lock:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if pid_file_path is not None:
                pid_file_path.write_text(str(proc.pid))

        stdout, stderr = await proc.communicate()

        pid_file_path.unlink()

        if log_output:
            for line in stdout.decode().splitlines():
                self.log.info(line)

            for line in stderr.decode().splitlines():
                self.log.error(line)

        if proc.returncode != 0:
            raise ProcessFailedError("An error occurred whilst invoking process")

    async def wait_for_child_pidfile(self, pid_file_path: Path):
        pid = int(pid_file_path.read_text().strip())

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            os.waitid,
            os.P_PID,
            pid,
            # Allow others to wait on process status, and wait for exit or stopped
            os.WNOWAIT | os.WEXITED | os.WSTOPPED,
        )

    def prepare_process_cmd(
        self,
        builder_class: type[Renderer],
        repo_path: Path,
        build_path: Path,
        base_url: str,
    ) -> list[str]:
        raise NotImplementedError

    async def execute(
        self,
        builder_class: type[Renderer],
        repo_path: Path,
        dest_path: Path,
        base_url: str,
    ):
        # Temporary build path
        build_path = tempfile.mkdtemp()

        # PID file with same name as dest
        pid_file_path = dest_path.with_suffix(".pid")

        if pid_file_path.exists():
            self.log.info("Waiting for concurrent build to finish")
            await self.wait_for_child_pidfile(pid_file_path)
        else:
            self.log.info("Running first build")
            cmd = self.prepare_process_cmd(
                builder_class, repo_path, build_path, base_url
            )
            # TODO: race condition here between setup and write?
            await self.run_process(cmd, pid_file_path=pid_file_path)
            shutil.copytree(build_path, dest_path, dirs_exist_ok=True)
            self.log.info("Build completed")


class DockerExecutor(ProcessBasedExecutor):
    debug = Bool(False, config=True)
    engine = Unicode("docker", config=True)
    image = Unicode("jupyterbook-pub:latest", allow_none=False, config=True)

    def prepare_process_cmd(
        self,
        builder_class: type[Renderer],
        repo_path: Path,
        build_path: Path,
        base_url: str,
    ):
        repo_mount_path = "/srv/source"
        dest_mount_path = "/srv/build"

        mounts = [
            f"type=bind,src={repo_path},dst={repo_mount_path},readonly",
            f"type=bind,src={build_path},dst={dest_mount_path}",
        ]

        # Debug
        extra_flags = []

        # Mount the source into the container
        if self.debug:
            this_package_path = Path(__file__).parent
            mounts.append(
                f"type=bind,src={this_package_path},dst=/opt/packages/jupyterbook_pub,readonly"
            )
            extra_flags.extend(["--env", "PYTHONPATH=/opt/packages/"])

        # Find config file for builder, and mount it
        builder_config_path = self.resolve_config_file(self.parent, builder_class)
        if builder_config_path is not None:
            # TODO nicer way to locate this explicitly
            dest_config_path = builder_config_path.name
            mounts.append(
                f"type=bind,src={builder_config_path},dst={dest_config_path},readonly"
            )

        builder_module = builder_class.__module__

        invocation_cmd = [
            self.engine,
            "run",
            "--rm",
            *(f for m in mounts for f in ("--mount", m)),
            *extra_flags,
            # For now, disable IPV6
            "--sysctl",
            "net.ipv6.conf.all.disable_ipv6=1",
            self.image,
        ]
        builder_cmd = [
            "python",
            "-m",
            builder_module,
            "--repo",
            repo_mount_path,
            "--dest",
            dest_mount_path,
            "--base-url",
            base_url,
            "--log-level",
            str(logging.INFO),
        ]
        return [*invocation_cmd, *builder_cmd]


class LocalProcessExecutor(BuildExecutor):
    def prepare_process_cmd(
        self, module: str, repo_path: Path, build_path: Path, base_url: str
    ):

        return [
            sys.executable,
            "-m",
            module,
            "--repo",
            repo_path,
            "--dest",
            build_path,
            "--base-url",
            base_url,
        ]
