import asyncio

from jupyterbook_pub.builder.base import PythonRenderer


class JupyterLiteBuilder(PythonRenderer):
    @classmethod
    def config_file_name(cls) -> str:
        return "jupyter_lite_builder"

    async def render(self):
        command = [
            "jupyter",
            "lite",
            "build",
            self.repo_path,
            "--output-dir",
            self.output_dir,
            "--contents",
            self.repo_path,
        ]
        proc = await asyncio.create_subprocess_exec(*command, cwd=self.repo_path)

        retcode = await proc.wait()
        if retcode != 0:
            raise Exception("jupyter lite build failed")


if __name__ == "__main__":
    app = JupyterLiteBuilder()
    asyncio.run(app.start())
