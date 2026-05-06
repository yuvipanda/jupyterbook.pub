from traitlets import Bool, Dict, Instance, Type, Unicode
from traitlets.config import Application, LoggingConfigurable
import asyncio
import sys
from pathlib import Path
import tempfile
import shutil

from .builder.base import Renderer, ReservedCommands
from .builder.book import JupyterBook2Builder


class ProcessFailedError(Exception): ...


class BuildExecutor(LoggingConfigurable):
    builder_class = Type(
        JupyterBook2Builder,
        klass=Renderer,
        allow_none=False,
        config=True,
        help="Builder to use for this installation",
    )

    storage_root = Unicode(
        None,
        allow_none=False,
        help="Path to use for artifact (sites, repos) storage",
    )

    async def execute(
        self,
        repo_path: Path,
        dest_path: Path,
        base_url: str,
    ):
        raise NotImplementedError


class LockingExecutor(BuildExecutor):
    """
    Build executor that relies on local processes, using events for concurrency
    control.
    """

    # Ensure that concurrent processes don't interleave around proc spawning
    # and PID writing. This is aggressive — we should really map this by path
    _build_events = Dict(
        key_trait=Instance(Path),
        value_trait=Instance(asyncio.Event),
    )

    def get_temporary_build_path(self, build_path: Path) -> Path:
        raise NotImplementedError

    async def execute(
        self,
        repo_path: Path,
        dest_path: Path,
        base_url: str,
    ):
        # Temporary build path
        build_path = self.get_temporary_build_path(dest_path)
        build_path.mkdir(exist_ok=True)

        try:
            build_finished_event = self._build_events[dest_path]
        except KeyError:
            # The build path doesn't exist, so this is either the first build or a pending
            # build
            build_finished_event = self._build_events[dest_path] = asyncio.Event()

            try:
                self.log.info("Running first build")
                await self.perform_build(repo_path, build_path, base_url)

                # Atomic move
                shutil.move(build_path, dest_path)
                self.log.info("Build completed")
            finally:
                # Signal to other consumers, even if the build failed
                # (we don't want people waiting on never-to-finish builds)
                build_finished_event.set()

                # Clear event
                self._build_events.pop(dest_path)
        else:
            self.log.info("Waiting for concurrent build to finish")
            await build_finished_event.wait()
            return


class LockingProcessExecutor(LockingExecutor):
    async def perform_build(
        self,
        repo_path: Path,
        build_path: Path,
        base_url: str,
    ):
        cmd = self.prepare_process_cmd(repo_path, build_path, base_url)

        await self.run_process(cmd)

    def prepare_process_cmd(
        self,
        repo_path: Path,
        build_path: Path,
        base_url: str,
    ) -> list[str]:
        raise NotImplementedError

    def get_temporary_build_path(self, build_path: Path) -> Path:
        return Path(tempfile.mkdtemp())

    async def run_process(
        self,
        args: list[str],
        *,
        log_output: bool = True,
    ):
        # Lock whilst creating the PID file
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await proc.communicate()

        is_error = proc.returncode != 0

        if log_output:
            for line in stdout.decode().splitlines():
                self.log.info(line)

            log_stderr = self.log.error if is_error else self.log.debug
            for line in stderr.decode().splitlines():
                log_stderr(line)

        # If there's an error, surface it
        if is_error:
            raise ProcessFailedError("An error occurred whilst invoking process")


class DockerExecutor(LockingProcessExecutor):
    debug = Bool(False, config=True)
    engine = Unicode("docker", config=True)
    image = Unicode("jupyterbook-pub:latest", allow_none=False, config=True)
    builder_config_file = Unicode(
        None, help="The builder config file to load", allow_none=True
    )

    def prepare_process_cmd(
        self,
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

        working_dir = Path("/tmp")

        # Allow pass-in of configuration
        container_config_path = None
        if self.builder_config_file is not None:
            builder_config_path = Path(self.builder_config_file).absolute()

            if builder_config_path.exists():
                container_config_path = working_dir / builder_config_path.name
                mounts.append(
                    f"type=bind,src={builder_config_path},dst={container_config_path},readonly"
                )
            else:
                self.log.warn(
                    f"Couldn't find builder config file: {builder_config_path}"
                )

        invocation_cmd = [
            self.engine,
            "run",
            "--rm",
            "--workdir",
            working_dir,
            *(f for m in mounts for f in ("--mount", m)),
            *extra_flags,
            # For now, disable IPV6
            "--sysctl",
            "net.ipv6.conf.all.disable_ipv6=1",
            self.image,
        ]
        builder_cmd = [
            str(p)
            for p in self.builder_class.entrypoint(
                repo_mount_path,
                dest_mount_path,
                base_url,
                config_path=container_config_path,
            )
        ]
        return [*invocation_cmd, *builder_cmd]


class LocalProcessExecutor(LockingProcessExecutor):
    builder_config_file = Unicode(
        None, help="The builder config file to load", allow_none=True
    )

    def prepare_process_cmd(
        self,
        repo_path: Path,
        build_path: Path,
        base_url: str,
    ):
        return tuple(
            [
                sys.executable if p is ReservedCommands.python else str(p)
                for p in self.builder_class.entrypoint(
                    repo_path,
                    build_path,
                    base_url,
                    config_path=self.builder_config_file,
                )
            ]
        )
