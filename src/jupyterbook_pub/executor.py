from traitlets import Bool, Dict, Instance, Unicode
from traitlets.config import Application, LoggingConfigurable
import asyncio
import sys
from pathlib import Path
import tempfile
import shutil

from .builder.base import Renderer, ReservedCommands


class ProcessFailedError(Exception): ...


class BuildExecutor(LoggingConfigurable):
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
        config_file_name = f"{builder_class.config_file_name()}.json"
        for _path in app.loaded_config_files:
            path = Path(_path)

            # For now, only JSON (easier to reason about)
            full_path = path.parent / config_file_name

            if full_path.exists():
                return full_path.absolute()

        this_dir_config = (Path.cwd() / config_file_name).absolute()
        if this_dir_config.exists():
            return this_dir_config

    async def execute(
        self,
        builder_class: type[Renderer],
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

        try:
            build_finished_event = self._build_events[dest_path]
        except KeyError:
            # The build path doesn't exist, so this is either the first build or a pending
            # build
            build_finished_event = self._build_events[dest_path] = asyncio.Event()

            try:
                self.log.info("Running first build")
                cmd = self.prepare_process_cmd(
                    builder_class, repo_path, build_path, base_url
                )

                await self.run_process(cmd)

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

        if log_output:
            for line in stdout.decode().splitlines():
                self.log.info(line)

            for line in stderr.decode().splitlines():
                self.log.error(line)

        # If there's an error, surface it
        if proc.returncode != 0:
            raise ProcessFailedError("An error occurred whilst invoking process")


class DockerExecutor(LockingExecutor):
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

        working_dir = Path("/tmp")

        # Find config file for builder, and mount it
        builder_config_path = self.resolve_config_file(self.parent, builder_class)
        if builder_config_path is not None:
            # TODO nicer way to locate this explicitly
            dest_config_path = working_dir / builder_config_path.name
            mounts.append(
                f"type=bind,src={builder_config_path},dst={dest_config_path},readonly"
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
            for p in builder_class.entrypoint(
                repo_mount_path,
                dest_mount_path,
                base_url,
            )
        ]
        return [*invocation_cmd, *builder_cmd]


class LocalProcessExecutor(LockingExecutor):
    def prepare_process_cmd(
        self,
        builder_class: type[Renderer],
        repo_path: Path,
        build_path: Path,
        base_url: str,
    ):
        return tuple(
            [
                sys.executable if p is ReservedCommands.python else str(p)
                for p in builder_class.entrypoint(repo_path, build_path, base_url)
            ]
        )
