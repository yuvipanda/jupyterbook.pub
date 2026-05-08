from traitlets import Bool, Dict, Instance, Type, List, Unicode
from traitlets.config import LoggingConfigurable
import asyncio
import sys
from pathlib import Path
import tempfile
import os
import os.path
import hashlib


from kubernetes_asyncio import config
from kubernetes_asyncio.client.api_client import ApiClient
from kubernetes_asyncio.client.api import core_v1_api
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.client import Configuration

from .builder.base import Renderer, ReservedCommands
from .builder.book import JupyterBook2Builder


class ProcessFailedError(Exception): ...


class BuildExecutor(LoggingConfigurable):
    """
    Base class for a build executor.
    """

    # Build executor owns the builder
    builder_class = Type(
        JupyterBook2Builder,
        klass=Renderer,
        allow_none=False,
        config=True,
        help="Builder to use for this installation",
    )

    # Directly passed by caller
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
    Build executor that uses in-memory events for concurrency control.
    """

    # Ensure that concurrent processes don't interleave around proc spawning
    # and PID writing. This is aggressive — we should really map this by path
    _build_events = Dict(
        key_trait=Instance(Path),
        value_trait=Instance(asyncio.Event),
    )

    def get_temporary_build_path(self, build_path: Path) -> Path:
        """
        Return a temporary directory to perform the build in. Once the build
        has completed, this path should be atomically moveable to the build destination.

        :param build_path: path that this temporary directory will be moved to
        (atomically).
        """
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
                build_path.rename(dest_path)
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
    """
    Build executor that performs concurrent builds using local processes.
    """

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
        try:
            stdout, stderr = await proc.communicate()
        except asyncio.CancelledError:
            # Clean up on cancellation
            proc.terminate()
            await proc.wait()
            raise

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
    """
    Build executor that performs containerised builds via the Docker CLI.
    """

    debug = Bool(False, config=True)
    engine = Unicode(
        "docker",
        config=True,
        help="Docker-like runtime to use. Must support bind mounts, sysctl flags, env flags, rm, and workdir flags",
    )
    image = Unicode(
        "jupyterbook-pub:latest",
        allow_none=False,
        config=True,
        help="Container image to use for build environment",
    )
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


def exponential_periods(dt: float, limit: float = None):
    while True:
        yield dt
        dt *= 2

        dt = min(dt, limit or dt)


class KubernetesExecutor(LockingExecutor):
    """
    Kubernetes-based executor.

    This executor makes the following assumptions:

    1. The storage root used by the main application can be found under the volume
       defined by `storage_volume`.
    2. That the specific repo and build paths passed to BuildExecutor.execute
       can be resolved relative to the main application storage root.
    3. That the built_sites and repos paths (defined as constants in `utils.py`) can be
       mounted with RW and RO permissions into the build pod.

    Although configuration of the builder is understood via the `--config` argument to
    the builder, each specific executor may make its own decisions about where to find
    this file.

    The Kubernetes executor provides the config file from a secret.
    """

    namespace = Unicode(
        None, allow_none=False, config=True, help="Kubernetes namespace to use"
    )
    image = Unicode(
        "jupyterbook-pub:latest",
        config=True,
        help="Container image to use for build environment",
    )
    image_pull_secrets = List(
        help="Secrets to use for pulling",
        config=True,
    )
    storage_volume = Dict(
        None,
        help="Volume (ignoring the name) that provides the base application with storage relative to the storage_root trait",
        allow_none=False,
        config=True,
    )
    builder_config_secret = Unicode(
        None,
        allow_none=True,
        config=True,
        help="Name of the Kubernetes secret to mount for builder config",
    )
    builder_config_name = Unicode(
        None,
        help="The name of the builder config file to load from the mounted secret",
        allow_none=True,
        config=True,
    )
    security_context = Dict(
        help="Container security context",
        config=True,
    )
    pod_security_context = Dict(
        help="Pod security context",
        config=True,
    )
    resources = Dict(help="Container resources", config=True)
    node_selector = Dict(
        key_trait=Unicode(), value_trait=Unicode(), help="Pod nodeSelector", config=True
    )
    affinity = Dict(help="Pod affinity", config=True)
    annotations = Dict(help="Pod annotations")
    labels = Dict(key_trait=Unicode(), value_trait=Unicode(), help="Pod labels")
    disable_strict_ssl_verification = Bool(
        False, help="Disable strict X509 SSL verification", config=True
    )

    def get_temporary_build_path(self, build_path: Path) -> Path:
        # The LockingExecutor uses move-after-build for "atomic" builds
        # We create the temporary directory under the storage PVC (by choosing
        # the name as a sibling of `build_path`).
        # This naturally ensures that the file is visible to both the build pod
        # and the executor.
        return build_path.with_name(f".{build_path.name}")

    def get_pod_name(self, repo_path: Path, build_path: Path, base_url: str) -> str:
        factory = hashlib.shake_256()
        factory.update(os.fspath(repo_path).encode("utf-8"))
        factory.update(os.fspath(build_path).encode("utf-8"))
        factory.update(base_url.encode("utf-8"))
        return f"jupyterbook-pub-build-{factory.hexdigest(16)}"

    def get_pod_manifest(
        self, pod_name: str, repo_path: Path, build_path: Path, base_url: str
    ) -> dict:
        repo_mount_path = Path("/srv/repo")
        dest_mount_path = Path("/srv/build")

        # If there is a builder config file, we mount it as a secret
        if self.builder_config_name is None:
            builder_config_file_path = None
            builder_config_mount_path = None
        else:
            builder_config_mount_path = Path("/var/run/secrets/jupyterbook.pub/")
            builder_config_file_path = (
                builder_config_mount_path / self.builder_config_name
            )

        builder_cmd = [
            str(p)
            for p in self.builder_class.entrypoint(
                repo_mount_path,
                dest_mount_path,
                base_url,
                config_path=builder_config_file_path,
            )
        ]

        # Resolve the build path (temporary) and repo path relative to the storage root.
        repo_path_relative_storage = repo_path.relative_to(self.storage_root)
        build_path_relative_storage = build_path.relative_to(self.storage_root)

        volumeMounts = [
            {
                "name": "storage",
                "mountPath": os.fspath(repo_mount_path),
                "readOnly": True,
                "subPath": os.fspath(repo_path_relative_storage),
            },
            {
                "name": "storage",
                "mountPath": os.fspath(dest_mount_path),
                "subPath": os.fspath(build_path_relative_storage),
            },
        ]
        volumes = [{"name": "storage", **self.storage_volume}]

        if builder_config_mount_path is not None:
            volumeMounts.append(
                {
                    "name": "secret",
                    "mountPath": os.fspath(builder_config_mount_path),
                }
            )
            volumes.append(
                {"name": "secret", "secret": {"secretName": self.builder_config_secret}}
            )

        build_container = {
            "image": self.image,
            "name": "build",
            "args": builder_cmd,
            "volumeMounts": volumeMounts,
            "securityContext": self.security_context,
            "imagePullSecrets": self.image_pull_secrets,
            "resources": self.resources,
        }
        pod_spec = {
            "restartPolicy": "Never",
            "containers": [build_container],
            "volumes": volumes,
            "securityContext": self.pod_security_context,
            "nodeSelector": self.node_selector,
            "affinity": self.affinity,
        }

        # Create a new pod
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": pod_name,
                "labels": self.labels,
                "annotations": self.annotations,
            },
            "spec": pod_spec,
        }

    async def perform_build(self, repo_path: Path, build_path: Path, base_url: str):
        configuration = Configuration()
        try:
            config.load_incluster_config(client_configuration=configuration)
        except config.ConfigException:
            await config.load_kube_config(client_configuration=configuration)

        # Some clusters have certificates that violate X509 strict requirements,
        # such as JetStream2 on K8s 1.33
        configuration.disable_strict_ssl_verification = (
            self.disable_strict_ssl_verification
        )

        async with ApiClient(configuration=configuration) as client:
            core_api = core_v1_api.CoreV1Api(client)

            pod_name = self.get_pod_name(repo_path, build_path, base_url)

            self.log.info("Checking for existing pod")
            try:
                await core_api.read_namespaced_pod(
                    name=pod_name, namespace=self.namespace
                )
            except ApiException as err:
                # We expect to be the only build job due to LockingExecutor
                if err.status != 404:
                    raise RuntimeError(f"Unknown error: {err}")
            else:
                raise RuntimeError(f"Existing build pod encountered: {pod_name}")

            # Create build pod
            self.log.info("Creating build pod")
            pod_manifest = self.get_pod_manifest(
                pod_name, repo_path, build_path, base_url
            )
            resp = await core_api.create_namespaced_pod(
                body=pod_manifest, namespace=self.namespace
            )
            try:
                # Wait for pod to have non-pending status
                for dt in exponential_periods(0.1, limit=5):
                    try:
                        resp = await core_api.read_namespaced_pod(
                            name=pod_name, namespace=self.namespace
                        )
                    except ApiException as err:
                        if err.status == 404:
                            # Pod finished and was cleaned up, we don't need to delete
                            return

                        raise RuntimeError(f"Unknown error reading pod status: {err}")
                    match resp.status.phase:
                        case "Pending" | "Running":
                            await asyncio.sleep(dt)
                        case "Succeeded":
                            break
                        case "Failed":
                            raise RuntimeError(f"Pod failed: {pod_name}")
            # Cleanup
            finally:
                self.log.info("Deleting build pod")
                try:
                    await core_api.delete_namespaced_pod(
                        name=pod_name, namespace=self.namespace
                    )
                except ApiException as err:
                    # We expect to be the only build job due to LockingExecutor
                    if err.status != 404:
                        raise RuntimeError(f"Unknown error: {err}")
