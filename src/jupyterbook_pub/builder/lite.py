import asyncio
from pathlib import Path

from jupyterbook_pub.builder.base import Renderer


class JupyterLiteBuilder(Renderer):
    async def render(self, repo_path: Path, built_path: Path, base_url: str):
        if not built_path.exists():
            # Explicitly pass in a random port, as otherwise jupyter-book will always
            # try to listen on port 5000 and hang forever if it can't.
            command = [
                "jupyter",
                "lite",
                "build",
                str(repo_path),
                "--output-dir",
                str(built_path),
                "--contents",
                str(repo_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = [s.decode() for s in await proc.communicate()]
            _ = await proc.wait()

            print(stdout)
            print(stderr)
