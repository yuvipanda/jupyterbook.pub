import asyncio
import shutil
import tempfile
from pathlib import Path

from jupyterbook_pub.builder.base import Renderer


class JupyterLiteBuilder(Renderer):
    async def render(self, repo_path: Path, built_path: Path, base_url: str):
        if not built_path.exists():
            with tempfile.TemporaryDirectory() as out_dir:
                print(out_dir)
                command = [
                    "jupyter",
                    "lite",
                    "build",
                    str(repo_path),
                    "--output-dir",
                    str(out_dir),
                    "--contents",
                    str(repo_path),
                ]
                proc = await asyncio.create_subprocess_exec(
                    *command, cwd=str(repo_path)
                )

                retcode = await proc.wait()
                if retcode == 0:
                    shutil.move(out_dir, built_path)
                else:
                    raise Exception("jupyter lite build failed")
